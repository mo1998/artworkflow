# Prompt and style guide

Prompts in this pipeline are assembled from three parts, in this order:

```
<subject>. <composition>. <style>.
```

- **subject** — `prompt` on the asset in `config/manifest.json`. What the thing *is*. Only
  this part changes between two assets that should look like siblings.
- **composition** — `composition` in `config/styles.yaml`. Camera, framing, background,
  and the ban list. Identical for every asset in a style.
- **style** — `style` in `config/styles.yaml`. Materials, palette, quality words. Identical
  for every asset in a style.

Bindings are resolved in `Job.compose_prompt()`; nothing assembles prompts ad hoc in a stage,
so a style change lands on every asset at once.

## Rules that come from measurement, not taste

1. **Write what the model actually does.** FLUX.1-dev will not produce a literal straight-down
   orthographic map view, no matter how many times the composition says "camera looking straight
   down". It produces isometric dioramas. The first version of `dark-fantasy-isometric-v1` asked
   for top-down and got isometric anyway; the block now describes an isometric diorama and bans
   only what genuinely breaks a sprite (water, neighbouring structures, text, hard borders).
   Measured cost of ignoring this: a whole batch of prompts fighting the model's prior.

2. **Ban the failure, not the concept.** "no water, no river, no lake, no moat, no sea" is a
   working ban list because those are the specific things FLUX adds around a building. "no
   background" is not actionable and is ignored.

3. **One subject per image.** "multiple buildings" in the negative list is load-bearing: the
   cutout and the clip checks both assume a single subject.

4. **Seeds are part of the art direction, not a debug detail.** A style is only usable once you
   have confirmed that two seeds produce two buildings that still belong to one set. That is
   what `demo_watchtower_a` and `demo_watchtower_b` exist to check.

5. **Do not generate animation frames from text.** Each independently generated frame drifts in
   shape, palette and position. Frames come from a rig or from a procedural scene with a clip
   (`blender/render_animation.py`); the prompt path produces stills only.

## Adding a style

Append to `config/styles.yaml`:

```yaml
  my-style-v1:
    description: One line for humans.
    style: >-
      material and quality words, palette, level of detail
    composition: >-
      camera, framing, background, and the ban list
    negative: >-
      comma separated
    generation: { steps: 24, guidance: 3.2, sampler: euler, scheduler: simple }
    processing: { remove_background: true, trim: true, padding: 12 }
```

Then reference it from an asset with `"style": "my-style-v1"`. `scripts/env_check.py` fails if a
manifest names a style that does not exist.

## Choosing `processing` per style

| Style kind | `remove_background` | `trim` | `resize` | why |
| --- | --- | --- | --- | --- |
| Isolated building / prop on a flat backdrop | `true` | `true` | target canvas | subject is a cutout; trim then anchor on a fixed grid |
| Character portrait with a painted background | `false` | `false` | target canvas | the background is part of the art |
| Seamless ground texture | `false` | `false` | target canvas | must stay edge-to-edge; trimming would break tiling |
| Blender procedural (transparent film) | `false` | `true` | target canvas | alpha comes from the render, so BiRefNet is wasted work |

## Background removal honesty

BiRefNet + fast foreground estimation (`General-HR`) handles hard-edged subjects well: timber,
stone, metal, cloth. It is weak on:

- individual hair strands and fur
- smoke, steam, fire and glow that should keep soft alpha
- glass, water and translucent fabric
- subjects that overlap the frame edge, because there is no visible boundary to find

The pipeline does not pretend otherwise: assets whose cutout leaves less than 2% or more than 97%
of the canvas as subject, or that touch the frame border, fail validation and are listed in the
report. Add a specialised mask-cleanup pass for a category that keeps failing, or mark it
`review_required` and fix it by hand.
