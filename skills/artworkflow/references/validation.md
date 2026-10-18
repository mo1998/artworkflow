# Validation — statuses and what each check means

Three outcomes, and the difference is the point:

| status | meaning | exported? |
| --- | --- | --- |
| `passed` | every configured check ran and passed | yes |
| `review_required` | technical checks passed, but something needs human eyes (a review check tripped, or a near-duplicate was found) | yes, flagged in its sidecar, record and the report |
| `failed` | a hard check failed | **no** — it stays in `assets/processed/` |

Plus progress markers `pending → generated → processed`, and `exported` once copied (with the
pre-export status preserved in `exported_status`).

`review_required` is not a pass. A pipeline that reports it as one is the reason this status
system exists.

## Hard checks — a failure means not engine-ready

| check | catches |
| --- | --- |
| `file_exists`, `format_is_png`, `not_empty`, `opens` | missing, truncated, mis-encoded output |
| `dimensions` | wrong canvas size, or a subject too small to be useful |
| `not_blank` | a flat wash — rgb stddev below the floor, measured on the 0–255 scale |
| `has_alpha`, `subject_present` | missing transparency, or 0 / over 97% subject coverage |
| `subject_size` | a subject whose short side is too small |
| `not_clipped` | subject flush with the *processed* canvas edge |
| `source_not_clipped` | the **render** was cropped by the camera. Procedural sources only |
| `frames_present`, `frame_opens`, `frames_uniform` | frame count or size mismatch |
| `frames_not_blank`, `frames_have_subject` | an empty frame inside a sequence |
| `registration_stable` | centroid drift — skipped for camera-moving clips |
| `has_motion` | a "loop" where nothing moves |
| `loop_continuous` | a loop seam: the last-to-first step dwarfs the average step |
| near-duplicates | two assets within a `dHash` hamming distance of each other |

### Why `source_not_clipped` exists separately

`not_clipped` runs on the processed file, where trimming crops to content and padding insets it —
so a *perfectly inset* sprite is produced even when the render was cut off. It cannot fail once
`trim` is on. That is how a cropped level-3 keep passed every check. The source check runs on
`assets/incoming/<run_key>.png` where clipping is still visible.

It is scoped to procedural renders: the pipeline owns the Blender camera, so content touching the
render border there means the camera was wrong. A painted render is the diffusion model's
composition, and a portrait is *meant* to crop its shoulders — the same rule would fail good art.

### Why `has_motion` is not a mean difference

A waving banner on a 512 px building moves about 550 pixels. A mean difference over the whole
canvas reads that as "no motion". The check uses peak per-pixel delta plus the fraction of pixels
that changed, which is answerable at any canvas size.

## Review checks — judgements the validator cannot make

- `subject_fill` — the subject covers less than ~15% or more than ~92% of the canvas. Technically
  fine, probably a composition problem.
- near-duplicate — a seed change that changed nothing.

## Thresholds

All in `config/pipeline.yaml` under `validation:` and `review:`. They are deliberately loose enough
to pass a coherent set and tight enough to catch a real failure; tighten them per project rather
than per asset.

## Reading a failure

```bash
python3 -c "import json;d=json.load(open('metadata/asset_records/<run_key>.json'));\
print(d['status']);[print(c['check'],c['ok'],c['detail']) for c in d['stages']['validation']['checks']]"
```

Or the MCP tool `artworkflow_asset_status` with `include_checks: true`. The record also carries the
processing steps actually applied, before/after measurements, the resolved prompt and seed, and a
short traceback for any stage that threw.

## Adding a check

1. Add an `imageops` measurement if the number does not exist yet. Keep it scale-explicit
   (`_0_255` suffix when it is not 0–1): a mismatched scale once made `not_blank` fail every asset.
2. Build a `Check(name, ok, detail, severity="error"|"review")` in `validate_assets.py`. Write the
   detail string for a human deciding what to do — include the measured value and the limit.
3. Add a unit test. If the check exists because of a bug, say so in the test docstring: that is
   what stops the bug coming back.
