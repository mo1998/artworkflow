# Art pipeline report - vampire3

Generated 2026-10-18T14:21:09+03:00 from `/home/mrazek/ArtWorkflow/config/manifest.json`.

## Totals

- assets: **6**
- exported: **6**
- failed: **0**
- review required: **0**
- retried at least once: **0**

| status | count |
| --- | --- |
| exported | 6 |

## Assets

| asset | source | status | seed | clip | exported to | notes |
| --- | --- | --- | --- | --- | --- | --- |
| vampire_keep | blender | exported | - | - | `assets/approved/buildings/vampire_keep.png` | - |
| vampire_keep__lvl2 | blender | exported | - | - | `assets/approved/buildings/vampire_keep__lvl2.png` | - |
| vampire_keep__lvl3 | blender | exported | - | - | `assets/approved/buildings/vampire_keep__lvl3.png` | - |
| vampire_grave | blender | exported | - | - | `assets/approved/props/vampire_grave.png` | - |
| vampire_gate_torch | blender | exported | - | torch_flicker | `assets/approved/animations/vampire_gate_torch.png` | - |
| vampire_watcher | blender | exported | - | turntable | `assets/approved/animations/vampire_watcher.png` | - |

## Provenance

| asset | model | workflow / generator | licence recorded |
| --- | --- | --- | --- |
| vampire_keep | procedural (Blender 4.5.9) | `generate_building.py` | yes |
| vampire_keep__lvl2 | procedural (Blender 4.5.9) | `generate_building.py` | yes |
| vampire_keep__lvl3 | procedural (Blender 4.5.9) | `generate_building.py` | yes |
| vampire_grave | procedural (Blender 4.5.9) | `generate_prop.py` | yes |
| vampire_gate_torch | procedural (Blender 4.5.9) | `generate_building.py` | yes |
| vampire_watcher | procedural (Blender 4.5.9) | `generate_prop.py` | yes |

## Logs

- `logs/vampire3/events.jsonl`
- `logs/vampire3/export-summary.json`
- `logs/vampire3/generate-blender-summary.json`
- `logs/vampire3/generate-comfyui-summary.json`
- `logs/vampire3/godot-check-summary.json`
- `logs/vampire3/godot-check.log.log`
- `logs/vampire3/godot-import.log.log`
- `logs/vampire3/process-summary.json`
- `logs/vampire3/spritesheet-summary.json`
- `logs/vampire3/validate-summary.json`
- `logs/vampire3/vampire_gate_torch-blender.log.log`
- `logs/vampire3/vampire_grave-blender.log.log`
- `logs/vampire3/vampire_keep-blender.log.log`
- `logs/vampire3/vampire_keep__lvl2-blender.log.log`
- `logs/vampire3/vampire_keep__lvl3-blender.log.log`
- `logs/vampire3/vampire_watcher-blender.log.log`

## Notes

- `review_required` means every automatic check passed but a human should look before shipping; it is not a pass.

