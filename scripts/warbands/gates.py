"""Deterministic acceptance gates for the Warbands v2 art set.

The critic ranks and describes; these functions decide. Every gate returns a numeric
measurement and a pass flag, so a report says *why* an asset passed or failed.

  building / card   silhouette IoU >= 0.90 vs the Blender mask, border margin >= 2px,
                    alpha coverage valid, bounding-box drift <= 4px (all at 512px)
  terrain           tile seams: the wrap step is no harsher than the texture's own steps
  wall              seamless after the game's 1/2 shear, in both directions
  backdrop          no alpha, continuous horizon that follows the source's horizon
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

IOU_MIN = 0.90
MARGIN_MIN = 2
DRIFT_MAX = 4
COVER = (0.02, 0.92)
# halo width: soft (0.1..0.9 alpha) edge pixels per silhouette-perimeter pixel. A clean
# anti-aliased cutout is ~1px wide whatever the shape; a ratio to the body AREA (the old
# test) failed thin-legged subjects like market stalls while they were clean
HALO_MAX_PX = 2.5
SEAM_RATIO_MAX = 1.6
# "weak materials": mean band-pass (DoG 0.8/2.5px) detail energy of the subject at 512px.
# Calibrated on HQ T0: good refines 3.2-3.5, flat high-denoise illustration 2.3-2.7.
WEAK_DETAIL = 2.8
PALETTE_LOCK = (24.0, 0.5)  # (sigma px at 1024, weight) - low-frequency colour back to Blender's


def _bbox(m: np.ndarray):
    ys, xs = np.where(m)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def detail_energy(rgb: np.ndarray, mask: np.ndarray | None = None) -> float:
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    dog = np.abs(cv2.GaussianBlur(g, (0, 0), 0.8) - cv2.GaussianBlur(g, (0, 0), 2.5))
    if mask is not None:
        m = cv2.erode(mask.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        return float(dog[m].mean()) if m.any() else 0.0
    return float(dog.mean())


def palette_lock(rgb: np.ndarray, src: np.ndarray, sigma: float = PALETTE_LOCK[0],
                 k: float = PALETTE_LOCK[1]) -> np.ndarray:
    """Pull the refine's large-scale colour toward the Blender source (Lab, low frequencies
    only). FLUX keeps its painted detail; every tier keeps the set's one palette."""
    r = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    s = cv2.cvtColor(src, cv2.COLOR_RGB2LAB).astype(np.float32)
    out = r + k * (cv2.GaussianBlur(s, (0, 0), sigma) - cv2.GaussianBlur(r, (0, 0), sigma))
    return cv2.cvtColor(np.clip(out, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)


def finish(rgba512: np.ndarray) -> np.ndarray:
    """The shipped frame's last step: a mild unsharp mask (deterministic)."""
    from PIL import ImageFilter
    im = Image.fromarray(rgba512)
    rgb = im.convert("RGB").filter(ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=2))
    rgb.putalpha(im.getchannel("A"))
    return np.asarray(rgb)


def composite_cutout(rgb: np.ndarray, cut: np.ndarray, src_mask: np.ndarray) -> np.ndarray:
    """Final RGBA: BiRefNet's soft alpha, limited to a few px around the Blender silhouette
    so a stray painted speck in the backdrop cannot survive into the sprite."""
    near = cv2.dilate(src_mask.astype(np.uint8), np.ones((11, 11), np.uint8)) > 0
    a = np.where(near, cut, 0).astype(np.uint8)
    return np.dstack([rgb, a])


SHADOW_RGB = (16, 20, 10)  # the shadow's own colour: a deep, slightly green-warm dark over grass


def with_shadow(rgba: np.ndarray, shadow: np.ndarray | None) -> np.ndarray:
    """Lay the building over its shadow layer (straight alpha 'over')."""
    if shadow is None:
        return rgba
    a = rgba[..., 3:4].astype(np.float32) / 255.0
    s = shadow[..., None].astype(np.float32) / 255.0
    out_a = a + s * (1 - a)
    rgb = (rgba[..., :3] * a + np.array(SHADOW_RGB, np.float32) * s * (1 - a)) / np.maximum(out_a, 1e-6)
    return np.dstack([np.clip(rgb, 0, 255), out_a[..., 0] * 255]).astype(np.uint8)


