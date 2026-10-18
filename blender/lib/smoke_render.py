"""Smoke test: can this Blender render headlessly at all?

Renders one small frame and reports the engine, GPU backend and elapsed time.
`scripts/env_check.py` calls this so a broken GPU path fails the environment check
instead of failing halfway through a batch.
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scene as S  # noqa: E402


def main() -> None:
    params = S.cli_args({"engine": "BLENDER_EEVEE_NEXT", "size": 128, "keep": False})
    started = time.time()
    scene = S.reset_scene(engine=str(params["engine"]))
    S.setup_render(scene, width=int(params["size"]), height=int(params["size"]), samples=8)
    S.setup_lights()
    S.setup_camera(scene, view="iso", ortho_scale=4.0)
    S.add_box("SmokeCube", (1.0, 1.0, 1.0), location=(0.0, 0.0, 0.5), material="timber")
    out = Path(tempfile.gettempdir()) / "artworkflow-smoke.png"
    S.render_still(scene, str(out))
    S.emit_summary({
        "ok": out.exists() and out.stat().st_size > 0,
        "engine": scene.render.engine,
        "file": str(out),
        "bytes": out.stat().st_size if out.exists() else 0,
        "seconds": round(time.time() - started, 2),
    })


if __name__ == "__main__":
    main()
