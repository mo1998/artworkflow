#!/usr/bin/env python3
"""Stage: turn raw renders into game-ready PNGs.

Pipeline per asset: optional background removal (ComfyUI + BiRefNet) -> trim to the subject
-> resize to the target size -> place on a transparent canvas at a fixed anchor.
Source renders in assets/incoming/ are never modified; everything is written to
assets/processed/ so any stage can be rerun in isolation.

The fixed anchor is the point: `bottom-center` on a square canvas gives every building in a
set the same ground line, which is what makes sprites stack on a tile grid without
per-asset nudging.

    python3 scripts/process_images.py --assets demo_hut demo_watchtower_a
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parent / "lib")]

from PIL import Image

from lib.common import PipelineError, STATUS_PROCESSED, rel_to_root  # noqa: E402
from lib.comfy import ComfyClient  # noqa: E402
from lib.imageops import (ImageError, content_bbox, measure, open_image, pixel_hash,  # noqa: E402
                          place_on_canvas, trim, fit_resize, to_rgba)
from lib.stage import Stage, add_common_args  # noqa: E402

DONE_STATUSES = {"processed", "passed", "review_required", "exported"}


class ProcessStage(Stage):
    name = "process"

    def __init__(self, *args, **kwargs):
        self._family_factors: dict[str, float] = {}
        super().__init__(*args, **kwargs)

    def build_parser(self) -> argparse.ArgumentParser:
        parser = add_common_args(argparse.ArgumentParser(description=__doc__))
        parser.add_argument("--no-background-removal", action="store_true",
                            help="skip the BiRefNet stage even for assets that request it")
        return parser

    def run(self) -> dict:
        self.preflight()
        needs_cutout = any(
            j.processing_settings().get("remove_background") for j in self.jobs
        ) and not self.args.no_background_removal
        client: ComfyClient | None = None
        if needs_cutout and not self.dry_run:
            client = ComfyClient(self.config, log=self.log)
            client.ensure_server()

        results: dict[str, object] = {"stage": self.name, "assets": {}}
        sink: dict[str, object] = results["assets"]  # type: ignore[assignment]
        for job in self.jobs:
            self.try_job(job, "processing", lambda job=job: self.process_one(job, client), sink)
        self.save_records()
        self.summarize(results)
        return results

    # ---- one asset ---------------------------------------------------------
    def process_one(self, job, client: ComfyClient | None) -> dict:
        if job.animation_settings():
            return self.process_frames(job, client)
        return self.process_still(job, client)

    def process_still(self, job, client: ComfyClient | None) -> dict:
        rec = self.record(job)
        src = self.find_incoming(job)
        if src is None:
            raise PipelineError(f"{job.run_key}: no incoming render found (run the generate stage first)")
        dest = self.processed_path(job)
        if dest.exists() and not self.force and dest.stat().st_mtime >= src.stat().st_mtime \
                and rec.data.get("status") in DONE_STATUSES:
            self.log.info(f"already processed -> {dest.name}", stage=self.name, asset=job.run_key)
            return {"skipped": "already processed", "file": str(dest)}
        if self.dry_run:
            self.log.info(f"would process {src.name} -> {dest.name}", stage=self.name, asset=job.run_key)
            return {"dry_run": True}

        steps = job.processing_settings()
        applied: list[str] = []
        scratch: Path | None = None
        try:
            image, source_path, scratch = self._prepare_source(job, src, client, steps, applied)
            before = measure(image)
            before_pixel_hash = pixel_hash(image)

            if steps.get("trim"):
                image, box = trim(image)
                applied.append("trim")
            else:
                box = None

            target = steps.get("resize")
            anchor = str(steps.get("anchor", "center"))
            padding = int(steps.get("padding", 0) or 0)
            scale_mode = str(steps.get("scale_mode", "fit")).lower()
            if target:
                canvas = int(target)
                # Resize to the canvas minus the padding, then inset. Resizing straight to the
                # canvas size and padding afterwards would push the subject against the edge,
                # which the not_clipped check (correctly) rejects.
                padding = padding if canvas - 2 * padding >= 8 else 0
                effective = canvas - 2 * padding
                resize_from = image.size
                if scale_mode == "family":
                    factor = self.family_factor(job, effective)
                    if factor > 0:
                        image = image.resize((max(1, round(image.width * factor)),
                                              max(1, round(image.height * factor))), Image.LANCZOS)
                        applied.append(f"resize(family x{factor:.4f} ->{image.width}x{image.height})")
                    else:
                        image = fit_resize(image, effective, axis="max")
                        applied.append(f"resize(fit-fallback ->{image.width}x{image.height})")
                else:
                    image = fit_resize(image, effective, axis="max")
                    applied.append(f"resize(fit {resize_from[0]}x{resize_from[1]}->{image.width}x{image.height})")
                image = place_on_canvas(image, canvas, anchor=anchor, padding=padding)
                applied.append(f"canvas({canvas},anchor={anchor},pad={padding},mode={scale_mode})")
            elif steps.get("trim"):
                # No fixed canvas requested: keep the trimmed size, no padding tricks.
                applied.append("no-canvas")

            image = to_rgba(image)
            self.ensure_dirs(dest.parent)
            image.save(dest, "PNG", optimize=True)
            after = measure(open_image(dest))
        finally:
            if scratch is not None:
                scratch.unlink(missing_ok=True)

        rec.complete_stage("processing", file=rel_to_root(dest), bytes=dest.stat().st_size,
                           source=rel_to_root(source_path),
                           steps=applied, trim_box=box, anchor=anchor, padding=padding,
                           scale_mode=scale_mode,
                           canvas=(int(target) if target else None),
                           source_pixel_hash=before_pixel_hash,
                           pixel_hash=pixel_hash(open_image(dest)),
                           before=before.as_dict(), after=after.as_dict())
        rec.set_status(STATUS_PROCESSED)
        self.log.info(f"processed -> {dest.name} {after.width}x{after.height} "
                      f"({dest.stat().st_size // 1024} KB) via {', '.join(applied) or 'copy'}",
                      stage=self.name, asset=job.run_key)
        return {"file": str(dest), "steps": applied, "measurements": after.as_dict()}

    def process_frames(self, job, client: ComfyClient | None) -> dict:
        """Frames are processed with one uniform recipe: per-frame trimming would break the
        loop's registration, so trimming is refused here even if the manifest asks."""
        rec = self.record(job)
        src_dir = self.animation_dir(job)
        frames = sorted(src_dir.glob("frame_*.png"))
        if not frames:
            raise PipelineError(f"{job.run_key}: no frames in {rel_to_root(src_dir)} (run the generate stage first)")
        dest_dir = self.config.path_for("processed") / job.run_key
        if dest_dir.exists() and not self.force and rec.data.get("status") in DONE_STATUSES:
            self.log.info("already processed", stage=self.name, asset=job.run_key)
            return {"skipped": "already processed", "dir": str(dest_dir)}
        if self.dry_run:
            self.log.info(f"would process {len(frames)} frames", stage=self.name, asset=job.run_key)
            return {"dry_run": True, "frames": len(frames)}

        steps = job.processing_settings()
        applied: list[str] = []
        target = steps.get("resize")
        anchor = str(steps.get("anchor", "center"))
        padding = int(steps.get("padding", 0) or 0)
        if steps.get("trim"):
            self.log.warn("trim disabled for animation frames: it would break frame registration",
                          stage=self.name, asset=job.run_key)
        self.ensure_dirs(dest_dir)

        sizes: set[tuple[int, int]] = set()
        written: list[str] = []
        for frame in frames:
            image = open_image(frame)
            if steps.get("remove_background") and client and not self.args.no_background_removal:
                raise PipelineError("background removal on animation frames is not supported yet; "
                                    "render with a transparent film instead (Blender does)")
            if target:
                canvas = int(target)
                pad = padding if canvas - 2 * padding >= 8 else 0
                image = fit_resize(image, canvas - 2 * pad, axis="max")
                image = place_on_canvas(image, canvas, anchor=anchor, padding=pad)
            image = to_rgba(image)
            dest = dest_dir / frame.name
            image.save(dest, "PNG", optimize=True)
            sizes.add(image.size)
            written.append(str(dest))
        if target:
            applied.append(f"canvas({int(target)},anchor={anchor})")
        if len(sizes) != 1:
            raise PipelineError(f"{job.run_key}: frames are not uniform after processing: {sorted(sizes)}")

        rec.complete_stage("processing", dir=rel_to_root(dest_dir), frames=len(written), steps=applied,
                           frame_size=list(sizes.pop()),
                           measurements=measure(open_image(Path(written[0]))).as_dict())
        rec.set_status(STATUS_PROCESSED)
        self.log.info(f"processed {len(written)} frames -> {dest_dir}", stage=self.name, asset=job.run_key)
        return {"dir": str(dest_dir), "frames": len(written), "steps": applied}

    # ---- helpers -----------------------------------------------------------
    def family_factor(self, job, effective: int) -> float:
        """One scale factor for a whole upgrade-tier family.

        Every sibling was rendered with the same locked camera framing, so their pixel sizes are
        directly comparable: scaling all of them by `effective / largest sibling` keeps the
        1 -> 2 -> 3 size progression a player expects. Normalising each tier to fill its own
        canvas would instead make every tier the same on-screen size.
        """
        asset_id = job.asset_id
        if asset_id in self._family_factors:
            return self._family_factors[asset_id]
        assert self.manifest is not None
        keys = self.manifest.family_run_keys(asset_id)
        largest = 0
        for key in keys:
            for suffix in ("png", "jpg", "jpeg", "webp"):
                path = self.config.path_for("incoming") / f"{key}.{suffix}"
                if not path.exists():
                    continue
                try:
                    box = content_bbox(open_image(path))
                except ImageError:
                    continue
                if box:
                    largest = max(largest, box[2] - box[0], box[3] - box[1])
                break
        if largest <= 0:
            self.log.warn("family scale requested but no sibling renders were measurable; "
                          "falling back to fit", stage=self.name, asset=job.run_key)
            return 0.0
        factor = effective / float(largest)
        self._family_factors[asset_id] = factor
        self.log.info(f"family scale for {asset_id}: x{factor:.4f} "
                      f"(largest sibling subject {largest}px -> {effective}px)",
                      stage=self.name, asset=job.run_key)
        return factor

    def _prepare_source(self, job, src: Path, client: ComfyClient | None, steps: dict,
                        applied: list[str]) -> tuple:
        """Return (in-memory image, source path, scratch path to delete or None)."""
        if steps.get("remove_background") and client and not self.args.no_background_removal:
            from remove_background import cutout_to_temp

            tmp = cutout_to_temp(client, self.config, src, log=self.log, asset=job.run_key)
            applied.append("remove_background")
            return open_image(tmp), src, tmp
        if steps.get("remove_background") and self.args.no_background_removal:
            applied.append("remove_background(skipped)")
        return open_image(src), src, None


if __name__ == "__main__":
    stage = ProcessStage()
    try:
        stage.run()
    except PipelineError as exc:
        stage.log.error(str(exc), stage=stage.name)
        raise SystemExit(1)
