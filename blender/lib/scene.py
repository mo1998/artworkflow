"""Shared Blender scene construction for the pipeline's procedural generators.

Design rules that make the procedural path worth having:
  * The camera never depends on the subject's size. It targets the world origin with a
    fixed orthographic scale, so every building tier of a family renders to the same
    framing and stacks in a spritesheet without rescaling.
  * Renders are transparent-film: geometry only. Ground is added by the game, not baked
    into the sprite, which is why procedural assets skip the background-removal stage.
  * Everything is driven by explicit parameters, so a rerun reproduces a known result
    exactly - the opposite of a diffusion reroll.

Run with: blender -b --factory-startup --python <script> -- --param value
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Euler, Vector

SUMMARY_MARKER = "ARTWORKFLOW_JSON"

# A restrained, game-legible palette. Named keys are the contract between the
# generators and any future material work.
PALETTE: dict[str, dict[str, object]] = {
    "plaster": {"color": (0.84, 0.80, 0.71), "roughness": 0.85},
    "timber": {"color": (0.26, 0.17, 0.11), "roughness": 0.75},
    "dark_timber": {"color": (0.16, 0.11, 0.08), "roughness": 0.8},
    "stone": {"color": (0.52, 0.51, 0.48), "roughness": 0.9},
    "thatch": {"color": (0.52, 0.39, 0.19), "roughness": 0.95},
    "tile": {"color": (0.36, 0.14, 0.12), "roughness": 0.6},
    "shingle": {"color": (0.24, 0.20, 0.17), "roughness": 0.7},
    "banner": {"color": (0.52, 0.08, 0.11), "roughness": 0.85},
    "bronze": {"color": (0.55, 0.42, 0.20), "roughness": 0.35, "metallic": 0.7},
    "iron": {"color": (0.35, 0.36, 0.38), "roughness": 0.45, "metallic": 0.8},
    # Gothic vampire direction. Named materials are the contract between a style block and the
    # procedural generators, so a new art direction adds palette entries rather than new scripts.
    "window_lit": {"color": (0.060, 0.040, 0.020), "roughness": 0.50,
                   "emission": (0.95, 0.60, 0.26), "emission_strength": 1.0},
    "obsidian": {"color": (0.115, 0.115, 0.135), "roughness": 0.65},
    "black_timber": {"color": (0.085, 0.068, 0.062), "roughness": 0.8},
    "bone": {"color": (0.80, 0.77, 0.68), "roughness": 0.85},
    "dry_blood": {"color": (0.24, 0.045, 0.045), "roughness": 0.9},
    "blood_banner": {"color": (0.42, 0.025, 0.045), "roughness": 0.85},
    "crimson_glow": {"color": (0.05, 0.015, 0.02), "roughness": 0.45,
                     "emission": (0.80, 0.055, 0.085), "emission_strength": 1.0},
    # Slate blue-grey: matches the painted roofs, which is what makes procedural and painted
    # assets read as one village instead of two.
    "slate": {"color": (0.165, 0.185, 0.235), "roughness": 0.72},
    "slate_dark": {"color": (0.105, 0.120, 0.160), "roughness": 0.75},
    "cold_moon": {"color": (0.05, 0.06, 0.10), "roughness": 0.4,
                  "emission": (0.55, 0.62, 0.95), "emission_strength": 1.0},
    # Character palette. Skin and cloth need their own entries rather than borrowing the building
    # materials: plaster reads as plaster on a wall and as a mannequin on a face.
    "skin_pale": {"color": (0.62, 0.55, 0.52), "roughness": 0.70},
    "hair_black": {"color": (0.035, 0.030, 0.035), "roughness": 0.55},
    "cloth_crimson": {"color": (0.21, 0.045, 0.070), "roughness": 0.86},
    "cloth_dark": {"color": (0.105, 0.095, 0.120), "roughness": 0.84},
    "leather": {"color": (0.165, 0.110, 0.075), "roughness": 0.74},
}


# ---- CLI -------------------------------------------------------------------

def parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def cli_args(defaults: dict[str, object]) -> dict[str, object]:
    """Parse `--key value` flags after Blender's `--` separator, typed from defaults."""
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser(add_help=False)
    for key, default in defaults.items():
        flag = "--" + key.replace("_", "-")
        if isinstance(default, bool):
            parser.add_argument(flag, type=parse_bool, default=default)
        elif isinstance(default, int):
            parser.add_argument(flag, type=int, default=default)
        elif isinstance(default, float):
            parser.add_argument(flag, type=float, default=default)
        else:
            parser.add_argument(flag, default=default)
    known, _ = parser.parse_known_args(argv)
    out = {k: v for k, v in vars(known).items()}
    # JSON blobs arrive as strings; decode the ones the callers use as structured data.
    for key in ("params", "extra"):
        if isinstance(out.get(key), str) and out[key].strip().startswith("{"):
            out[key] = json.loads(out[key])
    return out


