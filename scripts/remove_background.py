#!/usr/bin/env python3
"""Background removal through ComfyUI + BiRefNet.

Why not `rembg`: neither rembg nor onnxruntime is installed on this machine, and the
ComfyUI_BiRefNet_ll custom node with the General-HR weights is already present and is what
the Warbands pipeline uses in production. BiRefNet's fast-foreground-estimation reconstructs
true foreground colour at the cut edge, which keeps thin details - paddocks, hay rows, fence
posts - that a naive alpha cut clips into a halo.

Known weak spots (flagged rather than hidden): hair, smoke, glow, glass, translucent effects.
Assets that trip the validator after a cutout are marked review_required, not passed.

Standalone use, single file:
    python3 scripts/remove_background.py --src assets/incoming/demo_watchtower_a.png \
                                         --out /tmp/cutout.png
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parent / "lib")]

from lib.common import Config, PipelineError, RunLog, new_run_id  # noqa: E402
from lib.comfy import ComfyClient, ComfyError, check_workflow_requirements, load_workflow  # noqa: E402

CUTOUT_WORKFLOW = "workflows/comfyui/birefnet_cutout.json"


class CutoutError(PipelineError):
    pass


def cutout(client: ComfyClient, config: Config, src: Path, dest: Path, *,
           log: RunLog | None = None, asset: str | None = None, force: bool = False) -> Path:
    """Write a transparent-background copy of `src` to `dest`."""
    if dest.exists() and not force and dest.stat().st_mtime >= src.stat().st_mtime:
        if log:
            log.info(f"cutout is up to date -> {dest.name}", stage="background", asset=asset)
        return dest
    workflow = load_workflow(CUTOUT_WORKFLOW)
    problems = check_workflow_requirements(workflow, config, log=log)
    if problems:
        raise CutoutError("BiRefNet cutout is not available: " + "; ".join(problems))

    bg = config.get("comfyui.background_removal", {}) or {}
    uploaded = client.upload_image(src, subfolder="artworkflow-in")
    values = {
        "image_name": uploaded,
        "model_name": bg.get("model_name", "General-HR"),
        "width": int(bg.get("process_width", 1024)),
        "height": int(bg.get("process_height", 1024)),
        "filename_prefix": f"artworkflow/cutout-{src.stem}",
    }
    started = time.time()
    try:
        info = client.run_workflow(workflow, values, dest,
                                   timeout=float(config.get("comfyui.job_timeout_seconds", 900)))
    except ComfyError as exc:
        raise CutoutError(f"BiRefNet cutout failed for {src.name}: {exc}") from exc
    if log:
        log.info(f"cutout {src.name} -> {dest.name} ({dest.stat().st_size // 1024} KB, "
                 f"{round(time.time() - started, 1)}s)", stage="background", asset=asset)
    return dest


def cutout_to_temp(client: ComfyClient, config: Config, src: Path, *,
                   log: RunLog | None = None, asset: str | None = None) -> Path:
    """Cut out into a scratch file; used when the caller keeps working on the image."""
    tmp = Path(tempfile.mkdtemp(prefix="artworkflow-cutout-")) / f"{src.stem}.png"
    return cutout(client, config, src, tmp, log=log, asset=asset, force=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=None)
    parser.add_argument("--src", type=Path, help="source image")
    parser.add_argument("--out", type=Path, help="destination PNG")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if not args.src or not args.out:
        parser.error("--src and --out are required for the standalone utility")

    config = Config.load(args.config)
    log = RunLog(new_run_id(), Path(config.path_for("logs")), echo=True)
    client = ComfyClient(config, log=log)
    client.ensure_server()
    try:
        cutout(client, config, args.src, args.out, log=log, asset=args.src.stem, force=args.force)
    except PipelineError as exc:
        log.error(str(exc), stage="background")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