def building(rgba1024: np.ndarray, cut1024: np.ndarray, src_mask1024: np.ndarray, src_rgb1024: np.ndarray,
             shadow1024: np.ndarray | None = None) -> dict:
    """Gates at the shipped size (512). The SUBJECT (building layer) is held to the Blender
    silhouette; the shipped frame (building over its shadow) is held to margins/coverage.
    Returns {"pass", "gates", "scores", "rgba512"}."""
    def down(a: np.ndarray, mode=Image.LANCZOS) -> np.ndarray:
        return np.asarray(Image.fromarray(a).resize((512, 512), mode))

    subject = finish(down(rgba1024))
    rgba = with_shadow(subject, down(shadow1024, Image.BILINEAR) if shadow1024 is not None else None)
    a = rgba[..., 3].astype(np.float32) / 255.0
    sm = down((src_mask1024 * 255).astype(np.uint8), Image.BILINEAR) > 127
    cm = down(cut1024, Image.BILINEAR) > 127
    inter, union = np.logical_and(cm, sm).sum(), np.logical_or(cm, sm).sum()
    iou = float(inter / union) if union else 0.0
    body = subject[..., 3] > 127
    bb, sbb, fb = _bbox(body), _bbox(sm), _bbox(a > 0.02)
    h, w = a.shape
    margin = min(fb[0], fb[1], w - 1 - fb[2], h - 1 - fb[3]) if fb else -1
    drift = max(abs(p - q) for p, q in zip(bb, sbb)) if bb and sbb else 999
    cover = float(body.mean())
    sa = subject[..., 3].astype(np.float32) / 255.0
    solid = (sa >= 0.9).astype(np.uint8)
    perimeter = int((solid.astype(bool) & ~(cv2.erode(solid, np.ones((3, 3), np.uint8)) > 0)).sum())
    semi = float(((sa > 0.1) & (sa < 0.9)).sum() / max(1, perimeter))
    gates = {
        "iou": {"value": round(iou, 4), "min": IOU_MIN, "pass": iou >= IOU_MIN},
        "margin_px": {"value": int(margin), "min": MARGIN_MIN, "pass": margin >= MARGIN_MIN},
        "alpha": {"coverage": round(cover, 4), "halo_px": round(semi, 3),
                  "pass": COVER[0] <= cover <= COVER[1] and semi <= HALO_MAX_PX},
        "bbox_drift_px": {"value": int(drift), "max": DRIFT_MAX, "pass": drift <= DRIFT_MAX},
    }
    m = src_mask1024.astype(bool)
    detail = detail_energy(subject[..., :3], subject[..., 3] > 200)
    lab_r = cv2.cvtColor(np.ascontiguousarray(rgba1024[..., :3]), cv2.COLOR_RGB2LAB).astype(np.float32)
    lab_s = cv2.cvtColor(src_rgb1024, cv2.COLOR_RGB2LAB).astype(np.float32)
    color_drift = float(np.linalg.norm((lab_r - lab_s)[m].mean(axis=0)))
    scores = {"detail": round(detail, 3), "color_drift": round(color_drift, 2),
              "weak_materials": detail < WEAK_DETAIL}
    return {"pass": all(g["pass"] for g in gates.values()), "gates": gates, "scores": scores, "rgba512": rgba}


def seam_ratio(img: np.ndarray, axis: int) -> float:
    """Wrap step / the texture's own step scale along `axis` (1 = left/right, 0 = top/bottom).

    The reference is max(mean step, p95 step / 1.6): a texture with strong regular edges
    (log gaps, mortar joints) wrapping exactly on one of them is continuous, and must not be
    flagged; a real seam is a step the texture itself never makes."""
    a = img.astype(np.float32)
    if axis == 1:
        wrap = np.abs(a[:, 0] - a[:, -1]).mean()
        steps = np.abs(np.diff(a, axis=1)).mean(axis=(0, 2))
    else:
        wrap = np.abs(a[0] - a[-1]).mean()
        steps = np.abs(np.diff(a, axis=0)).mean(axis=(1, 2))
    ref = max(float(steps.mean()), float(np.percentile(steps, 95)) / SEAM_RATIO_MAX)
    return float(wrap / max(1e-3, ref))


