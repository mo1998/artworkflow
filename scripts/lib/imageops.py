"""Image processing and measurement primitives (Pillow + numpy).

Split in two halves:
  * transforms - trim, resize, anchor, pad: turn a raw render into a game-ready file
  * measurements - alpha coverage, bbox, centroid, flatness, dHash: feed the validator

Nothing here is style-specific, so new asset types reuse it unchanged.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
from PIL import Image, ImageChops
Image.MAX_IMAGE_PIXELS = None


class ImageError(RuntimeError):
    pass


MAGIC = {
    b"\x89PNG\r\n\x1a\n": "png",
    b"\xff\xd8\xff": "jpg",
    b"RIFF": "webp",
    b"GIF8": "gif",
}


def detect_format(data: bytes) -> str | None:
    for magic, name in MAGIC.items():
        if data.startswith(magic):
            return name
    return None


def open_image(path: Path) -> Image.Image:
    try:
        img = Image.open(path)
        img.load()
    except Exception as exc:
        raise ImageError(f"cannot open image {path}: {exc}") from exc
    return img


def has_alpha(img: Image.Image) -> bool:
    return img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)


def to_rgba(img: Image.Image) -> Image.Image:
    return img if img.mode == "RGBA" else img.convert("RGBA")


def alpha_array(img: Image.Image) -> np.ndarray:
    """Alpha channel as float 0..1; fully opaque when the image has no alpha."""
    if has_alpha(img):
        return np.asarray(to_rgba(img).getchannel("A"), dtype=np.float32) / 255.0
    return np.ones((img.height, img.width), dtype=np.float32)


def rgb_array(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0


@dataclass
class Measurements:
    width: int
    height: int
    mode: str
    has_alpha: bool
    alpha_coverage: float
    opaque_coverage: float  # pixels with alpha >= 0.5
    bbox: tuple[int, int, int, int] | None
    centroid: tuple[float, float] | None
    rgb_mean: tuple[float, float, float]
    rgb_stddev: float
    transparent_rgb_fraction: float
    touches_border: dict[str, bool]
    unique_colors: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def measure(img: Image.Image, *, alpha_threshold: float = 0.05) -> Measurements:
    rgba = to_rgba(img)
    alpha = alpha_array(rgba)
    rgb = rgb_array(rgba)
    mask = alpha > alpha_threshold

    ys, xs = np.nonzero(mask)
    if len(xs):
        bbox = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
        centroid = (float(xs.mean()), float(ys.mean()))
    else:
        bbox, centroid = None, None

    h, w = alpha.shape
    border = 1
    touches = {
        "left": bool(mask[:, :border].any()),
        "right": bool(mask[:, w - border:].any()),
        "top": bool(mask[:border, :].any()),
        "bottom": bool(mask[h - border:, :].any()),
    }

    # RGB of fully transparent pixels should be irrelevant; measure how many opaque
    # pixels carry near-black colour, which catches hard-cutout halos and empty renders.
    opaque = alpha >= 0.5
    if opaque.any():
        lum = rgb[opaque].mean(axis=1)
        transparent_rgb_fraction = float((lum < 0.02).mean())
    else:
        transparent_rgb_fraction = 1.0

    sample = np.asarray(rgba.convert("RGB").resize((min(w, 256), min(h, 256))), dtype=np.uint8)
    unique = int(np.unique(sample.reshape(-1, 3), axis=0).shape[0])

    return Measurements(
        width=w, height=h, mode=img.mode, has_alpha=has_alpha(img),
        alpha_coverage=float(mask.mean()), opaque_coverage=float(opaque.mean()),
        bbox=bbox, centroid=centroid,
        # Reported on the 0-255 scale that image tooling uses, so thresholds in
        # pipeline.yaml read the way a person expects ("stddev below 4/255 is flat").
        rgb_mean=tuple(round(float(v) * 255.0, 2) for v in rgb.reshape(-1, 3).mean(axis=0)),
        rgb_stddev=round(float(rgb.reshape(-1, 3).std(axis=0).mean()) * 255.0, 3),
        transparent_rgb_fraction=round(transparent_rgb_fraction, 4),
        touches_border=touches, unique_colors=unique,
    )


# ---- transforms ------------------------------------------------------------

def content_bbox(img: Image.Image, *, alpha_threshold: float = 0.02,
                 backdrop: tuple[int, int, int] | None = None, tolerance: int = 12) -> tuple[int, int, int, int] | None:
    """Bounding box of the subject.

    With alpha, the subject is the non-transparent region. Without alpha, fall back to
    "differs from the dominant background colour" which handles opaque backdrops.
    """
    rgba = to_rgba(img)
    alpha = alpha_array(rgba)
    if has_alpha(img):
        mask = alpha > alpha_threshold
    else:
        if backdrop is None:
            backdrop = dominant_color(rgba)
        rgb = rgb_array(rgba)
        ref = np.array(backdrop, dtype=np.float32) / 255.0
        mask = (np.abs(rgb - ref).max(axis=2) > (tolerance / 255.0))
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)


def dominant_color(img: Image.Image) -> tuple[int, int, int]:
    small = to_rgba(img).convert("RGB").resize((64, 64))
    arr = np.asarray(small, dtype=np.uint8).reshape(-1, 3)
    packed = (arr[:, 0].astype(np.int32) << 16) | (arr[:, 1].astype(np.int32) << 8) | arr[:, 2]
    values, counts = np.unique(packed, return_counts=True)
    top = int(values[int(counts.argmax())])
    return ((top >> 16) & 0xFF, (top >> 8) & 0xFF, top & 0xFF)


def trim(img: Image.Image, *, mode: str = "alpha", backdrop: tuple[int, int, int] | None = None,
         tolerance: int = 12) -> tuple[Image.Image, tuple[int, int, int, int] | None]:
    """Crop to the subject. Returns the cropped image and the box that was used."""
    box = content_bbox(img, backdrop=backdrop, tolerance=tolerance)
    if box is None:
        return img, None
    return img.crop(box), box


def fit_resize(img: Image.Image, target: int, *, axis: str = "max") -> Image.Image:
    """Scale so the subject's longest side is `target` px, preserving aspect ratio."""
    w, h = img.size
    if max(w, h) == 0:
        raise ImageError("degenerate image size")
    if axis == "max":
        scale = target / max(w, h)
    elif axis == "width":
        scale = target / w
    else:
        scale = target / h
    new = (max(1, round(w * scale)), max(1, round(h * scale)))
    return img.resize(new, Image.LANCZOS)


