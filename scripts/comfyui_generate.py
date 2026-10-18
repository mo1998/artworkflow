#!/usr/bin/env python3
"""Stage: generate raw artwork through ComfyUI.

Reads the manifest, binds each asset's prompt/seed/size into its workflow template and
writes the raw render to assets/incoming/. Nothing is validated here - a generated file is
not a finished asset. Failures are retried with a shifted seed, and the shifted seed is
recorded so the result stays reproducible.

    python3 scripts/comfyui_generate.py --assets demo_watchtower_a
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parent / "lib")]

from lib.common import (PipelineError, ROOT, STATUS_GENERATED, atomic_write_bytes,  # noqa: E402
                        rel_to_root)
from lib.comfy import ComfyClient, check_workflow_requirements, load_workflow  # noqa: E402
from lib.imageops import detect_format, open_image  # noqa: E402
from lib.stage import Stage, add_common_args  # noqa: E402
import argparse  # noqa: E402

DONE_STATUSES = {"generated", "processed", "passed", "review_required", "exported"}


class ComfyGenerateStage(Stage):
    name = "generate-comfyui"

    def build_parser(self) -> argparse.ArgumentParser:
        parser = add_common_args(argparse.ArgumentParser(description=__doc__))
        parser.add_argument("--steps", type=int, default=None, help="override step count for every asset")
        parser.add_argument("--size", type=int, default=None, help="override square output size")
        parser.add_argument("--seed", type=int, default=None, help="override every seed (breaks the manifest)")
        parser.add_argument("--no-autostart", action="store_true", help="do not start ComfyUI, require it running")
        return parser

    def run(self) -> dict:
        self.preflight()
        self.snapshot_manifest()
        if self.args.no_autostart:
            self.config.data.setdefault("comfyui", {})["autostart"] = False

        jobs = [j for j in self.jobs if j.source == "comfyui"]
        client = ComfyClient(self.config, log=self.log)
        results: dict[str, object] = {"stage": self.name, "assets": {}}
        if not jobs:
            self.log.warn("no comfyui assets selected", stage=self.name)
            self.summarize(results)
            return results

        if not self.dry_run:
            client.ensure_server()
            object_info = client.object_info()
        else:
            object_info = None

        results: dict[str, object] = {"stage": self.name, "assets": {}}
        sink: dict[str, object] = results["assets"]  # type: ignore[assignment]
        retries = int(self.config.get("retry.generation", 0))
        for job in jobs:
            self.try_job(job, "generation", lambda job=job: self.render_one(job, client, object_info,
                                                                           retries, results), sink)
        self.save_records()
        self.summarize(results)
        return results

    def render_one(self, job, client: ComfyClient, object_info, retries: int, results: dict) -> dict:
        rec = self.record(job)
        dest = self.incoming_path(job)
        if rec.data.get("status") in DONE_STATUSES and not self.force:
            existing = self.find_incoming(job)
            if existing:
                self.log.info(f"already generated -> {existing.name}", stage=self.name, asset=job.run_key)
                return {"skipped": "already generated", "file": str(existing)}
        if self.dry_run:
            self.log.info(f"would generate with {job.spec.get('generation', {}).get('workflow')}",
                          stage=self.name, asset=job.run_key)
            return {"dry_run": True}

        workflow_rel = (job.spec.get("generation") or {})["workflow"]
        workflow = load_workflow(workflow_rel)
        gen = job.generation_settings()
        if self.args.steps:
            gen["steps"] = int(self.args.steps)
        if self.args.size:
            gen["width"] = gen["height"] = int(self.args.size)
        if self.args.seed is not None:
            gen["seed"] = int(self.args.seed)

        problems = check_workflow_requirements(workflow, self.config, log=self.log, object_info=object_info)
        if problems:
            for problem in problems:
                self.log.error(f"workflow preflight: {problem}", stage=self.name, asset=job.run_key)
            raise PipelineError(f"{job.run_key}: workflow {workflow.name} is not runnable on this machine")

        last_error: str | None = None
        for attempt in range(retries + 1):
            seed = int(gen.get("seed") or 0) + attempt * 1013
            values = {
                "prompt": job.compose_prompt(),
                "negative_prompt": job.compose_negative(),
                "seed": seed,
                "steps": int(gen["steps"]),
                "width": int(gen["width"]),
                "height": int(gen["height"]),
                "guidance": float(gen.get("guidance", 3.5)),
                "sampler": gen.get("sampler", "euler"),
                "scheduler": gen.get("scheduler", "simple"),
                "filename_prefix": f"artworkflow/{job.run_key}",
            }
            unbindable = workflow.unbindable(values)
            if unbindable:
                self.log.warn(f"workflow has no binding for {unbindable}; using template values",
                              stage=self.name, asset=job.run_key)
            started = time.time()
            try:
                info = client.run_workflow(workflow, values, dest, timeout=float(
                    self.config.get("comfyui.job_timeout_seconds", 900)))
                data = Path(info["dest"]).read_bytes()
                fmt = detect_format(data) or "png"
                final = self.incoming_path(job, "jpg" if fmt == "jpg" else "png")
                if final != Path(info["dest"]):
                    atomic_write_bytes(final, data)
                    Path(info["dest"]).unlink(missing_ok=True)
                rendered = open_image(final)
                width, height, mode = rendered.width, rendered.height, rendered.mode
                try:
                    workflow_rel = str(workflow.path.relative_to(ROOT))
                except ValueError:
                    workflow_rel = str(workflow.path)
                rec.complete_stage("generation", file=rel_to_root(final), bytes=len(data), format=fmt,
                                   width=width, height=height, mode=mode, seed=seed,
                                   prompt=values["prompt"], negative_prompt=values["negative_prompt"],
                                   workflow=workflow_rel, workflow_name=workflow.name,
                                   prompt_id=info["prompt_id"], seconds=round(time.time() - started, 2),
                                   attempt=attempt)
                rec.set_status(STATUS_GENERATED)
                self.log.info(f"generated {final.name} ({len(data) // 1024} KB, seed={seed}, "
                              f"{round(time.time() - started, 1)}s)", stage=self.name, asset=job.run_key)
                return {"file": str(final), "seed": seed, "attempt": attempt, "bytes": len(data)}
            except Exception as exc:  # noqa: BLE001 - report and retry anything the server throws
                last_error = f"{type(exc).__name__}: {exc}"
                rec.bump_retry("generation")
                self.log.warn(f"attempt {attempt + 1}/{retries + 1} failed: {last_error[:300]}",
                              stage=self.name, asset=job.run_key)
                if attempt < retries:
                    time.sleep(2)
        self.record_error(job, "generation", last_error or "unknown failure")
        return {"error": last_error}


if __name__ == "__main__":
    stage = ComfyGenerateStage()
    try:
        stage.run()
    except PipelineError as exc:
        stage.log.error(str(exc), stage=stage.name)
        raise SystemExit(1)
