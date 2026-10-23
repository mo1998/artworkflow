"""Warbands Village Art V2 - the deterministic pipeline.

    Manifest -> Blender (beauty, depth, lineart, matid) -> FLUX + ControlNet refine
             -> vision critic -> deterministic gates -> iterate -> export

usage:
    python scripts/warbands/run.py --manifest config/manifest.warbands.json [--only ID ...]
           [--rounds 4] [--candidates 4] [--no-critic] [--workers 3] [--rerender]

Acceptance is decided by gates.py alone. The critic ranks gated candidates and steers the
next round; it never accepts or rejects. Iteration rules (max 4 rounds x 4 candidates):

    silhouette drift   -> lower denoise, raise lineart
    weak materials     -> raise denoise
    artifacts          -> new seeds
    tile seams         -> fix the source (flagged; sources are built periodic)
    camera mismatch    -> fix Blender (flagged, needs a scene change)
    upgrade unclear    -> raise the geometry difference (flagged by the family check)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import blender_run  # noqa: E402
import comfy_api  # noqa: E402
import critic  # noqa: E402
import gates  # noqa: E402
import passes  # noqa: E402
from refine import Knobs, refine  # noqa: E402

ROOT = HERE.parents[1]
WORK = ROOT / "assets" / "warbands_v2" / "work"
APPROVED = ROOT / "assets" / "approved" / "warbands_v2"
REPORTS = ROOT / "reports"

# calibrated on HQ T0 (scripts/warbands/exp.py): denoise 0.62 keeps the materials Blender
# modelled and paints them; >0.8 turns them into flat illustration (turf -> thatch)
_K = dict(sampler="dpmpp_2m", scheduler="beta", steps=30)
DEFAULT_KNOBS = {
    "building": Knobs(denoise=0.62, depth=0.55, lineart=0.55, end=0.75, **_K),
    "card": Knobs(denoise=0.62, depth=0.55, lineart=0.55, end=0.75, **_K),
    "wall_surface": Knobs(denoise=0.55, depth=0.45, lineart=0.45, end=0.7, **_K),
    "terrain": Knobs(denoise=0.6, depth=0.3, lineart=0.3, end=0.5, **_K),
    # a landscape can be repainted harder: the horizon gate guards the composition
    "backdrop": Knobs(denoise=0.78, depth=0.5, lineart=0.3, end=0.7, **_K),
}
OUT_DIR = {"building": "buildings", "card": "buildings", "wall_surface": "wall", "terrain": "terrain",
           "backdrop": "background"}

_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(time.strftime("%H:%M:%S"), msg, flush=True)


# ------------------------------------------------------------------ Blender stage

def _src_hash() -> str:
    h = hashlib.sha1()
    for p in sorted((ROOT / "blender" / "wb").glob("*.py")) + [blender_run.SCRIPT]:
        h.update(p.read_bytes())
    return h.hexdigest()[:12]


CAMERA = ROOT / "config" / "warbands_v2_camera.json"
PLATE_CARD = 4.4  # wall cards are list art only: their plate stays blender/wb/buildings.py's


def frames(assets: list[dict], rerender: bool) -> dict:
    """One fixed iso camera per framing group (all buildings share one, the wall cards
    another). The camera is PINNED in config/warbands_v2_camera.json, so a geometry edit to
    one building never re-frames the rest of the set; every subject is measured (cached
    against the scene source) and must fit inside its pinned frame."""
    cache = WORK / "_frames.json"
    key = _src_hash()
    measured = None
    if cache.exists() and not rerender:
        data = json.loads(cache.read_text())
        if data.get("key") == key:
            measured = data["frames"]
    if measured is None:
        groups: dict[str, list] = {}
        prints: dict[str, list] = {}
        for a in assets:
            if a["class"] in ("building", "card"):
                m = blender_run.run({"class": "building", "kind": a["kind"], "tier": a.get("tier", 0),
                                     "mode": "measure", "plate": a.get("plate")})
                groups.setdefault(a["class"], []).append(m["extents"])
                prints[a["asset_id"]] = m["footprint"]
        measured = {g: blender_run.union(es) for g, es in groups.items()}
        measured["_footprints"] = prints
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"key": key, "frames": measured}, indent=2))
    if not CAMERA.exists():
        return {k: v for k, v in measured.items() if not k.startswith("_")}
    # every building must stand inside its game cell: walls and props on the ground may not
    # spill over the lane (roofs and banners above 0.6 units may - they overhang)
    half = {a["asset_id"]: (PLATE_CARD if a["class"] == "card" else a["plate"]) / 2 for a in assets
            if a["class"] in ("building", "card")}
    bad = []
    for aid, fp in measured.get("_footprints", {}).items():
        if aid in half and max(abs(v) for v in fp) > half[aid] + 0.02:
            bad.append(f"  {aid}: footprint {[round(v, 2) for v in fp]} leaves its cell (+-{half[aid]})")
    if bad:
        raise SystemExit("buildings spill over their cell - pull the geometry in (blender/wb/buildings.py):\n"
                         + "\n".join(bad))
    pinned = json.loads(CAMERA.read_text())["frames"]
    for g, e in measured.items():
        if g.startswith("_"):
            continue
        f = pinned[g]
        for axis in ("r", "u"):
            if e[axis][0] < f[axis][0] - 1e-3 or e[axis][1] > f[axis][1] + 1e-3:
                raise SystemExit(f"{g}: subjects no longer fit the pinned camera on {axis} "
                                 f"({e[axis]} vs {f[axis]}) - shrink the geometry or re-pin {CAMERA.name}")
    return pinned


def blender_source(a: dict, frame: dict | None, rerender: bool) -> Path:
    d = WORK / a["asset_id"] / "blender"
    stamp = d / "stamp.json"
    job = {"class": "building" if a["class"] in ("building", "card") else a["class"], "kind": a["kind"],
           "tier": a.get("tier", 0), "mode": "render", "out_dir": str(d), "frame": frame,
           "res": a.get("source_res"), "samples": 96, "scene": a.get("scene"), "plate": a.get("plate")}
    job = {k: v for k, v in job.items() if v is not None}
    sig = hashlib.sha1((json.dumps(job, sort_keys=True) + _src_hash()).encode()).hexdigest()
    if not rerender and stamp.exists() and json.loads(stamp.read_text()).get("sig") == sig:
        return d
    res = blender_run.run(job)
    if res.get("anchor"):
        (d / "anchor.json").write_text(json.dumps(res["anchor"]))
    stamp.write_text(json.dumps({"sig": sig}))
    return d


def export_camera(assets: list[dict], manifest: dict) -> Path | None:
    """The building camera's anchor for the game, at the shipped 512px canvas: where the
    footprint's centre (world origin) lands, how many px one world unit is, and the cell
    (plate) size in world units. The scene places every sprite by it."""
    for a in assets:
        f = WORK / a["asset_id"] / "blender" / "anchor.json"
        if a["class"] == "building" and f.exists():
            an = json.loads(f.read_text())
            k = 512 / an["canvas"]
            out = APPROVED / "buildings" / "_camera.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({"canvas": 512, "origin": [round(an["origin"][0] * k, 2),
                                                                 round(an["origin"][1] * k, 2)],
                                       "px_per_unit": round(an["px_per_unit"] * k, 4),
                                       "grid_world": manifest["grid_world"], "plate": a["plate"]},
                                      indent=2) + "\n")
            return out
    return None


# ------------------------------------------------------------------ helpers

def tile2(src: Path, dst: Path) -> Path:
    a = np.asarray(Image.open(src).convert("RGB"))
    Image.fromarray(np.tile(a, (2, 2, 1))).save(dst)
    return dst


def seam_blend(a: np.ndarray, band: float = 0.22) -> np.ndarray:
    """Close the residual wrap seam: near each edge, cross-fade to the copy rolled by half a
    tile, whose content is continuous across the wrap. Both axes."""
    out = a.astype(np.float32)
    for axis in (1, 0):
        n = out.shape[axis]
        shifted = np.roll(out, n // 2, axis=axis)
        x = np.arange(n, dtype=np.float32)
        d = np.minimum(x, n - x) / max(1.0, n * band / 2)
        m = np.clip(1 - d, 0, 1)
        m = m * m * (3 - 2 * m)
        m = m[None, :, None] if axis == 1 else m[:, None, None]
        out = out * (1 - m) + shifted * m
    return np.clip(out, 0, 255).astype(np.uint8)


def on_grey(rgba: np.ndarray) -> np.ndarray:
    a = rgba[..., 3:4].astype(np.float32) / 255
    return (rgba[..., :3] * a + np.array([110, 112, 108]) * (1 - a)).astype(np.uint8)


# ------------------------------------------------------------------ one asset

def candidate(a: dict, inputs: dict, prompt: str, seed: int, k: Knobs, rdir: Path, tag: str,
              src_rgb: np.ndarray, src_mask: np.ndarray, bundle: Path, regate: bool = False) -> dict:
    cls = a["class"]
    size = Image.open(inputs["src"]).size
    cutout = cls in ("building", "card")
    reuse = {"rgb": rdir / f"{tag}.png", "mask": rdir / f"{tag}_mask.png" if cutout else None}
    if regate and reuse["rgb"].exists() and (not cutout or reuse["mask"].exists()):
        # --regate: same seed, same knobs -> the same painting; only the post-refine steps
        # (palette lock, shadow, finish) and the gates are redone
        res = reuse
    else:
        res = refine(inputs, prompt, seed, k, rdir, tag, cutout=cutout, size=size, upload_prefix=a["asset_id"])
    rgb = np.asarray(Image.open(res["rgb"]).convert("RGB"))
    c = {"tag": tag, "seed": seed, "knobs": k.as_dict(), "raw": str(res["rgb"])}
    if cls in ("building", "card"):
        cut = np.asarray(Image.open(res["mask"]).convert("L"))
        rgb = gates.palette_lock(rgb, src_rgb)
        rgba = gates.composite_cutout(rgb, cut, src_mask)
        shadow = np.asarray(Image.open(inputs["shadow"]).convert("L")) if inputs.get("shadow") else None
        g = gates.building(rgba, cut, src_mask, src_rgb, shadow)
        final = g.pop("rgba512")
        Image.fromarray(final).save(rdir / f"{tag}_final.png")
        Image.fromarray(on_grey(final)).save(rdir / f"{tag}_view.png")
    elif cls in ("terrain", "wall_surface"):
        h, w = rgb.shape[0] // 2, rgb.shape[1] // 2
        crop = rgb[h // 2:h // 2 + h, w // 2:w // 2 + w]
        gate = gates.terrain if cls == "terrain" else gates.wall
        # the 2x2-tiled refine already wraps; the blend is only the repair for a crop that does not
        final, g = crop, gate(crop)
        if not g["pass"]:
            final = seam_blend(crop)
            g = gate(final)
            g["scores"]["seam_blend"] = True
        Image.fromarray(final).save(rdir / f"{tag}_final.png")
        Image.fromarray(np.tile(final, (2, 2, 1))).save(rdir / f"{tag}_view.png")
    else:
        mid = np.asarray(Image.open(bundle / "matid.png").convert("RGBA"))
        sky = mid[..., 3] < 128
        meadow = (np.abs(mid[..., :3].astype(int) - np.array(passes.plate_id())).max(axis=2) <= 3) & ~sky
        rgb = gates.match_ground(rgb[..., :3], meadow, passes.grass_color())
        g = gates.backdrop(rgb, sky, src_rgb)
        Image.fromarray(rgb).save(rdir / f"{tag}_final.png")
        Image.fromarray(rgb).save(rdir / f"{tag}_view.png")
    c.update(g)
    c["final"] = str(rdir / f"{tag}_final.png")
    c["view"] = str(rdir / f"{tag}_view.png")
    return c


def failure_kind(c: dict) -> str:
    g = c["gates"]
    if "iou" in g and (not g["iou"]["pass"] or not g["bbox_drift_px"]["pass"]):
        return "silhouette_drift"
    if any(k.startswith(("seam", "sheared")) and not v["pass"] for k, v in g.items()):
        return "tile_seams"
    if "horizon_follows_source" in g and not g["horizon_follows_source"]["pass"]:
        return "silhouette_drift"
    return "artifacts"


def process(a: dict, manifest: dict, fr: dict, opts) -> dict:
    aid, cls = a["asset_id"], a["class"]
    t0 = time.time()
    bundle = blender_source(a, fr.get(cls) if cls in ("building", "card") else None, opts.rerender)
    wdir = WORK / aid
    inputs = passes.prepare(bundle, wdir / "inputs", building=cls in ("building", "card"))
    src_rgb = np.asarray(Image.open(inputs["src"]).convert("RGB"))
    src_mask = np.asarray(Image.open(inputs["mask"])) > 127
    if cls in ("terrain", "wall_surface"):
        for key in ("src", "depth", "lineart"):
            inputs[key] = tile2(inputs[key], wdir / "inputs" / f"{key}_2x2.png")
        src_view = wdir / "inputs" / "src_2x2.png"
    else:
        src_view = inputs["src"]
    focus = manifest["style"]["focus"][cls]
    prompt = f"{a['prompt']}, {manifest['style']['base']}, {focus}"
    knobs = DEFAULT_KNOBS[cls].but(**a.get("knobs", {}))
    base_seed = int(a.get("seed", manifest.get("seed", 0)))
    rounds: list[dict] = []
    best = None
    flags: list[str] = []
    for r in range(opts.rounds):
        rdir = wdir / f"round{r}"
        rdir.mkdir(parents=True, exist_ok=True)
        cands = []
        for i in range(opts.candidates):
            seed = base_seed + r * 1000 + i * 17
            cands.append(candidate(a, inputs, prompt, seed, knobs, rdir, f"c{i}", src_rgb, src_mask, bundle,
                                   regate=opts.regate and r == 0))
        review = (critic.review(Path(src_view), [Path(c["view"]) for c in cands], a.get("subject", aid), rdir)
                  if opts.critic else {"model": None, "ranking": [], "candidates": {}})
        for i, c in enumerate(cands):
            c["critic"] = review["candidates"].get(critic.LABELS[i], {})
        gated = [c for c in cands if c["pass"]]
        order = {lab: n for n, lab in enumerate(review.get("ranking", []))}

        def is_weak(c):
            return bool(c["scores"].get("weak_materials") or c["critic"].get("weak_materials"))

        def score(c):
            # gated non-weak first; among equals the critic's ranking, then detail
            crit = order.get(critic.LABELS[cands.index(c)], 9)
            s = c["scores"]
            det = -s.get("detail", 0.0) + (0.5 if c["critic"].get("artifacts") else 0.0)
            return (is_weak(c), crit, det)

        gated.sort(key=score)
        pick = gated[0] if gated else None
        rec = {"round": r, "knobs": knobs.as_dict(), "critic_model": review.get("model"),
               "critic_error": review.get("error"), "candidates": cands,
               "picked": pick["tag"] if pick else None}
        rounds.append(rec)
        weak = bool(pick and is_weak(pick))
        if pick and (best is None or not weak or best.get("_weak")):
            best = {**pick, "_weak": weak, "_round": r}
        log(f"{aid} r{r} knobs={knobs.as_dict()} gated={len(gated)}/{len(cands)} "
            f"pick={rec['picked']} weak={weak} critic={review.get('model')}")
        if pick and not weak:
            rec["decision"] = "accept"
            break
        # iteration rules
        if not gated:
            kinds = [failure_kind(c) for c in cands]
            top = max(set(kinds), key=kinds.count)
            rec["decision"] = f"retry:{top}"
            if top == "silhouette_drift":
                knobs = knobs.but(denoise=knobs.denoise - 0.08, lineart=knobs.lineart + 0.15)
            elif top == "tile_seams":
                flags.append("tile_seams: fix the source asset")
        elif weak:
            rec["decision"] = "retry:weak_materials"
            knobs = knobs.but(denoise=knobs.denoise + 0.07)
        if any(c["critic"].get("camera_mismatch") for c in cands if c["pass"]):
            flags.append("critic: camera mismatch reported (advisory) - check the Blender camera")
    status = "accepted" if best else "failed"
    out = None
    if best:
        out = APPROVED / OUT_DIR[cls] / f"{aid}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        Image.open(best["final"]).save(out)
    record = {"asset_id": aid, "class": cls, "kind": a["kind"], "tier": a.get("tier", 0), "status": status,
              "weak_materials": bool(best and best["_weak"]), "output": str(out) if out else None,
              "chosen": {k: v for k, v in (best or {}).items() if not k.startswith("_")},
              "accepted_round": best["_round"] if best else None, "flags": sorted(set(flags)),
              "rounds": rounds, "seconds": round(time.time() - t0, 1), "blender": str(bundle)}
    (wdir / "record.json").write_text(json.dumps(record, indent=2, default=str))
    log(f"{aid}: {status.upper()} in {record['seconds']}s")
    return record


# ------------------------------------------------------------------ families + report

def family_checks(manifest: dict, records: dict) -> dict:
    fams: dict[str, list] = {}
    for a in manifest["assets"]:
        if a["class"] == "building":
            fams.setdefault(a["kind"], []).append(a)
    out = {}
    for kind, items in fams.items():
        items.sort(key=lambda a: a.get("tier", 0))
        recs = [records.get(a["asset_id"]) for a in items]
        if not all(r and r["status"] == "accepted" for r in recs):
            out[kind] = {"pass": False, "reason": "not every tier accepted"}
            continue
        rgbas = [np.asarray(Image.open(r["output"]).convert("RGBA")) for r in recs]

        def inp(a, name, mode):
            return np.asarray(Image.open(WORK / a["asset_id"] / "inputs" / name).convert(mode).resize((512, 512)))

        subjects = [inp(a, "mask.png", "L") > 127 for a in items]
        srcs = [inp(a, "src.png", "RGB") for a in items]
        out[kind] = gates.family(subjects, rgbas, srcs)
        if not out[kind]["pass"] and not out[kind].get("upgrade_clear", True):
            out[kind]["flag"] = "upgrade unclear: increase the geometry difference between tiers"
    return out


def write_report(manifest: dict, records: dict, fam: dict) -> Path:
    REPORTS.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    data = {"run": stamp, "assets": records, "families": fam,
            "summary": {"accepted": sum(r["status"] == "accepted" for r in records.values()),
                        "failed": sum(r["status"] != "accepted" for r in records.values()),
                        "families_pass": sum(f.get("pass", False) for f in fam.values()),
                        "families": len(fam)}}
    jp = REPORTS / f"warbands_v2-{stamp}.json"
    jp.write_text(json.dumps(data, indent=2, default=str))
    lines = [f"# Warbands v2 art run {stamp}", "",
             f"accepted {data['summary']['accepted']} / {len(records)}, "
             f"families {data['summary']['families_pass']} / {data['summary']['families']}", "",
             "| asset | status | round | knobs | gates |", "|---|---|---|---|---|"]
    for aid, r in sorted(records.items()):
        ch = r.get("chosen") or {}
        gs = ", ".join(f"{k}={v.get('value', v.get('coverage', ''))}" for k, v in (ch.get("gates") or {}).items())
        kn = ch.get("knobs") or {}
        lines.append(f"| {aid} | {r['status']}{' (weak)' if r.get('weak_materials') else ''} | "
                     f"{r.get('accepted_round')} | d={kn.get('denoise')} l={kn.get('lineart')} | {gs} |")
    lines += ["", "## Families", ""]
    for k, f in fam.items():
        lines.append(f"- **{k}**: {'PASS' if f.get('pass') else 'FAIL'} {json.dumps(f)}")
    mp = jp.with_suffix(".md")
    mp.write_text("\n".join(lines) + "\n")
    return mp


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", default=str(ROOT / "config" / "manifest.warbands.json"))
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--candidates", type=int, default=4)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--no-critic", dest="critic", action="store_false")
    ap.add_argument("--rerender", action="store_true")
    ap.add_argument("--force", action="store_true", help="redo assets that are already accepted")
    ap.add_argument("--regate", action="store_true",
                    help="reuse round-0 paintings that already exist (post-refine/gate changes only)")
    ap.add_argument("--sources-only", action="store_true", help="render the Blender sources and stop")
    opts = ap.parse_args()
    manifest = json.loads(Path(opts.manifest).read_text())
    if manifest.get("schema_version") != 2:
        print("error: not a v2 (warbands-v2) manifest", file=sys.stderr)
        return 2
    assets = manifest["assets"]
    todo = [a for a in assets if not opts.only or a["asset_id"] in opts.only or a["kind"] in opts.only]
    fr = frames(assets, opts.rerender)
    log(f"frames: {json.dumps(fr)}")
    for a in todo:
        blender_source(a, fr.get(a["class"]) if a["class"] in ("building", "card") else None, opts.rerender)
    log(f"blender sources ready for {len(todo)} assets; camera anchor -> {export_camera(assets, manifest)}")
    if opts.sources_only:
        return 0
    if not comfy_api.up():
        print("error: ComfyUI is not reachable at", comfy_api.URL, file=sys.stderr)
        return 2
    records: dict = {}
    for p in sorted(WORK.glob("*/record.json")):
        r = json.loads(p.read_text())
        records[r["asset_id"]] = r

    def safe(a):
        prev = records.get(a["asset_id"])
        if (not opts.force and prev and prev.get("status") == "accepted" and prev.get("output")
                and Path(prev["output"]).exists()):
            log(f"{a['asset_id']}: already accepted (use --force to redo)")
            return prev
        try:
            return process(a, manifest, fr, opts)
        except Exception as e:  # one asset's crash must not sink the run
            log(f"{a['asset_id']}: ERROR {e}\n{traceback.format_exc()}")
            return {"asset_id": a["asset_id"], "class": a["class"], "kind": a["kind"], "status": "error",
                    "error": str(e)}

    with ThreadPoolExecutor(max_workers=opts.workers) as pool:
        for rec in pool.map(safe, todo):
            records[rec["asset_id"]] = rec
    fam = family_checks(manifest, records)
    report = write_report(manifest, records, fam)
    log(f"report: {report}")
    bad = [k for k, r in records.items() if r["status"] != "accepted"]
    return 1 if bad or not all(f.get("pass") for f in fam.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