ANCHORS = {
    "center": (0.5, 0.5),
    "bottom-center": (0.5, 1.0),
    "bottom-left": (0.0, 1.0),
    "bottom-right": (1.0, 1.0),
    "top-center": (0.5, 0.0),
    "top-left": (0.0, 0.0),
    "top-right": (1.0, 0.0),
}


def place_on_canvas(img: Image.Image, size: int | tuple[int, int], *, anchor: str = "center",
                    padding: int = 0) -> Image.Image:
    """Place the subject on a transparent square/rect canvas at a fixed anchor.

    Fixed anchors are what make a set of sprites share one ground line - critical for
    buildings and characters that must sit on the same tile grid.
    """
    if isinstance(size, int):
        size = (size, size)
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    max_w = max(1, size[0] - 2 * padding)
    max_h = max(1, size[1] - 2 * padding)
    subject = img
    if subject.width > max_w or subject.height > max_h:
        scale = min(max_w / subject.width, max_h / subject.height)
        subject = subject.resize((max(1, round(subject.width * scale)),
                                  max(1, round(subject.height * scale))), Image.LANCZOS)
    ax, ay = ANCHORS.get(anchor, ANCHORS["center"])
    # The anchor positions the subject inside the *padded* box, so a bottom-anchored sprite
    # sits `padding` px above the canvas edge instead of flush against it. Getting this wrong
    # is what makes every asset fail the not_clipped check.
    inner_x = float(padding)
    inner_y = float(padding)
    inner_w = max(0.0, size[0] - 2.0 * padding)
    inner_h = max(0.0, size[1] - 2.0 * padding)
    x = round(inner_x + (inner_w - subject.width) * ax)
    y = round(inner_y + (inner_h - subject.height) * ay)
    x = max(0, min(x, size[0] - subject.width))
    y = max(0, min(y, size[1] - subject.height))
    canvas.alpha_composite(subject, (x, y))
    return canvas


