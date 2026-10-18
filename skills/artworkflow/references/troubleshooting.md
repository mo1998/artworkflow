# Troubleshooting

Symptoms seen in practice, with the cause. Most are config, not code.

## `ComfyUI is not reachable`

- `artworkflow_env_check` / `env_check.py` resolves the checkout and says which path it used.
- Set `comfyui.home` in `config/pipeline.local.yaml`, or `COMFYUI_HOME`.
- Autostart runs `python main.py --listen 127.0.0.1 --port 8188` from the checkout and appends to
  `logs/comfyui-server.log`. First start loads a 17 GB checkpoint and can take minutes; the
  timeout is `comfyui.startup_timeout_seconds`.
- 8189 already in use is common if a stale server is running: `ss -ltnp | grep 8188`.

## `no python that can import torch was found`

The pipeline needs an interpreter that can run ComfyUI, which is usually *not* the interpreter
running the pipeline (the pipeline itself only needs Pillow, numpy, PyYAML, requests and OpenCV).
Point `comfyui.python` at it, or set `COMFYUI_PYTHON`. A conda env named `comfy*` is found
automatically.

## `unknown material 'obsidan'`

A typo in a `*_material` parameter. The error lists every valid name. The palette is `PALETTE` in
`blender/lib/scene.py`; see `materials.md`.

## Procedural render is pale / washed out / pink

Palette colour versus light energy. A dark palette under a hot key light renders pale; a bright
base colour with a strong emission clips to white or hot pink. Both are fixed in the style block:
lower `key_energy`, and give emissive materials a near-black base with the hue in the emission at
strength ~1.0. See `materials.md`.

## The tallest upgrade tier is cropped

Should be impossible now: framing is measured over the whole family's union bounds before any
render. If it recurs, check the `framing N sibling(s)` line in the generate log, and confirm
`--measure-only` works:

```bash
blender -b --factory-startup --python blender/generate_building.py -- \
    --kind keep --measure-only
```

## `not_clipped` passes but the sprite is cut off

`not_clipped` cannot fail on a trimmed asset — trimming and padding guarantee an inset subject.
Look at `source_not_clipped` instead, which measures the render. Its detail string names which
edge the subject is touching.

## `registration_stable` fails on a turntable

It should not: `turntable` is listed in `CAMERA_MOVING_CLIPS` in `blender/lib/anim_clips.py`
and the check is skipped for camera-moving clips. If you add a clip that moves the camera, add its
name there too.

## `has_motion` fails on an animation that clearly moves

The motion is real but small relative to the canvas. The check needs a peak delta of at least 8/255
and a changed-pixel fraction of 0.05%. Either enlarge the animated element in frame (`resize`,
`ortho_scale`) or raise the clip's amplitude. Do not simply lower the threshold.

## Godot check fails after a green Python validation

Read `logs/<run id>/godot-check.log` and the `problems` list in the response. Typical causes: a
spritesheet whose metadata names a sheet that is not there, or frame rects that run outside the
sheet. A PNG with a valid header but broken IDAT chunks imports in Pillow and fails in Godot,
which is exactly why this check exists.

## Godot import says nothing and takes forever

First import after a project change regenerates `.godot/`. If a previous run was interrupted,
delete `godot_project/.godot/` and retry.

## Everything is `failed` with `file_exists`

The generate stage did not run or wrote nothing. Check the stage order — the pipeline runs
generate → process → spritesheet → validate → export → godot → report — and that the selected
asset ids actually match (`--assets` takes run keys, which are `<asset_id>__<suffix>` for
variants).

## A stage crashed and later stages report "not attempted"

That should not happen: every stage wraps each job in `try_job`, records the error against the
asset and continues. If a stage does die, the record will hold the error and a short traceback;
check `logs/<run id>/events.jsonl`.

## "Are these two images crops of each other?"

They are different renders of the same asset family. Compare
`metadata/asset_records/<run_key>.json`: the `ortho_scale` and `frame_target_z` will match across
a family, and the `params` will differ. Tiers share a camera and a ground line by construction.
