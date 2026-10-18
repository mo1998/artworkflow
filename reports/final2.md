# Art pipeline report - final2

Generated 2026-10-18T13:35:36+03:00 from `/home/mrazek/ArtWorkflow/config/manifest.json`.

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
| demo_watchtower_a | comfyui | exported | 481516 | - | `assets/approved/buildings/demo_watchtower_a.png` | - |
| demo_watchtower_b | comfyui | exported | 90210 | - | `assets/approved/buildings/demo_watchtower_b.png` | - |
| demo_hut | blender | exported | - | - | `assets/approved/buildings/demo_hut.png` | - |
| demo_hut__lvl2 | blender | exported | - | - | `assets/approved/buildings/demo_hut__lvl2.png` | - |
| demo_hut__lvl3 | blender | exported | - | - | `assets/approved/buildings/demo_hut__lvl3.png` | - |
| demo_hut_flag | blender | exported | - | banner_wave | `assets/approved/animations/demo_hut_flag.png` | - |

## Provenance

| asset | model | workflow / generator | licence recorded |
| --- | --- | --- | --- |
| demo_watchtower_a | FLUX.1-dev fp8 | `workflows/comfyui/flux_txt2img.json` | yes |
| demo_watchtower_b | FLUX.1-dev fp8 | `workflows/comfyui/flux_txt2img.json` | yes |
| demo_hut | procedural (Blender 4.5.9) | `generate_building.py` | yes |
| demo_hut__lvl2 | procedural (Blender 4.5.9) | `generate_building.py` | yes |
| demo_hut__lvl3 | procedural (Blender 4.5.9) | `generate_building.py` | yes |
| demo_hut_flag | procedural (Blender 4.5.9) | `generate_building.py` | yes |

## Logs

- `logs/final2/demo_hut-blender.log.log`
- `logs/final2/demo_hut__lvl2-blender.log.log`
- `logs/final2/demo_hut__lvl3-blender.log.log`
- `logs/final2/demo_hut_flag-blender.log.log`
- `logs/final2/events.jsonl`
- `logs/final2/export-summary.json`
- `logs/final2/generate-blender-summary.json`
- `logs/final2/generate-comfyui-summary.json`
- `logs/final2/godot-check-summary.json`
- `logs/final2/godot-check.log.log`
- `logs/final2/godot-import.log.log`
- `logs/final2/process-summary.json`
- `logs/final2/spritesheet-summary.json`
- `logs/final2/validate-summary.json`

## Notes

- `review_required` means every automatic check passed but a human should look before shipping; it is not a pass.

