"""Render every terrain source and report its seams (debug helper: tile seams are fixed at the
source, so check the source first).

usage: python check_terrain_sources.py OUT_DIR
"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image

import blender_run as B
import gates

if __name__ == "__main__":
    out = Path(sys.argv[1])
    for k in ("grass", "dirt", "sand", "rock", "cobble", "wood"):
        d = out / k
        B.run({"class": "terrain", "kind": k, "mode": "render", "res": [512, 512], "out_dir": str(d)})
        a = np.asarray(Image.open(d / "beauty.png").convert("RGB")).astype(int)
        edge = np.abs(a[:, 0] - a[:, -1]).mean()
        inner = np.abs(np.diff(a, axis=1)).mean()
        print(f"{k:7s} seam_x={gates.seam_ratio(a, 1):.2f} seam_y={gates.seam_ratio(a, 0):.2f} "
              f"wrap_step={edge:.2f} mean_step={inner:.2f}")
