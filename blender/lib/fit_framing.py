"""Fit an orthographic camera to a world-space bounding box, from the command line.

Exists so the projection maths lives in exactly one place (`scene.fit_framing`) and the Python
pipeline can use it without importing bpy: the pipeline unions each asset family's measured
bounds, then asks Blender for the one camera that fits that union.

    blender -b --factory-startup --python blender/lib/fit_framing.py -- \
        --bounds '{"lo":[-2,-2,0],"hi":[2,2,5]}' --res-x 1024 --res-y 1024
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scene as S  # noqa: E402


def main() -> None:
    params = S.cli_args({"bounds": "", "view": "iso", "azimuth": 0.0, "elevation": 0.0,
                         "res_x": 1024, "res_y": 1024, "margin": 1.10})
    payload = params.get("bounds")
    if isinstance(payload, str):
        payload = json.loads(payload) if payload.strip().startswith("{") else None
    if not isinstance(payload, dict) or "lo" not in payload or "hi" not in payload:
        S.fail("--bounds must be a JSON object with 'lo' and 'hi' arrays")

    box = (tuple(float(v) for v in payload["lo"]), tuple(float(v) for v in payload["hi"]))
    azimuth = float(params["azimuth"]) or None
    elevation = float(params["elevation"]) or None
    ortho, target_z = S.fit_framing(box, view=str(params["view"]), azimuth=azimuth,
                                    elevation=elevation, res_x=int(params["res_x"]),
                                    res_y=int(params["res_y"]), margin=float(params["margin"]))
    S.emit_summary({
        "ok": True,
        "ortho_scale": round(ortho, 6),
        "frame_target_z": round(target_z, 6),
        "size": [round(box[1][i] - box[0][i], 4) for i in range(3)],
    })


if __name__ == "__main__":
    main()
