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
import bpy  # noqa: E402
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
    measure_only = "--measure-only" in argv and "true" in argv
    try:
        scene_module = importlib.import_module(scene_name)
    except ImportError as exc:
        S.fail(f"unknown --scene {scene_name!r}: {exc}")

    params = S.cli_args({**scene_module.DEFAULTS, **ANIM_DEFAULTS})
    out_dir = str(params.get("out_dir") or "").strip()
    if not out_dir and not measure_only:
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
    bounds = S.scene_bounds()
    ortho = float(params["ortho_scale"])
    target_z = float(params["frame_target_z"])
    if ortho <= 0.0 or target_z < 0.0:
        # A turntable sweeps the camera, so the frame has to fit the subject from every azimuth.
        # Widening the box to the footprint radius is the conservative stand-in for the union of
        # all rotations, and it is what stops a wing or a banner leaving the frame mid-turn.
        fit_box = bounds
        # A bone-driven clip moves the silhouette, so fit the animated extent rather than the rest
        # pose: a walk swings limbs and an attack raises an arm past where the rest pose sits.
        # Sampling costs a few scene evaluations and no rendering.
        if clip not in anim_clips.CAMERA_MOVING_CLIPS:
            boxes = [bounds]
            samples = max(4, min(frame_count, 8))
            for step in range(samples):
                anim_clips.apply_clip(scene, clip, round(step * frame_count / samples),
                                      frame_count, clip_params)
                bpy.context.view_layer.update()
                sampled = S.scene_bounds()
                if sampled:
                    boxes.append(sampled)
            lo = [min(box[0][axis] for box in boxes) for axis in range(3)]
            hi = [max(box[1][axis] for box in boxes) for axis in range(3)]
            fit_box = (tuple(lo), tuple(hi))
            anim_clips.apply_clip(scene, clip, 0, frame_count, clip_params)
            bpy.context.view_layer.update()
        if clip == "turntable":
            radius = max(abs(fit_box[0][0]), abs(fit_box[1][0]), abs(fit_box[0][1]), abs(fit_box[1][1]))
            radius = max(radius, 0.5)
            fit_box = ((-radius, -radius, fit_box[0][2]), (radius, radius, fit_box[1][2]))
        fitted_ortho, fitted_z = S.fit_framing(
            fit_box, view=str(params["view"]), azimuth=float(params["azimuth"]) or None,
            res_x=int(params["res_x"]), res_y=int(params["res_y"]), margin=1.10)
        if ortho <= 0.0:
            ortho = fitted_ortho
        if target_z < 0.0:
            target_z = fitted_z

    if measure_only:
        S.emit_summary({
            "ok": True, "measure_only": True, "clip": clip,
            "bounds": {"lo": list(bounds[0]), "hi": list(bounds[1])},
            "subject_top": round(subject_top, 4),
            "ortho_scale": round(ortho, 4), "frame_target_z": round(target_z, 4),
            "res": [int(params["res_x"]), int(params["res_y"])],
            **S.object_stats(),
        })
        return

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
        "bounds": {"lo": list(bounds[0]), "hi": list(bounds[1])},
        "ortho_scale": round(ortho, 4),
        "frame_target_z": round(target_z, 4),
        "res": [int(params["res_x"]), int(params["res_y"])],
        "frames": frames,
        **S.object_stats(),
    })


if __name__ == "__main__":
    main()