def emit_summary(payload: dict[str, object]) -> None:
    print(f"{SUMMARY_MARKER} {json.dumps(payload, default=str)}", flush=True)


def fail(message: str) -> None:
    print(f"BLENDER_ERROR {message}", file=sys.stderr, flush=True)
    raise SystemExit(3)


# ---- scene -----------------------------------------------------------------

def reset_scene(*, film_transparent: bool = True, engine: str = "BLENDER_EEVEE_NEXT") -> bpy.types.Scene:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = engine
    scene.render.film_transparent = film_transparent
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.resolution_percentage = 100
    scene.render.fps = 12
    # Standard transform keeps the exported colours predictable instead of
    # film-look tone mapped; agents and humans both read these sprites better.
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0
    return scene


def setup_render(scene: bpy.types.Scene, *, width: int, height: int, samples: int,
                 filepath: str | None = None, frame: int | None = None) -> None:
    scene.render.resolution_x = int(width)
    scene.render.resolution_y = int(height)
    engine = scene.render.engine
    if engine == "BLENDER_EEVEE_NEXT":
        eevee = scene.eevee
        if hasattr(eevee, "taa_render_samples"):
            eevee.taa_render_samples = max(8, int(samples))
        if hasattr(eevee, "use_raytracing"):
            eevee.use_raytracing = True
    elif engine == "CYCLES":
        scene.cycles.samples = max(8, int(samples))
        scene.cycles.use_denoising = True
    if frame is not None:
        scene.frame_set(int(frame))
    if filepath:
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        scene.render.filepath = str(filepath)


CAMERA_VIEWS = {
    # name: (azimuth_deg, elevation_deg) - azimuth measured around +Z from -Y
    "iso": (45.0, 30.0),          # classic game isometric (dimetric, 2:1 feel)
    "iso_true": (45.0, 35.264),   # true isometric
    "topdown": (0.0, 90.0),
    "front": (0.0, 0.0),
    "three_quarter": (35.0, 22.0),
}


def setup_camera(scene: bpy.types.Scene, *, view: str = "iso", ortho_scale: float = 6.0,
                 target: tuple[float, float, float] = (0.0, 0.0, 0.0),
                 azimuth: float | None = None, elevation: float | None = None,
                 distance: float = 24.0) -> bpy.types.Object:
    """Orthographic camera aimed at `target`.

    `ortho_scale` is the width of the visible world box, so it is independent of the
    subject: change the building, keep the framing.
    """
    default_az, default_el = CAMERA_VIEWS.get(view, CAMERA_VIEWS["iso"])
    az = float(default_az if azimuth is None else azimuth)
    el = float(default_el if elevation is None else elevation)

    cam_data = bpy.data.cameras.new("Camera")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = float(ortho_scale)
    cam_data.clip_start = 0.01
    cam_data.clip_end = 400.0
    cam = bpy.data.objects.new("Camera", cam_data)
    bpy.context.collection.objects.link(cam)

    # Camera euler that yields the requested view: pitch from horizontal, then yaw.
    pitch = math.radians(90.0 - el)
    yaw = math.radians(az)
    cam.rotation_euler = Euler((pitch, 0.0, yaw), "XYZ")
    forward = cam.rotation_euler.to_matrix() @ Vector((0.0, 0.0, -1.0))
    cam.location = Vector(target) - forward * float(distance)

    scene.camera = cam
    return cam


