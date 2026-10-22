# Reusable character rigs

Implemented. `humanoid.py` builds a skinned low-poly humanoid plus its armature, and the `idle`,
`walk` and `attack` clips in `blender/lib/anim_clips.py` pose it.

```bash
blender -b --factory-startup --python blender/render_animation.py -- \
    --scene reusable_rigs.humanoid --clip walk --frame-count 16 \
    --out-dir assets/animations/vampire_thrall_walk
```

Through the pipeline it is just another Blender generator: `blender.generator` in the manifest names
`reusable_rigs/humanoid.py`, the stage converts that to the module name `reusable_rigs.humanoid`, and
nothing else changes. Three assets ship: `vampire_thrall_idle`, `_walk`, `_attack`.

## Why a rig instead of per-frame prompts

Every other animated asset here is a clip driving an already-built scene, and a rigged character
needs that property more than a building does: generating each pose from a prompt produces a
character whose face, equipment and proportions drift between frames. Here the mesh is built once and
only bone rotations change, so the character is identical in every frame by construction.

## The contract a rig must satisfy

1. **`DEFAULTS` plus `build(params)`**, the same shape as the building and prop generators. That is
   all `render_animation.py` needs.
2. **Clips are pure functions of the frame index** - `(scene, index, total, params)` - added to
   `blender/lib/anim_clips.py`. A clip that reads a previous frame's state does not loop.
3. **Every bone a clip touches is set on every call.** A bone left untouched keeps the previous
   frame's rotation and the loop stops closing.
4. **The rig is reusable across subjects.** `humanoid.py` is parameterised by height, build, palette
   and optional mantle/hood; a second character is a manifest entry, not a second script.

## Two decisions worth knowing before editing

**Rigid skinning, not bone heat.** Each body part is weighted 1.0 to exactly one bone. Blender's
automatic weights (`ARMATURE_AUTO`) runs a heat solver that fails on overlapping or non-manifold
geometry - which is what a body built from intersecting primitives is - and it fails
*non-deterministically* across builds. Rigid segments with overlapping ball joints at the shoulders,
elbows, hips and knees deform without a solver and are identical on every machine. The cost is no
smooth crease at a joint; at sprite scale that is the right trade.

**Bone axes depend on which way the bone points.** A bone's local Y runs head to tail, so:

| bone | local Y | `x` | `y` | `z` |
| --- | --- | --- | --- | --- |
| vertical (root, hips, spine, chest, neck, head) | up | forward/back bend | **twist / yaw** | side bend |
| hanging down (upperarm, forearm, hand, thigh, shin) | down | forward/back swing | twist along the limb | side sway |
| foot | forward, down | ankle pitch | - | - |

Getting this backwards is invisible in a still frame and violent in motion: an early version used `z`
for a torso twist, which is a *sideways bend*, and the torso sheared while the head slid off the neck.

## Weighting is written per vertex, never inferred

Weights go into a bmesh deform layer for the exact vertices each primitive op returns. Guessing new
geometry by index range or by element-identity sets does not work - bmesh does not guarantee new
elements land at the end of the index order, and freed elements leave dangling references. Both
guesses were tried here and both produced mis-assigned vertices: a shin rendered in boot leather, then
a spike dragged across the head whenever the pose changed.

## What is still missing

A second rig (quadruped, or a character with a weapon hand), and blend weights at the joints so a
severe bend does not show a hard edge. Both are additive: the contract above is what the pipeline
depends on.
