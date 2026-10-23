"""Render one Blender source job and print its result (debug helper).

usage: python render_one.py CLASS KIND OUT_DIR [TIER]
"""

import json
import sys

import blender_run as B

if __name__ == "__main__":
    cls, kind, out = sys.argv[1:4]
    tier = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    print(json.dumps(B.run({"class": cls, "kind": kind, "tier": tier, "mode": "render", "out_dir": out})))