def setup_lights(*, key_energy: float = 4.0, fill_energy: float = 1.4, rim_energy: float = 1.0,
                 azimuth: float = 45.0, elevation: float = 55.0) -> dict[str, bpy.types.Object]:
    """Three-light rig; deterministic, no HDRI dependency."""
    scene = bpy.context.scene
    lights: dict[str, bpy.types.Object] = {}

    sun_data = bpy.data.lights.new("KeySun", type="SUN")
    sun_data.energy = float(key_energy)
    sun_data.angle = math.radians(6.0)
    sun = bpy.data.objects.new("KeySun", sun_data)
    sun.rotation_euler = Euler((math.radians(90.0 - elevation), 0.0, math.radians(azimuth)), "XYZ")
    bpy.context.collection.objects.link(sun)
    lights["key"] = sun

    for name, energy, az, el in (("Fill", fill_energy, azimuth + 150.0, 25.0),
                                 ("Rim", rim_energy, azimuth - 120.0, 35.0)):
        data = bpy.data.lights.new(name, type="AREA")
        data.energy = float(energy) * 220.0
        data.size = 9.0
        obj = bpy.data.objects.new(name, data)
        pitch = math.radians(90.0 - el)
        obj.rotation_euler = Euler((pitch, 0.0, math.radians(az)), "XYZ")
        forward = obj.rotation_euler.to_matrix() @ Vector((0.0, 0.0, -1.0))
        obj.location = -forward * 14.0
        bpy.context.collection.objects.link(obj)
        lights[name.lower()] = obj

    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs[0].default_value = (0.55, 0.56, 0.58, 1.0)
        bg.inputs[1].default_value = 0.55
    return lights


# ---- materials -------------------------------------------------------------

def get_material(name: str) -> bpy.types.Material:
    existing = bpy.data.materials.get(name)
    if existing:
        return existing
    if name not in PALETTE:
        # Loud failure beats a silent grey fallback: a typo in a manifest's wall_material would
        # otherwise produce a whole batch of plausible-looking, wrongly-coloured assets.
        fail(f"unknown material {name!r}; known materials: {sorted(PALETTE)}")
    spec = PALETTE[name]
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        color = tuple(spec.get("color", (0.6, 0.6, 0.6)))  # type: ignore[arg-type]
        bsdf.inputs["Base Color"].default_value = (*color, 1.0)
        bsdf.inputs["Roughness"].default_value = float(spec.get("roughness", 0.8))  # type: ignore[arg-type]
        if spec.get("metallic"):
            bsdf.inputs["Metallic"].default_value = float(spec["metallic"])  # type: ignore[arg-type]
        if spec.get("emission") and "Emission Color" in bsdf.inputs:
            emission = tuple(spec["emission"])  # type: ignore[arg-type]
            bsdf.inputs["Emission Color"].default_value = (*emission, 1.0)
            bsdf.inputs["Emission Strength"].default_value = float(spec.get("emission_strength", 4.0))  # type: ignore[arg-type]
    return mat


def assign(obj: bpy.types.Object, material: str | None) -> bpy.types.Object:
    if material:
        obj.data.materials.clear()
        obj.data.materials.append(get_material(material))
    return obj


# ---- geometry --------------------------------------------------------------

def mesh_object(name: str, verts: list[tuple[float, float, float]],
                faces: list[tuple[int, ...]], *, location: tuple[float, float, float] = (0.0, 0.0, 0.0),
                rotation: tuple[float, float, float] = (0.0, 0.0, 0.0), material: str | None = None,
                smooth: bool = False) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.validate()
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    if smooth:
        for poly in mesh.polygons:
            poly.use_smooth = True
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    obj.rotation_euler = Euler(rotation, "XYZ")
    bpy.context.collection.objects.link(obj)
    return assign(obj, material)


