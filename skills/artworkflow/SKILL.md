---
name: artworkflow
description: Produce game-ready art assets with a local pipeline instead of hand-drawing or guessing. Generates painted sprites, portraits, buildings and props through ComfyUI/FLUX, procedurally consistent buildings and upgrade tiers plus animation frames through Blender, then cuts out backgrounds, validates every asset against configurable checks, packs spritesheets, exports to the engine and verifies the result by loading it in headless Godot. Use when asked to create or extend game art, generate a building/prop/character sprite, make upgrade tiers, produce a spritesheet or animation frames, add a new art direction or style, validate or export existing assets, or when a game project needs assets and no artist is available.
---

# ArtWorkflow

Turn a JSON manifest into validated, engine-checked game assets. Two generation paths feed one
processing, validation and export chain.

| want | path | why |
| --- | --- | --- |
| painted building, prop, portrait | `comfyui` (FLUX.1-dev) | richness diffusion gives you for free |
| exact upgrade tiers, animation frames | `blender` (procedural) | one camera per family, frames that cannot drift |
| background removed | either, then BiRefNet | `remove_background: true` |
| 1 → 2 → 3 upgrade levels | `blender` + `variants` | shared camera, shared scale, shared ground line |

## Before anything else

```bash
python3 scripts/env_check.py          # or the artworkflow_env_check MCP tool
```

It resolves ComfyUI, its python, Blender and Godot; reports whether each workflow's checkpoint
and custom nodes are installed; and test-renders in Blender. Every failure it reports is a real
blocker, and every one of them is a config fix rather than a code fix:

- `comfyui.home` / `COMFYUI_HOME` — the ComfyUI checkout
- `comfyui.python` / `COMFYUI_PYTHON` — an interpreter that can `import torch`
- `blender.binary` / `BLENDER_BIN`
- `godot.binary` / `GODOT_BIN`

Put machine-specific values in `config/pipeline.local.yaml` (untracked) rather than the tracked
`config/pipeline.yaml`.

## The loop

```bash
# full pipeline for the whole manifest
python3 scripts/run_pipeline.py

# one asset, all seven stages
python3 scripts/run_pipeline.py --assets vampire_keep

# stage by stage while iterating
python3 scripts/blender_generate.py --assets vampire_keep --force
python3 scripts/process_images.py   --assets vampire_keep
python3 scripts/validate_assets.py  --assets vampire_keep
python3 scripts/export_assets.py
python3 scripts/godot_check.py
python3 scripts/build_report.py
```

Via MCP the same stages are `artworkflow_generate`, `_process`, `_validate`, `_export`,
`_godot_check`, `_report`, or `artworkflow_run` for the lot. Instant read-only tools:
`artworkflow_manifest`, `_styles`, `_asset_status`, `_inspect`, `_env_check`.

If you have no MCP client, the CLI is the whole interface — the MCP server is a thin wrapper
over these same scripts.

## Rules that are not negotiable

1. **Never report an asset as done because a file exists.** The truth is in
   `metadata/asset_records/<run_key>.json`: `passed`, `review_required`, `failed`, `exported`.
   `review_required` means every technical check passed and a human should look — it is *not* a
   pass, and saying otherwise is the failure mode this pipeline exists to prevent.
2. **Read `reports/<run id>.md` before claiming success.** It carries the failed checks per
   asset and any missing licence.
3. **Change data before code.** Look, style, subject, size, seed and animation all live in
   `config/manifest.json` and `config/styles.yaml`. If you are editing a stage script to change
   how art looks, you are probably holding it wrong.
4. **Aesthetic judgements are yours, not the validator's.** The checks catch a cropped roof, a
   blank image, a broken loop, a duplicate. They cannot tell you a face looks wrong. Run the
   pipeline, then look at the output with the `read` tool on the PNG.
5. **One GPU job at a time.** `concurrency.gpu_jobs: 1`. Do not parallelise ComfyUI and Blender.
6. **Do not commit generated pixels.** `assets/` and `logs/` are ignored; the manifest, records
   and reports are the provenance that gets versioned.

## References

| file | read it when |
| --- | --- |
| `references/manifest.md` | writing or editing assets, variants, animation, export targets |
| `references/styles.md` | adding or changing an art direction |
| `references/materials.md` | colouring procedural geometry, or a material name is rejected |
| `references/tiers.md` | building upgrade tiers, or tiers do not line up |
| `references/validation.md` | an asset failed or is review_required, and you need to know why |
| `references/troubleshooting.md` | something errored and the cause is not obvious |

## Worked example: a new art direction

1. Add style blocks to `config/styles.yaml` — usually a building block, a prop block, a portrait
   block, and a `blender-` block carrying lighting and processing defaults.
2. Add `PALETTE` entries in `blender/lib/scene.py` if the direction needs new colours. Emissive
   entries keep a near-black base colour with the hue in the emission, at strength ~1.0.
3. Add assets to `config/manifest.json` naming those styles. Painted subjects need a `prompt`;
   procedural ones need `blender.params` referencing palette names.
4. Run it. Then put painted and procedural output side by side and *look*: matching palette is
   what decides whether they belong to one world, and nothing in the pipeline measures that.

Shipped example: the `gothic-vampire-*` and `blender-gothic-vampire-v1` styles, ten assets
covering painted buildings, a prop, a portrait, a procedural tiered keep, a grain stone, a
flickering torch gate and a rotating statue.
