# Third-party licences

`LICENSE` (MIT) covers the pipeline **code** in this repository. It does not cover the models,
checkpoints, LoRAs, custom nodes or fonts the pipeline can drive — each carries its own licence,
and you are responsible for checking it before shipping anything.

## What the shipped examples use

| component | licence |
| --- | --- |
| [FLUX.1-dev](https://huggingface.co/black-forest-labs/FLUX.1-dev) (`flux1-dev-fp8.safetensors`) | **non-commercial** — verify before any commercial use |
| [ComfyUI_BiRefNet_ll](https://github.com/lldacing/ComfyUI_BiRefNet_ll) + `General-HR` weights | see the node pack and the BiRefNet model card |
| [Blender](https://www.blender.org/) | GPL; output geometry and renders are yours |
| [Godot](https://godotengine.org/) | MIT |

## Notes

- A base model's licence does not automatically cover every added component, nor does it grant
  rights to every training source.
- Generated output may carry its own restrictions depending on the model and jurisdiction.
- Every asset record in `metadata/asset_records/` stores the model, the model file and a licence
  URL, and `reports/*.md` flags any asset with a missing licence — but that is bookkeeping, not
  legal advice.
