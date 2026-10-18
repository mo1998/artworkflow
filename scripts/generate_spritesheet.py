#!/usr/bin/env python3
"""Stage: pack frame sequences into spritesheets + frame metadata, then export.

Emitted per animated asset:
  <name>.png        the packed sheet
  <name>.json       sheet metadata: frame size, columns/rows, per-frame rects, fps, loop
  <run_key>/        the processed frames, still individually addressable

Godot 4's SpriteFrames can be built directly from the JSON, so the engine never has to
re-derive the grid.

    python3 scripts/generate_spritesheet.py
    python3 scripts/generate_spritesheet.py --assets demo_hut_flag
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parent / "lib")]

from lib.common import PipelineError, STATUS_EXPORTED, atomic_write_json, now_iso  # noqa: E402
from lib.imageops import motion_metrics, open_image, pack_spritesheet, to_rgba  # noqa: E402
from lib.stage import Stage, add_common_args  # noqa: E402


class SpritesheetStage(Stage):
    name = "spritesheet"

    def build_parser(self) -> argparse.ArgumentParser:
        parser = add_common_args(argparse.ArgumentParser(description=__doc__))
        parser.add_argument("--columns", type=int, default=None, help="override the manifest layout")
        return parser

    def run(self) -> dict:
        self.preflight()
        results: dict[str, object] = {"stage": self.name, "sheets": {}}
        sink: dict[str, object] = results["sheets"]  # type: ignore[assignment]
        for job in self.jobs:
            anim = job.animation_settings()
            if not anim:
                continue
            self.try_job(job, "spritesheet", lambda job=job, anim=anim: self.build_sheet(job, anim), sink)
        self.save_records()
        self.summarize(results)
        return results

    def build_sheet(self, job, anim: dict) -> dict:
        frames_dir = self.config.path_for("processed") / job.run_key
        frames = sorted(frames_dir.glob("frame_*.png"))
        if not frames:
            raise PipelineError(f"{job.run_key}: no processed frames in {frames_dir}")
        if len(frames) != int(anim["frame_count"]):
            raise PipelineError(f"{job.run_key}: {len(frames)} processed frames but the manifest "
                                f"says {anim['frame_count']}")

        export = job.export_settings()
        sheet_cfg = export.get("spritesheet") or {}
        columns = int(self.args.columns or sheet_cfg.get("columns") or 0)
        if columns <= 0:
            # Default to a roughly square sheet, which keeps texture memory reasonable.
            columns = max(1, int(len(frames) ** 0.5 + 0.999))
        padding = int(sheet_cfg.get("padding", 0) or 0)
        name = str(sheet_cfg.get("name") or job.run_key)

        images = [to_rgba(open_image(f)) for f in frames]
        sheet, rects = pack_spritesheet(images, columns=columns, padding=padding)
        sheet_dir = self.spritesheet_dir()
        if self.dry_run:
            self.log.info(f"would pack {len(frames)} frames into {columns}-column sheet",
                          stage=self.name, asset=job.run_key)
            return {"dry_run": True}

        self.ensure_dirs(sheet_dir)
        sheet_path = sheet_dir / f"{name}.png"
        sheet.save(sheet_path, "PNG", optimize=True)

        frame_width, frame_height = images[0].size
        rows = (len(images) + columns - 1) // columns
        motion = [motion_metrics(images[i], images[i + 1]) for i in range(len(images) - 1)]
        metadata = {
            "name": name,
            "asset_id": job.asset_id,
            "run_key": job.run_key,
            "generated_at": now_iso(),
            "sheet": sheet_path.name,
            "sheet_size": [sheet.width, sheet.height],
            "frame_size": [frame_width, frame_height],
            "frame_count": len(images),
            "columns": columns,
            "rows": rows,
            "padding": padding,
            "frame_rate": int(anim["frame_rate"]),
            "loop": bool(anim.get("loop", True)),
            "clip": anim.get("clip"),
            "frames": rects,
            "frame_files": [str(f) for f in frames],
            "motion_between_frames": motion,
            "godot": {
                "note": "Load in Godot with a SpriteFrames built from `frames` rects, or split the "
                        "sheet with AtlasTexture using the same rects.",
                "res_path_expected": export.get("godot"),
            },
            "provenance": job.provenance(),
        }
        atomic_write_json(sheet_dir / f"{name}.json", metadata)

        rec = self.record(job)
        rec.complete_stage("spritesheet", sheet=str(sheet_path), metadata=str(sheet_dir / f"{name}.json"),
                           columns=columns, rows=rows, frame_size=[frame_width, frame_height],
                           frames=len(images), sheet_bytes=sheet_path.stat().st_size)
        self.log.info(f"packed {len(images)} frames -> {sheet_path.name} ({sheet.width}x{sheet.height}, "
                      f"{columns}x{rows})", stage=self.name, asset=job.run_key)
        return {"sheet": str(sheet_path), "metadata": str(sheet_dir / f"{name}.json"),
                "columns": columns, "rows": rows, "sheet_size": [sheet.width, sheet.height]}


if __name__ == "__main__":
    stage = SpritesheetStage()
    try:
        stage.run()
    except PipelineError as exc:
        stage.log.error(str(exc), stage=stage.name)
        raise SystemExit(1)
