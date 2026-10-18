# Art pipeline report - vampire1

Generated 2026-10-18T14:15:44+03:00 from `/home/mrazek/ArtWorkflow/config/manifest.json`.

## Totals

- assets: **10**
- exported: **10**
- failed: **0**
- review required: **0**
- retried at least once: **0**

| status | count |
| --- | --- |
| exported | 10 |

## Assets

| asset | source | status | seed | clip | exported to | notes |
| --- | --- | --- | --- | --- | --- | --- |
| vampire_manor_house | comfyui | exported | 771901 | - | `assets/approved/buildings/vampire_manor_house.png` | - |
| vampire_crypt | comfyui | exported | 449213 | - | `assets/approved/buildings/vampire_crypt.png` | - |
| vampire_blood_well | comfyui | exported | 55021 | - | `assets/approved/props/vampire_blood_well.png` | - |
| vampire_lord | comfyui | exported | 18327 | - | `assets/approved/portraits/vampire_lord.png` | errors: 1 |
| vampire_keep | blender | exported | - | - | `assets/approved/buildings/vampire_keep.png` | - |
| vampire_keep__lvl2 | blender | exported | - | - | `assets/approved/buildings/vampire_keep__lvl2.png` | - |
| vampire_keep__lvl3 | blender | exported | - | - | `assets/approved/buildings/vampire_keep__lvl3.png` | - |
| vampire_grave | blender | exported | - | - | `assets/approved/props/vampire_grave.png` | - |
| vampire_gate_torch | blender | exported | - | torch_flicker | `assets/approved/animations/vampire_gate_torch.png` | - |
| vampire_watcher | blender | exported | - | turntable | `assets/approved/animations/vampire_watcher.png` | - |

## Provenance

| asset | model | workflow / generator | licence recorded |
| --- | --- | --- | --- |
| vampire_manor_house | FLUX.1-dev fp8 | `workflows/comfyui/flux_txt2img.json` | yes |
| vampire_crypt | FLUX.1-dev fp8 | `workflows/comfyui/flux_txt2img.json` | yes |
| vampire_blood_well | FLUX.1-dev fp8 | `workflows/comfyui/flux_txt2img.json` | yes |
| vampire_lord | FLUX.1-dev fp8 | `workflows/comfyui/flux_txt2img.json` | yes |
| vampire_keep | procedural (Blender 4.5.9) | `generate_building.py` | yes |
| vampire_keep__lvl2 | procedural (Blender 4.5.9) | `generate_building.py` | yes |
| vampire_keep__lvl3 | procedural (Blender 4.5.9) | `generate_building.py` | yes |
| vampire_grave | procedural (Blender 4.5.9) | `generate_prop.py` | yes |
| vampire_gate_torch | procedural (Blender 4.5.9) | `generate_building.py` | yes |
| vampire_watcher | procedural (Blender 4.5.9) | `generate_prop.py` | yes |

## Logs

- `logs/vampire1/events.jsonl`
- `logs/vampire1/export-summary.json`
- `logs/vampire1/generate-blender-summary.json`
- `logs/vampire1/generate-comfyui-summary.json`
- `logs/vampire1/godot-check-summary.json`
- `logs/vampire1/godot-check.log.log`
- `logs/vampire1/godot-import.log.log`
- `logs/vampire1/process-summary.json`
- `logs/vampire1/report-summary.json`
- `logs/vampire1/spritesheet-summary.json`
- `logs/vampire1/validate-summary.json`
- `logs/vampire1/vampire_gate_torch-blender.log.log`
- `logs/vampire1/vampire_grave-blender.log.log`
- `logs/vampire1/vampire_keep-blender.log.log`
- `logs/vampire1/vampire_keep__lvl2-blender.log.log`
- `logs/vampire1/vampire_keep__lvl3-blender.log.log`
- `logs/vampire1/vampire_watcher-blender.log.log`

## Notes

- `review_required` means every automatic check passed but a human should look before shipping; it is not a pass.

