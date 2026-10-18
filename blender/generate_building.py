"""Procedural building generator - the deterministic half of the pipeline.

One parameter set in, one transparent-background PNG out, identical every run. Because
the camera targets the world origin with a fixed orthographic scale, a family of upgrade
tiers renders to identical framing and stacks in the game without rescaling.

Usage (the pipeline does this for you; direct use is for debugging and manual rerolls):
    blender -b --factory-startup --python blender/generate_building.py -- \
        --kind hut --width 2.4 --depth 2.2 --wall-height 1.5 \
        --res-x 1024 --res-y 1024 --out assets/incoming/demo_hut.png
"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

sys.path[:0] = [str(_p) for _p in (Path(__file__).resolve().parent,
                                   Path(__file__).resolve().parent / "lib")]

import bpy  # noqa: E402
import scene as S  # noqa: E402

DEFAULTS: dict[str, object] = {
    # subject
    "kind": "hut",
    "width": 2.4,
    "depth": 2.2,
    "wall_height": 1.5,
    "wall_material": "plaster",
    "roof": "gable",
    "roof_material": "thatch",
    "window_material": "window_lit",
    "door_material": "dark_timber",
    "post_material": "timber",
    "banner_material": "banner",
    "plinth": True,
    "plinth_material": "stone",
    "door": True,
    "windows": 2,
    "chimney": False,
    "banner": False,
    "battlements": False,
    "seed": 0,
    # render
    "engine": "BLENDER_EEVEE_NEXT",
    "res_x": 1024,
    "res_y": 1024,
    "samples": 64,
    "view": "iso",
    "ortho_scale": 0.0,      # 0 = fit exactly to the scene bounds
    "frame_target_z": -1.0,  # <0 = derive from the bounds
    "frame_bounds": "",      # JSON {"lo":[..],"hi":[..]} union over an upgrade-tier family
    "measure_only": False,   # build the scene, report its bounds, render nothing
    "out": "",
    # lighting
    "key_energy": 4.0,
    "fill_energy": 1.4,
    "azimuth": 45.0,
}


def roof_height(params: dict[str, object]) -> float:
    width = float(params["width"])
    depth = float(params["depth"])
    roof = str(params["roof"])
    short = min(width, depth)
    if roof == "gable":
        return max(0.4, short * 0.55)
    if roof == "hip":
        return max(0.4, short * 0.6)
    if roof == "cone":
        return max(0.9, max(width, depth) * 0.85)
    return 0.14


def build(params: dict[str, object]) -> dict[str, object]:
    rng = random.Random(int(params["seed"]))
    width, depth = float(params["width"]), float(params["depth"])
    wall_h = float(params["wall_height"])
    wall_material = str(params["wall_material"])
    roof_kind = str(params["roof"])
    roof_material = str(params["roof_material"])
    window_material = str(params.get("window_material", "window_lit"))
    door_material = str(params.get("door_material", "dark_timber"))
    post_material = str(params.get("post_material", "timber"))
    banner_material = str(params.get("banner_material", "banner"))
    plinth_h = 0.18 if bool(params["plinth"]) else 0.0
    top_of_walls = plinth_h + wall_h
    roof_h = roof_height(params)
    objects: dict[str, object] = {}

    if bool(params["plinth"]):
        objects["plinth"] = S.add_box(
            "Plinth", (width + 0.26, depth + 0.26, plinth_h),
            location=(0.0, 0.0, plinth_h / 2.0), material=str(params["plinth_material"]),
        )

    kind = str(params["kind"])
    if kind == "tower":
        radius = min(width, depth) / 2.0
        objects["tower"] = S.add_cylinder(
            "Tower", radius=radius, height=wall_h, segments=16,
            location=(0.0, 0.0, plinth_h + wall_h / 2.0), material=wall_material,
        )
        objects["roof"] = S.add_cone(
            "Roof", radius=radius * 1.16, height=max(0.9, radius * 2.0), segments=16,
            location=(0.0, 0.0, top_of_walls + max(0.9, radius * 2.0) / 2.0), material=roof_material,
        )
    else:
        objects["walls"] = S.add_box(
            "Walls", (width, depth, wall_h),
            location=(0.0, 0.0, plinth_h + wall_h / 2.0), material=wall_material,
        )
        for name, (dx, dy) in {"PostA": (-1, -1), "PostB": (1, -1), "PostC": (1, 1), "PostD": (-1, 1)}.items():
            objects[name] = S.add_box(
                f"Post{name[-1]}", (0.16, 0.16, wall_h + 0.06),
                location=(dx * (width / 2.0), dy * (depth / 2.0), plinth_h + (wall_h + 0.06) / 2.0),
                material=post_material,
            )
        # A parapet with merlons sits *above* the wall and the roof is set back inside it.
        # Merlons placed at the wall top under an overhanging roof read as a row of blocks
        # stuck to the roof slope, which is what the first vampire keep looked like.
        parapet_h = 0.30 if bool(params["battlements"]) else 0.0
        if parapet_h:
            S.add_box("Parapet", (width + 0.24, depth + 0.24, parapet_h),
                      location=(0.0, 0.0, top_of_walls + parapet_h / 2.0), material=wall_material)
            merlon_z = top_of_walls + parapet_h + 0.17
            count_x = max(3, int(width / 0.60))
            count_y = max(2, int(depth / 0.60))
            for i in range(count_x):
                x = -width / 2.0 + (i + 0.5) * (width / count_x)
                for side in (1.0, -1.0):
                    S.add_box(f"Merlon{i}{'F' if side > 0 else 'B'}", (0.29, 0.29, 0.34),
                              location=(x, side * (depth / 2.0 + 0.12), merlon_z),
                              material=wall_material)
            for i in range(count_y):
                y = -depth / 2.0 + (i + 0.5) * (depth / count_y)
                for side in (1.0, -1.0):
                    S.add_box(f"MerlonY{i}{'R' if side > 0 else 'L'}", (0.29, 0.29, 0.34),
                              location=(side * (width / 2.0 + 0.12), y, merlon_z),
                              material=wall_material)
            top_of_walls += parapet_h

        roof_offset = top_of_walls
        inset = 0.94 if parapet_h else 1.0
        overhang = 0.05 if parapet_h else 0.12
        if roof_kind == "gable":
            objects["roof"] = S.add_gable_roof(
                "Roof", width=width * inset, depth=depth * inset, height=roof_h, overhang=overhang,
                material=roof_material, location=(0.0, 0.0, roof_offset),
            )
        elif roof_kind == "hip":
            objects["roof"] = S.add_hip_roof(
                "Roof", width=width * inset, depth=depth * inset, height=roof_h, overhang=overhang,
                material=roof_material, location=(0.0, 0.0, roof_offset),
            )
        else:
            objects["roof"] = S.add_flat_roof(
                "Roof", width=width * inset, depth=depth * inset, overhang=overhang,
                material=roof_material, location=(0.0, 0.0, roof_offset),
            )

    if bool(params["door"]):
        door_w = min(0.62, width * 0.3)
        door_h = min(1.05, wall_h * 0.75)
        objects["door"] = S.add_box(
            "Door", (door_w, 0.1, door_h),
            location=(0.0, -depth / 2.0 - 0.02, plinth_h + door_h / 2.0), material=door_material,
        )
        S.add_box("DoorLintel", (door_w + 0.2, 0.12, 0.1),
                  location=(0.0, -depth / 2.0 - 0.02, plinth_h + door_h + 0.05), material=post_material)

    window_count = int(params["windows"])
    # Window faces in visibility order for the default iso camera: the -Y and +X walls
    # face the camera, so a two-window building shows both windows instead of hiding one.
    face_specs = [(0, -1), (1, 0), (0, 1), (-1, 0)]
    for i in range(window_count):
        nx, ny = face_specs[i % len(face_specs)]
        w = 0.34 + rng.uniform(-0.04, 0.04)
        h = 0.4 + rng.uniform(-0.05, 0.05)
        z = plinth_h + wall_h * 0.55
        if ny:
            # Offset off-centre so the doorway stays clear on the front wall.
            frame_size = (w + 0.12, 0.08, h + 0.12)
            lit_size = (w, 0.1, h)
            x = width * 0.30 * rng.choice((-1.0, 1.0))
            S.add_box(f"WindowFrame{i}", frame_size, location=(x, ny * (depth / 2.0 + 0.01), z),
                      material=post_material)
            S.add_box(f"Window{i}", lit_size, location=(x, ny * (depth / 2.0 + 0.02), z),
                      material=window_material)
        else:
            frame_size = (0.08, w + 0.12, h + 0.12)
            lit_size = (0.1, w, h)
            y = depth * 0.30 * rng.choice((-1.0, 1.0))
            S.add_box(f"WindowFrame{i}", frame_size, location=(nx * (width / 2.0 + 0.01), y, z),
                      material=post_material)
            S.add_box(f"Window{i}", lit_size, location=(nx * (width / 2.0 + 0.02), y, z),
                      material=window_material)

    chimney_h = 0.0
    if bool(params["chimney"]):
        chimney_h = max(0.6, wall_h * 0.55)
        S.add_box("Chimney", (0.36, 0.36, chimney_h),
                  location=(width * 0.28, depth * 0.16, top_of_walls + roof_h * 0.72 + chimney_h / 2.0),
                  material="stone")

    banner_h = 0.0
    if bool(params["banner"]):
        pole_h = max(0.9, wall_h * 0.7)
        pole_x = -width * 0.3
        S.add_cylinder("BannerPole", radius=0.05, height=pole_h,
                       location=(pole_x, depth * 0.22, top_of_walls + roof_h * 0.5 + pole_h / 2.0),
                       material=post_material)
        banner_h = 0.8
        banner_w = 0.62
        S.add_banner("Banner", width=banner_w, height=banner_h,
                     origin=(pole_x + banner_w / 2.0, depth * 0.22,
                             top_of_walls + roof_h * 0.5 + pole_h - 0.05),
                     axis="x", amplitude=0.22, material=banner_material)
        objects["banner"] = bpy.data.objects.get("Banner")

    subject_top = top_of_walls + roof_h + chimney_h
    horizontal = math.sqrt(width ** 2 + depth ** 2) / 2.0 + 0.35
    bevelled = S.bevel_hard_edges(width=max(0.008, min(width, depth) * 0.006))
    return {"subject_top": subject_top, "horizontal": horizontal, "roof_height": roof_h,
            "bevelled": bevelled}


def bounds_from_param(value: object) -> tuple | None:
    """Decode a `--frame-bounds` JSON blob into ((lx,ly,lz),(hx,hy,hz))."""
    import json

    if isinstance(value, str):
        if not value.strip().startswith("{"):
            return None
        value = json.loads(value)
    if isinstance(value, dict) and "lo" in value and "hi" in value:
        return (tuple(float(v) for v in value["lo"]), tuple(float(v) for v in value["hi"]))
    return None


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

    subject_top = float(info["subject_top"])
    horizontal = float(info["horizontal"])
    # Measure what actually has to fit in frame instead of estimating it from the parameters.
    bounds = S.scene_bounds()

    ortho = float(params["ortho_scale"])
    target_z = float(params["frame_target_z"])
    if ortho <= 0.0 or target_z < 0.0:
        fitted_ortho, fitted_z = S.fit_framing(
            bounds_from_param(params.get("frame_bounds")) or bounds,
            view=str(params["view"]), azimuth=float(params["azimuth"]),
            res_x=int(params["res_x"]), res_y=int(params["res_y"]), margin=1.10)
        if ortho <= 0.0:
            ortho = fitted_ortho
        if target_z < 0.0:
            target_z = fitted_z

    if measure_only:
        S.emit_summary({
            "ok": True, "measure_only": True, "kind": params["kind"],
            "bounds": {"lo": list(bounds[0]), "hi": list(bounds[1])},
            "subject_top": round(subject_top, 4),
            "ortho_scale": round(ortho, 4), "frame_target_z": round(target_z, 4),
            "res": [int(params["res_x"]), int(params["res_y"])],
            **S.object_stats(),
        })
        return

    S.setup_camera(scene, view=str(params["view"]), ortho_scale=ortho, target=(0.0, 0.0, target_z))
    S.setup_render(scene, width=int(params["res_x"]), height=int(params["res_y"]),
                   samples=int(params["samples"]))
    S.render_still(scene, out)

    S.emit_summary({
        "ok": Path(out).exists(),
        "out": out,
        "kind": params["kind"],
        "seed": int(params["seed"]),
        "engine": scene.render.engine,
        "ortho_scale": round(ortho, 4),
        "frame_target_z": round(target_z, 4),
        "subject_top": round(subject_top, 4),
        "roof_height": round(float(info["roof_height"]), 4),
        "bounds": {"lo": list(bounds[0]), "hi": list(bounds[1])},
        "res": [int(params["res_x"]), int(params["res_y"])],
        **S.object_stats(),
    })


if __name__ == "__main__":
    main()
