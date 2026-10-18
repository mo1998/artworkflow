# Styles — adding or changing an art direction

Look lives in `config/styles.yaml`, not in code. The prompt is assembled as:

```
<subject>. <composition>. <style>.
```

- **subject** — the asset's `prompt` in the manifest. What the thing *is*. The only part that
  changes between two assets that should look like siblings.
- **composition** — the style's `composition`. Camera, framing, background, and the ban list.
- **style** — the style's `style`. Materials, palette, quality words.

Negatives merge (asset + style). Resolution happens in `Job.compose_prompt()`; no stage assembles
prompts ad hoc, so a style change lands on every asset at once.

## A painted building style

```yaml
  gothic-vampire-isometric-v1:
    description: One line for humans.
    style: >-
      material and quality words, palette, level of detail
    composition: >-
      camera, framing, background, and the ban list
    negative: >-
      comma separated
    generation: { steps: 28, guidance: 3.2, sampler: euler, scheduler: simple }
    processing: { remove_background: true, trim: true, padding: 12 }
```

## A procedural style carries no prompt

A `blender-` style is about lighting and processing. Every asset naming it inherits these, and an
asset's own `blender.params` still wins where it is explicit:

```yaml
  blender-gothic-vampire-v1:
    style: >-
      dark gothic stone and blackened timber, crimson emissive windows
    composition: >-
      fixed isometric orthographic camera locked per asset family; geometry only,
      transparent film, no ground plane
    negative: ""
    generation:
      key_energy: 2.2      # a dark palette under a hot key light renders as a pale toy
      fill_energy: 0.8
      azimuth: 40.0
    processing: { remove_background: false, trim: true, padding: 12 }
```

Recognised `generation` keys for procedural styles: `view`, `key_energy`, `fill_energy`,
`azimuth`, `ortho_scale`, `frame_target_z`, `samples`, `engine`, `width`, `height`.

## Rules learned by measurement, not taste

1. **Write what the model actually does.** FLUX.1-dev will not produce a literal straight-down
   orthographic map view, whatever the composition says. It produces isometric dioramas. An early
   style asked for top-down and got isometric anyway; the block now describes an isometric diorama
   and bans only what genuinely breaks a sprite.
2. **Negative prompts are advisory.** The vampire manor's negative list bans bats and fence lines,
   and the render has both. A first portrait grew a watermark-shaped mark with `watermark` in the
   negatives. Anything that must not appear needs a detector, not a prompt.
3. **Ban the failure, not the concept.** "no water, no river, no lake, no moat, no sea" works.
   "no background" is ignored.
4. **One subject per image.** `multiple subjects` belongs in the negatives: the cutout and the
   validation both assume a single subject.
5. **Seeds are art direction.** A style is usable once you have confirmed two seeds produce two
   assets that still belong to one set. That is what `demo_watchtower_a` and `_b` check.
6. **Never generate animation frames from text.** Independent frames drift in shape, palette and
   position. Frames come from a rig or a procedural clip.

## Choosing `processing` per style kind

| style kind | `remove_background` | `trim` | `resize` | why |
| --- | --- | --- | --- | --- |
| isolated building / prop | `true` | `true` | target canvas | subject is a cutout; trim then anchor on a fixed grid |
| character portrait | `false` | `false` | target canvas | the background is part of the art, and the crop is intentional |
| seamless texture | `false` | `false` | target canvas | must stay edge-to-edge; trimming would break tiling |
| Blender procedural | `false` | `true` | target canvas | alpha comes from the transparent film; a cutout would be wasted work |
| animation frames | `false` | `false` | `null` | per-frame trimming would break frame registration |

## Background removal, honestly

BiRefNet with fast foreground estimation handles hard-edged subjects well: timber, stone, metal,
cloth. It is weak on individual hair strands, smoke, steam, fire and glow, glass and translucent
fabric, and on subjects that overlap the frame edge (no visible boundary to find).

The pipeline does not pretend otherwise: an asset whose cutout leaves under 2% or over 97% of the
canvas as subject, or that touches the frame border on a procedural render, fails validation and
is listed in the report. Add a mask-cleanup pass for a category that keeps failing, or accept
`review_required` and fix it by hand.
