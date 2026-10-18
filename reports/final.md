# Art pipeline report - release

Generated 2026-10-18T15:41:41+03:00 from `config/manifest.json`.

## Totals

- assets: **16**
- exported: **16**
- failed: **0**
- review required: **0**
- retried at least once: **0**

| status | count |
| --- | --- |
| exported | 16 |

## Assets

| asset | source | status | seed | clip | exported to | notes |
| --- | --- | --- | --- | --- | --- | --- |
| demo_watchtower_a | comfyui | exported | 481516 | - | `assets/approved/buildings/demo_watchtower_a.png` | - |
| demo_watchtower_b | comfyui | exported | 90210 | - | `assets/approved/buildings/demo_watchtower_b.png` | - |
| demo_hut | blender | exported | - | - | `assets/approved/buildings/demo_hut.png` | - |
| demo_hut__lvl2 | blender | exported | - | - | `assets/approved/buildings/demo_hut__lvl2.png` | - |
| demo_hut__lvl3 | blender | exported | - | - | `assets/approved/buildings/demo_hut__lvl3.png` | - |
| demo_hut_flag | blender | exported | - | banner_wave | `assets/approved/animations/demo_hut_flag.png` | - |
| vampire_manor_house | comfyui | exported | 771901 | - | `assets/approved/buildings/vampire_manor_house.png` | - |
| vampire_crypt | comfyui | exported | 449213 | - | `assets/approved/buildings/vampire_crypt.png` | - |
| vampire_blood_well | comfyui | exported | 55021 | - | `assets/approved/props/vampire_blood_well.png` | - |
| vampire_lord | comfyui | exported | 615042 | - | `assets/approved/portraits/vampire_lord.png` | - |
| vampire_keep | blender | exported | - | - | `assets/approved/buildings/vampire_keep.png` | - |
| vampire_keep__lvl2 | blender | exported | - | - | `assets/approved/buildings/vampire_keep__lvl2.png` | - |
| vampire_keep__lvl3 | blender | exported | - | - | `assets/approved/buildings/vampire_keep__lvl3.png` | - |
| vampire_grave | blender | exported | - | - | `assets/approved/props/vampire_grave.png` | - |
| vampire_gate_torch | blender | exported | - | torch_flicker | `assets/approved/animations/vampire_gate_torch.png` | - |
| vampire_watcher | blender | exported | - | turntable | `assets/approved/animations/vampire_watcher.png` | - |

## Provenance

| asset | model | workflow / generator | licence recorded |
| --- | --- | --- | --- |
| demo_watchtower_a | FLUX.1-dev fp8 | `workflows/comfyui/flux_txt2img.json` | yes |
| demo_watchtower_b | FLUX.1-dev fp8 | `workflows/comfyui/flux_txt2img.json` | yes |
| demo_hut | procedural (Blender 4.5.9) | `generate_building.py` | yes |
| demo_hut__lvl2 | procedural (Blender 4.5.9) | `generate_building.py` | yes |
| demo_hut__lvl3 | procedural (Blender 4.5.9) | `generate_building.py` | yes |
| demo_hut_flag | procedural (Blender 4.5.9) | `generate_building.py` | yes |
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

- `logs/release/demo_hut-blender.log.log`
- `logs/release/demo_hut-measure.log.log`
- `logs/release/demo_hut__lvl2-blender.log.log`
- `logs/release/demo_hut__lvl2-measure.log.log`
- `logs/release/demo_hut__lvl3-blender.log.log`
- `logs/release/demo_hut__lvl3-measure.log.log`
- `logs/release/demo_hut_flag-blender.log.log`
- `logs/release/demo_hut_flag-measure.log.log`
- `logs/release/events.jsonl`
- `logs/release/export-summary.json`
- `logs/release/framing.log`
- `logs/release/generate-blender-summary.json`
- `logs/release/generate-comfyui-summary.json`
- `logs/release/godot-check-summary.json`
- `logs/release/godot-check.log.log`
- `logs/release/godot-import.log.log`
- `logs/release/process-summary.json`
- `logs/release/report-summary.json`
- `logs/release/spritesheet-summary.json`
- `logs/release/validate-summary.json`
- `logs/release/vampire_gate_torch-blender.log.log`
- `logs/release/vampire_gate_torch-measure.log.log`
- `logs/release/vampire_grave-blender.log.log`
- `logs/release/vampire_grave-measure.log.log`
- `logs/release/vampire_keep-blender.log.log`
- `logs/release/vampire_keep-measure.log.log`
- `logs/release/vampire_keep__lvl2-blender.log.log`
- `logs/release/vampire_keep__lvl2-measure.log.log`
- `logs/release/vampire_keep__lvl3-blender.log.log`
- `logs/release/vampire_keep__lvl3-measure.log.log`
- `logs/release/vampire_watcher-blender.log.log`
- `logs/release/vampire_watcher-measure.log.log`

## Notes

- `review_required` means every automatic check passed but a human should look before shipping; it is not a pass.

