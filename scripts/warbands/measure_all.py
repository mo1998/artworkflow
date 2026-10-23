"""Print every building frame's projected extents (sizing the shared iso camera)."""

import blender_run as B

TIERS = {"headquarters": 3, "timber_camp": 3, "clay_pit": 3, "iron_mine": 3, "farm": 3, "warehouse": 3,
         "barracks": 3, "market": 2, "stable": 2, "academy": 1, "wall_palisade": 1, "wall_timber": 1,
         "wall_stone": 1}

if __name__ == "__main__":
    for k, n in TIERS.items():
        for t in range(n):
            e = B.run({"class": "building", "kind": k, "tier": t, "mode": "measure"})["extents"]
            print(f"{k:14s} t{t} r=[{e['r'][0]:.2f},{e['r'][1]:.2f}] u=[{e['u'][0]:.2f},{e['u'][1]:.2f}] "
                  f"span_u={e['u'][1] - e['u'][0]:.2f}")
