# Materials — colouring procedural geometry

Procedural geometry is coloured **by name**. `PALETTE` in `blender/lib/scene.py` is the single
declaration; generators, manifest params and style blocks reference it by string only
(`"wall_material": "obsidian"`).

```python
PALETTE = {
    "plaster":       {"color": (0.84, 0.80, 0.71), "roughness": 0.85},
    "timber":        {"color": (0.26, 0.17, 0.11), "roughness": 0.75},
    "stone":         {"color": (0.52, 0.51, 0.48), "roughness": 0.90},
    "obsidian":      {"color": (0.115, 0.115, 0.135), "roughness": 0.65},
    "slate":         {"color": (0.165, 0.185, 0.235), "roughness": 0.72},
    "iron":          {"color": (0.35, 0.36, 0.38), "roughness": 0.45, "metallic": 0.8},
    "crimson_glow":  {"color": (0.05, 0.015, 0.02), "roughness": 0.45,
                      "emission": (0.80, 0.055, 0.085), "emission_strength": 1.0},
}
```

Colours are linear 0–1, not sRGB hex. Renders use the `Standard` view transform, so what you put
in is close to what lands in the PNG.

## The contract is enforced from three sides

- **Manifest validation** rejects an unknown `*_material` before anything renders and lists the
  known names. A typo like `obsidan` fails validation, not after four minutes of GPU time.
- **Blender fails loudly** on an unknown material rather than silently falling back to grey. A
  fallback turns one typo into a whole batch of plausible-looking, wrongly-coloured assets.
- **A unit test** asserts the palette has no duplicate keys. A duplicate in a dict literal
  silently overrides — the last one wins — and that happened for real: a new dark `cold_moon` lost
  to an older bright one.

## Emissive materials: two rules, both learned by getting them wrong

1. **Near-black base colour, hue in the emission.**
2. **`emission_strength` around 1.0.**

A bright base colour plus a strong emission clips under the Standard view transform. The first
vampire keep rendered hot pink windows and a salmon roof for exactly this reason: base
`(0.62, 0.06, 0.10)` plus emission strength `1.9` pushed red past 1.0 while green and blue stayed
low, and the result desaturated towards pink rather than reading as deep crimson.

Correct shape:

```python
"crimson_glow": {"color": (0.05, 0.015, 0.02),            # base is almost black
                 "emission": (0.80, 0.055, 0.085),        # the hue lives here
                 "emission_strength": 1.0},               # and does not clip
```

`tests/test_pipeline.py::test_emissive_materials_use_a_dark_base_colour` asserts both properties,
so the mistake cannot come back silently.

## Adding a material

1. Append to `PALETTE` with a lowercase name describing the material, not its role in one asset
   (`slate`, not `keep_roof`).
2. Reference it from `config/manifest.json` under `blender.params`, or from a style block's
   `generation` if a whole direction should use it.
3. Nothing else. There is no material registry, no shader file, and no code path to update.

## Lighting is the other half

A dark palette under a hot key light renders pale — the point of the material is lost. Lighting
belongs in the style block, next to the palette it was tuned for:

```yaml
    generation:
      key_energy: 2.2
      fill_energy: 0.8
      azimuth: 40.0
```

Shared rig: a sun key plus two area fills, aimable with `azimuth` and `elevation`. There is no
HDRI dependency, so renders reproduce without external assets.
