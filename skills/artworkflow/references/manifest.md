# Manifest reference

`config/manifest.json` is the input to everything. A JSON Schema for editors lives beside it at
`config/asset_manifest.schema.json`; the validator that actually runs is `scripts/lib/manifest.py`.

```jsonc
{
  "schema_version": 1,
  "assets": [
    {
      "asset_id": "vampire_crypt",           // unique, lower_snake_case; becomes the run_key
      "asset_type": "building",              // building | prop | character | portrait | texture | background | effect | ui
      "description": "One line a human can search for later.",
      "source": "comfyui",                   // comfyui | blender
      "style": "gothic-vampire-isometric-v1",// key in config/styles.yaml
      "prompt": "a gothic vampire family crypt, ...",  // the SUBJECT clause only
      "seed": 449213,                        // pin it: two assets differing only here must differ
      "generation": {
        "workflow": "workflows/comfyui/flux_txt2img.json",  // comfyui only
        "width": 1024, "height": 1024, "steps": 28
      },
      "processing": {
        "remove_background": true,           // BiRefNet cutout; false for Blender (film is already transparent)
        "trim": true,                        // crop to the subject; must be false for frame sequences
        "resize": 512,                       // square canvas; null keeps the trimmed size
        "anchor": "bottom-center",           // where the subject sits: this is what shares a ground line
        "padding": 12,
        "scale_mode": "fit"                  // fit = fill the canvas | family = one factor for all variants
      },
      "animation": { "enabled": false },
      "variants": [ /* upgrade tiers, see references/tiers.md */ ],
      "export": {
        "format": "png",
        "target_directory": "assets/approved/buildings",  // relative, must stay inside the project
        "godot": "res://assets/buildings",   // mirror path for the engine-side check
        "spritesheet": { "columns": 4, "padding": 2, "name": "sheet_name" }
      },
      "provenance": {
        "model": "FLUX.1-dev fp8",           // required
        "model_file": "flux1-dev-fp8.safetensors",
        "license_url": "https://...",        // missing is reported, not fatal
        "license_note": "Non-commercial licence. Verify before shipping."
      },
      "tags": ["vampire", "building"]
    }
  ]
}
```

## Blender assets

```jsonc
"source": "blender",
"blender": {
  "generator": "generate_building.py",   // or generate_prop.py, or reusable_rigs/humanoid.py;
                                         // all expose DEFAULTS + build(params)
  "params": {                            // passed to the generator as --key value
    "kind": "keep",                      // building: hut|house|tower|keep|gate ; prop: coffin|gravestone|altar|lamp|statue
    "width": 3.0, "depth": 2.8, "wall_height": 2.2,
    "wall_material": "obsidian",         // names from PALETTE in blender/lib/scene.py
    "post_material": "black_timber",
    "window_material": "crimson_glow",
    "roof": "hip",                       // gable | hip | flat | cone
    "roof_material": "slate",
    "windows": 4, "chimney": true, "banner": true, "battlements": true,
    "seed": 66                           // drives the small per-asset jitter, deterministically
  }
}
```

Framing is measured, not configured: the pipeline builds each sibling's scene, reads back its
world-space bounds, unions them per family and fits one camera. `ortho_scale` and
`frame_target_z` are escape hatches for locking a camera by hand.

## Animation

```jsonc
"animation": {
  "enabled": true,
  "clip": "torch_flicker",          // see the clip registry below
  "clip_params": { "material": "crimson_glow", "cycles": 2.0 },
  "frame_count": 16,
  "frame_rate": 12,
  "loop": true
}
```

Set `processing.trim: false` and `resize: null` for animated assets: trimming each frame
individually would shift the registration and the loop would jitter.

| clip | what it does | needs |
| --- | --- | --- |
| `banner_wave` | cross-faded shape-key travelling wave | a mesh built with `banner: true` |
| `torch_flicker` | seeded looping flicker on lights and one emissive material | `clip_params.material` names an emissive palette entry |
| `turntable` | full camera orbit | nothing; the frame is widened to the footprint radius for you |
| `wheel_spin` | constant rotation of objects named `wheel*` | geometry named `wheel*` |
| `bob` | sinusoidal vertical bob | objects named with `clip_params.prefix` |
| `idle` | breathing plus a slow weight shift | an armature from `reusable_rigs/humanoid.py` |
| `walk` | walk in place: alternating stride, counter-swinging arms, two hip bobs | ditto |
| `attack` | one overhead strike per cycle: wind up, fast hit, slow recovery | ditto |

`turntable` is declared camera-moving, so the registration check is skipped for it — a turntable
is supposed to move the subject across the frame.

## Checks the validator enforces

- `asset_id` unique; `variants[].suffix` unique (they become `<id>__<suffix>`)
- `export.target_directory` must resolve inside the project — anything else is refused
- `source: comfyui` needs a `style` that exists and a `generation.workflow` file on disk
- `source: blender` needs a `blender.generator` on disk, and every `*_material` param must name a
  real `PALETTE` entry
- `provenance.model` required; a missing `license_url` is reported in the run report
- `animation.frame_count >= 2` and a `frame_rate` when animation is enabled
