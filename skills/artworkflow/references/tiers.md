# Upgrade tiers — what a "level" is and what it has to do

In a village-builder one building exists at several **tiers**: a level-1 hut, a level-2 house, a
level-3 hall. The player upgrades in place, so the game swaps the sprite on the same tile. That is
what `variants` produces.

```jsonc
{
  "asset_id": "vampire_keep",                    // the base is level 1
  "source": "blender",
  "blender": { "params": { "width": 3.0, "depth": 2.8, "wall_height": 2.2,
                           "banner": true, "chimney": true, "seed": 66 } },
  "processing": { "resize": 512, "anchor": "bottom-center", "scale_mode": "family" },
  "variants": [
    { "suffix": "lvl2", "blender_params": { "width": 3.8, "wall_height": 3.0, "seed": 67 } },
    { "suffix": "lvl3", "blender_params": { "width": 4.4, "wall_height": 3.8, "seed": 68 } }
  ]
}
```

`variants[].blender_params` merge over the base params, so a tier states only what changes. Each
tier becomes its own job and its own output: `vampire_keep`, `vampire_keep__lvl2`,
`vampire_keep__lvl3`.

## Three properties, all enforced

1. **One camera for the whole family.** Sizes are only comparable if framing is identical, so
   every sibling renders through the same measured camera. Tiers that drift in framing cannot be
   swapped on a tile.
2. **A shared scale factor** — `scale_mode: family` scales all tiers by one factor
   (`effective / largest sibling subject`), so level 3 is *visibly larger*. The default
   `scale_mode: fit` normalises each tier to fill its own canvas, which makes every tier the same
   size and defeats the point.
3. **A shared ground line** — `anchor: bottom-center` keeps the footprint on the tile.

Measured on the shipped keeps: 234×317, 285×407, 322×488 px, all ending on canvas row 499.

## How the family camera is chosen

Measured, not inherited:

1. the pipeline builds **every** sibling's scene with `--measure-only` and reads back its
   world-space bounding box (no rendering, ~0.2 s each);
2. it unions those boxes per asset family;
3. Blender fits one orthographic camera to the union (`blender/lib/fit_framing.py`, so the
   projection maths lives in `scene.fit_framing` and nowhere else);
4. every sibling renders through that camera, with `--frame-bounds` carrying the union.

A single-asset job fits its own bounds the same way. A `turntable` widens the fit to the
footprint radius, because the camera sweeps and every azimuth has to fit.

**Why it is done this way:** the camera used to be taken from the first render and reused. That
preserved relative scale but framed the family for its *smallest* tier, so the level-3 keep's roof
and banner fell outside the frame — and no check caught it, because trimming to content and then
padding guarantees an inset subject, so `not_clipped` could never fail. For the keeps the fix moved
`ortho 9.19 → 11.26`, roughly the amount it had been cropping. `source_not_clipped` now checks the
render itself.

## What a tier does *not* do

The pipeline does not invent an upgrade. It renders the geometry you describe, so tier differences
come from the manifest. Scaling only `width`/`wall_height` gives "the same box, bigger" —
mechanically correct, artistically thin. A convincing upgrade needs **features**: a second storey,
a tower, more windows, a different roof, an annexe. `generate_building.py` supports `kind`
(`hut|house|tower|keep|gate`), `windows`, `chimney`, `banner`, `battlements`, `roof`
(`gable|hip|flat|cone`) and per-material changes. Adding a feature is a manifest edit, not code.

## Painted tiers

For painted assets, tiers are separate assets with their own prompts and there is no framing lock
across them, because the diffusion model's composition is not under the pipeline's control. Painted
tiers will not align to a tile the way procedural ones do. If a game needs tile-aligned tiers,
generate them procedurally.

## Verification

```bash
python3 -m unittest tests.test_pipeline.TestFamilies -v
```

Asserts, against the last run's own records: siblings share one camera, higher tiers are larger,
tiers share a ground line, and procedural renders are inside their frame.
