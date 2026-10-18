# Reusable character rigs — not implemented in v1

This directory exists as the agreed home for the character-animation path. It is empty of code
on purpose: a partly-working rig generator would be worse than none, because it would produce
assets that look like they animate until you look at the feet.

## Why this path is separate from everything else

Every other animated asset in this pipeline comes from a clip driving an already-built scene
(`blender/lib/anim_clips.py`), which is exact because the scene is built once. Characters need
that property even more than buildings do: generating each pose from a prompt produces a
character whose face, equipment and proportions drift between frames.

## The contract a rig must satisfy to plug in

1. A generator under this directory builds an armature plus a skinned mesh from parameters, and
   exposes `DEFAULTS` and `build(params)` the way `blender/generate_building.py` does. That is all
   `blender/render_animation.py` needs to drive it, via `--scene <module name>`.
2. Clips are added to `blender/lib/anim_clips.py` as functions of
   `(scene, frame_index, frame_count, params)` that pose the rig. Because they are pure functions
   of the frame index, a clip that is already rigged is exactly reproducible.
3. Clips must loop: frame 0 and frame `frame_count` have to be the same pose. The validator's
   `loop_continuous` check measures the seam and fails the asset if it is too large.
4. The rig must be re-usable across subjects — one humanoid rig driving several characters, the
   way the README's "reusable rigs" requirement intends. A rig that only works for one mesh is a
   mesh, not a rig.

## What this buys, and what it costs

- **Buys**: idle, walk, attack and death clips that are consistent frame to frame, and a
  character that can be re-rendered at a new resolution later without redoing the art.
- **Costs**: real modelling work up front, and a rig that has to be authored or found under a
  licence you can ship. Verify the licence before adopting any third-party rig or animation
  library — a rig licence is separate from the model licence.

Until this exists, the pipeline ships painted stills for characters and procedural animation for
buildings and props. That limitation is recorded in the main README rather than worked around.
