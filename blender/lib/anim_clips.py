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
    """Seeded, looping flicker on every light plus the emissive window material."""
    amount = float(params.get("amount", 0.22))
    cycles = float(params.get("cycles", 3.0))
    seed = float(params.get("seed", 7.0))
    t = 2.0 * math.pi * cycles * (index / max(1, total))
    factor = 1.0 + amount * (0.6 * math.sin(t + seed) + 0.4 * math.sin(2.3 * t + seed * 1.7))
    touched = 0
    for obj in bpy.data.objects:
        if obj.type == "LIGHT":
            if "base_energy" not in obj:
                obj["base_energy"] = obj.data.energy
            obj.data.energy = float(obj["base_energy"]) * factor
            touched += 1
    mat = bpy.data.materials.get("window_lit")
    if mat and mat.use_nodes:
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf and "Emission Strength" in bsdf.inputs:
            base = mat.get("base_emission", 6.0)
            mat["base_emission"] = base
            bsdf.inputs["Emission Strength"].default_value = float(base) * factor
    return {"factor": round(factor, 4), "lights": touched}


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


CLIPS: dict[str, dict[str, Any]] = {
    "banner_wave": {
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
}


def clip_names() -> list[str]:
    return sorted(CLIPS)


def apply_clip(scene: bpy.types.Scene, name: str, index: int, total: int,
               params: dict[str, Any] | None = None) -> dict[str, Any]:
    if name not in CLIPS:
        raise KeyError(f"unknown clip {name!r}; known: {clip_names()}")
    fn: Callable[..., dict[str, Any]] = CLIPS[name]["fn"]
    return fn(scene, index, total, params or {})