def add_prism(name: str, outline: list[tuple[float, float]], height: float, *,
              location: tuple[float, float, float] = (0.0, 0.0, 0.0),
              rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
              material: str | None = None, smooth: bool = False) -> bpy.types.Object:
    """Extrude a closed 2D outline in Z. Used for anything with a silhouette, e.g. a coffin."""
    if len(outline) < 3:
        raise ValueError("outline needs at least 3 points")
    half = height / 2.0
    verts = [(x, y, -half) for x, y in outline] + [(x, y, half) for x, y in outline]
    n = len(outline)
    faces: list[tuple[int, ...]] = [tuple(range(n)), tuple(range(n, 2 * n))[::-1]]
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, j, n + j, n + i))
    return mesh_object(name, verts, faces, location=location, rotation=rotation,
                       material=material, smooth=smooth)


def add_sphere(name: str, *, radius: float, location: tuple[float, float, float] = (0.0, 0.0, 0.0),
               segments: int = 20, rings: int = 10, material: str | None = None,
               smooth: bool = True) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=int(segments), v_segments=int(rings),
                              radius=float(radius))
    bm.to_mesh(mesh)
    bm.free()
    if smooth:
        for poly in mesh.polygons:
            poly.use_smooth = True
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    bpy.context.collection.objects.link(obj)
    return assign(obj, material)


def add_box(name: str, size: tuple[float, float, float], *, location: tuple[float, float, float] = (0.0, 0.0, 0.0),
            rotation: tuple[float, float, float] = (0.0, 0.0, 0.0), material: str | None = None) -> bpy.types.Object:
    sx, sy, sz = (d / 2.0 for d in size)
    verts = [(-sx, -sy, -sz), (sx, -sy, -sz), (sx, sy, -sz), (-sx, sy, -sz),
             (-sx, -sy, sz), (sx, -sy, sz), (sx, sy, sz), (-sx, sy, sz)]
    faces = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    return mesh_object(name, verts, faces, location=location, rotation=rotation, material=material)


def add_cylinder(name: str, *, radius: float, height: float, segments: int = 16,
                 location: tuple[float, float, float] = (0.0, 0.0, 0.0),
                 rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
                 material: str | None = None, smooth: bool = True) -> bpy.types.Object:
    return _add_cone(name, radius1=radius, radius2=radius, height=height, segments=segments,
                     location=location, rotation=rotation, material=material, smooth=smooth)


def add_cone(name: str, *, radius: float, height: float, segments: int = 16,
             location: tuple[float, float, float] = (0.0, 0.0, 0.0),
             rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
             material: str | None = None, smooth: bool = False) -> bpy.types.Object:
    return _add_cone(name, radius1=radius, radius2=0.0, height=height, segments=segments,
                     location=location, rotation=rotation, material=material, smooth=smooth)


def _add_cone(name: str, *, radius1: float, radius2: float, height: float, segments: int,
              location: tuple[float, float, float], rotation: tuple[float, float, float],
              material: str | None, smooth: bool) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=int(segments),
                          radius1=float(radius1), radius2=float(radius2), depth=float(height))
    bm.to_mesh(mesh)
    bm.free()
    if smooth:
        for poly in mesh.polygons:
            poly.use_smooth = True
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    obj.rotation_euler = Euler(rotation, "XYZ")
    bpy.context.collection.objects.link(obj)
    return assign(obj, material)