def flatten_on(img: Image.Image, color: tuple[int, int, int] = (255, 0, 255)) -> Image.Image:
    """Composite over a solid colour - for previewing cutouts and diffing masks."""
    base = Image.new("RGBA", img.size, (*color, 255))
    base.alpha_composite(to_rgba(img))
    return base.convert("RGB")


# ---- fingerprints ----------------------------------------------------------

def dhash(img: Image.Image, *, size: int = 8) -> int:
    """Difference hash as a 64-bit int; stable across small resizes and re-encodes."""
    small = img.convert("L").resize((size + 1, size), Image.LANCZOS)
    px = np.asarray(small, dtype=np.int16)
    diff = px[:, 1:] > px[:, :-1]
    bits = 0
    for bit in diff.flatten():
        bits = (bits << 1) | int(bit)
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def dhash_hex(img: Image.Image) -> str:
    return f"{dhash(img):016x}"


def pixel_hash(img: Image.Image) -> str:
    """SHA-256 of the raw RGBA pixel bytes, ignoring file metadata.

    Better evidence of "same render" than a file hash: Blender stamps a `tEXt Date` chunk into
    every PNG, so two renders of the same scene have identical pixels and different file bytes.
    """
    return hashlib.sha256(to_rgba(img).tobytes()).hexdigest()


def file_digest(path: Path, *, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


# ---- animation helpers -----------------------------------------------------

def frame_centroid(img: Image.Image) -> tuple[float, float]:
    m = measure(img)
    return m.centroid or (img.width / 2, img.height / 2)


def pack_spritesheet(frames: Sequence[Image.Image], *, columns: int, padding: int = 0) -> tuple[Image.Image, list[dict[str, int]]]:
    """Grid-pack equally sized frames. Returns the sheet and per-frame rects."""
    if not frames:
        raise ImageError("no frames to pack")
    fw, fh = frames[0].size
    for i, f in enumerate(frames):
        if f.size != (fw, fh):
            raise ImageError(f"frame {i} is {f.size}, expected {(fw, fh)}; frames must be uniform")
    columns = max(1, min(columns, len(frames)))
    rows = (len(frames) + columns - 1) // columns
    sheet_w = columns * fw + padding * 2 * columns
    sheet_h = rows * fh + padding * 2 * rows
    sheet = Image.new("RGBA", (sheet_w, sheet_h), (0, 0, 0, 0))
    rects: list[dict[str, int]] = []
    for i, frame in enumerate(frames):
        c, r = i % columns, i // columns
        x = c * (fw + padding * 2) + padding
        y = r * (fh + padding * 2) + padding
        sheet.alpha_composite(to_rgba(frame), (x, y))
        rects.append({"index": i, "x": x, "y": y, "w": fw, "h": fh,
                      "column": c, "row": r})
    return sheet, rects


def frames_differ(a: Image.Image, b: Image.Image) -> float:
    """Mean absolute pixel difference 0..1 between two same-size frames."""
    if a.size != b.size:
        b = b.resize(a.size, Image.LANCZOS)
    arr_a = np.asarray(a.convert("RGB"), dtype=np.float32)
    arr_b = np.asarray(b.convert("RGB"), dtype=np.float32)
    return float(np.abs(arr_a - arr_b).mean() / 255.0)


def motion_metrics(a: Image.Image, b: Image.Image, *, change_threshold: int = 2) -> dict[str, float | int]:
    """How much actually moved between two frames.

    The mean difference over the whole canvas is a bad signal for a small animated detail on
    a large sprite - a waving banner on a 512px building moves 550 pixels and a mean-difference
    threshold calls that "no motion". Peak delta plus the fraction of pixels that changed
    answers the real question: did anything visibly move?
    """
    if a.size != b.size:
        b = b.resize(a.size, Image.LANCZOS)
    arr_a = np.asarray(a.convert("RGB"), dtype=np.int16)
    arr_b = np.asarray(b.convert("RGB"), dtype=np.int16)
    delta = np.abs(arr_a - arr_b).max(axis=2)
    pixels = int(delta.size)
    return {
        "mean": round(float(delta.mean()) / 255.0, 6),
        "changed_fraction": round(float((delta > change_threshold).sum()) / max(1, pixels), 6),
        "peak_delta": int(delta.max()),
    }


def is_flat(img: Image.Image, *, stddev_min: float) -> tuple[bool, float]:
    m = measure(img)
    return m.rgb_stddev < stddev_min, m.rgb_stddev
