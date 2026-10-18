"""Render an animation clip from a procedural scene as a numbered frame sequence.

The scene is built once and only the clip parameters change per frame, so the subject
cannot drift in shape, colour or proportions between frames - the reason this path
exists next to prompt-generated animation.

Usage:
    blender -b --factory-startup --python blender/render_animation.py -- \
        --kind hut --banner true --clip banner_wave --frame-count 12 \
        --out-dir assets/animations/demo_hut_flag
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path[:0] = [str(_p) for _p in (Path(__file__).resolve().parent,
                                   Path(__file__).resolve().parent / "lib")]

import anim_clips  # noqa: E402
import scene as S  # noqa: E402

ANIM_DEFAULTS: dict[str, object] = {
    "scene": "generate_building",
    "clip": "banner_wave",
    "clip_params": "{}",
    "frame_count": 12,
    "frame_rate": 12,
    "start_index": 0,
    "out_dir": "",
    "prefix": "frame",
    "frame_padding": 4,
}


def main() -> None:
    # The scene generator is selected by name so one sequencer drives every procedural
    # subject; render_animation owns the frame loop, the scene module owns the geometry.
    import importlib

    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    scene_name = "generate_building"
    for i, token in enumerate(argv):
        if token == "--scene" and i + 1 < len(argv):
            scene_name = argv[i + 1]
    try:
        scene_module = importlib.import_module(scene_name)
    except ImportError as exc:
        S.fail(f"unknown --scene {scene_name!r}: {exc}")

    params = S.cli_args({**scene_module.DEFAULTS, **ANIM_DEFAULTS})
    out_dir = str(params.get("out_dir") or "").strip()
    if not out_dir:
        S.fail("--out-dir is required")
    clip = str(params["clip"])
    if clip not in anim_clips.CLIPS:
        S.fail(f"unknown clip {clip!r}; known: {anim_clips.clip_names()}")
    clip_params = params.get("clip_params") or {}
    if isinstance(clip_params, str):
        clip_params = json.loads(clip_params or "{}")

    frame_count = int(params["frame_count"])
    if frame_count < 2:
        S.fail("--frame-count must be >= 2")

    scene = S.reset_scene(engine=str(params["engine"]))
    scene.render.fps = int(params["frame_rate"])
    info = scene_module.build(params)
    S.setup_lights(key_energy=float(params["key_energy"]), fill_energy=float(params["fill_energy"]),
                   azimuth=float(params["azimuth"]))

    subject_top = float(info["subject_top"])
    horizontal = float(info["horizontal"])
    ortho = float(params["ortho_scale"])
    if ortho <= 0.0:
        ortho = max(horizontal * 2.0 * 0.82, subject_top * 1.25) * 1.32
    target_z = float(params["frame_target_z"])
    if target_z < 0.0:
        target_z = subject_top * 0.42

    S.setup_camera(scene, view=str(params["view"]), ortho_scale=ortho, target=(0.0, 0.0, target_z))
    S.setup_render(scene, width=int(params["res_x"]), height=int(params["res_y"]),
                   samples=int(params["samples"]))

    # Clips that move the camera need the framing we just chose.
    if clip == "turntable":
        clip_params = {"target": [0.0, 0.0, target_z],
                       "elevation": 90.0 - math.degrees(scene.camera.rotation_euler.x),
                       **clip_params}

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    start = int(params["start_index"])
    padding = int(params["frame_padding"])
    frames: list[dict[str, object]] = []
    for index in range(frame_count):
        state = anim_clips.apply_clip(scene, clip, index, frame_count, clip_params)
        name = f"{params['prefix']}_{start + index:0{padding}d}.png"
        dest = out_path / name
        scene.frame_set(index)
        S.render_still(scene, str(dest))
        frames.append({"index": index, "file": str(dest), "bytes": dest.stat().st_size if dest.exists() else 0,
                       "clip_state": state})

    S.emit_summary({
        "ok": all(f["bytes"] > 0 for f in frames),
        "clip": clip,
        "frame_count": frame_count,
        "frame_rate": int(params["frame_rate"]),
        "out_dir": str(out_path),
        "ortho_scale": round(ortho, 4),
        "frame_target_z": round(target_z, 4),
        "res": [int(params["res_x"]), int(params["res_y"])],
        "frames": frames,
        **S.object_stats(),
    })


if __name__ == "__main__":
    main()
