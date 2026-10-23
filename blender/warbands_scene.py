"""Warbands v2 Blender entry point: one job JSON in, a pass bundle out.

    blender -b --factory-startup --python blender/warbands_scene.py -- --job job.json

job = {
  "class": "building" | "wall_surface" | "terrain" | "backdrop",
  "kind": "headquarters", "tier": 0,
  "mode": "measure" | "render",
  "frame": {"r": [..], "u": [..], "d": [..]},   # family extents (render mode, buildings)
  "res": [1024, 1024], "pad_px": 24, "fill_px": 976, "samples": 96,
  "out_dir": "..."
}
A building family is measured first (every tier), the extents are unioned and every tier
is rendered with the SAME camera - so tiers share one scale, one ground line and one
plate, and stack in the game without drift.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE / "wb")]

import core  # noqa: E402
import buildings  # noqa: E402
import env  # noqa: E402
import backdrop  # noqa: E402


def job_from_argv() -> dict:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    path = argv[argv.index("--job") + 1]
    return json.loads(Path(path).read_text())


def run_building(job: dict) -> None:
    scene = core.reset()
    if job.get("plate"):
        # the footprint is the game cell's grass square (from the manifest), not a hand value
        buildings.PLATES[job["kind"]] = float(job["plate"])
    buildings.KINDS[job["kind"]](int(job.get("tier", 0)))
    right, up, fwd, _ = core.iso_basis()
    ext = core.projected_extents(right, up, fwd)
    if job["mode"] == "measure":
        core.emit({"extents": ext, "footprint": core.footprint()})
        return
    frame = job.get("frame") or ext
    res = job.get("res", [1024, 1024])
    core.iso_camera(scene, frame, res[0], job.get("pad_px", 24), job.get("fill_px", 976))
    core.lights(scene)
    d0, d1 = frame["d"]
    written = core.render_passes(scene, Path(job["out_dir"]), tuple(res), job.get("samples", 96),
                                 (d0 + 60.0, d1 + 60.0))
    # where the world origin (the footprint's centre) and one world unit land on the canvas:
    # the game places the sprite by this anchor, so the building stands on its cell's centre
    cam = scene.camera
    S = cam.data.ortho_scale
    right, up, _, _ = core.iso_basis()
    cx = res[0] / 2 - cam.data.shift_x * res[0]
    cy = res[1] / 2 + cam.data.shift_y * res[0]
    anchor = {"canvas": res[0], "origin": [cx, cy], "px_per_unit": res[0] / S}
    core.emit({"extents": ext, "frame": frame, "written": written, "anchor": anchor})


def main() -> None:
    job = job_from_argv()
    cls = job.get("class", "building")
    if cls == "building":
        run_building(job)
    elif cls == "wall_surface":
        env.run_wall_surface(job)
    elif cls == "terrain":
        env.run_terrain(job)
    elif cls == "backdrop":
        backdrop.run_backdrop(job)
    else:
        raise SystemExit(f"unknown class {cls}")


main()