def terrain(rgb: np.ndarray) -> dict:
    sx, sy = seam_ratio(rgb, 1), seam_ratio(rgb, 0)
    low = cv2.GaussianBlur(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32), (0, 0), rgb.shape[0] / 8)
    gates = {
        "seam_x": {"value": round(sx, 3), "max": SEAM_RATIO_MAX, "pass": sx <= SEAM_RATIO_MAX},
        "seam_y": {"value": round(sy, 3), "max": SEAM_RATIO_MAX, "pass": sy <= SEAM_RATIO_MAX},
        "size": {"value": list(rgb.shape[:2]), "pass": rgb.shape[0] == rgb.shape[1] == 512},
    }
    return {"pass": all(g["pass"] for g in gates.values()), "gates": gates,
            "scores": {"vignette_std": round(float(low.std()), 2)}}


def shear_wrap(a: np.ndarray, k: float = 0.5) -> np.ndarray:
    """The game's shear (scripts/sync-artworkflow-art.py): column x rolls up by k*x, wrapping."""
    out = np.empty_like(a)
    for x in range(a.shape[1]):
        out[:, x] = np.roll(a[:, x], -int(round(k * x)), axis=0)
    return out


def wall(rgb: np.ndarray) -> dict:
    h, w = rgb.shape[:2]
    sheared = shear_wrap(rgb)
    gates = {
        "aspect": {"value": [w, h], "pass": w == 2 * h},
        "seam_x": {"value": round(seam_ratio(rgb, 1), 3), "pass": seam_ratio(rgb, 1) <= SEAM_RATIO_MAX},
        "seam_y": {"value": round(seam_ratio(rgb, 0), 3), "pass": seam_ratio(rgb, 0) <= SEAM_RATIO_MAX},
        # after the shear, the left/right wrap must still continue the courses: column w-1
        # sits next to column 0 of the next tile, which the shear has moved by exactly h
        "sheared_seam_x": {"value": round(seam_ratio(sheared, 1), 3),
                           "pass": seam_ratio(sheared, 1) <= SEAM_RATIO_MAX},
        "sheared_seam_y": {"value": round(seam_ratio(sheared, 0), 3),
                           "pass": seam_ratio(sheared, 0) <= SEAM_RATIO_MAX},
    }
    return {"pass": all(g["pass"] for g in gates.values()), "gates": gates, "scores": {}}


def skyline(sky: np.ndarray) -> np.ndarray:
    """Per column, the row where the land begins (0 = no sky in that column)."""
    h = sky.shape[0]
    land = ~sky
    return np.where(land.any(axis=0), land.argmax(axis=0), h)


