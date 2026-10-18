"""Stage scaffolding shared by every entry point in scripts/.

Each stage stays independently callable and reads its inputs from disk (the manifest plus
the per-asset records), so a failure in one stage never forces a regeneration of another.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any, Iterable, Sequence

from .common import (EXPORTABLE, ROOT, AssetRecord, Config, PipelineError, RunLog,
                     STATUS_FAILED, atomic_write_json, ensure_inside_project, new_run_id,
                     resolve_path)
from .manifest import Job, Manifest, check_paths, load_manifest, validate_manifest


def add_common_args(parser: argparse.ArgumentParser, *, manifest: bool = True) -> argparse.ArgumentParser:
    parser.add_argument("--config", default=None, help="path to pipeline.yaml (default config/pipeline.yaml)")
    if manifest:
        parser.add_argument("--manifest", default=None, help="path to the asset manifest JSON")
    parser.add_argument("--assets", nargs="*", default=None,
                        help="only these asset ids / run keys (variants use id__suffix)")
    parser.add_argument("--run-id", default=None, help="reuse an existing run id (keeps logs together)")
    parser.add_argument("--force", action="store_true", help="redo work even if a record says it is done")
    parser.add_argument("--dry-run", action="store_true", help="report what would happen, change nothing")
    parser.add_argument("--quiet", action="store_true", help="do not echo log lines to stdout")
    return parser


class Stage:
    """Loads config + manifest + records, and gives the stage its output paths."""

    name = "stage"

    def __init__(self, name: str | None = None, *, argv: Sequence[str] | None = None,
                 with_manifest: bool = True):
        self.name = name or self.name
        self.args = self.parse_args(argv)
        self.config = Config.load(self.args.config)
        check_paths(self.config)
        self.log = RunLog(self.args.run_id or new_run_id(), self.config.path_for("logs"),
                          echo=not getattr(self.args, "quiet", False))
        self.only = self.args.assets or None
        self.force = bool(getattr(self.args, "force", False))
        self.dry_run = bool(getattr(self.args, "dry_run", False))
        self.manifest: Manifest | None = None
        self.jobs: list[Job] = []
        self.records: dict[str, AssetRecord] = {}
        if with_manifest:
            self.manifest = load_manifest(self.args.manifest, self.config)
            self.jobs = self.manifest.jobs(self.only)
            self.records = {job.run_key: AssetRecord.load(job.run_key) for job in self.jobs}
        self.log.log("stage_start", stage=self.name, msg=f"run {self.log.run_id}",
                     assets=[j.run_key for j in self.jobs] or None,
                     manifest=str(self.manifest.path) if self.manifest else None)

    # ---- overridable --------------------------------------------------------
    def build_parser(self) -> argparse.ArgumentParser:
        return add_common_args(argparse.ArgumentParser(description=self.name))

    def parse_args(self, argv: Sequence[str] | None) -> argparse.Namespace:
        parser = self.build_parser()
        return parser.parse_args(list(argv) if argv is not None else None)

    # ---- helpers -----------------------------------------------------------
    def record(self, job: Job) -> AssetRecord:
        return self.records.setdefault(job.run_key, AssetRecord.load(job.run_key))

    def save_records(self, *, status: str | None = None) -> None:
        if self.dry_run:
            return
        for rec in self.records.values():
            if status:
                rec.set_status(status)
            rec.save()

    def preflight(self) -> None:
        if not self.manifest:
            return
        problems = validate_manifest(self.manifest, self.config)
        if problems:
            for problem in problems:
                self.log.error(f"manifest: {problem}", stage=self.name)
            raise PipelineError(f"manifest validation failed with {len(problems)} problem(s)")
        self.log.info(f"manifest ok: {len(self.jobs)} job(s) from {self.manifest.path.name}", stage=self.name)

    def snapshot_manifest(self) -> Path:
        """Record exactly which manifest produced this run."""
        assert self.manifest is not None
        dest = self.config.path_for("manifests") / f"{self.log.run_id}.json"
        if not self.dry_run:
            atomic_write_json(dest, {
                "run_id": self.log.run_id,
                "manifest_path": str(self.manifest.path),
                "schema_version": self.manifest.schema_version,
                "jobs": [j.run_key for j in self.jobs],
                "source": self.manifest.data,
            })
        return dest

    # ---- paths -------------------------------------------------------------
    def incoming_path(self, job: Job, suffix: str = "png") -> Path:
        return self.config.path_for("incoming") / f"{job.run_key}.{suffix}"

    def find_incoming(self, job: Job) -> Path | None:
        for suffix in ("png", "jpg", "jpeg", "webp"):
            candidate = self.incoming_path(job, suffix)
            if candidate.exists():
                return candidate
        return None

    def processed_path(self, job: Job) -> Path:
        return self.config.path_for("processed") / f"{job.run_key}.png"

    def animation_dir(self, job: Job) -> Path:
        return self.config.path_for("animations") / job.run_key

    def spritesheet_dir(self) -> Path:
        return self.config.path_for("spritesheets")

    def export_dirs(self, job: Job) -> tuple[Path, Path | None]:
        """Return (project export dir, godot mirror dir or None)."""
        settings = job.export_settings()
        target = ensure_inside_project(settings["target_directory"],
                                       what=f"{job.run_key} export.target_directory")
        godot_res = settings.get("godot")
        mirror = None
        if godot_res:
            rel = str(godot_res).replace("res://", "").strip("/")
            mirror = resolve_path(self.config.get("godot.project_dir", "godot_project")) / "assets" / rel
        return target, mirror

    def ensure_dirs(self, *paths: Path) -> None:
        if self.dry_run:
            return
        for path in paths:
            path.mkdir(parents=True, exist_ok=True)

    def copy_export(self, sources: Iterable[Path], dest_dir: Path, mirror: Path | None) -> list[str]:
        written: list[str] = []
        if self.dry_run:
            return [str(p) for p in sources]
        self.ensure_dirs(dest_dir)
        if mirror:
            self.ensure_dirs(mirror)
        for src in sources:
            if not src.exists():
                continue
            target = dest_dir / src.name
            shutil.copy2(src, target)
            written.append(str(target.relative_to(ROOT)))
            if mirror:
                shutil.copy2(src, mirror / src.name)
        return written

    def write_sidecar(self, record: AssetRecord, dest_dir: Path, mirror: Path | None,
                      payload: dict[str, Any]) -> None:
        """`<run_key>.export.json`, deliberately not `<run_key>.json`: an animated asset's
        spritesheet metadata already claims that name, and a sidecar that silently overwrites
        the frame rects would break the engine-side check it exists to support."""
        if self.dry_run:
            return
        name = f"{record.run_key}.export.json"
        atomic_write_json(dest_dir / name, payload)
        if mirror:
            atomic_write_json(mirror / name, payload)

    def summarize(self, results: dict[str, Any]) -> None:
        if not self.dry_run:
            atomic_write_json(self.log.dir / f"{self.name}-summary.json", results)

    # ---- status bookkeeping ------------------------------------------------
    def try_job(self, job: Job, stage: str, fn: Any, sink: dict[str, Any]) -> Any:
        """Run one job and survive anything it throws.

        A stage that dies mid-list leaves the remaining assets with no status and no error,
        which reads as "not attempted" when the truth is "the stage crashed". Catching here
        keeps the failure attached to the asset that caused it and lets the rest proceed.
        """
        import traceback

        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - deliberately broad: never lose a whole stage
            frames = traceback.format_exc(limit=8).strip().splitlines()
            self.record_error(job, stage, f"{type(exc).__name__}: {exc}",
                              traceback=" | ".join(frames[-4:]))
            sink[job.run_key] = {"error": f"{type(exc).__name__}: {exc}"}
            return None

    def record_error(self, job: Job, stage: str, error: str, *, traceback: str | None = None) -> None:
        rec = self.record(job)
        rec.fail_stage(stage, error)
        if traceback and not self.dry_run:
            rec.stage(stage)["traceback"] = traceback
        rec.set_status(STATUS_FAILED)
        self.log.error(f"{stage} failed: {error[:400]}", stage=self.name, asset=job.run_key)
        if traceback:
            self.log.error(f"{stage} traceback: {traceback[-400:]}", stage=self.name, asset=job.run_key)
