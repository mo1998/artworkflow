"""Minimal ComfyUI HTTP client for the Warbands v2 refine loop (standard library only)."""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

URL = "http://127.0.0.1:8188"


class ComfyError(RuntimeError):
    pass


def _req(path: str, data: bytes | None = None, headers: dict | None = None, timeout: float = 60) -> bytes:
    req = urllib.request.Request(URL + path, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def up() -> bool:
    try:
        _req("/system_stats", timeout=5)
        return True
    except OSError:
        return False


def upload(path: Path, name: str | None = None) -> str:
    """Upload an image into ComfyUI's input/warbands_v2/ and return the LoadImage name."""
    boundary = uuid.uuid4().hex
    name = name or path.name
    body = b"".join([
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\n"
        "Content-Type: image/png\r\n\r\n".encode(), path.read_bytes(), b"\r\n",
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"subfolder\"\r\n\r\nwarbands_v2\r\n".encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n".encode(),
        f"--{boundary}--\r\n".encode(),
    ])
    out = json.loads(_req("/upload/image", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}))
    sub = out.get("subfolder")
    return f"{sub}/{out['name']}" if sub else out["name"]


def run(graph: dict, timeout: float = 900) -> dict:
    """Queue a graph, wait for it, return {node_id: [image dicts]}."""
    payload = json.dumps({"prompt": graph, "client_id": "warbands-v2"}).encode()
    try:
        res = json.loads(_req("/prompt", payload, {"Content-Type": "application/json"}))
    except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
        raise ComfyError(e.read().decode(errors="replace")[:2000]) from e
    pid = res["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        hist = json.loads(_req(f"/history/{pid}"))
        if pid in hist:
            entry = hist[pid]
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                msgs = [m for m in status.get("messages", []) if m[0] == "execution_error"]
                raise ComfyError(json.dumps(msgs)[:2000])
            return {k: v.get("images", []) for k, v in entry.get("outputs", {}).items()}
        time.sleep(1.0)
    raise ComfyError(f"timeout after {timeout}s")


def fetch(image: dict, dest: Path) -> Path:
    q = urllib.parse.urlencode({"filename": image["filename"], "subfolder": image.get("subfolder", ""),
                                "type": image.get("type", "output")})
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_req(f"/view?{q}"))
    return dest
