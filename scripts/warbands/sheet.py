"""Contact sheet of every Blender source (or every approved frame) - for eyeballing a set.

usage: python sheet.py OUT.png [--approved]
"""

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "assets" / "warbands_v2" / "work"
APPROVED = ROOT / "assets" / "approved" / "warbands_v2"


def main():
    out = Path(sys.argv[1])
    approved = "--approved" in sys.argv
    manifest = json.loads((ROOT / "config" / "manifest.warbands.json").read_text())
    tiles = []
    for a in manifest["assets"]:
        if a["class"] not in ("building", "card"):
            continue
        if approved:
            p = APPROVED / "buildings" / f"{a['asset_id']}.png"
        else:
            p = WORK / a["asset_id"] / "blender" / "beauty.png"
        if not p.exists():
            continue
        im = Image.open(p).convert("RGBA")
        bg = Image.new("RGBA", im.size, (120, 140, 100, 255))
        bg.alpha_composite(im)
        t = bg.convert("RGB").resize((256, 256))
        ImageDraw.Draw(t).text((4, 4), a["asset_id"].replace("wb_", ""), fill=(255, 255, 255))
        tiles.append(t)
    cols = 6
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 256, rows * 256), (30, 30, 30))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % cols) * 256, (i // cols) * 256))
    sheet.save(out)
    print(out, len(tiles))


if __name__ == "__main__":
    main()
