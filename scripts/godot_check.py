#!/usr/bin/env python3
"""Stage: engine-side verification with headless Godot.

Two steps, both required:
  1. `godot --headless --import` - generate the .import sidecars, which is the step that
     actually fails when a PNG is malformed or a name collides.
  2. `godot --headless --script res://tests/asset_check.gd` - load every exported texture and
     every spritesheet's metadata, and confirm the frame rects fit the sheet.

A green Python validator plus a red Godot check means the asset is not engine-ready, and the
pipeline reports exactly that.

    python3 scripts/godot_check.py
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parent / "lib")]

from lib.common import PipelineError, resolve_path, run_cmd  # noqa: E402
from lib.stage import Stage, add_common_args  # noqa: E402

MARKER = "ARTWORKFLOW_GODOT "


class GodotCheckStage(Stage):
    name = "godot-check"

    def build_parser(self) -> argparse.ArgumentParser:
        parser = add_common_args(argparse.ArgumentParser(description=__doc__))
        parser.add_argument("--skip-import", action="store_true", help="reuse existing .import files")
        return parser

    @property
    def project_dir(self) -> Path:
        return resolve_path(self.config.get("godot.project_dir", "godot_project"))

    def run(self) -> dict:
        binary = shutil.which(str(self.config.get("godot.binary", "godot"))) \
            or str(self.config.get("godot.binary", "godot"))
        results: dict[str, object] = {"stage": self.name, "project": str(self.project_dir)}
        if not self.project_dir.exists():
            raise PipelineError(f"Godot project not found: {self.project_dir}")
        assets = list((self.project_dir / "assets").rglob("*.png"))
        results["assets_present"] = len(assets)
        if not assets:
            self.log.warn("no PNGs in the Godot project; run the export stage first",
                          stage=self.name)
        if self.dry_run:
            self.log.info(f"would import {len(assets)} asset(s) and run asset_check.gd",
                          stage=self.name)
            results["dry_run"] = True
            self.summarize(results)
            return results

        import_log = self.log.stage_file("godot-import.log")
        if not self.args.skip_import:
            proc = run_cmd([binary, "--headless", "--path", str(self.project_dir), "--import"],
                           timeout=float(self.config.get("godot.import_timeout_seconds", 300)),
                           log_path=import_log, log=self.log, stage=self.name)
            # An import pass that reports errors still exits 0 in some Godot versions, so scan
            # the transcript as well as the exit code.
            transcript = (proc.stdout or "") + (proc.stderr or "")
            errors = [line for line in transcript.splitlines()
                      if "ERROR" in line or "Failed to load" in line]
            results["import_errors"] = errors[:20]
            self.log.info(f"godot --import exit={proc.returncode}, {len(errors)} error line(s)",
                          stage=self.name)
            if errors:
                for line in errors[:10]:
                    self.log.warn(f"import: {line.strip()[:200]}", stage=self.name)

        check_log = self.log.stage_file("godot-check.log")
        proc = run_cmd([binary, "--headless", "--path", str(self.project_dir),
                        "--script", "res://tests/asset_check.gd"],
                       timeout=float(self.config.get("godot.check_timeout_seconds", 180)),
                       log_path=check_log, log=self.log, stage=self.name)
        payload = self._parse(proc.stdout or "")
        results.update(payload or {})
        if payload is None:
            results["ok"] = False
            results["error"] = f"asset_check.gd produced no summary (exit {proc.returncode})"
            self.log.error(results["error"], stage=self.name)
        elif not payload.get("ok"):
            for problem in list(payload.get("problems", []))[:20]:
                self.log.error(f"godot: {problem}", stage=self.name)
        else:
            self.log.info(f"godot ok: {payload.get('textures_checked')} texture(s), "
                          f"{payload.get('sheets_checked')} sheet(s), "
                          f"{payload.get('frames_checked')} frame rect(s)", stage=self.name)

        self.summarize(results)
        if not results.get("ok"):
            raise PipelineError("Godot verification failed; see logs/godot-check.log")
        return results

    def _parse(self, stdout: str) -> dict | None:
        for line in reversed(stdout.splitlines()):
            if MARKER in line:
                try:
                    return json.loads(line.split(MARKER, 1)[1].strip())
                except json.JSONDecodeError:
                    return None
        return None


if __name__ == "__main__":
    stage = GodotCheckStage()
    try:
        stage.run()
    except PipelineError as exc:
        stage.log.error(str(exc), stage=stage.name)
        raise SystemExit(1)
