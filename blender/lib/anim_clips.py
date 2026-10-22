"""Reusable animation clips for procedural assets.

A clip is a pure function of (frame index, frame count) that mutates the already-built
scene. That means one scene definition plus one clip yields a whole sequence with no
frame-to-frame identity drift - the failure mode of generating each frame from a prompt.

Clips are written to loop: frame 0 and frame N are the same pose, so `loop: true` assets
play seamlessly.
"""

from __future__ import annotations

import math
from typing import Any, Callable

import bpy


def _banner_objects() -> list[bpy.types.Object]:
    out = []
    for obj in bpy.data.objects:
        if obj.type == "MESH" and obj.data.shape_keys and any(
            kb.name.startswith("wave_") for kb in obj.data.shape_keys.key_blocks
        ):
            out.append(obj)
    return out


def _set_banner_phase(obj: bpy.types.Object, phase: float, phases: int) -> None:
    """Cross-fade the two shape keys adjacent to `phase` for a smooth travelling wave."""
    keys = [obj.data.shape_keys.key_blocks[f"wave_{i}"] for i in range(phases)]
    t = (phase % phases)
    i0 = int(math.floor(t)) % phases
    i1 = (i0 + 1) % phases
    frac = t - math.floor(t)
    for i, kb in enumerate(keys):
        if i == i0:
            kb.value = 1.0 - frac
        elif i == i1:
            kb.value = frac
        else:
            kb.value = 0.0


def banner_wave(scene: bpy.types.Scene, index: int, total: int, params: dict[str, Any]) -> dict[str, Any]:
    phases = int(params.get("phases", 4))
    cycles = float(params.get("cycles", 1.0))
    objects = _banner_objects()
    if not objects:
        raise RuntimeError("banner_wave clip needs an object with wave_* shape keys (set banner=true)")
    phase = (index / max(1, total)) * phases * cycles
    for obj in objects:
        _set_banner_phase(obj, phase, phases)
    return {"phase": round(phase, 4), "banners": len(objects)}


def torch_flicker(scene: bpy.types.Scene, index: int, total: int, params: dict[str, Any]) -> dict[str, Any]:
    """Seeded, looping flicker on every light plus the emissive material named by `material`.

    `material` defaults to `window_lit` but takes any emissive palette key, so a style that lights
    its windows crimson (`crimson_glow`) flickers those instead.
    """
    amount = float(params.get("amount", 0.22))
    cycles = float(params.get("cycles", 3.0))
    seed = float(params.get("seed", 7.0))
    material_name = str(params.get("material", "window_lit"))
    t = 2.0 * math.pi * cycles * (index / max(1, total))
    factor = 1.0 + amount * (0.6 * math.sin(t + seed) + 0.4 * math.sin(2.3 * t + seed * 1.7))
    touched = 0
    for obj in bpy.data.objects:
        if obj.type == "LIGHT":
            if "base_energy" not in obj:
                obj["base_energy"] = obj.data.energy
            obj.data.energy = float(obj["base_energy"]) * factor
            touched += 1
    mat = bpy.data.materials.get(material_name)
    if mat is None:
        raise RuntimeError(f"torch_flicker: no material named {material_name!r} in the scene")
    if mat.use_nodes:
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf and "Emission Strength" in bsdf.inputs:
            base = mat.get("base_emission", bsdf.inputs["Emission Strength"].default_value)
            mat["base_emission"] = base
            bsdf.inputs["Emission Strength"].default_value = float(base) * factor
    return {"factor": round(factor, 4), "lights": touched, "material": material_name}


def turntable(scene: bpy.types.Scene, index: int, total: int, params: dict[str, Any]) -> dict[str, Any]:
    """Orbit the camera around the subject - a full turn per loop."""
    cam = scene.camera
    if cam is None:
        raise RuntimeError("turntable clip needs a camera")
    turns = float(params.get("turns", 1.0))
    elevation = float(params.get("elevation", params.get("elevation_deg", 30.0)))
    distance = float(params.get("distance", 24.0))
    target = params.get("target", (0.0, 0.0, 0.0))
    azimuth = 360.0 * turns * (index / max(1, total))
    pitch = math.radians(90.0 - elevation)
    yaw = math.radians(azimuth)
    from mathutils import Euler, Vector

    cam.rotation_euler = Euler((pitch, 0.0, yaw), "XYZ")
    forward = cam.rotation_euler.to_matrix() @ Vector((0.0, 0.0, -1.0))
    cam.location = Vector(target) - forward * distance
    return {"azimuth": round(azimuth, 3)}


