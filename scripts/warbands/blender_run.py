"""Run Blender jobs for the Warbands v2 pipeline (one process per job, GPU 1)."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BLENDER = Path(os.environ.get("BLENDER", Path.home() / "blender" / "blender-4.5.9-linux-x64" / "blender"))
SCRIPT = ROOT / "blender" / "warbands_scene.py"


class BlenderError(RuntimeError):
    pass


def run(job: dict, timeout: float = 600) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(job, fh)
        path = fh.name
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": os.environ.get("WB_BLENDER_GPU", "1")}
    try:
        p = subprocess.run([str(BLENDER), "-b", "--factory-startup", "--python", str(SCRIPT), "--", "--job", path],
                           capture_output=True, text=True, timeout=timeout, env=env)
    finally:
        os.unlink(path)
    for line in p.stdout.splitlines():
        if line.startswith("WB_JSON "):
            return json.loads(line[8:])
    tail = (p.stdout + p.stderr)[-3000:]
    raise BlenderError(f"blender job failed ({p.returncode}): {tail}")


def union(exts: list[dict]) -> dict:
    return {k: [min(e[k][0] for e in exts), max(e[k][1] for e in exts)] for k in ("r", "u", "d")}
