# ArtWorkflow

A manifest-driven pipeline that turns a JSON spec into game-ready sprite sheets, transparent
PNGs and engine-verified assets using only local tools.

Two generation paths feed one processing, validation and export chain:

- **ComfyUI + FLUX.1-dev** for painted art — buildings, props, portraits, backgrounds.
- **Blender procedural scenes** for anything that must be exact — upgrade tiers from one fixed
  camera, and animation frames from a clip instead of from a prompt.

The pipeline is deliberately not a wrapper around a GUI. Every stage is a script with an HTTP
API or a `-b` background invocation behind it, so a batch runs unattended and a rerun reproduces
the same result from the recorded seed.

```
config/manifest.json  ──►  generate  ──►  process  ──►  validate  ──►  export  ──►  Godot check
     + styles.yaml           (2 paths)      (cutout,      (technical    (approved/    (engine can
                                          trim, scale)    + review)     + mirror)     load it)
                                  │                             │
                                  └──────────►  records  ◄───────┘
                                        metadata/asset_records/*.json
                                                    │
                                                    └──►  report  ──►  reports/<run id>.md
```

## Status of this repository

Built and verified on this machine against the tools listed under
[Environment](#environment). Two art directions ship, covering both generation paths:

**`config/manifest.json` — demo set (engine plumbing)**

| asset | path | result |
| --- | --- | --- |
| `demo_watchtower_a`, `demo_watchtower_b` | ComfyUI + FLUX + BiRefNet | passed, exported, distinct images from two seeds |
| `demo_hut`, `demo_hut__lvl2`, `demo_hut__lvl3` | Blender procedural, one locked camera | passed, exported, size progression preserved |
| `demo_hut_flag` | Blender procedural + `banner_wave` clip, 12 frames | passed, exported, 1 sheet + frames verified in Godot |

**Vampire set (a real art direction, 10 assets / 13 jobs)**

| asset | path | result |
| --- | --- | --- |
| `vampire_manor_house`, `vampire_crypt` | painted, `gothic-vampire-isometric-v1` | passed, exported |
| `vampire_blood_well` | painted prop, `gothic-vampire-prop-v1` | passed, exported |
| `vampire_lord` | painted portrait, `gothic-vampire-portrait-v1` | passed, exported (no cutout, no trim) |
| `vampire_keep`, `__lvl2`, `__lvl3` | procedural, `blender-gothic-vampire-v1`, family scale | passed, exported, tiers grow |
| `vampire_grave` | procedural prop, new `generate_prop.py` | passed, exported |
| `vampire_gate_torch` | procedural, `torch_flicker` on a crimson material, 16 frames | passed, exported |
| `vampire_watcher` | procedural, `turntable` clip, 24 frames | passed, exported |

Verification evidence from the last full run (`reports/final.md`, `logs/final/`):

```
assets: 16  exported: 16  failed: 0  review_required: 0  retried: 0
godot ok: 68 texture(s), 3 sheet(s), 52 frame rect(s)
python3 -m unittest discover -s tests   ->  36 tests, OK
```

Diffusion reproducibility was measured, not assumed: after `--force`, all four painted vampire
assets came back **byte-identical** (same seed, same checkpoint, same workflow, same ComfyUI).

## Quick start

```bash
cd /home/mrazek/ArtWorkflow
.venv/bin/python scripts/env_check.py          # prove the toolchain before spending GPU time
.venv/bin/python scripts/run_pipeline.py       # full run: generate -> report
```

Run one stage on its own, which is the normal way to work:

```bash
.venv/bin/python scripts/comfyui_generate.py --assets demo_watchtower_a
.venv/bin/python scripts/process_images.py   --assets demo_watchtower_a --force
.venv/bin/python scripts/validate_assets.py  --assets demo_watchtower_a
.venv/bin/python scripts/export_assets.py
.venv/bin/python scripts/godot_check.py
.venv/bin/python scripts/build_report.py     --run-id 20261018-140000
```

Useful flags: `--assets id [id…]`, `--stages generate,process,validate`, `--force`, `--dry-run`,
`--strict` (export only outright passes), `--skip-godot`, `--allow-failures`.
`run_pipeline.py` exits non-zero when any asset failed.

## Environment

Discovered with `scripts/env_check.py`; all of it is configuration, not hardcoded assumptions.

| Component | Path / version |
| --- | --- |
| ComfyUI | `/home/mrazek/comfy/ComfyUI`, v0.34.0, autostarted on `127.0.0.1:8188` |
| ComfyUI python | `/home/ubuntu/anaconda3/envs/comfy/bin/python` (torch 2.6.0+cu124) |
| Checkpoint | `models/checkpoints/flux1-dev-fp8.safetensors` |
| Cutout node pack | `ComfyUI_BiRefNet_ll`, weights `models/BiRefNet/General-HR.safetensors` |
| Blender | `~/blender/blender-4.5.9-linux-x64/blender`, 4.5.9 LTS, headless EEVEE Next |
| Godot | `godot` 4.7.2 on PATH, check project at `godot_project/` |
| Pipeline python | `.venv` (created with `--system-site-packages`, so it reuses anaconda's PIL 11.3, numpy 1.26.4, OpenCV 5.0, PyYAML 5.4, requests) |
| GPU | 2 x RTX 4090 24 GB; `concurrency.gpu_jobs: 1` serialises ComfyUI and Blender |

Not installed, and not required: standalone `rembg` and `onnxruntime`. Background removal goes
through the BiRefNet ComfyUI node instead, which is the path this machine actually supports.

## Layout

```
ArtWorkflow/
├── config/
│   ├── pipeline.yaml            tool paths, retries, thresholds, review tolerances
│   ├── styles.yaml              style blocks (look lives in data, not code)
│   ├── manifest.json            what to produce (the input to everything)
│   └── asset_manifest.schema.json
├── workflows/comfyui/
│   ├── flux_txt2img.json        API-format graph + binding map
│   └── birefnet_cutout.json     ditto, for background removal
├── scripts/
│   ├── run_pipeline.py          entry point: sequences the stages
│   ├── env_check.py             toolchain preflight
│   ├── comfyui_generate.py      stage: generate via ComfyUI
│   ├── blender_generate.py      stage: generate via Blender (stills + frame sequences)
│   ├── process_images.py        stage: cutout, trim, scale, anchor
│   ├── remove_background.py     BiRefNet cutout library + single-file CLI
│   ├── validate_assets.py       stage: checks, statuses, duplicate scan
│   ├── generate_spritesheet.py  stage: pack sheets + frame metadata
│   ├── export_assets.py         stage: approved/ + Godot mirror + sidecars
│   ├── godot_check.py           stage: headless import + engine-side verification
│   ├── build_report.py          stage: run report (markdown + json)
│   └── lib/                     common, manifest, comfy, imageops, blender, stage
├── blender/
│   ├── generate_building.py     parameterised building generator
│   ├── generate_prop.py         coffins, gravestones, altars, lamps, statues
│   ├── render_animation.py      clip sequencer (frame loop lives here)
│   ├── lib/scene.py             camera, lights, PALETTE, geometry, bevel
│   ├── lib/anim_clips.py        reusable clips: banner_wave, torch_flicker, turntable, …
│   └── reusable_rigs/           character rigs — not implemented in v1, see its README
├── godot_project/               engine-side check: import + load every exported asset
├── assets/{incoming,processed,animations,spritesheets,approved}/
├── metadata/{asset_records,manifests}/
├── logs/, reports/
└── tests/test_pipeline.py       30 unit tests, no GPU needed
```

Source renders are never overwritten: each stage writes to its own directory, so any stage can
be rerun without regenerating earlier work.

## How a run works

1. **`generate`** reads the manifest and renders raw files into `assets/incoming/` (ComfyUI) or
   `assets/animations/<run_key>/` (Blender frame sequences). Failures retry with a shifted seed
   (`seed + 1013 * attempt`) and the *actual* seed is recorded, so a retry stays reproducible.
2. **`process`** cuts the background out through BiRefNet, trims to the subject, scales and
   places the subject on a fixed canvas at a fixed anchor. Alpha produced by Blender's
   transparent film skips the cutout entirely.
3. **`spritesheet`** packs frame sequences into a sheet plus a JSON of frame rects, fps and loop
   flag.
4. **`validate`** runs the checks and sets one of four statuses. It never guesses.
5. **`export`** copies passing assets into `assets/approved/<target>/`, mirrors them into the
   Godot project, and writes a `<run_key>.export.json` sidecar carrying the status.
6. **`godot`** runs `godot --headless --import` and then loads every exported texture and every
   sheet's frame rects inside the engine.
7. **`report`** writes `reports/<run id>.md` and `.json`.

## Manifest reference

`config/manifest.json` is the contract. Full field list in
`config/asset_manifest.schema.json`; the validator that actually runs is
`scripts/lib/manifest.py`.

```jsonc
{
  "asset_id": "demo_hut",
  "asset_type": "building",
  "source": "blender",                  // "comfyui" | "blender"
  "style": "blender-procedural-v1",
  "blender": { "generator": "generate_building.py", "params": { "kind": "hut", /* … */ } },
  "generation": { "width": 1024, "height": 1024, "engine": "BLENDER_EEVEE_NEXT", "samples": 64 },
  "processing": { "remove_background": false, "trim": true, "padding": 12,
                  "resize": 512, "anchor": "bottom-center", "scale_mode": "family" },
  "animation": { "enabled": false },
  "variants": [
    { "suffix": "lvl2", "blender_params": { "width": 3.0, "height": 2.0, "seed": 12 } }
  ],
  "export": { "format": "png", "target_directory": "assets/approved/buildings",
              "godot": "res://assets/buildings" },
  "provenance": { "model": "procedural (Blender 4.5.9)", "license_url": "https://…" }
}
```

Rules the validator enforces:

- `asset_id` unique, and every `variants[].suffix` unique (they become `<id>__<suffix>`).
- `export.target_directory` must resolve **inside** the project; anything else is refused
  (`PathSafetyError`), which is what stops a manifest from writing over your home directory.
- `source: comfyui` requires a `style` that exists in `styles.yaml` and a `generation.workflow`
  file that exists on disk.
- `source: blender` requires a `blender.generator` that exists under `blender/`.
- `provenance.model` is required; a missing `license_url` is reported rather than fatal.
- `animation.frame_count >= 2` and a `frame_rate` when animation is enabled.

## Style blocks

Look lives in `config/styles.yaml`, not in code: adding a style is a data change.
`Job.compose_prompt()` assembles `<subject>. <composition>. <style>.`; the negatives merge.
See `prompts/style_guide.md` for the rules and the seven shipped styles.

Six styles ship, in three kinds:

| kind | styles |
| --- | --- |
| painted buildings | `dark-fantasy-isometric-v1`, `norse-frontier-topdown-v1`, `gothic-vampire-isometric-v1` |
| painted props and portraits | `stylized-flat-prop-v1`, `gothic-vampire-prop-v1`, `painterly-portrait-v1`, `gothic-vampire-portrait-v1` |
| procedural (no prompt) | `blender-procedural-v1`, `blender-gothic-vampire-v1` |
| textures | `tileable-texture-v1` |

A `blender-*` style carries no prompt at all — its `generation` block is where the look is set,
and it is inherited by every asset that names it:

```yaml
  blender-gothic-vampire-v1:
    generation:
      key_energy: 2.2      # a dark palette under a hot key light renders as a pale toy
      fill_energy: 0.8
      azimuth: 40.0
    processing: { remove_background: false, trim: true, padding: 12 }
```

Lighting, framing and processing defaults live in the style so a whole direction changes in one
place; an asset's own `blender.params` still wins where it is explicit.

## Materials: the palette contract

Procedural geometry is coloured by name. `PALETTE` in `blender/lib/scene.py` is the single
declaration; generators, variants and manifest params only ever reference it by string
(`wall_material: "obsidian"`). That contract is enforced from both sides:

- **Manifest validation** rejects an unknown `*_material` before anything renders, listing the
  known names. `obsidan` fails at validation, not after four minutes of GPU time.
- **Blender fails loudly** on an unknown material rather than falling back to grey, because a
  silent fallback turns a typo into a batch of plausible-looking, wrongly-coloured assets.
- **A unit test** asserts the palette has no duplicate keys. A duplicate in a `PALETTE` literal
  silently overrides, and this happened for real: a new dark `cold_moon` lost to an older bright
  one.

Two rules for emissive entries, learned by getting them wrong:

- the base colour stays near black and the **emission carries the hue**;
- `emission_strength` stays at ~1.0.

A bright base colour plus strong emission clips in the `Standard` view transform: the first
vampire keep rendered hot pink windows and a salmon roof. A test now asserts both properties.

## Workflows and parameter binding

A ComfyUI workflow here is an API-format graph plus a binding map, in one file:

```json
"_artworkflow": {
  "name": "flux_txt2img",
  "requires": { "checkpoint": "flux1-dev-fp8.safetensors", "custom_nodes": [] },
  "bindings": {
    "prompt": { "node": "2", "input": "text" },
    "seed":   { "node": "6", "input": "seed" },
    "width":  { "node": "5", "input": "width" }
  },
  "output_node": "8"
}
```

The stage fills only the keys the manifest provides, so one workflow serves every asset in a
style. Adding a workflow is dropping a JSON file into `workflows/comfyui/` — `env_check.py`
preflights each one's checkpoints and custom nodes, and reports which parameters it can bind.

Keys without a binding are reported as unbindable instead of being silently dropped, and a
binding that points at a missing node id fails loudly.

## Scale modes: `fit` and `family`

The same `resize: 512` means two different things depending on what the asset is:

- **`fit`** (default) — normalise the subject to fill the canvas. Right for a set of unrelated
  sprites that should each use their canvas fully, like the two watchtowers.
- **`family`** — scale every variant of one asset by one shared factor
  (`effective / largest sibling subject`). Right for upgrade tiers: a level-3 building must look
  bigger than a level-1, and normalising each tier independently would make them the same size.

For `family` to work the renders must share a camera. `blender_generate.py` guarantees this by
capturing the first render's `ortho_scale` and `frame_target_z` and forcing them onto every
sibling, so the tiers are directly comparable in pixels.

Measured on the demo family: `demo_hut` 370x396, `demo_hut__lvl2` 442x462,
`demo_hut__lvl3` 488x476 — all anchored to a shared ground line.

## Reproducibility

Measured, not assumed. `blender_generate.py --force` on the demo family, comparing SHA-256 of the
raw renders:

- **Pixel-identical.** Two renders of the same scene differ in 0 of 65 536 pixels. The scene,
  camera, lights, materials and all the geometry jitter keyed off the seed are fully deterministic.
- **Not byte-identical.** The only difference between the PNGs is a `tEXt Date` chunk that Blender
  stamps with the render time. So `sha256sum` on raw renders is the wrong reproducibility test, and
  `imageops.pixel_hash()` (SHA-256 over raw RGBA bytes) is what the records store.
- **Processed output is byte-identical.** Every processed PNG matched its SHA-256 across a forced
  rerun, because the processing stage re-encodes through PIL and drops the render metadata.

Diffusion output is a different story: the same seed reproduces the same image only while the
checkpoint, workflow and ComfyUI version are unchanged, which is why every record stores the
workflow path and a hash of it.



Two kinds of check, and the distinction is the point of the status system.

**Hard checks** — a failure means the asset is not engine-ready:

| check | what it catches |
| --- | --- |
| `file_exists`, `format_is_png`, `not_empty`, `opens` | missing, truncated or mis-encoded output |
| `dimensions` | wrong canvas size, or a subject too small to be useful |
| `not_blank` | a flat wash (rgb stddev below the floor, on a 0-255 scale) |
| `has_alpha`, `subject_present` | transparency missing, or 0 missing/2 %…97 % subject coverage |
| `subject_size` | a subject whose short side is too small |
| `not_clipped` | subject flush with the canvas edge, i.e. the render was cut off |
| `frames_present`, `frame_opens`, `frames_uniform` | frame count or size mismatch |
| `frames_not_blank`, `frames_have_subject` | an empty frame inside a sequence |
| `registration_stable` | centroid drift across frames |
| `has_motion` | a "loop" where nothing moves — measured by peak delta and the fraction of pixels that changed, because a mean over the canvas cannot see a waving banner on a large building |
| `loop_continuous` | a seam: the last-to-first step is much larger than the average step |
| near-duplicates | two assets within a dHash hamming distance, so a seed change that did nothing gets caught |

**Review checks** — technically clean, but a judgement the validator cannot make. These set
`review_required` rather than passing the asset.

Statuses:

| status | meaning |
| --- | --- |
| `pending` → `generated` → `processed` | progress markers |
| `passed` | every configured check ran and passed |
| `review_required` | all hard checks passed, a review check tripped or a near-duplicate was found |
| `failed` | a hard check failed; not exported |
| `exported` | copied to `assets/approved/`, with the pre-export status kept in `exported_status` |

Export accepts `passed` and `review_required`. A `review_required` asset is exported **and**
flagged in its sidecar, the record and the report — it is never quietly blessed. `--strict`
exports only outright passes. A `failed` asset stays in `assets/processed/` with its record
explaining why.

## Procedural generation with Blender

`blender/generate_building.py` builds a building from parameters and renders it on transparent
film, which is why procedural assets need no background removal. Design rules in
`blender/lib/scene.py`:

- the camera targets the world origin with a fixed orthographic scale, so framing is independent
  of the subject and every tier of a family renders directly comparable;
- a bevel on every hard edge, because flat-shaded primitives otherwise read as untextured CAD
  blocks with no highlight along an edge;
- `Standard` view transform instead of a filmic look, so exported colours are predictable;
- no ground plane: the game supplies ground, so sprites ship as clean cutouts.

Animation clips (`blender/lib/anim_clips.py`) are pure functions of `(frame index, frame count)`
that mutate the already-built scene, and are written to loop with frame 0 == frame N. Shipped
clips: `banner_wave` (cross-faded shape keys), `torch_flicker`, `turntable`, `wheel_spin`, `bob`.
Because the scene is built once, frames cannot drift in shape, colour or proportion — the failure
mode of generating each frame from a prompt.

## Godot integration

`godot_project/` is a real Godot 4.7 project whose only job is verification. The pipeline mirrors
exported assets into it, runs `godot --headless --import`, then runs
`res://tests/asset_check.gd`, which walks every exported PNG and JSON and asserts:

- each PNG loads as a `Texture2D` with a non-empty size;
- each spritesheet's metadata parses, names a sheet that exists, and declares the sheet's real
  size;
- every frame rect lies inside the sheet.

Export failures are reported with their file paths, so a green Python validator plus a red Godot
check says exactly which file the engine cannot consume.

## Records, logs and reports

- `metadata/asset_records/<run_key>.json` — durable per-asset state: status, per-stage timings
  and attempts, the full prompt and negative prompt, the actual seed, workflow and its SHA-256
  prefix, generator parameters, before/after measurements, processing steps applied, every check
  with its detail string, and any error with a short traceback.
- `metadata/manifests/<run id>.json` — the manifest snapshot that produced a run, plus the job list.
- `logs/<run id>/events.jsonl` — every event as structured JSON; `<stage>.log` per stage,
  `comfyui-server.log`, `godot-import.log`, one Blender transcript per asset.
- `reports/<run id>.md` / `.json` — totals, per-asset table, provenance table including a
  `licence recorded: missing` column, near-duplicates, retried assets, and the log inventory.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -v
```

36 tests over the pure parts, no GPU required. Several of them encode bugs this pipeline actually
had:

- `test_padding_is_respected_on_every_edge` — the anchor used to place the subject flush against
  the canvas edge, which made *every* asset fail `not_clipped`;
- `test_rgb_stddev_uses_the_0_255_scale` — the metric used to be 0-1 while the configured floor
  was 4.0, so `not_blank` failed everything;
- `test_seed_comes_from_the_asset_when_generation_omits_it` — the seed used to be read only from
  `generation.seed`, so two assets with different top-level seeds silently rendered the same image;
- `test_accepts_an_rgb_subject_that_exactly_fills_the_canvas` — `place_on_canvas` assumed an RGBA
  subject, which only broke for the portrait, the one asset whose subject exactly fills its canvas;
- `test_motion_metrics_see_a_small_moving_detail` — mean difference over the canvas called a
  waving banner "no motion";
- `test_sheet_and_sidecar_metadata_do_not_collide` — the export sidecar used to overwrite a
  spritesheet's frame metadata;
- `test_paths_outside_the_project_are_refused` — manifest-controlled paths must not escape;
- `test_pixel_hash_ignores_file_metadata` — Blender stamps a render timestamp into every PNG, so
  "did the render change?" must be answered on pixels, not file bytes;
- `test_emissive_materials_use_a_dark_base_colour` and `test_palette_has_no_duplicate_keys` — the
  two mistakes behind the first vampire keep's pink windows and mis-coloured roof;
- `test_unknown_material_in_the_manifest_is_reported` — an art-direction typo must fail
  validation, not render grey.

## Adding a new asset

1. Add an entry to `config/manifest.json` (or copy a file from `prompts/asset_templates/`).
2. Name a style that exists in `config/styles.yaml`.
3. `.venv/bin/python scripts/run_pipeline.py --assets <asset_id>`
4. Read `reports/<run id>.md`. If the asset is `review_required`, look at the PNG before shipping;
   if it is `failed`, the record names the failed check.

### Adding a whole art direction

Worked example — that is exactly how the vampire set was built:

1. `config/styles.yaml`: a `-isometric-` building block, a `-prop-` block, a `-portrait-` block, and
   a `blender-` block carrying lighting and processing defaults.
2. `blender/lib/scene.py`: add however many `PALETTE` entries the direction needs. A dark direction
   needs lower `key_energy` in its style block, or every material renders pale.
3. `config/manifest.json`: assets naming those styles. Painted subjects get a `prompt`; procedural
   ones get `blender.params` referencing palette names.
4. Run it, then **look at the board**: put painted and procedural output side by side. Palette
   matching is what decides whether they belong to one world, and no check in the pipeline
   measures that.

## Known limitations, honestly

1. **FLUX will not give you a straight-down map view.** Its prior is isometric; the composition
   block now describes an isometric diorama instead of fighting it. Measured, not assumed.
2. **Negative prompts are advisory.** The vampire manor's negative list bans bats and fence lines,
   and the render has both. The first `vampire_lord` render also grew a watermark-shaped mark in a
   corner despite `watermark` being in the negative list — no validator can see that, so the fix
   was a stronger negative list plus a new seed, which is the only tool available. Anything that
   genuinely must not appear needs a detector, not a prompt.
3. **Painted assets look richer than procedural ones.** The painted manor has shingles, ironwork
   and a fenced base; the procedural keep is flat-shaded blocks. Matching palette, framing and
   lighting make them sit together, and hand-authored materials or textures would close the rest
   of the gap. The pipeline does not pretend the two paths produce identical fidelity.
4. **Same seed is not the same image forever.** It held byte-for-byte across a forced rerun here,
   but only while the checkpoint, workflow and ComfyUI version are unchanged, which is why every
   record stores the workflow path and a hash of it.
5. **Background removal is imperfect** for hair, smoke, glow, glass and translucent effects, and
   for subjects that overlap the frame edge. Those assets fail or are flagged for review.
6. **Animation comes from rigs and clips, not prompts.** The 2D character path
   (`blender/reusable_rigs/`) is not implemented in v1.
7. **A turntable always has angles where a thin feature is edge-on.** The watcher's wings present
   their edge from some azimuths; no amount of wing geometry removes that, it is what rotation is
   for.
8. **Technical checks are not art direction.** Near-duplicate detection catches a seed change
   that did nothing; it cannot tell you a face looks wrong. Use `review_required` for that.
9. **Licences are your problem.** FLUX.1-dev is non-commercial; the manifest carries a
   `license_note` saying so, and the report flags assets with no recorded licence. Verify before
   shipping anything.
10. **One GPU job at a time.** ComfyUI and Blender are serialised deliberately; two RTX 4090s are
    available but parallel generation is not implemented yet.

## Agent instructions

When driving this repository non-interactively:

```bash
.venv/bin/python scripts/env_check.py
.venv/bin/python scripts/run_pipeline.py --assets <ids>
```

- Work only inside this directory; `ensure_inside_project()` refuses everything else, and the
  table tool lives outside the pipeline.
- Never report an asset as complete unless its record says `passed`, `review_required` or
  `exported`, and never describe `review_required` as a pass.
- Prefer a manifest edit over a code edit; the pipeline is meant to be extended with data.
- If a tool is unavailable, document it and continue with the assets that are independent, rather
  than half-running a batch.
- Do not commit generated assets or logs; commit the manifest, the records and the report.
