# Autonomous Game-Art Pipeline

A free, automation-first workflow for generating game-ready art assets and animations using **OpenCode** as the orchestrator. The goal is to minimize manual GUI work by using local APIs, command-line tools, and scripts wherever possible.

> **Important:** This pipeline can run without manually operating the applications, but fully unattended, production-quality artwork is not guaranteed. Automated validation, retries, consistent styles, and reusable animation rigs are key to making it reliable.

## Goals

- Generate characters, props, buildings, textures, portraits, and backgrounds.
- Process generated images into game-ready assets.
- Create repeatable animation frames or rigged animations.
- Export spritesheets, metadata, and engine-compatible resources.
- Validate outputs automatically and retry failed stages.
- Record prompts, seeds, model information, licenses, errors, and output paths.

## Recommended Stack

| Tool | Role | Automation interface | Best use |
|---|---|---|---|
| [OpenCode](https://opencode.ai/) | Orchestration and code generation | CLI, shell commands, tools/MCP integrations | Coordinate the workflow, launch scripts, inspect failures, and produce reports |
| [ComfyUI](https://www.comfy.org/) | AI image generation | Local HTTP API and WebSockets | Generate art variations and batch assets from reusable workflows |
| [FLUX.1 schnell](https://huggingface.co/black-forest-labs/FLUX.1-schnell) | Image-generation model | Run through a compatible ComfyUI workflow | Concept art, props, portraits, and stylized illustrations |
| [Blender](https://www.blender.org/) | 3D production and animation | Python API and background mode | Isometric buildings, props, rigs, animation, and consistent renders |
| [Python](https://www.python.org/) + [Pillow](https://pillow.readthedocs.io/) / [OpenCV](https://opencv.org/) | Image processing and quality checks | Scripts and CLI | Resize, crop, inspect, compare, and prepare assets |
| [rembg](https://github.com/danielgatis/rembg) | Background removal | Python package and CLI | Produce transparent PNGs from generated images |
| [Godot](https://godotengine.org/) | Game integration and validation | GDScript, editor scripts, and command-line tools | Import assets, build scenes, animate 2D rigs, run checks, and export builds |
| [Pixelorama](https://pixelorama.org/) | Optional pixel-art workflow | CLI/headless export options, depending on version | Pixel-art projects, frames, and spritesheet export |

### Recommended starting stack

Start with **OpenCode + ComfyUI + Python + Blender + Godot**. Add Pixelorama only if the art direction requires pixel-art editing or its project/spritesheet workflow.

Use one image-generation model and one saved ComfyUI workflow at first. Add reference conditioning, pose controls, LoRAs, or additional models only after testing shows that they improve consistency.

## Architecture

```text
OpenCode (orchestrator)
        |
        v
Asset manifest + task queue
        |
        v
ComfyUI API -------------------- Blender Python
Generate 2D artwork              Procedural 3D assets, rigs, animation, renders
        |                                      |
        +------------------+-------------------+
                           v
               Python processing stage
           Transparency, crop, resize, checks
                           |
                           v
                 Animation/export stage
            Spritesheets, frame data, metadata
                           |
                           v
                 Godot integration checks
              Import, scene, animation, build
                           |
                           v
                 QA report and asset manifest
```

Each stage should be callable independently so a failure does not require regenerating every asset.

## Suggested Project Structure

```text
game-art-pipeline/
├── README.md
├── config/
│   ├── pipeline.yaml
│   └── asset_manifest.json
├── workflows/
│   └── comfyui/
│       └── base_asset_workflow.json
├── prompts/
│   ├── style_guide.md
│   └── asset_templates/
├── scripts/
│   ├── run_pipeline.py
│   ├── comfyui_client.py
│   ├── process_images.py
│   ├── remove_background.py
│   ├── validate_assets.py
│   ├── generate_spritesheet.py
│   └── build_report.py
├── blender/
│   ├── generate_building.py
│   ├── render_animation.py
│   └── reusable_rigs/
├── godot_project/
│   ├── project.godot
│   ├── scenes/
│   ├── scripts/
│   └── assets/
├── assets/
│   ├── incoming/
│   ├── processed/
│   ├── animations/
│   ├── spritesheets/
│   └── approved/
├── metadata/
│   ├── asset_records/
│   └── manifests/
├── logs/
├── reports/
└── tests/
```

Keep generated source files and intermediate outputs. Do not overwrite source artwork with processed images; write each pipeline stage to its own output directory.

## Asset Manifest

Every asset should have a machine-readable specification. JSON is a reasonable initial format:

```json
{
  "asset_id": "medieval_watchtower_level_01",
  "asset_type": "building",
  "description": "A dark-fantasy medieval wooden watchtower",
  "prompt": "A stylized dark-fantasy medieval wooden watchtower, isolated game asset, readable silhouette, consistent materials, no text",
  "negative_prompt": "text, watermark, multiple buildings, cropped roof, blurry details",
  "style": "dark-fantasy-isometric-v1",
  "seed": 481516,
  "generation": {
    "workflow": "workflows/comfyui/base_asset_workflow.json",
    "width": 1024,
    "height": 1024,
    "transparent_background": true
  },
  "animation": {
    "enabled": false,
    "type": null,
    "frame_rate": null,
    "frame_count": null
  },
  "export": {
    "format": "png",
    "target_directory": "assets/approved/buildings"
  },
  "provenance": {
    "model": "FLUX.1 schnell",
    "model_version": "record-exact-version-here",
    "license_url": "https://huggingface.co/black-forest-labs/FLUX.1-schnell"
  },
  "status": "pending"
}
```

Treat this as a template, not a complete schema. Validate it before starting jobs. Record the actual model/checkpoint, workflow version, seed, prompt, generation settings, and any external model or LoRA licenses used for each result.

## End-to-End Workflow

### 1. Read and validate the manifest

- Check required fields and unique asset IDs.
- Verify output paths are inside the project directory.
- Check that requested models, workflows, and tools are available.
- Split the manifest into independent tasks and avoid launching more GPU jobs than the machine can handle.

### 2. Generate artwork with ComfyUI

- Start ComfyUI with the intended model and required custom nodes.
- Submit a saved workflow through its local API.
- Track execution, retrieve outputs, and associate each output with its asset ID and generation metadata.
- Use fixed seeds where repeatability matters, but remember that the same seed does not guarantee identical output after model, workflow, or software changes.
- Use reference or pose conditioning when consistent character identity or composition is important.

ComfyUI API reference and example:
- [ComfyUI repository](https://github.com/comfyanonymous/ComfyUI)
- [WebSocket API example](https://github.com/comfyanonymous/ComfyUI/blob/master/script_examples/websockets_api_example.py)

### 3. Process images with Python

Possible steps:

- Convert or standardize output formats.
- Remove backgrounds where appropriate.
- Crop transparent margins and resize to target dimensions.
- Preserve the original source and write processed files to a separate directory.
- Detect empty, nearly empty, corrupted, or incorrectly sized files.
- Check alpha-channel presence when transparency is required.
- Record processing decisions and errors in structured logs.

Background removal can fail on fine hair, smoke, glows, glass, and translucent effects. Add specialized mask-cleanup rules or a manual-review flag for assets that repeatedly fail quality checks.

### 4. Create animations

Choose the method based on the asset category and visual style.

| Asset | Preferred method |
|---|---|
| Isometric village buildings and upgrade tiers | Use Blender scenes with fixed camera, lighting, materials, and render settings; change the building parameters and batch-render each variant |
| 3D characters with idle, walk, or attack motions | Reuse a rig and Blender animation clips, then render consistent frames or export a 3D asset |
| 2D characters with multiple articulated motions | Use layered artwork with a reusable Godot 2D skeleton, or prepare a rigged source asset in a suitable animation tool |
| Pixel-art characters and tiles | Generate or draw consistent frames, then export and validate the frames/spritesheet with Pixelorama or Python |
| Magic, glow, and repeated effects | Create reusable animation frames or use Godot's particle and shader systems |

Do not rely solely on generating each animation frame independently from text prompts. The character can drift in shape, face, equipment, position, and proportions. Reusable rigs or carefully controlled frame workflows are more consistent.

### 5. Export game-ready assets

For each asset, specify the expected export format and dimensions. Depending on the game, outputs may include:

- Transparent PNG files.
- Spritesheets and frame-layout metadata.
- Blender source projects and rendered sequences.
- Godot scenes, animations, materials, and resources.
- Tilemaps or other engine-specific resources.

Never mark an asset complete just because an image was generated. It must also pass the checks required by its manifest.

### 6. Validate and retry

Possible automated checks include:

- File exists and can be opened.
- Dimensions and format match the manifest.
- Alpha channel exists when transparency is expected.
- Image is not blank, corrupted, or nearly uniform.
- Asset is not unexpectedly clipped at the image edges.
- Frame count, frame size, and spritesheet layout are correct.
- Animation files or scenes can be loaded by the intended tool.
- A Godot test project can import the asset and pass its relevant checks.
- Exact or near-duplicate assets are flagged for review.

Use configurable retry limits. Log the error and continue with independent tasks after a failure. For aesthetic issues that are difficult to measure automatically, label the asset as `review_required` rather than falsely claiming it passed.

### 7. Produce a report

Create a report at the end of each run with:

- Total, passed, failed, retried, and skipped assets.
- Output paths and asset IDs.
- Model, workflow, prompt, and seed information.
- Validation results and retry counts.
- Error summaries and any review-required items.
- License/provenance fields missing from the manifest.

## OpenCode Instructions

Use the following as a project instruction for an OpenCode agent:

```text
You are an autonomous game-art pipeline engineer.

Goal: Build a fully automated, repeatable pipeline for creating game-ready 2D assets and animations using free local tools.

Tools:
- OpenCode for orchestration and code generation.
- ComfyUI for AI image generation through its local API.
- Python, Pillow, OpenCV, and rembg for image processing and quality checks.
- Blender for procedural asset creation, rigs, animation, and rendering.
- Godot for asset import, animation integration, testing, and export.
- Pixelorama when pixel-art project or spritesheet export is needed.

Requirements:
1. Inspect installed tools and available model resources before running the pipeline.
2. Create and validate an asset manifest with ID, prompt, dimensions, style, seed, transparency, animation settings, output format, and model/license information.
3. Generate assets through APIs or command-line tools, not simulated mouse or keyboard interactions.
4. Save reusable workflows, source projects, scripts, and configuration files.
5. Validate outputs programmatically, including missing files, transparency, dimensions, blank images, clipping, frame consistency, and duplicates where possible.
6. Retry failed generation or processing a configurable number of times. Record failures and continue with independent tasks.
7. Generate spritesheets, metadata, and Godot-compatible assets as appropriate.
8. Run headless import, animation, and build checks where supported.
9. Log prompts, seeds, source models, licenses, output paths, errors, and validation results.
10. Never report an asset as complete unless its files exist and required checks passed.
11. Do not ask for manual approval during normal execution. If a task needs unavailable dependencies, document the setup and continue with independent work.
12. Work only inside the designated project directory. Do not access secrets or unrelated files. Do not run destructive commands without an explicit allowlist.

Deliverables:
- Documented project structure.
- Executable pipeline entry point.
- Reusable generation and animation scripts.
- Automated validation and retry logic.
- Summary report of generated, passed, failed, and skipped assets.

Start by inspecting the environment and writing a plan. Then implement the smallest end-to-end workflow using one test asset. Run it, verify the output on disk, and expand only after the test passes.
```

### Example non-interactive OpenCode invocation

From the project's root directory, you can use the non-interactive command supported by your installed OpenCode version. For example:

```bash
opencode run --auto "Implement and test the game-art pipeline described in README.md. Start with one test asset and report the verified output paths."
```

Check the current [OpenCode documentation](https://opencode.ai/docs/) for the exact flags supported by your installed version. Configure permissions deliberately: unattended execution should not imply unrestricted access to the machine.

## Local Setup Checklist

Installation differs by operating system, GPU, Python version, and model. Before running the pipeline, confirm that:

- [ ] OpenCode is installed and can run commands in the project directory.
- [ ] ComfyUI starts and its API is reachable locally.
- [ ] A compatible image-generation model and all required workflow components are installed.
- [ ] Blender starts normally and can execute a simple background Python script.
- [ ] Python dependencies are installed in a dedicated virtual environment.
- [ ] rembg's chosen model is available locally if offline processing is required.
- [ ] Godot can open the test project and run the intended command-line checks.
- [ ] Output directories have sufficient disk space.
- [ ] Model and asset licenses have been reviewed for the intended use.

Do not assume that every tool runs fully offline immediately after installation. Some tools or models may download dependencies or weights on first use.

## Safety and Reliability

- Run automation in a dedicated project directory and preferably a dedicated Python environment.
- Limit OpenCode permissions to the commands and directories required for the pipeline.
- Do not put API keys, passwords, or personal secrets in prompts, manifests, or logs.
- Keep generation settings and source files so outputs can be reproduced as closely as possible.
- Pin or record tool, model, workflow, and dependency versions.
- Review the license of every model, checkpoint, LoRA, custom node, font, texture, and other third-party resource used. The license of a base model does not automatically cover every added component or guarantee rights to every training source.
- Retain failed outputs and logs when useful for debugging, but keep temporary data under control with a cleanup policy.
- Use automated checks to detect technical failures; do not treat them as a guarantee of artistic quality.

## Known Limitations

1. Generated art can vary in style, composition, anatomy, and details. Reference conditioning and consistent prompts help but do not eliminate drift.
2. Background removal is imperfect for thin, soft, reflective, and translucent elements.
3. Automatically generating visually coherent animation from independent images is difficult. Rigs and procedural renders are usually more reliable for repeatable motion.
4. GPU memory, disk space, model license terms, and custom-node compatibility can constrain the pipeline.
5. Some aesthetic judgments are hard to automate. Use a `review_required` status for cases the validator cannot confidently assess.

## Suggested First Milestone

Build a minimal end-to-end test before scaling up:

1. Generate one isolated medieval building through ComfyUI.
2. Process it into a transparent PNG if needed.
3. Validate file integrity, size, transparency, and clipping.
4. Generate a second building variant with the same style settings—or render one from a reusable Blender scene.
5. Import both into a small Godot test scene.
6. Run automated checks and write a report with exact output paths.

Once this test is reliable, add batch generation, character animation, spritesheets, retries, and larger asset manifests.