def add_gable_roof(name: str, *, width: float, depth: float, height: float,
                   overhang: float = 0.12, material: str | None = None,
                   location: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> bpy.types.Object:
    """Triangular prism ridge running along X (the building's long axis)."""
    hw = width / 2.0 + overhang
    hd = depth / 2.0 + overhang
    verts = [(-hw, -hd, 0.0), (hw, -hd, 0.0), (hw, hd, 0.0), (-hw, hd, 0.0),
             (-hw, 0.0, height), (hw, 0.0, height)]
    faces = [(0, 1, 2, 3), (0, 1, 5, 4), (2, 3, 4, 5), (0, 3, 4), (1, 2, 5)]
    return mesh_object(name, verts, faces, location=location, material=material)


def add_hip_roof(name: str, *, width: float, depth: float, height: float,
                 overhang: float = 0.12, material: str | None = None,
                 location: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> bpy.types.Object:
    """Rectangular pyramid - four sloped faces meeting at a point."""
    hw = width / 2.0 + overhang
    hd = depth / 2.0 + overhang
    ridge = max(height, min(width, depth) * 0.35)
    verts = [(-hw, -hd, 0.0), (hw, -hd, 0.0), (hw, hd, 0.0), (-hw, hd, 0.0), (0.0, 0.0, ridge)]
    faces = [(0, 1, 2, 3), (0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)]
    return mesh_object(name, verts, faces, location=location, material=material)


def add_flat_roof(name: str, *, width: float, depth: float, thickness: float = 0.14,
                  overhang: float = 0.16, material: str | None = None,
                  location: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> bpy.types.Object:
    return add_box(name, (width + overhang * 2, depth + overhang * 2, thickness),
                   location=(location[0], location[1], location[2] + thickness / 2.0),
                   material=material)


def add_banner(name: str, *, width: float, height: float, origin: tuple[float, float, float],
               axis: str = "x", segments_x: int = 12, segments_y: int = 6,
               phases: int = 4, amplitude: float = 0.16,
               material: str = "banner") -> bpy.types.Object:
    """A subdivided plane with `phases` shape keys, each a travelling wave offset.

    The animation stage cross-fades between these keys, which gives a real deforming
    cloth loop instead of a sequence of unrelated generated images.
    """
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for iy in range(segments_y + 1):
        for ix in range(segments_x + 1):
            u = ix / segments_x
            v = iy / segments_y
            verts.append((u * width - width / 2.0, 0.0, -v * height))
    for iy in range(segments_y):
        for ix in range(segments_x):
            a = iy * (segments_x + 1) + ix
            b = a + 1
            c = a + segments_x + 1
            d = c + 1
            faces.append((a, b, d, c))

    obj = mesh_object(name, verts, faces, location=origin, material=material)
    base = obj.shape_key_add(name="Basis", from_mix=False)
    _ = base
    count = len(obj.data.vertices)
    for phase_index in range(phases):
        key = obj.shape_key_add(name=f"wave_{phase_index}", from_mix=False)
        phase = 2.0 * math.pi * phase_index / phases
        for vi in range(count):
            co = obj.data.vertices[vi].co
            u = (co.x + width / 2.0) / width if axis == "x" else (co.z + height) / height
            # Travelling wave; amplitude grows toward the free end so the hoist stays put.
            offset = amplitude * u * math.sin(2.0 * math.pi * (1.1 * u) - phase)
            key.data[vi].co = (co.x + offset if axis == "x" else co.x,
                               offset if axis != "x" else co.y,
                               co.z + (offset if axis != "x" else 0.0))
    obj.data.shape_keys.key_blocks["Basis"].value = 0.0
    for kb in obj.data.shape_keys.key_blocks:
        kb.value = 0.0
    return obj


def add_ground_plate(name: str = "Ground", *, size: float = 6.0, material: str = "stone",
                     z: float = -0.01) -> bpy.types.Object:
    """Optional contact plate. Off by default: sprites ship without baked ground."""
    return add_box(name, (size, size, 0.02), location=(0.0, 0.0, z), material=material)


def bevel_hard_edges(width: float = 0.016, segments: int = 2, angle_limit: float = 25.0,
                     skip: tuple[str, ...] = ("Banner", "Ground")) -> int:
    """Bevel every hard edge in the scene.

    Without this, flat-shaded primitives read as untextured CAD blocks: no highlight
    runs along an edge, so the silhouette is the only shape cue. A sub-centimetre bevel
    is enough to catch the key light and make procedural assets look intentional.
    """
    touched = 0
    for obj in bpy.data.objects:
        if obj.type != "MESH" or obj.name in skip or obj.data.shape_keys:
            continue
        mod = obj.modifiers.new("EdgeBevel", "BEVEL")
        mod.width = float(width)
        mod.segments = int(segments)
        mod.limit_method = "ANGLE"
        mod.angle_limit = math.radians(float(angle_limit))
        mod.harden_normals = False
        touched += 1
    return touched


def scene_bounds() -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    """World-space bounding box over every mesh in the scene, modifiers evaluated.

    Measuring beats guessing: the old framer estimated the subject's size from its parameters
    with a fudge factor, which cropped the top off the tallest upgrade tier of a family.
    """
    from mathutils import Vector

    low = [float("inf")] * 3
    high = [float("-inf")] * 3
    found = False
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        evaluated = obj.evaluated_get(depsgraph)
        matrix = evaluated.matrix_world
        for corner in evaluated.bound_box:
            world = matrix @ Vector(corner)
            for axis in range(3):
                low[axis] = min(low[axis], world[axis])
                high[axis] = max(high[axis], world[axis])
            found = True
    if not found:
        return None
    return (tuple(low), tuple(high))  # type: ignore[return-value]


def fit_framing(bounds: tuple[tuple[float, float, float], tuple[float, float, float]], *,
                view: str = "iso", azimuth: float | None = None, elevation: float | None = None,
                res_x: int = 1024, res_y: int = 1024, margin: float = 1.10) -> tuple[float, float]:
    """Orthographic scale and camera-target height that fit `bounds` exactly.

    Projects the bounding box into camera space, so the result is correct for any view rather
    than tuned for one. The target keeps x/y at the world origin, which is what holds a family's
    ground line steady while the buildings above it grow.

    Returns (ortho_scale, target_z).
    """
    from mathutils import Euler, Vector

    (lx, ly, lz), (hx, hy, hz) = bounds
    target_z = (lz + hz) / 2.0
    default_az, default_el = CAMERA_VIEWS.get(view, CAMERA_VIEWS["iso"])
    az = float(default_az if azimuth is None else azimuth)
    el = float(default_el if elevation is None else elevation)
    rot = Euler((math.radians(90.0 - el), 0.0, math.radians(az)), "XYZ").to_matrix()
    right = rot @ Vector((1.0, 0.0, 0.0))
    up = rot @ Vector((0.0, 1.0, 0.0))

    max_x = 0.0
    max_y = 0.0
    for x in (lx, hx):
        for y in (ly, hy):
            for z in (lz, hz):
                offset = Vector((x, y, z - target_z))
                max_x = max(max_x, abs(offset.dot(right)))
                max_y = max(max_y, abs(offset.dot(up)))
    aspect = float(res_x) / float(res_y)  # visible height is ortho_scale / aspect
    ortho = max(2.0 * max_x * margin, 2.0 * max_y * margin * aspect)
    return (max(ortho, 0.01), target_z)


def union_bounds(boxes: list[tuple[tuple[float, float, float], tuple[float, float, float]]]) -> tuple:
    """Smallest box containing all of `boxes` - how a whole upgrade-tier family gets framed."""
    low = [min(b[0][i] for b in boxes) for i in range(3)]
    high = [max(b[1][i] for b in boxes) for i in range(3)]
    return (tuple(low), tuple(high))


# ---- output ----------------------------------------------------------------

def render_still(scene: bpy.types.Scene, path: str) -> str:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    return str(path)


def object_stats() -> dict[str, object]:
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    return {
        "mesh_objects": len(meshes),
        "vertices": sum(len(o.data.vertices) for o in meshes),
        "polygons": sum(len(o.data.polygons) for o in meshes),
        "materials": sorted({m.name for m in bpy.data.materials}),
    }