def wheel_spin(scene: bpy.types.Scene, index: int, total: int, params: dict[str, Any]) -> dict[str, Any]:
    """Spin anything named wheel* about its local Y - water wheels, grindstones."""
    turns = float(params.get("turns", 1.0))
    angle = 2.0 * math.pi * turns * (index / max(1, total))
    axis = params.get("axis", "y")
    count = 0
    for obj in bpy.data.objects:
        if obj.type == "MESH" and obj.name.lower().startswith("wheel"):
            base = obj.get("base_rotation")
            if base is None:
                base = list(obj.rotation_euler)
                obj["base_rotation"] = base
            rot = list(base)
            rot[{"x": 0, "y": 1, "z": 2}[axis]] = float(base[{"x": 0, "y": 1, "z": 2}[axis]]) + angle
            obj.rotation_euler = rot
            count += 1
    return {"angle_deg": round(math.degrees(angle), 3), "wheels": count}


def bob(scene: bpy.types.Scene, index: int, total: int, params: dict[str, Any]) -> dict[str, Any]:
    """Gentle vertical bob for floating or hanging props."""
    amplitude = float(params.get("amplitude", 0.08))
    cycles = float(params.get("cycles", 1.0))
    prefix = str(params.get("prefix", "bob"))
    offset = amplitude * math.sin(2.0 * math.pi * cycles * (index / max(1, total)))
    count = 0
    for obj in bpy.data.objects:
        if obj.type == "MESH" and obj.name.lower().startswith(prefix.lower()):
            base = obj.get("base_location")
            if base is None:
                base = list(obj.location)
                obj["base_location"] = base
            obj.location = (base[0], base[1], base[2] + offset)
            count += 1
    return {"offset": round(offset, 4), "objects": count}


# ---- rigged character clips -------------------------------------------------
#
# These pose an armature built by blender/reusable_rigs/humanoid.py. Like the scene clips above they
# are pure functions of the frame index, which is why a rigged sequence cannot drift between frames.
# Every bone a clip touches is set on every call: a bone left untouched keeps the previous frame's
# rotation and the loop stops closing.

def _rig() -> "bpy.types.Object":
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE":
            return obj
    raise RuntimeError("no armature in the scene; this clip needs a rigged subject")


