"""Procedural prop generator — coffins, gravestones, altars, lamps, statue.

Same contract as `generate_building.py` (`DEFAULTS` + `build(params)`), so
`blender/render_animation.py` can drive it through `--scene generate_prop` and the pipeline treats
it as just another Blender generator. Props are where the turntable clip earns its keep: an
inventory or codex preview needs the object rotating, and a rotating object has to be real
geometry, not a painted still.

    blender -b --factory-startup --python blender/generate_prop.py -- \
        --kind coffin --res-x 512 --res-y 512 --out assets/incoming/coffin.png
"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

sys.path[:0] = [str(_p) for _p in (Path(__file__).resolve().parent,
                                   Path(__file__).resolve().parent / "lib")]

import scene as S  # noqa: E402

DEFAULTS: dict[str, object] = {
    # subject
    "kind": "coffin",
    "scale": 1.0,
    "body_material": "black_timber",
    "trim_material": "iron",
    "accent_material": "dry_blood",
    "glow_material": "crimson_glow",
    "detail_material": "bone",
    "seed": 0,
    # render
    "engine": "BLENDER_EEVEE_NEXT",
    "res_x": 1024,
    "res_y": 1024,
    "samples": 64,
    "view": "iso",
    "ortho_scale": 0.0,
    "frame_target_z": -1.0,
    "out": "",
    "key_energy": 4.0,
    "fill_energy": 1.4,
    "azimuth": 45.0,
}


def _wing(name: str, profile: list[tuple[float, float]], thickness: float, *,
          location: tuple[float, float, float], material: str,
          rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> object:
    """A flat, tapered plate: profile in (Y, Z), extruded along X.

    A box cannot taper, so a box-slab wing reads as a blade. This builds the wing from its
    silhouette instead, which is the only thing that makes it legible from an iso camera.
    `rotation` matters for a turntable: wings left parallel to the body present their edge
    from the front and vanish, so they are yawed outward to keep a face toward the camera.
    """
    half = thickness / 2.0
    n = len(profile)
    verts = [(half, y, z) for y, z in profile] + [(-half, y, z) for y, z in profile]
    faces: list[tuple[int, ...]] = [tuple(range(n)), tuple(range(n, 2 * n))[::-1]]
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, j, n + j, n + i))
    return S.mesh_object(name, verts, faces, location=location, rotation=rotation,
                         material=material)


def _coffin(params: dict[str, object]) -> dict[str, object]:
    """A tapered hexagonal coffin on a trestle bier, lid ajar, iron bands."""
    s = float(params["scale"])
    length, width, height = 2.2 * s, 0.78 * s, 0.52 * s
    material = str(params["body_material"])
    trim = str(params["trim_material"])
    # Classic coffin outline: wide at the shoulders, tapering to the foot.
    shoulder = length * 0.22
    foot = length * 0.30
    half_w = width / 2.0
    outline = [
        (0.0, -length / 2.0),
        (half_w * 0.62, -length / 2.0 + foot),
        (half_w, -length / 2.0 + foot + shoulder),
        (half_w, length / 2.0 - shoulder),
        (half_w * 0.72, length / 2.0),
        (0.0 - half_w * 0.72, length / 2.0),
        (-half_w, length / 2.0 - shoulder),
        (-half_w, -length / 2.0 + foot + shoulder),
        (-half_w * 0.62, -length / 2.0 + foot),
    ]
    bier_z = 0.42 * s
    S.add_prism("CoffinBody", outline, height, location=(0.0, 0.0, bier_z + height / 2.0),
                material=material)
    lid_outline = [(x * 1.04, y * 1.01) for x, y in outline]
    lid = S.add_prism("CoffinLid", lid_outline, 0.07 * s,
                      location=(0.0, length * 0.05, bier_z + height + 0.03 * s),
                      material=material)
    # Lid ajar: tilted about the foot, which is what reads as "recently opened".
    lid.rotation_euler = (math.radians(-9.0), 0.0, 0.0)
    # Bands are hoops around the girth: a thin prism of the coffin's own (slightly enlarged)
    # outline. Slabs spanning the width look like fins, because the body tapers and they do not.
    hoop_outline = [(x * 1.04, y * 1.01) for x, y in outline]
    for i, frac in enumerate((0.30, 0.72)):
        S.add_prism(f"CoffinBand{i}", hoop_outline, 0.055 * s,
                    location=(0.0, 0.0, bier_z + height * frac), material=trim)
    lid_z = bier_z + height + 0.10 * s
    S.add_box("CoffinCrossV", (0.07 * s, 0.32 * s, 0.06 * s),
              location=(0.0, -length * 0.30, lid_z), material=trim)
    S.add_box("CoffinCrossH", (0.22 * s, 0.07 * s, 0.06 * s),
              location=(0.0, -length * 0.30, lid_z), material=trim)
    # Bier: two beams on four legs, tall enough to read from the iso camera.
    for i, y in enumerate((-length * 0.30, length * 0.30)):
        S.add_box(f"BierBeam{i}", (width * 0.98, 0.13 * s, 0.11 * s),
                  location=(0.0, y, 0.36 * s), material=trim)
        for j, dx in enumerate((-0.34, 0.34)):
            S.add_box(f"BierLeg{i}{j}", (0.09 * s, 0.09 * s, 0.36 * s),
                      location=(dx * s, y, 0.18 * s), material=trim)
    return {"top": lid_z + 0.34 * s, "radius": length * 0.55}


def _gravestone(params: dict[str, object]) -> dict[str, object]:
    """A leaning headstone on a base, with a cross and a bone pile."""
    s = float(params["scale"])
    stone = str(params["body_material"])
    base_h = 0.16 * s
    slab_h = 1.05 * s
    S.add_box("GraveBase", (0.92 * s, 0.62 * s, base_h), location=(0.0, 0.0, base_h / 2.0),
              material=stone)
    slab = S.add_prism("GraveSlab", [(-0.26 * s, -0.09 * s), (0.26 * s, -0.09 * s),
                                     (0.26 * s, 0.09 * s), (-0.26 * s, 0.09 * s)],
                       slab_h, location=(0.0, 0.0, base_h + slab_h / 2.0), material=stone)
    rng = random.Random(int(params["seed"]))
    slab.rotation_euler = (0.0, math.radians(rng.uniform(-9.0, 9.0)), math.radians(rng.uniform(-6.0, 6.0)))
    top = base_h + slab_h
    S.add_box("GraveCrossV", (0.10 * s, 0.10 * s, 0.34 * s),
              location=(0.0, 0.0, top + 0.12 * s), material=stone)
    S.add_box("GraveCrossH", (0.36 * s, 0.10 * s, 0.09 * s),
              location=(0.0, 0.0, top + 0.20 * s), material=stone)
    for i, (dx, dy, rot) in enumerate(((-0.34, -0.18, 12.0), (0.36, -0.20, -8.0), (0.30, 0.22, -20.0))):
        S.add_box(f"GraveBone{i}", (0.24 * s, 0.06 * s, 0.06 * s),
                  location=(dx * s, dy * s, 0.03 * s),
                  rotation=(0.0, 0.0, math.radians(rot)),
                  material=str(params["detail_material"]))
    return {"top": top + 0.30 * s, "radius": 0.75 * s}


def _altar(params: dict[str, object]) -> dict[str, object]:
    """A three-step altar with a blood channel and lit candles."""
    s = float(params["scale"])
    stone = str(params["body_material"])
    accent = str(params["accent_material"])
    glow = str(params["glow_material"])
    steps = ((1.5, 1.1, 0.18), (1.2, 0.86, 0.18), (0.94, 0.68, 0.16))
    z = 0.0
    for i, (w, d, h) in enumerate(steps):
        S.add_box(f"AltarStep{i}", (w * s, d * s, h * s),
                  location=(0.0, 0.0, z * s + h * s / 2.0), material=stone)
        z += h
    S.add_box("AltarSlab", (1.06 * s, 0.76 * s, 0.12 * s),
              location=(0.0, 0.0, z * s + 0.06 * s), material=stone)
    z += 0.12
    S.add_box("AltarChannel", (0.66 * s, 0.12 * s, 0.05 * s),
              location=(0.0, 0.16 * s, z * s + 0.025 * s), material=accent)
    for i, dx in enumerate((-0.34, 0.34)):
        candle_h = (0.34 if i == 0 else 0.26) * s
        S.add_box(f"Candle{i}", (0.09 * s, 0.09 * s, candle_h),
                  location=(dx * s, -0.18 * s, z * s + candle_h / 2.0),
                  material=str(params["detail_material"]))
        S.add_cone(f"Flame{i}", radius=0.045 * s, height=0.13 * s, segments=8,
                   location=(dx * s, -0.18 * s, z * s + candle_h + 0.06 * s), material=glow)
    return {"top": (z + 0.55) * s, "radius": 0.95 * s}


def _lamp(params: dict[str, object]) -> dict[str, object]:
    """An iron street lamp with a lit lantern - a prop that also reads at village scale."""
    s = float(params["scale"])
    iron = str(params["trim_material"])
    glow = str(params["glow_material"])
    post_h = 2.05 * s
    S.add_box("LampFoot", (0.32 * s, 0.32 * s, 0.12 * s), location=(0.0, 0.0, 0.06 * s),
              material=iron)
    S.add_cylinder("LampPost", radius=0.065 * s, height=post_h,
                   location=(0.0, 0.0, post_h / 2.0 + 0.10 * s), material=iron)
    top_z = 0.10 * s + post_h
    # Open cage: a solid box would hide the lit glass inside it. Four corner posts plus a
    # floor and a roof leave the glow visible from every angle the turntable sees.
    glass = 0.20 * s
    S.add_box("LanternFloor", (0.32 * s, 0.32 * s, 0.05 * s),
              location=(0.0, 0.0, top_z + 0.03 * s), material=iron)
    S.add_box("LanternGlass", (glass, glass, 0.30 * s),
              location=(0.0, 0.0, top_z + 0.22 * s), material=glow)
    for i, (dx, dy) in enumerate(((-1, -1), (1, -1), (1, 1), (-1, 1))):
        S.add_box(f"LanternPost{i}", (0.045 * s, 0.045 * s, 0.36 * s),
                  location=(dx * 0.15 * s, dy * 0.15 * s, top_z + 0.22 * s), material=iron)
    S.add_box("LanternRoof", (0.36 * s, 0.36 * s, 0.06 * s),
              location=(0.0, 0.0, top_z + 0.42 * s), material=iron)
    S.add_cone("LanternCap", radius=0.24 * s, height=0.16 * s, segments=8,
               location=(0.0, 0.0, top_z + 0.53 * s), material=iron)
    S.add_cone("LanternFinial", radius=0.05 * s, height=0.11 * s, segments=8,
               location=(0.0, 0.0, top_z + 0.66 * s), material=iron)
    return {"top": top_z + 0.78 * s, "radius": 0.55 * s}


def _statue(params: dict[str, object]) -> dict[str, object]:
    """A winged watcher on a plinth: the turntable subject.

    Silhouette first. An earlier version had arms angled off the body and small wings, and from
    the iso camera it read as a blade crossing a column - the wings are now the widest, most
    legible element and the arms are gone.
    """
    s = float(params["scale"])
    stone = str(params["body_material"])
    glow = str(params["glow_material"])
    plinth_h = 0.46 * s
    S.add_box("StatuePlinth", (0.86 * s, 0.86 * s, plinth_h),
              location=(0.0, 0.0, plinth_h / 2.0), material=stone)
    S.add_box("StatuePlinthCap", (0.98 * s, 0.98 * s, 0.10 * s),
              location=(0.0, 0.0, plinth_h + 0.05 * s), material=stone)
    body_z0 = plinth_h + 0.10 * s
    body_h = 1.30 * s
    S.add_cylinder("StatueRobes", radius=0.34 * s, height=0.34 * s,
                   location=(0.0, 0.0, body_z0 + 0.17 * s), material=stone, segments=12)
    S.add_cylinder("StatueBody", radius=0.23 * s, height=body_h,
                   location=(0.0, 0.0, body_z0 + body_h / 2.0), material=stone, segments=12)
    S.add_box("StatueShoulders", (0.52 * s, 0.26 * s, 0.14 * s),
              location=(0.0, 0.0, body_z0 + body_h * 0.94), material=stone)
    head_z = body_z0 + body_h + 0.22 * s
    S.add_sphere("StatueHead", radius=0.18 * s, location=(0.0, 0.0, head_z),
                 material=stone, segments=16, rings=8)
    S.add_cone("StatueCrown", radius=0.15 * s, height=0.24 * s, segments=6,
               location=(0.0, 0.05 * s, head_z + 0.18 * s), material=stone)
    for i, dx in enumerate((-0.07, 0.07)):
        S.add_box(f"StatueEye{i}", (0.05 * s, 0.05 * s, 0.04 * s),
                  location=(dx * s, 0.16 * s, head_z + 0.05 * s), material=glow)
    # Wings: broad, swept, tapered plates seen face-on from the iso camera. Their silhouette is
    # the cue that says "gargoyle" rather than "column".
    wing_profile = [
        (0.00, 0.00),      # leading edge, root
        (0.03, 0.48),
        (0.07, 0.98),      # leading edge, top
        (0.34, 1.16),      # tip
        (0.40, 0.74),      # trailing edge, upper sweep
        (0.36, 0.34),
        (0.18, 0.05),      # trailing edge, root
    ]
    for i, sx in enumerate((-1.0, 1.0)):
        _wing(f"StatueWing{i}", wing_profile, 0.115 * s,
              location=(sx * 0.22 * s, 0.12 * s, body_z0 + body_h * 0.52), material=stone,
              rotation=(math.radians(-10.0), math.radians(sx * 6.0), math.radians(sx * 26.0)))
    return {"top": head_z + 0.36 * s, "radius": 0.95 * s}


BUILDERS = {
    "coffin": _coffin,
    "gravestone": _gravestone,
    "altar": _altar,
    "lamp": _lamp,
    "statue": _statue,
}


def build(params: dict[str, object]) -> dict[str, object]:
    kind = str(params["kind"])
    if kind not in BUILDERS:
        S.fail(f"unknown prop kind {kind!r}; choose from {sorted(BUILDERS)}")
    info = BUILDERS[kind](params)
    top = float(info["top"])
    radius = float(info["radius"])
    bevelled = S.bevel_hard_edges(width=max(0.006, radius * 0.012))
    return {"subject_top": top, "horizontal": radius + 0.15, "roof_height": 0.0,
            "bevelled": bevelled, "kind": kind}


def main() -> None:
    params = S.cli_args({**DEFAULTS})
    out = str(params.get("out") or "").strip()
    if not out:
        S.fail("--out is required")

    scene = S.reset_scene(engine=str(params["engine"]))
    info = build(params)
    S.setup_lights(key_energy=float(params["key_energy"]), fill_energy=float(params["fill_energy"]),
                   azimuth=float(params["azimuth"]))

    subject_top = float(info["subject_top"])
    horizontal = float(info["horizontal"])
    ortho = float(params["ortho_scale"])
    if ortho <= 0.0:
        # Props frame tighter than buildings: they have no ground plate, and a turntable that
        # leaves 40% of every frame empty wastes texture memory across a whole sheet.
        ortho = max(horizontal * 2.0 * 0.82, subject_top * 1.25) * 1.16
    target_z = float(params["frame_target_z"])
    if target_z < 0.0:
        target_z = subject_top * 0.42

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
        "res": [int(params["res_x"]), int(params["res_y"])],
        **S.object_stats(),
    })


if __name__ == "__main__":
    main()
