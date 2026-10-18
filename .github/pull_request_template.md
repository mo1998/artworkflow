<!--
Keep this short. The point is to make the reviewer's job possible, not to add ceremony.
-->

## What and why

<!-- One paragraph. What changes, and what problem it solves. -->

## How it was verified

- [ ] `python scripts/check.py` passes
- [ ] If this changes how art looks: I looked at
      `assets/approved/...` and it is right
- [ ] If this adds a check: it has a test naming the failure it catches
- [ ] If this adds a dependency or config key: the docs and CI install step are updated
      (see the invariants table in CONTRIBUTING.md)

## Does this touch any of these?

<!-- Tick, or delete the section. Each one has a script somewhere that agrees with a file here. -->

- [ ] a clip in `blender/lib/anim_clips.py` → manifest `animation.clip`, and `CAMERA_MOVING_CLIPS` if it moves the camera
- [ ] a stage script → `run_pipeline.py` STAGE_PLAN and an `artworkflow_<stage>` MCP tool
- [ ] a validation check → `skills/artworkflow/references/validation.md`
- [ ] the manifest schema → `config/asset_manifest.schema.json` and the manifest reference doc
- [ ] an MCP tool name → `mcp_server/README.md`

## Notes for the reviewer

<!-- Anything you are unsure about, deliberately left out, or that needs a human eye. -->
