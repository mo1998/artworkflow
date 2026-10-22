"""A reusable skinned humanoid rig, built procedurally.

This is the contract `render_animation.py` expects from any rig: `DEFAULTS` plus
`build(params)`, the same shape as the building and prop generators. One rig drives any subject,
which is why the body is described by parameters (height, build, palette, optional mantle and
hood) rather than hardcoded geometry.

Two decisions worth knowing before editing:

**Rigid skinning, not bone heat.** Every body part is weighted 1.0 to exactly one bone. Blender's
automatic weights (`ARMATURE_AUTO`) runs a heat solver that fails on overlapping or
non-manifold geometry - exactly what a body built from intersecting primitives is - and it fails
*non-deterministically* across builds. Rigid segments with overlapping ball joints at the shoulders,
elbows, hips and knees deform without a solver, read correctly at sprite scale, and are identical on
every machine. The cost is no smooth skin crease at a joint; at 512 px with a stylised palette that
is the right trade.

**Bones point down the limb.** A bone's local Y runs head→tail, so for a limb hanging downward
local X is the forward/back swing axis. Clips rely on that: `rotation_euler.x` is a swing,
`rotation_euler.z` is a side sway.

    blender -b --factory-startup --python blender/render_animation.py -- \
        --scene reusable_rigs.humanoid --clip walk --frame-count 16 \
        --out-dir assets/animations/vampire_thrall_walk
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1]),
                 str(Path(__file__).resolve().parents[1] / "lib")]

import bmesh  # noqa: E402
import bpy  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402

import scene as S  # noqa: E402

DEFAULTS: dict[str, object] = {
    # subject
    "height": 1.80,
    "build": 1.0,            # 1.0 = average, >1 broader, <1 slimmer
    "skin_material": "skin_pale",
    "hair_material": "hair_black",
    "cloth_material": "cloth_crimson",
    "trouser_material": "cloth_dark",
    "trim_material": "iron",
    "belt_material": "leather",
    "eye_material": "crimson_glow",
    "mantle": True,          # short shoulder cape
    "hood": False,
    "eye_glow": True,
    "seed": 0,
    # render (same keys as the other generators, so the pipeline treats this identically)
    "engine": "BLENDER_EEVEE_NEXT",
    "res_x": 1024,
    "res_y": 1024,
    "samples": 64,
    "view": "three_quarter",
    "ortho_scale": 0.0,
    "frame_target_z": -1.0,
    "frame_bounds": "",
    "measure_only": False,
    "out": "",
    "key_energy": 3.0,
    "fill_energy": 1.1,
    "azimuth": 35.0,
}

# Rig definition: name -> (head, tail, parent, deform). Coordinates are for a 1.80 unit figure and
# are scaled by `height / 1.80`. `.L` is +X, `.R` is -X.
BONES: list[tuple[str, tuple[float, float, float], tuple[float, float, float], str | None, bool]] = [
    ("root", (0.0, 0.0, 0.00), (0.0, 0.0, 0.22), None, False),
    ("hips", (0.0, 0.0, 0.94), (0.0, 0.0, 1.08), "root", True),
    ("spine", (0.0, 0.0, 1.08), (0.0, 0.0, 1.30), "hips", True),
    ("chest", (0.0, 0.0, 1.30), (0.0, 0.0, 1.50), "spine", True),
    ("neck", (0.0, 0.0, 1.50), (0.0, 0.0, 1.60), "chest", True),
    ("head", (0.0, 0.0, 1.60), (0.0, 0.0, 1.80), "neck", True),
]
for _side, _sx in (("L", 1.0), ("R", -1.0)):
    BONES += [
        (f"upperarm.{_side}", (_sx * 0.20, 0.0, 1.46), (_sx * 0.27, 0.0, 1.18), "chest", True),
        (f"forearm.{_side}", (_sx * 0.27, 0.0, 1.18), (_sx * 0.30, 0.0, 0.96), f"upperarm.{_side}", True),
        (f"hand.{_side}", (_sx * 0.30, 0.0, 0.96), (_sx * 0.31, 0.0, 0.88), f"forearm.{_side}", True),
        (f"thigh.{_side}", (_sx * 0.10, 0.0, 0.92), (_sx * 0.10, 0.0, 0.50), "hips", True),
        (f"shin.{_side}", (_sx * 0.10, 0.0, 0.50), (_sx * 0.10, 0.0, 0.09), f"thigh.{_side}", True),
        (f"foot.{_side}", (_sx * 0.10, 0.0, 0.09), (_sx * 0.10, -0.17, 0.03), f"shin.{_side}", True),
    ]


class _Body:
    """Accumulates primitives into one mesh while tracking bone weights and material slots.

    Weights are written into a bmesh deform layer for the exact vertices each op returns. Guessing
    at new geometry by index range does not work: bmesh does not guarantee that new elements are
    appended to the end of the index order, and a wrong guess assigns a head vertex to the chest
    group - which shows up as a spike dragged across the model when the pose changes.
    """

    def __init__(self, bone_names: list[str]) -> None:
        self.bmesh = bmesh.new()
        self.deform = self.bmesh.verts.layers.deform.verify()
        self.group_index = {name: index for index, name in enumerate(bone_names)}
        self.materials: list[str] = []

    def _material_index(self, material: str) -> int:
        if material not in self.materials:
            self.materials.append(material)
        return self.materials.index(material)

    def _assign(self, verts: list, bone: str, material: str) -> None:
        group = self.group_index[bone]
        for vert in verts:
            weights = vert[self.deform]
            weights.clear()
            weights[group] = 1.0
        material_index = self._material_index(material)
        # Faces incident to these vertices are exactly this primitive's faces.
        for face in {face for vert in verts for face in vert.link_faces}:
            face.material_index = material_index

    def box(self, bone: str, material: str, center: tuple[float, float, float],
            size: tuple[float, float, float], *, rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> None:
        matrix = (Matrix.Translation(Vector(center))
                  @ Matrix.Rotation(rotation[2], 4, "Z")
                  @ Matrix.Rotation(rotation[1], 4, "Y")
                  @ Matrix.Rotation(rotation[0], 4, "X")
                  @ Matrix.Diagonal((*size, 1.0)))
        result = bmesh.ops.create_cube(self.bmesh, size=1.0, matrix=matrix)
        self._assign(result["verts"], bone, material)

    def taper(self, bone: str, material: str, head: tuple[float, float, float],
              tail: tuple[float, float, float], radius_head: float, radius_tail: float,
              *, segments: int = 10) -> None:
        """A limb segment from head to tail, radius tapering."""
        p0, p1 = Vector(head), Vector(tail)
        direction = p1 - p0
        length = max(direction.length, 1e-5)
        rotation = direction.to_track_quat("Z", "Y").to_matrix().to_4x4()
        matrix = Matrix.Translation((p0 + p1) / 2.0) @ rotation
        result = bmesh.ops.create_cone(self.bmesh, cap_ends=True, cap_tris=False, segments=segments,
                                       radius1=radius_head, radius2=radius_tail, depth=length,
                                       matrix=matrix)
        self._assign(result["verts"], bone, material)

    def ball(self, bone: str, material: str, center: tuple[float, float, float], radius: float,
             *, scale: tuple[float, float, float] = (1.0, 1.0, 1.0),
             segments: int = 14, rings: int = 8) -> None:
        matrix = Matrix.Translation(Vector(center)) @ Matrix.Diagonal((*scale, 1.0))
        result = bmesh.ops.create_uvsphere(self.bmesh, u_segments=segments, v_segments=rings,
                                           radius=radius, matrix=matrix)
        self._assign(result["verts"], bone, material)

    def cone(self, bone: str, material: str, center: tuple[float, float, float], radius: float,
             height: float, *, segments: int = 8,
             rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> None:
        matrix = (Matrix.Translation(Vector(center))
                  @ Matrix.Rotation(rotation[0], 4, "X")
                  @ Matrix.Rotation(rotation[1], 4, "Y")
                  @ Matrix.Rotation(rotation[2], 4, "Z"))
        result = bmesh.ops.create_cone(self.bmesh, cap_ends=True, cap_tris=False, segments=segments,
                                       radius1=radius, radius2=0.0, depth=height, matrix=matrix)
        self._assign(result["verts"], bone, material)


def build(params: dict[str, object]) -> dict[str, object]:
    """Build the skinned mesh and its armature. Returns the same info dict as the other generators."""
    height = float(params["height"])
    build_scale = float(params["build"])
    unit = height / 1.80
    skin = str(params["skin_material"])
    hair = str(params["hair_material"])
    cloth = str(params["cloth_material"])
    trousers = str(params["trouser_material"])
    trim = str(params["trim_material"])
    belt = str(params["belt_material"])
    eye = str(params["eye_material"])

    def p(x: float, y: float, z: float) -> tuple[float, float, float]:
        """Scale a 1.80-unit rig coordinate into this figure, widening by `build`."""
        return (x * unit * build_scale, y * unit * build_scale, z * unit)

    body = _Body([name for name, *_rest in BONES])
    shoulder_w = 0.19 * build_scale

    # ---- torso ------------------------------------------------------------
    body.box("hips", trousers, p(0.0, 0.0, 0.96), (0.30 * unit * build_scale, 0.19 * unit, 0.17 * unit))
    body.box("spine", cloth, p(0.0, 0.0, 1.15), (0.30 * unit * build_scale, 0.19 * unit, 0.18 * unit))
    body.box("chest", cloth, p(0.0, 0.0, 1.35), (0.34 * unit * build_scale, 0.20 * unit, 0.22 * unit))
    body.box("hips", belt, p(0.0, 0.0, 1.03), (0.33 * unit * build_scale, 0.21 * unit, 0.05 * unit))
    body.box("chest", trim, p(0.0, -0.10 * build_scale, 1.32), (0.06 * unit, 0.025 * unit, 0.14 * unit))

    # ---- neck and head ----------------------------------------------------
    body.taper("neck", skin, p(0.0, 0.0, 1.48), p(0.0, 0.0, 1.60), 0.055 * unit, 0.050 * unit)
    body.ball("head", skin, p(0.0, 0.0, 1.68), 0.120 * unit, scale=(1.0, 1.05, 1.12))
    # Hair is a flattened cap sitting on top and slightly back. A full sphere of the head radius
    # reads as a helmet, and one offset backwards protrudes as a wedge from a three-quarter view.
    body.ball("head", hair, p(0.0, 0.024, 1.722), 0.122 * unit, scale=(1.02, 1.02, 0.62))
    body.ball("head", hair, p(0.0, 0.072, 1.652), 0.116 * unit, scale=(0.94, 0.72, 1.0))
    if bool(params.get("hood", False)):
        body.cone("head", cloth, p(0.0, 0.03, 1.77), 0.18 * unit, 0.26 * unit)
    if bool(params.get("eye_glow", True)):
        for sx in (-1.0, 1.0):
            body.box("head", eye, (sx * 0.042 * unit * build_scale, -0.112 * unit, 1.700 * unit),
                     (0.030 * unit, 0.020 * unit, 0.020 * unit))

    # ---- arms -------------------------------------------------------------
    for side, sx in (("L", 1.0), ("R", -1.0)):
        body.ball(f"upperarm.{side}", cloth, (sx * 0.200 * unit * build_scale, 0.0, 1.440 * unit),
                  0.075 * unit, segments=12)
        body.taper(f"upperarm.{side}", cloth, p(sx * 0.205, 0.0, 1.430), p(sx * 0.245, 0.0, 1.160),
                   0.058 * unit, 0.046 * unit)
        body.ball(f"forearm.{side}", skin, p(sx * 0.245, 0.0, 1.150), 0.046 * unit, segments=10)
        body.taper(f"forearm.{side}", skin, p(sx * 0.245, 0.0, 1.140), p(sx * 0.265, 0.0, 0.940),
                   0.044 * unit, 0.036 * unit)
        body.box(f"hand.{side}", skin, p(sx * 0.268, 0.0, 0.900),
                 (0.058 * unit, 0.042 * unit, 0.095 * unit))

    # ---- legs -------------------------------------------------------------
    for side, sx in (("L", 1.0), ("R", -1.0)):
        body.ball(f"thigh.{side}", trousers, p(sx * 0.090, 0.0, 0.920), 0.082 * unit, segments=12)
        body.taper(f"thigh.{side}", trousers, p(sx * 0.090, 0.0, 0.910), p(sx * 0.095, 0.0, 0.510),
                   0.082 * unit, 0.064 * unit)
        body.ball(f"shin.{side}", trousers, p(sx * 0.095, 0.0, 0.500), 0.062 * unit, segments=10)
        body.taper(f"shin.{side}", trousers, p(sx * 0.095, 0.0, 0.490), p(sx * 0.098, 0.0, 0.100),
                   0.060 * unit, 0.046 * unit)
        body.box(f"foot.{side}", belt, p(sx * 0.098, -0.040, 0.050),
                 (0.100 * unit, 0.230 * unit, 0.090 * unit))

    # ---- shoulder mantle ---------------------------------------------------
    # Short on purpose: a full-length cape hides the arm swing, which is the only thing the walk
    # and attack clips have to show.
    if bool(params.get("mantle", True)):
        body.taper("chest", cloth, p(0.0, 0.015, 1.470), p(0.0, 0.015, 1.350),
                   0.170 * unit * build_scale, 0.215 * unit * build_scale, segments=12)

    # ---- mesh object ------------------------------------------------------
    mesh = bpy.data.meshes.new("ThrallMesh")
    body.bmesh.to_mesh(mesh)
    body.bmesh.free()
    mesh.validate()
    for polygon in mesh.polygons:
        polygon.use_smooth = True

    for name in body.materials:
        mesh.materials.append(S.get_material(name))

    mesh_obj = bpy.data.objects.new("Thrall", mesh)
    bpy.context.collection.objects.link(mesh_obj)
    # One group per bone, created in the same order the deform layer used, so the layer's group
    # indices line up with the object's vertex groups.
    for bone_name, _index in sorted(body.group_index.items(), key=lambda item: item[1]):
        mesh_obj.vertex_groups.new(name=bone_name)

    # ---- armature ---------------------------------------------------------
    armature = bpy.data.armatures.new("ThrallRig")
    arm_obj = bpy.data.objects.new("ThrallRig", armature)
    bpy.context.collection.objects.link(arm_obj)

    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode="EDIT")
    for name, head, tail, parent, deform in BONES:
        bone = armature.edit_bones.new(name)
        # Same transform as the mesh, `build` widening included: a broader figure with
        # unwidened bones would deform around the wrong axis.
        bone.head = Vector(p(*head))
        bone.tail = Vector(p(*tail))
        bone.use_deform = deform
        if parent:
            bone.parent = armature.edit_bones[parent]
            bone.use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")

    for pose_bone in arm_obj.pose.bones:
        pose_bone.rotation_mode = "XYZ"

    modifier = mesh_obj.modifiers.new("Armature", "ARMATURE")
    modifier.object = arm_obj
    modifier.use_vertex_groups = True
    mesh_obj.parent = arm_obj

    # The rest pose is the frame clips revert to; keep it as the bound pose.
    armature.pose_position = "POSE"

    bounds = S.scene_bounds()
    top = bounds[1][2] if bounds else height
    horizontal = max(abs(bounds[0][0]), abs(bounds[1][0]), abs(bounds[0][1]), abs(bounds[1][1])) if bounds else 0.4
    return {"subject_top": top, "horizontal": horizontal, "roof_height": 0.0,
            "bevelled": 0, "kind": "humanoid", "bones": len(armature.bones)}


def main() -> None:
    params = S.cli_args({**DEFAULTS})
    measure_only = bool(params.get("measure_only"))
    out = str(params.get("out") or "").strip()
    if not out and not measure_only:
        S.fail("--out is required")

    scene = S.reset_scene(engine=str(params["engine"]))
    info = build(params)
    S.setup_lights(key_energy=float(params["key_energy"]), fill_energy=float(params["fill_energy"]),
                   azimuth=float(params["azimuth"]))

    bounds = S.scene_bounds()
    ortho = float(params["ortho_scale"])
    target_z = float(params["frame_target_z"])
    if ortho <= 0.0 or target_z < 0.0:
        from generate_building import bounds_from_param  # one decoder for the family bounds blob

        fitted_ortho, fitted_z = S.fit_framing(
            bounds_from_param(params.get("frame_bounds")) or bounds,
            view=str(params["view"]), azimuth=float(params["azimuth"]),
            res_x=int(params["res_x"]), res_y=int(params["res_y"]), margin=1.12)
        if ortho <= 0.0:
            ortho = fitted_ortho
        if target_z < 0.0:
            target_z = fitted_z

    if measure_only:
        S.emit_summary({"ok": True, "measure_only": True, "kind": "humanoid",
                        "bounds": {"lo": list(bounds[0]), "hi": list(bounds[1])},
                        "subject_top": round(float(info["subject_top"]), 4),
                        "ortho_scale": round(ortho, 4), "frame_target_z": round(target_z, 4),
                        "res": [int(params["res_x"]), int(params["res_y"])],
                        "bones": int(info["bones"]), **S.object_stats()})
        return

    S.setup_camera(scene, view=str(params["view"]), ortho_scale=ortho, target=(0.0, 0.0, target_z))
    S.setup_render(scene, width=int(params["res_x"]), height=int(params["res_y"]),
                   samples=int(params["samples"]))
    S.render_still(scene, out)

    S.emit_summary({"ok": Path(out).exists(), "out": out, "kind": "humanoid",
                    "seed": int(params["seed"]), "engine": scene.render.engine,
                    "ortho_scale": round(ortho, 4), "frame_target_z": round(target_z, 4),
                    "bounds": {"lo": list(bounds[0]), "hi": list(bounds[1])},
                    "res": [int(params["res_x"]), int(params["res_y"])],
                    "bones": int(info["bones"]), **S.object_stats()})


if __name__ == "__main__":
    main()
