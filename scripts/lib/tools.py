"""Locate the external tools the pipeline drives.

Nothing here is hardcoded to one machine. Each resolver prefers an explicit environment
variable, then a `config/pipeline.local.yaml` override, then the usual install locations, then
PATH. That is what lets the same repo run on another machine without editing tracked files.

    COMFYUI_HOME, COMFYUI_PYTHON, BLENDER_BIN, GODOT_BIN
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

from .common import PipelineError, ROOT, resolve_path


class ToolNotFound(PipelineError):
    pass


def _first_existing(candidates: Iterable[str | Path | None]) -> Path | None:
    for candidate in candidates:
        if not candidate:
            continue
        path = resolve_path(candidate)
        if path.exists():
            return path
    return None


def _glob_first(patterns: Iterable[str]) -> Path | None:
    for pattern in patterns:
        hits = sorted(glob.glob(os.path.expanduser(pattern)))
        if hits:
            return Path(hits[-1])  # newest version when several are installed
    return None


def _explicit(value: str | None) -> Path | None:
    """A configured path if one was given, else None. Does NOT fall back to detection.

    An explicitly configured path wins or the tool is unavailable. Falling through to a different
    install would run a tool the user did not choose - another Godot version, another Blender -
    and report success. `resolve_tools` turns the missing case into a precise message.
    """
    if value is None or not str(value).strip():
        return None
    return resolve_path(value)


def _configured_but_missing(value: str | None) -> bool:
    configured = _explicit(value)
    return configured is not None and not configured.exists()


def find_comfyui_home(explicit: str | None = None) -> Path | None:
    """A ComfyUI checkout: the directory containing main.py and models/."""
    configured = _explicit(explicit)
    if configured is not None:
        return configured if (configured / "main.py").exists() else None
    env = os.environ.get("COMFYUI_HOME")
    if env:
        candidate = resolve_path(env)
        if (candidate / "main.py").exists():
            return candidate
    for pattern in ("~/comfy/ComfyUI", "~/ComfyUI", "~/comfyui", "~/src/ComfyUI",
                    "~/.local/share/ComfyUI", "/opt/ComfyUI", "/srv/ComfyUI"):
        candidate = _first_existing([pattern])
        if candidate and (candidate / "main.py").exists():
            return candidate
    hit = _glob_first(["~/comfy/*/ComfyUI", "~/ComfyUI*", "/opt/ComfyUI*"])
    return hit if hit and (hit / "main.py").exists() else None


def find_comfyui_python(explicit: str | None = None, home: Path | None = None) -> str | None:
    """An interpreter that can actually import torch and run ComfyUI.

    Tries an explicit config, then the checkout's own venv, then conda environments named for
    ComfyUI, then the interpreter running this pipeline if it has torch.
    """
    configured = _explicit(explicit)
    if configured is not None:
        return str(configured) if configured.exists() else None
    env = os.environ.get("COMFYUI_PYTHON")
    if env:
        path = resolve_path(env)
        if path.exists():
            return str(path)
    candidates: list[str] = []
    for root in ([home] if home else []) + [find_comfyui_home()]:
        if not root:
            continue
        candidates += [str(root / "venv" / "bin" / "python"), str(root / ".venv" / "bin" / "python")]
    # Conda envs named for ComfyUI, wherever conda was installed: this machine's checkout lives
    # under one user while the python comes from another user's anaconda, which a ~-relative glob
    # alone would miss.
    for pattern in ("~/anaconda3/envs/comfy*/bin/python", "~/miniconda3/envs/comfy*/bin/python",
                    "/home/*/anaconda3/envs/comfy*/bin/python",
                    "/home/*/miniconda3/envs/comfy*/bin/python",
                    "/opt/conda/envs/comfy*/bin/python", "/opt/anaconda3/envs/comfy*/bin/python"):
        candidates += sorted(glob.glob(os.path.expanduser(pattern)))
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    for prefix in (os.environ.get("CONDA_PREFIX"),):
        if prefix:
            candidate = Path(prefix) / "bin" / "python"
            if _has_torch(candidate):
                return str(candidate)
    on_path = shutil.which("python3")
    if on_path and _has_torch(Path(on_path)):
        return on_path
    return None


def _has_torch(python: Path) -> bool:
    if not python.exists():
        return False
    try:
        proc = subprocess.run([str(python), "-c", "import torch"], capture_output=True, timeout=60)
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def find_blender(explicit: str | None = None) -> Path | None:
    configured = _explicit(explicit)
    if configured is not None:
        return configured if configured.exists() else None
    env = os.environ.get("BLENDER_BIN")
    if env:
        candidate = resolve_path(env)
        if candidate.exists():
            return candidate
    on_path = shutil.which("blender")
    if on_path:
        return Path(on_path)
    for pattern in ("~/blender*/blender-*/blender", "~/blender*/blender", "~/blender/blender",
                    "/opt/blender*/blender", "/usr/local/blender*/blender",
                    "/snap/bin/blender", "/usr/bin/blender"):
        hit = _glob_first([pattern])
        if hit:
            return hit
    return None


def find_godot(explicit: str | None = None) -> str | None:
    configured = _explicit(explicit)
    if configured is not None:
        return str(configured) if configured.exists() else None
    env = os.environ.get("GODOT_BIN")
    if env:
        candidate = resolve_path(env)
        if candidate.exists():
            return str(candidate)
    for name in ("godot", "godot4", "godot-headless"):
        hit = shutil.which(name)
        if hit:
            return hit
    hit = _first_existing(["~/.local/bin/godot", "/usr/local/bin/godot", "/usr/bin/godot"])
    return str(hit) if hit else None


def resolve_tools(config) -> dict[str, object]:
    """Every tool location the pipeline needs, resolved once.

    Returns a dict with `comfyui_home`, `comfyui_python`, `blender`, `godot` and a `problems`
    list naming anything that could not be found. Callers decide whether a missing tool is
    fatal: `env_check` reports all of it, a stage fails only on the tool it needs.
    """
    comfy_home = find_comfyui_home(config.get("comfyui.home") or None)
    comfy_python = find_comfyui_python(config.get("comfyui.python") or None, comfy_home)
    blender = find_blender(config.get("blender.binary") or None)
    godot = find_godot(config.get("godot.binary") or None)

    problems: list[str] = []
    configured = {
        "comfyui.home": config.get("comfyui.home"),
        "comfyui.python": config.get("comfyui.python"),
        "blender.binary": config.get("blender.binary"),
        "godot.binary": config.get("godot.binary"),
    }
    missing = {
        "comfyui.home": ("ComfyUI checkout not found; set comfyui.home or COMFYUI_HOME", comfy_home),
        "comfyui.python": ("a python that can import torch was not found; set comfyui.python or COMFYUI_PYTHON", comfy_python),
        "blender.binary": ("Blender not found; set blender.binary or BLENDER_BIN", blender),
        "godot.binary": ("Godot not found; set godot.binary or GODOT_BIN", godot),
    }
    for key, (message, resolved) in missing.items():
        if resolved:
            continue
        if _configured_but_missing(configured[key]):
            problems.append(f"{key} is set to {configured[key]!r}, which does not exist")
        else:
            problems.append(message)

    return {"comfyui_home": comfy_home, "comfyui_python": comfy_python,
            "blender": blender, "godot": godot, "problems": problems}


def require(tool: str, config) -> object:
    """Resolve one tool or raise with an actionable message."""
    resolved = resolve_tools(config)
    value = resolved.get(tool)
    if not value:
        hint = {"comfyui_home": "comfyui.home", "comfyui_python": "comfyui.python",
                "blender": "blender.binary", "godot": "godot.binary"}.get(tool, tool)
        raise ToolNotFound(f"{tool} not found. Set {hint} in config/pipeline.yaml "
                           f"(or config/pipeline.local.yaml) or the matching environment variable.")
    return value
