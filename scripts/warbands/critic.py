"""Vision critic: ranks candidates, names defects, compares them to the Blender source.

It NEVER decides acceptance - the gates do. Its output steers the next round (new seed on
artifacts, more denoise on weak materials) and breaks ties between gated candidates.

Primary:  opencode/nemotron-3.5-super-vl-free  (via `opencode run`; free tier, 1-3 min a call)
Fallback: qwen3-vl:8b-instruct on a local ollama server (GPU, a few seconds a call)
Dispatch: Nemotron takes a review only when it is idle; while it is busy (or when it fails)
the review goes straight to Qwen instead of queueing - that is what keeps the critic off the
pipeline's critical path. A full outage degrades to the deterministic ranking; it never blocks.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OPENCODE = os.environ.get("OPENCODE", str(Path.home() / ".opencode" / "bin" / "opencode"))
PRIMARY = "opencode/nemotron-3.5-super-vl-free"
# the -instruct tag: the plain qwen3-vl:8b always reasons first and spends its token budget
# thinking, returning an empty answer (`think: false` and "/no_think" are both ignored)
FALLBACK = os.environ.get("WB_CRITIC_FALLBACK", "qwen3-vl:8b-instruct")
OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
LABELS = "ABCDEFGH"
# one call per model at a time: parallel `opencode run` calls on the free tier stall
_NEMOTRON = threading.Lock()
_QWEN = threading.Lock()
# circuit breaker: when the free tier keeps timing out, stop paying its timeout every round
_BREAKER = {"fails": 0, "until": 0.0}
BREAK_AFTER, BREAK_FOR = 2, 600.0

PROMPT = """You are an art director reviewing game sprites for a norse village strategy game.
The attached sheet has panels. Panel SRC is the 3D blockout (the required shape, camera and
composition). Panels {labels} are painted candidates of the same {subject}.
For each candidate judge: does it keep the SRC silhouette, camera and composition; are the
painted materials rich (wood grain, stone, moss, weathering) or still flat/plastic; are there
artifacts (smears, melted geometry, extra objects, text, broken edges, floating bits).
Reply with ONLY one JSON object, no prose:
{{"ranking": ["best label", "...", "worst label"],
  "candidates": {{"A": {{"silhouette_drift": false, "weak_materials": false, "artifacts": false,
                        "camera_mismatch": false, "defects": ["short phrase", "..."]}}, "...": {{}}}}}}"""


def contact_sheet(src: Path, candidates: list[Path], out: Path, tile: int = 384) -> Path:
    ims = [Image.open(src).convert("RGB")] + [Image.open(p).convert("RGB") for p in candidates]
    labels = ["SRC"] + list(LABELS[:len(candidates)])
    w0, h0 = ims[0].size
    th = int(tile * h0 / w0)
    sheet = Image.new("RGB", (tile * len(ims), th + 34), (24, 24, 24))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 24)
    except OSError:
        font = ImageFont.load_default()
    for i, (im, lab) in enumerate(zip(ims, labels)):
        sheet.paste(im.resize((tile, th)), (i * tile, 34))
        d.text((i * tile + 10, 4), lab, fill=(255, 220, 120), font=font)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def _parse(text: str) -> dict | None:
    for m in re.finditer(r"\{", text):
        depth = 0
        for j in range(m.start(), len(text)):
            depth += text[j] == "{"
            depth -= text[j] == "}"
            if depth == 0:
                try:
                    obj = json.loads(text[m.start():j + 1])
                except json.JSONDecodeError:
                    break
                if isinstance(obj, dict) and "ranking" in obj:
                    return obj
                break
    return None


def _opencode(sheet: Path, prompt: str, timeout: int) -> str:
    p = subprocess.run([OPENCODE, "run", "-m", PRIMARY, "-f", str(sheet), "--format", "json", prompt],
                       capture_output=True, text=True, timeout=timeout, cwd="/tmp")
    texts = []
    for line in p.stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        part = ev.get("part") or {}
        if ev.get("type") == "text" and part.get("text"):
            texts.append(part["text"])
    return "\n".join(texts)


def _ollama(sheet: Path, prompt: str, timeout: int) -> str:
    # num_ctx is load-bearing: the default 262k context makes the model 46 GB and half of
    # it runs on the CPU (~60 s a review); at 8k it is 6.5 GB, all on the GPU (~2 s)
    body = json.dumps({"model": FALLBACK, "stream": False, "format": "json", "keep_alive": "2h",
                       "options": {"temperature": 0, "num_predict": 900, "num_ctx": 8192},
                       "messages": [{"role": "user", "content": prompt,
                                     "images": [base64.b64encode(sheet.read_bytes()).decode()]}]}).encode()
    req = urllib.request.Request(f"{OLLAMA}/api/chat", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read()).get("message", {}).get("content", "")


def _call(name: str, call, lock: threading.Lock, sheet: Path, prompt: str, timeout: int,
          block: bool) -> tuple[dict | None, str | None]:
    if not lock.acquire(blocking=block):
        return None, None  # busy: not an error, just someone else's turn
    try:
        obj = _parse(call(sheet, prompt, timeout))
        return obj, None if obj else f"{name}: no JSON in reply"
    except (OSError, subprocess.SubprocessError, ValueError, urllib.error.URLError) as e:
        return None, f"{name}: {e}"
    finally:
        lock.release()


def review(src: Path, candidates: list[Path], subject: str, work: Path, timeout: int = 90) -> dict:
    """Returns {"model", "ranking", "candidates"} or {"model": None, "error": ...}."""
    sheet = contact_sheet(src, candidates, work / "critic_sheet.png")
    labels = ", ".join(LABELS[:len(candidates)])
    prompt = PROMPT.format(labels=labels, subject=subject)
    errors: list[str] = []
    # Nemotron if idle, else Qwen at once; Qwen also covers a Nemotron failure. Qwen waits
    # for its own turn (seconds), so a review never queues behind a free-tier call.
    plan = (("nemotron", _opencode, _NEMOTRON, False), ("qwen3-vl", _ollama, _QWEN, True))
    for name, call, lock, block in plan:
        if name == "nemotron" and time.time() < _BREAKER["until"]:
            continue
        obj, err = _call(name, call, lock, sheet, prompt, timeout if name == "nemotron" else 120, block)
        if name == "nemotron" and (obj or err):
            _BREAKER["fails"] = 0 if obj else _BREAKER["fails"] + 1
            if _BREAKER["fails"] >= BREAK_AFTER:
                _BREAKER.update(fails=0, until=time.time() + BREAK_FOR)
                errors.append(f"nemotron: {BREAK_AFTER} failures in a row, skipped for {int(BREAK_FOR)}s")
        if err:
            errors.append(err)
        if obj:
            valid = [x for x in obj.get("ranking", []) if x in LABELS[:len(candidates)]]
            obj["ranking"] = valid + [x for x in LABELS[:len(candidates)] if x not in valid]
            obj["model"] = name
            obj.setdefault("candidates", {})
            return obj
    return {"model": None, "error": "; ".join(errors), "ranking": [], "candidates": {}}
