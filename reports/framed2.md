# Art pipeline report - framed2

Generated 2026-10-18T14:53:39+03:00 from `/home/mrazek/ArtWorkflow/config/manifest.json`.

## Totals

- assets: **10**
- exported: **9**
- failed: **1**
- review required: **0**
- retried at least once: **0**

| status | count |
| --- | --- |
| exported | 9 |
| failed | 1 |

## Assets

| asset | source | status | seed | clip | exported to | notes |
| --- | --- | --- | --- | --- | --- | --- |
| demo_hut | blender | exported | - | - | `assets/approved/buildings/demo_hut.png` | - |
| demo_hut__lvl2 | blender | exported | - | - | `assets/approved/buildings/demo_hut__lvl2.png` | - |
| demo_hut__lvl3 | blender | exported | - | - | `assets/approved/buildings/demo_hut__lvl3.png` | - |
| demo_hut_flag | blender | exported | - | banner_wave | `assets/approved/animations/demo_hut_flag.png` | - |
| vampire_keep | blender | exported | - | - | `assets/approved/buildings/vampire_keep.png` | - |
| vampire_keep__lvl2 | blender | exported | - | - | `assets/approved/buildings/vampire_keep__lvl2.png` | - |
| vampire_keep__lvl3 | blender | exported | - | - | `assets/approved/buildings/vampire_keep__lvl3.png` | - |
| vampire_grave | blender | exported | - | - | `assets/approved/props/vampire_grave.png` | - |
| vampire_gate_torch | blender | exported | - | torch_flicker | `assets/approved/animations/vampire_gate_torch.png` | - |
| vampire_watcher | blender | failed | - | turntable | `assets/approved/animations/vampire_watcher.png` | failed: registration_stable |

## Provenance

| asset | model | workflow / generator | licence recorded |
| --- | --- | --- | --- |
| demo_hut | procedural (Blender 4.5.9) | `generate_building.py` | yes |
| demo_hut__lvl2 | procedural (Blender 4.5.9) | `generate_building.py` | yes |
| demo_hut__lvl3 | procedural (Blender 4.5.9) | `generate_building.py` | yes |
| demo_hut_flag | procedural (Blender 4.5.9) | `generate_building.py` | yes |
| vampire_keep | procedural (Blender 4.5.9) | `generate_building.py` | yes |
| vampire_keep__lvl2 | procedural (Blender 4.5.9) | `generate_building.py` | yes |
| vampire_keep__lvl3 | procedural (Blender 4.5.9) | `generate_building.py` | yes |
| vampire_grave | procedural (Blender 4.5.9) | `generate_prop.py` | yes |
| vampire_gate_torch | procedural (Blender 4.5.9) | `generate_building.py` | yes |
| vampire_watcher | procedural (Blender 4.5.9) | `generate_prop.py` | yes |

## Logs

- `logs/framed2/demo_hut-blender.log.log`
- `logs/framed2/demo_hut-measure.log.log`
- `logs/framed2/demo_hut__lvl2-blender.log.log`
- `logs/framed2/demo_hut__lvl2-measure.log.log`
- `logs/framed2/demo_hut__lvl3-blender.log.log`
- `logs/framed2/demo_hut__lvl3-measure.log.log`
- `logs/framed2/demo_hut_flag-blender.log.log`
- `logs/framed2/demo_hut_flag-measure.log.log`
- `logs/framed2/events.jsonl`
- `logs/framed2/export-summary.json`
- `logs/framed2/framing.log.log`
- `logs/framed2/generate-blender-summary.json`
- `logs/framed2/generate-comfyui-summary.json`
- `logs/framed2/godot-check-summary.json`
- `logs/framed2/godot-check.log.log`
- `logs/framed2/godot-import.log.log`
- `logs/framed2/process-summary.json`
- `logs/framed2/spritesheet-summary.json`
- `logs/framed2/validate-summary.json`
- `logs/framed2/vampire_gate_torch-blender.log.log`
- `logs/framed2/vampire_gate_torch-measure.log.log`
- `logs/framed2/vampire_grave-blender.log.log`
- `logs/framed2/vampire_grave-measure.log.log`
- `logs/framed2/vampire_keep-blender.log.log`
- `logs/framed2/vampire_keep-measure.log.log`
- `logs/framed2/vampire_keep__lvl2-blender.log.log`
- `logs/framed2/vampire_keep__lvl2-measure.log.log`
- `logs/framed2/vampire_keep__lvl3-blender.log.log`
- `logs/framed2/vampire_keep__lvl3-measure.log.log`
- `logs/framed2/vampire_watcher-blender.log.log`
- `logs/framed2/vampire_watcher-measure.log.log`

## Notes

- `review_required` means every automatic check passed but a human should look before shipping; it is not a pass.

