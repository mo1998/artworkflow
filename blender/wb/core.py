"""Warbands v2 scene core: palette, primitives, camera framing and render passes.

Every subject (building, wall card, wall surface, terrain tile, backdrop) is built from
these parts, so one palette, one sun and one camera serve the whole set. Renders are
deterministic: the same job JSON produces the same pixels.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

import bmesh
import bpy
from mathutils import Euler, Vector

# ---- camera / light: the set's single art direction ------------------------------
ISO_ELEVATION = 30.0   # 2:1 dimetric, the game's own projection
ISO_AZIMUTH = 45.0
# light from the screen's upper left: the -Y (left) face is lit, +X (right) is shade
SUN_DIR = Vector((0.62, 0.55, -0.68)).normalized()
SUN_COLOR = (1.0, 0.90, 0.76)
SUN_STRENGTH = 3.6
SKY_COLOR = (0.52, 0.60, 0.70)
SKY_STRENGTH = 0.75

# ---- palette: name -> base colour, roughness, variation ----------------------------
PALETTE: dict[str, dict] = {
    "timber": {"color": (0.15, 0.09, 0.05), "rough": 0.8, "vary": 0.25, "grain": True},
    "timber_light": {"color": (0.46, 0.31, 0.17), "rough": 0.8, "vary": 0.2, "grain": True},
    "plank": {"color": (0.24, 0.15, 0.08), "rough": 0.85, "vary": 0.25, "grain": True},
    "log": {"color": (0.27, 0.18, 0.11), "rough": 0.9, "vary": 0.3, "grain": True},
    "log_end": {"color": (0.66, 0.48, 0.28), "rough": 0.8, "vary": 0.15},
    "turf": {"color": (0.17, 0.32, 0.06), "rough": 0.95, "vary": 0.35, "nscale": 9.0},
    "thatch": {"color": (0.55, 0.42, 0.20), "rough": 0.95, "vary": 0.25},
    "shingle": {"color": (0.24, 0.19, 0.15), "rough": 0.8, "vary": 0.3},
    "stone": {"color": (0.46, 0.45, 0.42), "rough": 0.9, "vary": 0.3, "nscale": 6.0},
    "stone_dark": {"color": (0.28, 0.28, 0.27), "rough": 0.9, "vary": 0.3},
    "rock": {"color": (0.36, 0.35, 0.33), "rough": 0.95, "vary": 0.35, "nscale": 3.0},
    "iron": {"color": (0.20, 0.20, 0.22), "rough": 0.45, "metal": 0.8, "vary": 0.1},
    "bronze": {"color": (0.58, 0.40, 0.17), "rough": 0.35, "metal": 0.8, "vary": 0.1},
    "gold": {"color": (0.85, 0.62, 0.20), "rough": 0.3, "metal": 0.9, "vary": 0.05},
    "banner": {"color": (0.50, 0.05, 0.06), "rough": 0.85, "vary": 0.15},
    "cloth": {"color": (0.56, 0.46, 0.31), "rough": 0.9, "vary": 0.15},
    "cloth_blue": {"color": (0.13, 0.24, 0.42), "rough": 0.9, "vary": 0.15},
    "window": {"color": (0.06, 0.04, 0.02), "rough": 0.5, "emit": (1.0, 0.55, 0.18), "emit_k": 1.2},
    "fire": {"color": (0.9, 0.35, 0.08), "rough": 0.5, "emit": (1.0, 0.40, 0.08), "emit_k": 3.0},
    "dark": {"color": (0.025, 0.02, 0.02), "rough": 0.9, "vary": 0.0},
    "grass": {"color": (0.16, 0.32, 0.07), "rough": 0.95, "vary": 0.3, "nscale": 5.0},
    "earth": {"color": (0.26, 0.17, 0.10), "rough": 0.95, "vary": 0.3},
    "dirt": {"color": (0.38, 0.27, 0.16), "rough": 0.95, "vary": 0.25, "nscale": 7.0},
    "hay": {"color": (0.78, 0.62, 0.26), "rough": 0.95, "vary": 0.2},
    "crop": {"color": (0.62, 0.55, 0.18), "rough": 0.95, "vary": 0.3, "nscale": 12.0},
    "crop_green": {"color": (0.22, 0.38, 0.10), "rough": 0.95, "vary": 0.3, "nscale": 12.0},
    "clay": {"color": (0.58, 0.36, 0.24), "rough": 0.7, "vary": 0.2},
    "clay_wet": {"color": (0.40, 0.30, 0.25), "rough": 0.4, "vary": 0.2},
    "brick": {"color": (0.62, 0.32, 0.20), "rough": 0.85, "vary": 0.25},
    "ore": {"color": (0.17, 0.13, 0.12), "rough": 0.7, "vary": 0.4, "metal": 0.3},
    "slag": {"color": (0.12, 0.11, 0.11), "rough": 0.8, "vary": 0.3},
    "water": {"color": (0.10, 0.22, 0.27), "rough": 0.15, "vary": 0.1},
    "rope": {"color": (0.55, 0.45, 0.30), "rough": 0.9, "vary": 0.1},
    "bone": {"color": (0.82, 0.78, 0.68), "rough": 0.8, "vary": 0.1},
    "mortar": {"color": (0.30, 0.29, 0.26), "rough": 0.95, "vary": 0.3},
    "leaf": {"color": (0.07, 0.17, 0.08), "rough": 0.95, "vary": 0.35, "nscale": 5.0},
    "leaf_far": {"color": (0.10, 0.20, 0.17), "rough": 0.95, "vary": 0.25},
    "mountain": {"color": (0.30, 0.34, 0.40), "rough": 0.95, "vary": 0.3, "nscale": 0.8},
    "snow": {"color": (0.85, 0.88, 0.92), "rough": 0.7, "vary": 0.05},
    "sand": {"color": (0.72, 0.62, 0.44), "rough": 0.95, "vary": 0.2},
}


def reset() -> bpy.types.Scene:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    _gpu(scene)
    return scene


def _gpu(scene: bpy.types.Scene) -> None:
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
    except KeyError:
        return
    for kind in ("OPTIX", "CUDA"):
        try:
            prefs.compute_device_type = kind
            prefs.get_devices()
            gpus = [d for d in prefs.devices if d.type == kind]
            if gpus:
                for d in prefs.devices:
                    d.use = d.type == kind
                scene.cycles.device = "GPU"
                return
        except (TypeError, AttributeError):
            continue


# ---- materials ---------------------------------------------------------------------

def material(name: str) -> bpy.types.Material:
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    if name not in PALETTE:
        raise SystemExit(f"unknown material {name!r}")
    spec = PALETTE[name]
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = spec.get("rough", 0.8)
    bsdf.inputs["Metallic"].default_value = spec.get("metal", 0.0)
    color = (*spec["color"], 1.0)
    vary = float(spec.get("vary", 0.2))
    if vary > 0:
        tc = nt.nodes.new("ShaderNodeTexCoord")
        noise = nt.nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = float(spec.get("nscale", 4.0))
        noise.inputs["Detail"].default_value = 6.0
        if spec.get("grain"):
            # wood grain: a noise stretched along Z reads as long fibres
            mapping = nt.nodes.new("ShaderNodeMapping")
            mapping.inputs["Scale"].default_value = (6.0, 6.0, 0.6)
            nt.links.new(tc.outputs["Object"], mapping.inputs["Vector"])
            nt.links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
        else:
            nt.links.new(tc.outputs["Object"], noise.inputs["Vector"])
        rng = nt.nodes.new("ShaderNodeMapRange")
        rng.inputs["From Min"].default_value = 0.3
        rng.inputs["From Max"].default_value = 0.7
        rng.inputs["To Min"].default_value = 1.0 - vary
        rng.inputs["To Max"].default_value = 1.0 + vary
        nt.links.new(noise.outputs["Fac"], rng.inputs["Value"])
        hsv = nt.nodes.new("ShaderNodeHueSaturation")
        hsv.inputs["Color"].default_value = color
        nt.links.new(rng.outputs["Result"], hsv.inputs["Value"])
        nt.links.new(hsv.outputs["Color"], bsdf.inputs["Base Color"])
        bump = nt.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.25
        nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
        nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    else:
        bsdf.inputs["Base Color"].default_value = color
    if spec.get("emit"):
        bsdf.inputs["Emission Color"].default_value = (*spec["emit"], 1.0)
        bsdf.inputs["Emission Strength"].default_value = float(spec.get("emit_k", 2.0))
    return mat


# ---- frames and primitives --------------------------------------------------------

class F:
    """A placement frame: translate + rotate about Z. Parts are written in local space."""

    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0, rz: float = 0.0):
        self.x, self.y, self.z, self.rz = x, y, z, rz

    def p(self, lx: float, ly: float, lz: float) -> tuple[float, float, float]:
        c, s = math.cos(self.rz), math.sin(self.rz)
        return (self.x + lx * c - ly * s, self.y + lx * s + ly * c, self.z + lz)

    def sub(self, lx: float, ly: float, lz: float = 0.0, rz: float = 0.0) -> "F":
        x, y, z = self.p(lx, ly, lz)
        return F(x, y, z, self.rz + rz)


ORIGIN = F()
_count = [0]


def _name(mat: str) -> str:
    _count[0] += 1
    return f"{mat}.{_count[0]:04d}"


def _obj(me: bpy.types.Mesh, mat: str, loc, rot, bevel: float) -> bpy.types.Object:
    obj = bpy.data.objects.new(me.name, me)
    obj.location = loc
    obj.rotation_euler = Euler(rot, "XYZ")
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material(mat))
    obj["wb_mat"] = mat
    if bevel > 0:
        mod = obj.modifiers.new("bevel", "BEVEL")
        mod.width = bevel
        mod.segments = 2
        mod.limit_method = "ANGLE"
        mod.angle_limit = math.radians(30)
    return obj


def mesh(verts, faces, mat: str, f: F = ORIGIN, at=(0, 0, 0), rot=(0, 0, 0), bevel=0.0, smooth=False):
    me = bpy.data.meshes.new(_name(mat))
    me.from_pydata([tuple(v) for v in verts], [], [tuple(x) for x in faces])
    me.validate()
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    if smooth:
        for poly in me.polygons:
            poly.use_smooth = True
    return _obj(me, mat, f.p(*at), (rot[0], rot[1], rot[2] + f.rz), bevel)


def box(size, at, mat: str, f: F = ORIGIN, rot=(0, 0, 0), bevel=0.02):
    """Box with its BOTTOM centre at `at` (local), size (x, y, z)."""
    sx, sy, sz = (d / 2.0 for d in size)
    v = [(-sx, -sy, 0), (sx, -sy, 0), (sx, sy, 0), (-sx, sy, 0),
         (-sx, -sy, 2 * sz), (sx, -sy, 2 * sz), (sx, sy, 2 * sz), (-sx, sy, 2 * sz)]
    faces = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    return mesh(v, faces, mat, f, at, rot, bevel=min(bevel, min(size) * 0.3))


def cyl(r, h, at, mat: str, f: F = ORIGIN, rot=(0, 0, 0), seg=12, r2=None, smooth=True, bevel=0.0):
    """Cylinder/frustum along local Z from `at` upward (before `rot`)."""
    r2 = r if r2 is None else r2
    me = bpy.data.meshes.new(_name(mat))
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=seg, radius1=r, radius2=r2, depth=h)
    bmesh.ops.translate(bm, verts=bm.verts, vec=(0, 0, h / 2.0))
    bm.to_mesh(me)
    bm.free()
    if smooth:
        for poly in me.polygons:
            poly.use_smooth = True
    return _obj(me, mat, f.p(*at), (rot[0], rot[1], rot[2] + f.rz), bevel)


def cone(r, h, at, mat: str, f: F = ORIGIN, seg=12, smooth=False):
    return cyl(r, h, at, mat, f, seg=seg, r2=0.0, smooth=smooth)


def blob(r, at, mat: str, f: F = ORIGIN, squash=(1, 1, 1), seed=0, rough=0.18, sub=2):
    """A lumpy rock / heap: an icosphere with deterministic vertex noise."""
    rng = random.Random(seed)
    me = bpy.data.meshes.new(_name(mat))
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=sub, radius=r)
    for v in bm.verts:
        k = 1.0 + rng.uniform(-rough, rough)
        v.co = Vector((v.co.x * k * squash[0], v.co.y * k * squash[1], v.co.z * k * squash[2]))
    bm.to_mesh(me)
    bm.free()
    return _obj(me, mat, f.p(*at), (0, 0, f.rz), 0.0)


# ---- camera and lights ----------------------------------------------------------------

def iso_basis() -> tuple[Vector, Vector, Vector, Euler]:
    rot = Euler((math.radians(90 - ISO_ELEVATION), 0.0, math.radians(ISO_AZIMUTH)), "XYZ")
    m = rot.to_matrix()
    return m @ Vector((1, 0, 0)), m @ Vector((0, 1, 0)), m @ Vector((0, 0, -1)), rot


def projected_extents(right: Vector, up: Vector, fwd: Vector) -> dict:
    """Exact extents of all geometry in the camera plane (modifiers evaluated)."""
    dg = bpy.context.evaluated_depsgraph_get()
    r0 = u0 = d0 = float("inf")
    r1 = u1 = d1 = float("-inf")
    for obj in bpy.data.objects:
        if obj.type != "MESH" or obj.get("wb_plate"):
            continue  # the plate is the footprint, not the subject: it never sizes the frame
        ev = obj.evaluated_get(dg)
        me = ev.to_mesh()
        mw = ev.matrix_world
        for v in me.vertices:
            w = mw @ v.co
            r, u, d = w.dot(right), w.dot(up), w.dot(fwd)
            r0, r1, u0, u1, d0, d1 = min(r0, r), max(r1, r), min(u0, u), max(u1, u), min(d0, d), max(d1, d)
        ev.to_mesh_clear()
    return {"r": [r0, r1], "u": [u0, u1], "d": [d0, d1]}


def iso_camera(scene, ext: dict, res: int, pad_px: float, fill_px: float) -> bpy.types.Object:
    """Ortho iso camera: the extents fill `fill_px` and their bottom sits `pad_px` above
    the canvas bottom, horizontally centred - the sprite contract, done by the camera."""
    _, _, fwd, rot = iso_basis()
    span = max(ext["r"][1] - ext["r"][0], ext["u"][1] - ext["u"][0])
    S = span * res / fill_px
    data = bpy.data.cameras.new("Cam")
    data.type = "ORTHO"
    data.ortho_scale = S
    data.clip_start = 0.1
    data.clip_end = 500
    data.shift_x = ((ext["r"][0] + ext["r"][1]) / 2) / S
    data.shift_y = (ext["u"][0] + (0.5 - pad_px / res) * S) / S
    cam = bpy.data.objects.new("Cam", data)
    cam.rotation_euler = rot
    cam.location = -fwd * 60.0
    bpy.context.collection.objects.link(cam)
    scene.camera = cam
    return cam


def lights(scene, sun_dir: Vector = SUN_DIR, strength: float = SUN_STRENGTH, sky=SKY_COLOR,
           sky_k: float = SKY_STRENGTH, angle_deg: float = 4.0):
    data = bpy.data.lights.new("Sun", type="SUN")
    data.energy = strength
    data.color = SUN_COLOR
    data.angle = math.radians(angle_deg)
    sun = bpy.data.objects.new("Sun", data)
    sun.rotation_euler = sun_dir.to_track_quat("-Z", "Y").to_euler()
    bpy.context.collection.objects.link(sun)
    world = bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (*sky, 1.0)
    bg.inputs[1].default_value = sky_k
    return sun


# ---- passes -------------------------------------------------------------------------

def _emission_material(name: str, build) -> bpy.types.Material:
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    build(nt, em)
    return mat


def _depth_material(d0: float, d1: float) -> bpy.types.Material:
    def build(nt, em):
        cam = nt.nodes.new("ShaderNodeCameraData")
        rng = nt.nodes.new("ShaderNodeMapRange")
        rng.clamp = True
        rng.inputs["From Min"].default_value = d0
        rng.inputs["From Max"].default_value = d1
        rng.inputs["To Min"].default_value = 1.0   # near = white (ControlNet convention)
        rng.inputs["To Max"].default_value = 0.1
        nt.links.new(cam.outputs["View Z Depth"], rng.inputs["Value"])
        nt.links.new(rng.outputs["Result"], em.inputs["Color"])
    return _emission_material("pass_depth", build)


def _normal_material() -> bpy.types.Material:
    def build(nt, em):
        geo = nt.nodes.new("ShaderNodeNewGeometry")
        vt = nt.nodes.new("ShaderNodeVectorTransform")
        vt.vector_type = "NORMAL"
        vt.convert_from = "WORLD"
        vt.convert_to = "CAMERA"
        mul = nt.nodes.new("ShaderNodeVectorMath")
        mul.operation = "MULTIPLY_ADD"
        mul.inputs[1].default_value = (0.5, 0.5, 0.5)
        mul.inputs[2].default_value = (0.5, 0.5, 0.5)
        nt.links.new(geo.outputs["Normal"], vt.inputs["Vector"])
        nt.links.new(vt.outputs["Vector"], mul.inputs[0])
        nt.links.new(mul.outputs["Vector"], em.inputs["Color"])
    return _emission_material("pass_normal", build)


def _id_color(name: str) -> tuple[float, float, float]:
    rng = random.Random(sum((i + 1) * ord(c) for i, c in enumerate(name)))
    return (rng.uniform(0.1, 1.0), rng.uniform(0.1, 1.0), rng.uniform(0.1, 1.0))


def _flat_material(name: str, col) -> bpy.types.Material:
    def build(nt, em):
        em.inputs["Color"].default_value = (*col, 1.0)
    return _emission_material(name, build)


def render_passes(scene, out_dir: Path, res: tuple[int, int], samples: int,
                  depth_range: tuple[float, float]) -> dict:
    """beauty (lit, RGBA), depth (16-bit, near white), normal (camera space), matid (flat, aliased)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    scene.render.resolution_x, scene.render.resolution_y = res
    written = {}

    def shot(name: str, depth: str = "8"):
        scene.render.image_settings.color_depth = depth
        scene.render.filepath = str(out_dir / f"{name}.png")
        bpy.ops.render.render(write_still=True)
        written[name] = scene.render.filepath

    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.cycles.seed = 0
    scene.view_settings.view_transform = "Standard"
    shot("beauty")
    # the plate only catches shadows in the beauty pass; in the data passes it is the ground
    # (depth/normal for ControlNet) and the footprint (matid)
    for obj in bpy.data.objects:
        if obj.get("wb_plate"):
            obj.is_shadow_catcher = False
    # data passes: raw values, no tone mapping, no denoise, no dither (dither breaks exact ids)
    scene.view_settings.view_transform = "Raw"
    scene.render.dither_intensity = 0.0
    scene.cycles.use_denoising = False
    vl = scene.view_layers[0]
    scene.cycles.samples = 16
    vl.material_override = _depth_material(*depth_range)
    shot("depth", "16")
    vl.material_override = _normal_material()
    shot("normal")
    vl.material_override = None
    ids: dict[str, bpy.types.Material] = {}
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        key = obj.get("wb_mat", "x")
        if key not in ids:
            ids[key] = _flat_material(f"id_{key}", _id_color(key))
        obj.data.materials.clear()
        obj.data.materials.append(ids[key])
    scene.cycles.samples = 1
    scene.cycles.filter_width = 0.01
    # transparent film for the id pass: alpha 0 = sky / no geometry (the horizon gate needs it)
    scene.render.film_transparent = True
    shot("matid")
    scene.cycles.filter_width = 1.5
    return written


def footprint() -> list[float]:
    """World XY bounds of everything except the plate: must stay inside the game cell."""
    dg = bpy.context.evaluated_depsgraph_get()
    lo = [float("inf")] * 2
    hi = [float("-inf")] * 2
    for obj in bpy.data.objects:
        if obj.type != "MESH" or obj.get("wb_plate"):
            continue
        ev = obj.evaluated_get(dg)
        me = ev.to_mesh()
        for v in me.vertices:
            w = ev.matrix_world @ v.co
            if w.z > 0.6:
                continue  # roof overhangs and banners are allowed over the lane; walls are not
            for i in range(2):
                lo[i], hi[i] = min(lo[i], w[i]), max(hi[i], w[i])
        ev.to_mesh_clear()
    return [lo[0], lo[1], hi[0], hi[1]]


def emit(payload: dict) -> None:
    print("WB_JSON " + json.dumps(payload), flush=True)
