# Contributing

Thanks for looking. This is a small pipeline with a lot of self-checks, and the point of them is
that you should not have to know any of the history in this repo to change it safely.

## Setup

```bash
git clone https://github.com/mo1998/artworkflow.git
cd artworkflow
python3 -m venv .venv                      # Python 3.9+
.venv/bin/python -m pip install -r requirements.txt
```

That is the entire dependency list. You do **not** need a GPU, ComfyUI, Blender or Godot to work on
the pipeline, its validation, its docs, its MCP server or its tests — only to generate new pixels.

## Before you push

```bash
.venv/bin/python scripts/check.py
```

One command. It runs a static sweep (every Python file compiles and parses, including the Blender
scripts that import `bpy` and therefore can never be imported here, plus every YAML and JSON config)
and then the test suite.

To see what CI will say:

```bash
.venv/bin/python scripts/check.py --verbose
.venv/bin/python scripts/env_check.py --skip-smoke   # exits 1 on a machine with no toolchain: correct
```

## What CI enforces

`.github/workflows/ci.yml` runs on Python 3.9, 3.11 and 3.12, plus two focused jobs:

| job | what it proves |
| --- | --- |
| `checks` (matrix) | the static sweep and the suite pass, the MCP server answers a handshake, and `env_check` fails *cleanly* (exit 1, no traceback) where no toolchain exists |
| `no-machine-state` | no committed absolute home path, no credential-shaped string, no generated output, no oversized file |
| `manifest` | the shipped manifest and workflow bindings validate |

The matrix is not decoration. A test helper once used `sys.stdlib_module_names` (Python 3.10+) and
passed on 3.11 while classifying every stdlib import as third-party on 3.9.

## Rules for tests

1. **A test must pass on a machine with no GPU, no ComfyUI, no Blender and no Godot.** If what it
   checks needs a tool, `self.skipTest(...)` when the tool is absent — see
   `TestToolDetection.test_resolves_the_tools_installed_here`. Never `assertIsNotNone` on a
   detected tool.
2. **Tests that read generated output must skip when it is absent.** `assets/` is not committed, so
   a fresh clone has none. Existing examples: `TestFamilies`, `TestExportedArtifacts`.
3. **Do not let the suite go quiet.** `scripts/check.py` fails the build if fewer than 60 tests
   actually execute, so a change that turns the suite into a no-op cannot pass as green.
4. **Record the bug in the test.** When you fix something, the docstring should say what broke and
   how. Most tests in this repo were born from a real failure — that is what stops the failure
   returning.

## Invariants: if you change X, update Y

These are checked automatically; this table is so you know before CI tells you.

| change | also update |
| --- | --- |
| add, rename or remove a clip in `blender/lib/anim_clips.py` | the manifest's `animation.clip`; if it moves the camera, add it to `CAMERA_MOVING_CLIPS` |
| add a `*_material` name to `PALETTE` in `blender/lib/scene.py` | nothing else — but manifest validation will now accept that name and reject typos |
| add a style to `config/styles.yaml` | reference it from `config/manifest.json`; document it if it is a new direction |
| add a stage script in `scripts/` | `STAGE_PLAN` and `STAGE_ORDER` in `run_pipeline.py`, and an `artworkflow_<stage>` tool in `mcp_server/server.py` |
| add a third-party import | `REQUIRED_MODULES` in `scripts/env_check.py`, `requirements.txt`, and the install line in `README.md` — a test asserts all three agree |
| read a new config key | add it to `config/pipeline.yaml`; a typo'd key silently returns the default |
| add or rename a doc | relative links in `README.md`, and the reference table in `skills/artworkflow/SKILL.md` |
| change a check in `validate_assets.py` | `skills/artworkflow/references/validation.md` |
| add a manifest field | `config/asset_manifest.schema.json` and `skills/artworkflow/references/manifest.md` |
| rename an MCP tool | `mcp_server/README.md` — the docs are asserted against the server's tool list |

## Adding an art direction

See [`skills/artworkflow/references/styles.md`](skills/artworkflow/references/styles.md). The short
version: style blocks in `config/styles.yaml`, `PALETTE` entries if you need new colours, assets in
`config/manifest.json`, then look at the output. Palette matching between painted and procedural
assets is the one thing no check measures.

## Adding a validation check

See the end of [`skills/artworkflow/references/validation.md`](skills/artworkflow/references/validation.md).
Two things matter: write the `detail` string for a human deciding what to do (include the measured
value and the limit), and add a test that describes the failure the check exists to catch.

## Pull requests

- One change per PR, with the *why* in the description. The commit history here explains reasoning,
  not just edits, and that is the useful part.
- Say what you ran. `scripts/check.py` output is enough.
- If you touched how art *looks*, say which asset you looked at. CI cannot judge a sprite.
- Do not commit anything under `assets/` or `logs/` — `.gitignore` covers them, and `NOTICE.md`
  explains the licence situation for models and their output.

## Reporting a bug

Include the stage, the asset id, the report line (`reports/<run id>.md`) and the record
(`metadata/asset_records/<run_key>.json`). The record carries the prompt, seed, resolved workflow,
processing steps, every check with its measured value, and a short traceback — usually enough to
diagnose without reproducing.