def match_ground(rgb: np.ndarray, ground: np.ndarray, target_rgb: tuple, dL: float = -4.0) -> np.ndarray:
    """Shift the meadow's colour (Lab mean over `ground`) onto the village yard's grass
    (`target_rgb`, a touch darker: the land outside the village sits a step back), with a
    soft mask so trees, rocks and sky keep their own colours."""
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    tgt = cv2.cvtColor(np.uint8([[target_rgb]]), cv2.COLOR_RGB2LAB).astype(np.float32)[0, 0]
    tgt[0] += dL * 255 / 100
    shift = tgt - lab[ground].mean(axis=0)
    w = cv2.GaussianBlur(ground.astype(np.float32), (0, 0), 6)[..., None]
    out = lab + shift * w
    return cv2.cvtColor(np.clip(out, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)


def backdrop(rgba: np.ndarray, src_sky: np.ndarray, src_rgb: np.ndarray) -> dict:
    """The skyline (where the forested ridge meets the sky) is continuous - one land/sky
    boundary per column, no sky pockets inside the land, no floating land in the sky - and
    follows the Blender source; the picture is opaque and 2048x1024."""
    rgb = rgba[..., :3]
    has_alpha = rgba.shape[2] == 4 and int(rgba[..., 3].min()) < 255
    h = rgb.shape[0]
    src_line = skyline(src_sky)
    cols = src_line > 0
    # sky in the refine: close to the source's sky colour, row by row
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    ref = np.zeros((h, 3), np.float32)
    last = lab[0].mean(axis=0)
    for y in range(h):
        if src_sky[y].sum() > 8:
            last = np.median(lab[y][src_sky[y]], axis=0)
        ref[y] = last
    sky = np.linalg.norm(lab - ref[:, None, :], axis=2) < 14
    sky = cv2.morphologyEx(sky.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8)) > 0
    line = skyline(sky)
    dev = np.abs(line.astype(np.float32) - src_line)[cols] if cols.any() else np.zeros(1)
    # continuity: below the skyline there is no sky (pockets), above it no land (islands)
    rows = np.arange(h)[:, None]
    pockets = float((sky & (rows > line[None, :] + 6)).mean())
    islands = float((~sky & (rows < line[None, :] - 6)).mean())
    gates = {
        "size": {"value": [rgb.shape[1], h], "pass": (rgb.shape[1], h) == (2048, 1024)},
        "no_alpha": {"value": has_alpha, "pass": not has_alpha},
        "skyline_follows_source": {"median_px": float(np.median(dev)), "p95_px": float(np.percentile(dev, 95)),
                                   "pass": float(np.median(dev)) <= 10 and float(np.percentile(dev, 95)) <= 40},
        "skyline_continuous": {"pockets": round(pockets, 5), "islands": round(islands, 5),
                               "pass": pockets <= 0.002 and islands <= 0.002},
    }
    detail = detail_energy(np.asarray(Image.fromarray(rgb).resize((1024, 512), Image.LANCZOS)))
    return {"pass": all(g["pass"] for g in gates.values()), "gates": gates,
            "scores": {"detail": round(detail, 3), "weak_materials": detail < WEAK_DETAIL * 0.6}}


def matid_color(name: str) -> tuple[int, int, int]:
    """The matid pass colour of a palette material (mirrors blender/wb/core.py:_id_color)."""
    import random
    rng = random.Random(sum((i + 1) * ord(c) for i, c in enumerate(name)))
    return tuple(int(round(rng.uniform(0.1, 1.0) * 255)) for _ in range(3))  # type: ignore[return-value]


def plate_mask(matid: np.ndarray, size: int = 512) -> np.ndarray:
    """Pixels whose Blender material is the yard plate (grass top, cut-earth rim), at `size`."""
    small = np.asarray(Image.fromarray(matid).resize((size, size), Image.NEAREST)).astype(np.int32)
    m = np.zeros(small.shape[:2], bool)
    for name in ("grass", "earth"):
        m |= (np.abs(small[..., :3] - np.array(matid_color(name))).max(axis=2) <= 3) & (small[..., 3] > 127)
    return m


def family(subjects: list[np.ndarray], rgbas: list[np.ndarray], srcs: list[np.ndarray]) -> dict:
    """Cross-tier consistency for one building (512px frames).

    Registration is the camera's job (one pinned camera, one footprint per cell - checked in
    Blender); here: the refine shifts every tier's colours the same way (one palette), and
    every tier's silhouette is visibly bigger than the one before (the upgrade reads)."""
    out: dict = {"tiers": len(subjects)}
    if len(subjects) < 2:
        out["pass"] = True
        return out

    def lab(a, m):
        return cv2.cvtColor(np.ascontiguousarray(a[..., :3]), cv2.COLOR_RGB2LAB).astype(np.float32)[m]

    shifts = []
    for m, r, s in zip(subjects, rgbas, srcs):
        m = cv2.erode(m.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
        shifts.append(np.median(lab(r, m) - lab(s, m), axis=0))
    out["palette_shift_dE"] = round(float(max(np.linalg.norm(a - b) for a in shifts for b in shifts)), 2)
    growth = [round(float(subjects[i].sum() / max(1, subjects[i - 1].sum())), 3) for i in range(1, len(subjects))]
    out["area_growth"] = growth
    out["upgrade_clear"] = all(g >= 1.06 for g in growth)
    out["pass"] = out["palette_shift_dE"] <= 12 and out["upgrade_clear"]
    return out
