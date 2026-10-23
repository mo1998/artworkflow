"""FLUX.1-dev + ControlNet-Union-Pro-2.0 refinement of a Blender render.

img2img from the Blender beauty pass, held in place by two ControlNets (depth + lineart).
The refine only repaints SURFACES - wood grain, stone, moss, weathering, warm light - and
must not move the silhouette, the camera or the composition. The knobs the loop turns:

  denoise     how much FLUX may repaint (higher = richer materials, more drift)
  depth       ControlNet strength on the depth pass
  lineart     ControlNet strength on the lineart pass
  end         the fraction of the schedule the ControlNets stay on
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path

import comfy_api as C

CKPT = "flux1-dev-fp8.safetensors"
CONTROLNET = "flux-union-pro-2.0.safetensors"

KEEP = "same silhouette, same camera, same composition, same proportions"


@dataclass(frozen=True)
class Knobs:
    denoise: float = 0.55
    depth: float = 0.55
    lineart: float = 0.50
    end: float = 0.75
    guidance: float = 3.0
    steps: int = 26
    sampler: str = "euler"
    scheduler: str = "simple"

    def as_dict(self) -> dict:
        return asdict(self)

    def but(self, **kw) -> "Knobs":
        clamp = {"denoise": (0.25, 0.85), "depth": (0.2, 1.0), "lineart": (0.2, 1.0), "end": (0.4, 1.0)}
        for k, v in list(kw.items()):
            if k in clamp:
                lo, hi = clamp[k]
                kw[k] = round(min(hi, max(lo, v)), 3)
        return replace(self, **kw)


def graph(src: str, depth: str, lineart: str, prompt: str, seed: int, k: Knobs, cutout: bool,
          width: int, height: int) -> dict:
    g: dict = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["1", 1]}},
        "4": {"class_type": "FluxGuidance", "inputs": {"guidance": k.guidance, "conditioning": ["2", 0]}},
        "10": {"class_type": "LoadImage", "inputs": {"image": src}},
        "11": {"class_type": "VAEEncode", "inputs": {"pixels": ["10", 0], "vae": ["1", 2]}},
        "12": {"class_type": "LoadImage", "inputs": {"image": depth}},
        "13": {"class_type": "LoadImage", "inputs": {"image": lineart}},
        "14": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": CONTROLNET}},
        "15": {"class_type": "ControlNetApplyAdvanced", "inputs": {
            "positive": ["4", 0], "negative": ["3", 0], "control_net": ["14", 0], "image": ["12", 0],
            "strength": k.depth, "start_percent": 0.0, "end_percent": k.end, "vae": ["1", 2]}},
        "16": {"class_type": "ControlNetApplyAdvanced", "inputs": {
            "positive": ["15", 0], "negative": ["15", 1], "control_net": ["14", 0], "image": ["13", 0],
            "strength": k.lineart, "start_percent": 0.0, "end_percent": k.end, "vae": ["1", 2]}},
        "17": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["16", 0], "negative": ["16", 1], "latent_image": ["11", 0],
            "seed": int(seed), "steps": k.steps, "cfg": 1.0, "sampler_name": k.sampler, "scheduler": k.scheduler,
            "denoise": k.denoise}},
        "18": {"class_type": "VAEDecode", "inputs": {"samples": ["17", 0], "vae": ["1", 2]}},
        "19": {"class_type": "SaveImage", "inputs": {"images": ["18", 0], "filename_prefix": "warbands_v2/refine"}},
    }
    if cutout:
        g["20"] = {"class_type": "AutoDownloadBiRefNetModel",
                   "inputs": {"model_name": "General-HR", "device": "AUTO", "dtype": "float16"}}
        g["21"] = {"class_type": "RembgByBiRefNetAdvanced", "inputs": {
            "model": ["20", 0], "images": ["18", 0], "width": 1024, "height": 1024,
            "upscale_method": "bilinear", "blur_size": 90, "blur_size_two": 6, "fill_color": False,
            "color": 0, "mask_threshold": 0.0}}
        g["22"] = {"class_type": "MaskToImage", "inputs": {"mask": ["21", 1]}}
        g["23"] = {"class_type": "SaveImage", "inputs": {"images": ["22", 0], "filename_prefix": "warbands_v2/mask"}}
    return g


def refine(inputs: dict, prompt: str, seed: int, k: Knobs, out_dir: Path, tag: str, cutout: bool,
           size: tuple[int, int], upload_prefix: str) -> dict:
    """One candidate. Returns {"rgb": path, "mask": path|None}.

    Uploads are namespaced by `upload_prefix` (the asset id): several assets refine in
    parallel and ComfyUI's input folder is shared, so a bare "c0_src.png" would let one
    asset's candidate be painted from another asset's render."""
    names = {key: C.upload(Path(inputs[key]), f"{upload_prefix}_{key}.png") for key in ("src", "depth", "lineart")}
    full = f"{prompt}, {KEEP}"
    outs = C.run(graph(names["src"], names["depth"], names["lineart"], full, seed, k, cutout, *size))
    res = {"rgb": C.fetch(outs["19"][0], out_dir / f"{tag}.png"), "mask": None}
    if cutout:
        res["mask"] = C.fetch(outs["23"][0], out_dir / f"{tag}_mask.png")
    return res
