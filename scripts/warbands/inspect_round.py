"""Recompute the gates for one asset's round from its saved candidates (debug helper).

usage: python inspect_round.py ASSET_ID ROUND
"""

import json
import sys

import numpy as np
from PIL import Image

import gates
from run import WORK

if __name__ == "__main__":
    aid, r = sys.argv[1], int(sys.argv[2])
    w = WORK / aid
    src_rgb = np.asarray(Image.open(w / "inputs" / "src.png").convert("RGB"))
    src_mask = np.asarray(Image.open(w / "inputs" / "mask.png")) > 127
    for c in sorted((w / f"round{r}").glob("c?.png")):
        rgb = np.asarray(Image.open(c).convert("RGB"))
        cut = np.asarray(Image.open(c.with_name(c.stem + "_mask.png")).convert("L"))
        g = gates.building(gates.composite_cutout(rgb, cut, src_mask), cut, src_mask, src_rgb)
        g.pop("rgba512")
        print(c.stem, json.dumps({k: v for k, v in g["gates"].items()}), g["scores"])
