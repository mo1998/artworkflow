#!/usr/bin/env python3
"""Stage: export validated assets to their target directories and the Godot project.

Only assets that passed - or that passed every technical check and are flagged
review_required - are exported. A `failed` asset is left in assets/processed/ with its record
explaining why; nothing is copied to look finished when it is not.

Each exported asset gets a JSON sidecar carrying its status and provenance, so an engine-side
consumer can tell a reviewed asset from a merely technically-clean one.

    python3 scripts/export_assets.py
    python3 scripts/export_assets.py --strict     # exclude review_required assets
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parent / "lib")]

from lib.common import (EXPORTABLE, PipelineError, STATUS_EXPORTED, STATUS_PASSED,  # noqa: E402
                        STATUS_REVIEW, now_iso)
from lib.stage import Stage, add_common_args  # noqa: E402


class ExportStage(Stage):
    name = "export"

    def build_parser(self) -> argparse.ArgumentParser:
        parser = add_common_args(argparse.ArgumentParser(description=__doc__))
        parser.add_argument("--strict", action="store_true",
                            help="export only assets whose validation passed outright")
        return parser

    def run(self) -> dict:
        self.preflight()
        allowed = (STATUS_PASSED, STATUS_EXPORTED) if self.args.strict else EXPORTABLE
        results: dict[str, object] = {"stage": self.name, "assets": {}, "skipped": {}}
        sink: dict[str, object] = results["assets"]  # type: ignore[assignment]
        for job in self.jobs:
            rec = self.record(job)
            status = rec.data.get("status")
            if status not in allowed:
                self.log.warn(f"not exported (status {status!r})", stage=self.name, asset=job.run_key)
                results["skipped"][job.run_key] = status
                continue
            self.try_job(job, "export", lambda job=job, status=status: self.export_one(job, status), sink)
        self.save_records()
        self.summarize(results)
        return results

    def export_one(self, job, status: str) -> dict:
        target_dir, mirror = self.export_dirs(job)
        anim = job.animation_settings()
        written: list[str] = []

        if anim:
            name = str((job.export_settings().get("spritesheet") or {}).get("name") or job.run_key)
            sheet_dir = self.spritesheet_dir()
            sources = [sheet_dir / f"{name}.png", sheet_dir / f"{name}.json"]
            missing = [s for s in sources if not s.exists()]
            if missing:
                raise PipelineError(f"{job.run_key}: missing spritesheet output {[str(m) for m in missing]}")
            written += self.copy_export(sources, target_dir, mirror)
            frames = sorted((self.config.path_for("processed") / job.run_key).glob("frame_*.png"))
            if frames:
                frame_target = target_dir / f"{name}_frames"
                frame_mirror = (mirror / f"{name}_frames") if mirror else None
                written += self.copy_export(frames, frame_target, frame_mirror)
        else:
            src = self.processed_path(job)
            if not src.exists():
                raise PipelineError(f"{job.run_key}: processed file missing {src}")
            written += self.copy_export([src], target_dir, mirror)

        payload = {
            "asset_id": job.asset_id,
            "run_key": job.run_key,
            "exported_at": now_iso(),
            "status": status,
            "review_required": status == STATUS_REVIEW,
            "validation": self.record(job).stage("validation"),
            "provenance": job.provenance(),
            "files": written,
        }
        if not self.dry_run:
            self.write_sidecar(self.record(job), target_dir, mirror, payload)
            rec = self.record(job)
            rec.complete_stage("export", files=written, target=str(target_dir),
                               mirror=str(mirror) if mirror else None, validation_status=status)
            rec.set_status(STATUS_EXPORTED, exported_status=status)
            self.log.info(f"exported {len(written)} file(s) -> {target_dir}"
                          + (f" (+ godot mirror)" if mirror else ""),
                          stage=self.name, asset=job.run_key)
        else:
            self.log.info(f"would export to {target_dir}", stage=self.name, asset=job.run_key)
        return {"files": written, "target": str(target_dir), "status": status}


if __name__ == "__main__":
    stage = ExportStage()
    try:
        stage.run()
    except PipelineError as exc:
        stage.log.error(str(exc), stage=stage.name)
        raise SystemExit(1)