def _pose(arm: "bpy.types.Object", name: str, *, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> None:
    """Set a bone rotation in degrees, in the bone's own axes.

    A bone's local **Y runs head to tail**, so the meaning of each axis depends on which way the
    bone points - the mistake that first turned a twist into a sideways bend:

    * vertical bones (root, hips, spine, chest, neck, head): local Y is up, so **y = twist/yaw**,
      x = forward/back bend, z = side bend.
    * bones hanging downward (upperarm, forearm, hand, thigh, shin): local Y points down, so
      **x = forward/back swing**, z = side sway, y = twist along the limb.
    * feet point forward and down, so x is roughly the ankle pitch.

    Getting this backwards is not subtle in motion - it shears the torso and slides the head off
    the neck - but it is invisible in a still frame, which is why it is written down here.
    """
    bone = arm.pose.bones.get(name)
    if bone is None:
        raise RuntimeError(f"no bone named {name!r}; the rig does not match this clip")
    bone.rotation_euler = (math.radians(x), math.radians(y), math.radians(z))


def _root_lift(arm: "bpy.types.Object", amount: float) -> None:
    """Raise the whole figure by `amount` world units.

    A pose bone's location is in its own local space, where **Y runs along the bone**. The root bone
    points up, so lifting is location.y - using location.z moves the character sideways instead of
    up, which is what the first walk did.
    """
    root = arm.pose.bones.get("root")
    if root is not None:
        root.location = (0.0, amount, 0.0)


def idle(scene: bpy.types.Scene, index: int, total: int, params: dict[str, Any]) -> dict[str, Any]:
    """Breathing plus a slow weight shift. Small amplitudes on purpose: an idle that reads as
    movement at sprite scale looks like a character who cannot stand still."""
    arm = _rig()
    phase = 2.0 * math.pi * index / max(1, total)
    amplitude = float(params.get("amplitude", 1.0))
    breathe = math.sin(phase) * amplitude
    sway = math.sin(phase + 0.9) * amplitude

    _pose(arm, "hips", y=sway * 1.2)
    _pose(arm, "spine", x=breathe * 1.8, y=sway * 0.8)
    _pose(arm, "chest", x=breathe * 2.2, y=-sway * 1.0)
    _pose(arm, "neck", x=-breathe * 1.2)
    _pose(arm, "head", x=-breathe * 1.6, y=sway * 2.4)
    for side, sign in (("L", 1.0), ("R", -1.0)):
        _pose(arm, f"upperarm.{side}", x=breathe * 2.4, z=sign * breathe * 1.6)
        _pose(arm, f"forearm.{side}", x=-breathe * 3.0)
        _pose(arm, f"hand.{side}", x=breathe * 1.5)
        _pose(arm, f"thigh.{side}", x=-sway * 0.8)
        _pose(arm, f"shin.{side}", x=max(0.0, sway * 1.2))
        _pose(arm, f"foot.{side}", x=0.0)
    _root_lift(arm, 0.006 * math.sin(2.0 * phase) * amplitude)
    return {"clip": "idle", "breathe": round(breathe, 4), "sway": round(sway, 4)}


def walk(scene: bpy.types.Scene, index: int, total: int, params: dict[str, Any]) -> dict[str, Any]:
    """A walk in place: legs alternate, arms counter-swing, hips bob twice per cycle.

    Loops by construction - every channel is a sine of `2*pi*index/total`, so the last frame steps
    back to the first by exactly one frame's worth of motion, which is what the loop check measures.
    """
    arm = _rig()
    phase = 2.0 * math.pi * index / max(1, total)
    stride = float(params.get("stride", 26.0))
    lift = float(params.get("lift", 1.0))
    swing = math.sin(phase)
    counter = math.sin(phase + math.pi)

    _pose(arm, "hips", x=2.0, y=counter * 3.0)
    _pose(arm, "spine", y=counter * 2.0)
    _pose(arm, "chest", x=-3.0, y=counter * -4.0)
    _pose(arm, "neck", x=2.0)
    _pose(arm, "head", y=counter * -1.5)

    for side, sign in (("L", 1.0), ("R", -1.0)):
        leg = swing * sign
        # The knee folds while the leg is behind the body, which is when a real knee bends.
        knee = 14.0 + 16.0 * max(0.0, -leg)
        _pose(arm, f"thigh.{side}", x=stride * leg)
        _pose(arm, f"shin.{side}", x=-knee)
        _pose(arm, f"foot.{side}", x=stride * leg * 0.35)
        _pose(arm, f"upperarm.{side}", x=-stride * 0.75 * leg, z=sign * 4.0)
        _pose(arm, f"forearm.{side}", x=-(10.0 + 12.0 * max(0.0, -leg)))
        _pose(arm, f"hand.{side}", x=-4.0)
    # Hips rise on the passing pose and drop on contact: two bobs per stride cycle.
    _root_lift(arm, (0.018 * math.cos(2.0 * phase) - 0.006) * lift)
    return {"clip": "walk", "phase": round(phase, 4), "stride": stride}


def _swing_curve(t: float) -> float:
    """0 -> -1 (wind up) -> +1 (strike) -> 0 (recover). Starts and ends at rest, so it loops."""
    def smooth(x: float) -> float:
        x = min(1.0, max(0.0, x))
        return x * x * (3.0 - 2.0 * x)

    if t < 0.30:
        return -smooth(t / 0.30)
    if t < 0.55:
        return -1.0 + 2.0 * smooth((t - 0.30) / 0.25)
    return 1.0 - smooth((t - 0.55) / 0.45)


def attack(scene: bpy.types.Scene, index: int, total: int, params: dict[str, Any]) -> dict[str, Any]:
    """One overhead swing per cycle: wind up, strike fast, recover slowly.

    Asymmetric on purpose - a symmetric sine reads as waving, not hitting.
    """
    arm = _rig()
    t = index / max(1, total)
    shaped = _swing_curve(t)
    power = float(params.get("power", 1.0))

    # Small per-joint rotations on purpose. They accumulate down the chain, and with rigid
    # skinning a large cumulative twist pulls consecutive segments apart at the seams - the torso
    # visibly sheared when this was 6/8/12 degrees. The arm carries the motion instead.
    _pose(arm, "hips", y=-6.0 * shaped * power)
    _pose(arm, "spine", x=-3.0 * shaped * power, y=-5.0 * shaped * power)
    _pose(arm, "chest", x=-4.0 * shaped * power, y=-7.0 * shaped * power)
    _pose(arm, "neck", x=2.0 * shaped * power)
    _pose(arm, "head", y=6.0 * shaped * power)
    for side, sign in (("L", 1.0), ("R", -1.0)):
        # The right arm leads; the left follows a beat behind.
        lead = shaped if side == "R" else _swing_curve(max(0.0, t - 0.06))
        # Negative X is *forward* on a downward-hanging arm (the walk relies on that). So the
        # wind-up is positive and the strike negative: the arm travels overhead from behind the
        # body to in front of it. A positive strike just pushes forward and reads as a shove.
        _pose(arm, f"upperarm.{side}", x=-70.0 * lead * power, z=sign * (5.0 - 8.0 * lead) * power)
        _pose(arm, f"forearm.{side}", x=(-28.0 - 18.0 * lead) * power)
        _pose(arm, f"hand.{side}", x=-6.0 * lead * power)
        _pose(arm, f"thigh.{side}", x=-4.0 * lead * power)
        _pose(arm, f"shin.{side}", x=8.0 + 3.0 * abs(lead))
        _pose(arm, f"foot.{side}", x=0.0)
    _root_lift(arm, -0.018 * abs(shaped) * power)
    return {"clip": "attack", "t": round(t, 4), "swing": round(shaped, 4)}


CLIPS: dict[str, dict[str, Any]] = {    "banner_wave": {
        "fn": banner_wave,
        "frames_default": 12,
        "requires": "an object built with banner=true",
        "description": "Cross-faded shape-key travelling wave across a banner.",
    },
    "torch_flicker": {
        "fn": torch_flicker,
        "frames_default": 12,
        "requires": "at least one light",
        "description": "Looping seeded flicker on lights and lit windows.",
    },
    "turntable": {
        "fn": turntable,
        "frames_default": 36,
        "requires": "a camera (set by generate_building.py)",
        "description": "Full 360 degree camera orbit; turn count configurable.",
    },
    "wheel_spin": {
        "fn": wheel_spin,
        "frames_default": 16,
        "requires": "an object named wheel*",
        "description": "Constant-rate rotation for water wheels and grindstones.",
    },
    "bob": {
        "fn": bob,
        "frames_default": 16,
        "requires": "objects whose name starts with the configured prefix",
        "description": "Sinusoidal vertical bob for floating props.",
    },
    "idle": {
        "fn": idle,
        "frames_default": 16,
        "requires": "an armature from blender/reusable_rigs/humanoid.py",
        "description": "Breathing plus weight shift; subtle by design.",
    },
    "walk": {
        "fn": walk,
        "frames_default": 16,
        "requires": "an armature from blender/reusable_rigs/humanoid.py",
        "description": "Walk in place: alternating stride, counter-swinging arms, two hip bobs.",
    },
    "attack": {
        "fn": attack,
        "frames_default": 12,
        "requires": "an armature from blender/reusable_rigs/humanoid.py",
        "description": "One overhead swing per cycle: wind up, fast strike, slow recovery.",
    },
}


def clip_names() -> list[str]:
    return sorted(CLIPS)

# Clips that move the camera rather than the subject. A validator that demands a stable subject
# centroid is measuring the wrong thing for these: a turntable *should* move the subject across
# the frame, which is the whole point of a turntable. Declared as a literal so the Python
# pipeline can read it without importing bpy.
CAMERA_MOVING_CLIPS: tuple[str, ...] = ("turntable",)


def apply_clip(scene: bpy.types.Scene, name: str, index: int, total: int,
               params: dict[str, Any] | None = None) -> dict[str, Any]:
    if name not in CLIPS:
        raise KeyError(f"unknown clip {name!r}; known: {clip_names()}")
    fn: Callable[..., dict[str, Any]] = CLIPS[name]["fn"]
    return fn(scene, index, total, params or {})
