"""Turn a Blender pass bundle into ControlNet inputs: lineart, normalised depth, the img2img source.

Lineart is derived, not rendered: an edge wherever the material id changes (exact, the
matid pass is aliased), where the surface normal turns sharply, or where depth jumps.
That gives the clean construction lines a painter would ink, and nothing else.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

BG = (188, 190, 186)  # neutral backdrop for the img2img source; BiRefNet cuts it away
GRASS_TILE = Path(__file__).resolve().parents[2] / "assets" / "approved" / "warbands_v2" / "terrain" / "wb_terrain_grass.png"
GRASS_FALLBACK = (96, 128, 52)


def grass_color() -> tuple[int, int, int]:
    """The village yard's own grass (the approved terrain tile): buildings are refined
    standing on it, so FLUX paints their base, bounce light and shadows for that ground."""
    if GRASS_TILE.exists():
        return tuple(int(c) for c in np.asarray(Image.open(GRASS_TILE).convert("RGB")).reshape(-1, 3).mean(0))
    return GRASS_FALLBACK


def plate_id() -> tuple[int, int, int]:
    """matid colour of the plate (material "grass"); mirrors blender/wb/core.py:_id_color."""
    import random
    rng = random.Random(sum((i + 1) * ord(c) for i, c in enumerate("grass")))
    return tuple(int(round(rng.uniform(0.1, 1.0) * 255)) for _ in range(3))  # type: ignore[return-value]


def split_matid(bundle: Path) -> tuple[np.ndarray, np.ndarray]:
    """(subject, plate) masks from the matid pass."""
    m = np.asarray(Image.open(bundle / "matid.png").convert("RGBA")).astype(np.int32)
    solid = m[..., 3] > 127
    plate = solid & (np.abs(m[..., :3] - np.array(plate_id())).max(axis=2) <= 3)
    return solid & ~plate, plate


def load_rgba(p: Path) -> np.ndarray:
    return np.asarray(Image.open(p).convert("RGBA"))


def depth16(p: Path) -> np.ndarray:
    a = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
    if a.ndim == 3:
        a = a[..., 2] if a.shape[2] >= 3 else a[..., 0]
    return a.astype(np.float32) / (65535.0 if a.dtype == np.uint16 else 255.0)


def mask_of(beauty: np.ndarray) -> np.ndarray:
    return beauty[..., 3] > 127


def lineart(bundle: Path, normal_deg: float = 28.0, depth_jump: float = 0.012, width: int = 2,
            building: bool = False) -> np.ndarray:
    matid = np.asarray(Image.open(bundle / "matid.png").convert("RGBA")).astype(np.int32)
    q = (matid[..., :3] + 4) // 8  # tolerate +-1 quantisation; id colours are far apart
    ids = (q[..., 0] << 12) | (q[..., 1] << 6) | q[..., 2]
    subject, plate = split_matid(bundle)
    if not building:
        subject, plate = matid[..., 3] > 127, np.zeros(ids.shape, bool)
    ids[(matid[..., 3] < 128) | plate] = -1  # the plate is ground, not a shape to ink
    edge = np.zeros(ids.shape, bool)
    edge[:, 1:] |= ids[:, 1:] != ids[:, :-1]
    edge[1:, :] |= ids[1:, :] != ids[:-1, :]
    nrm = np.asarray(Image.open(bundle / "normal.png").convert("RGB")).astype(np.float32) / 127.5 - 1.0
    nrm /= np.linalg.norm(nrm, axis=2, keepdims=True) + 1e-6
    cos_t = np.cos(np.radians(normal_deg))
    edge[:, 1:] |= (nrm[:, 1:] * nrm[:, :-1]).sum(2) < cos_t
    edge[1:, :] |= (nrm[1:, :] * nrm[:-1, :]).sum(2) < cos_t
    d = depth16(bundle / "depth.png")
    edge[:, 1:] |= np.abs(d[:, 1:] - d[:, :-1]) > depth_jump
    edge[1:, :] |= np.abs(d[1:, :] - d[:-1, :]) > depth_jump
    if building:
        # ink the subject only: the plate's own outline and the ground's depth/normal steps
        # are not lines a painter would draw
        edge &= cv2.dilate(subject.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    out = edge.astype(np.uint8) * 255
    if width > 1:
        out = cv2.dilate(out, np.ones((width, width), np.uint8))
    return out


def shadow_layer(beauty: np.ndarray, subject: np.ndarray, plate: np.ndarray) -> np.ndarray:
    """The shadow the building casts on its cell (the catcher's alpha off the subject),
    feathered out toward the cell's edge and the canvas edge, as uint8 alpha."""
    a = beauty[..., 3].astype(np.float32) / 255.0
    a[subject] = 0.0
    # the catcher also records a faint, even sky occlusion over the whole cell (~3%): left in,
    # it paints a darker diamond under every building - exactly the tile we are removing
    open_ground = plate & (cv2.dilate(subject.astype(np.uint8), np.ones((41, 41), np.uint8)) == 0)
    floor = float(np.percentile(a[open_ground], 35)) if open_ground.any() else 0.0
    a = np.clip((a - floor) / max(1e-3, 1.0 - floor), 0, 1) * 0.85
    a *= cv2.GaussianBlur(plate.astype(np.float32), (0, 0), 10)
    h, w = a.shape
    ramp, keep = 32.0, 10.0  # fully clear for `keep` px at the canvas edge (the 2px margin gate)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    edge = (np.minimum.reduce([xx, yy, w - 1 - xx, h - 1 - yy]) - keep) / ramp
    a *= np.clip(edge, 0, 1)
    return (np.clip(a, 0, 1) * 255).astype(np.uint8)


def prepare(bundle: Path, work: Path, building: bool = False) -> dict:
    """Write src.png (beauty over the ground), depth_cn.png, lineart.png, mask.png (the
    subject) and, for buildings, shadow.png (the catcher's shadow alpha)."""
    work.mkdir(parents=True, exist_ok=True)
    beauty = load_rgba(bundle / "beauty.png")
    alpha = beauty[..., 3:4].astype(np.float32) / 255.0
    subject, plate = split_matid(bundle)
    shadow = shadow_layer(beauty, subject, plate) if building else None
    if building:
        # the source FLUX refines is what the game will show: the building on the yard's grass
        # with the cleaned shadow (no faint catcher diamond for FLUX to paint as a tile)
        alpha = np.where(subject[..., None], alpha, shadow[..., None].astype(np.float32) / 255.0)
    if alpha.min() >= 0.999:  # opaque subjects (terrain, walls, backdrop) have no backdrop
        src = beauty[..., :3]
    else:
        bg = np.array(grass_color() if building else BG, np.float32)
        src = (beauty[..., :3] * alpha + bg * (1 - alpha)).astype(np.uint8)
    Image.fromarray(src).save(work / "src.png")
    m = subject if building else mask_of(beauty)
    Image.fromarray((m * 255).astype(np.uint8)).save(work / "mask.png")
    out = {"src": work / "src.png", "depth": work / "depth_cn.png", "lineart": work / "lineart.png",
           "mask": work / "mask.png"}
    if building:
        Image.fromarray(shadow).save(work / "shadow.png")
        out["shadow"] = work / "shadow.png"
    d = depth16(bundle / "depth.png")
    region = (m | plate) if building else m
    if region.any() and not region.all():
        lo, hi = float(d[region].min()), float(d[region].max())
        dn = np.where(region, 0.12 + 0.88 * (d - lo) / max(1e-6, hi - lo), 0.0)
    else:
        lo, hi = float(d.min()), float(d.max())
        dn = 0.12 + 0.88 * (d - lo) / max(1e-6, hi - lo)
    Image.fromarray((np.clip(dn, 0, 1) * 255).astype(np.uint8)).convert("RGB").save(work / "depth_cn.png")
    Image.fromarray(lineart(bundle, building=building)).convert("RGB").save(work / "lineart.png")
    return out
