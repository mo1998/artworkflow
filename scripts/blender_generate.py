#!/usr/bin/env python3
"""Stage: generate raw artwork with Blender procedural generators.

Two things this stage does that a naive wrapper would not:

  * Family framing lock - when an asset defines variants (upgrade tiers, pose sets), the
    first render's camera framing is captured and forced onto every later variant, so the
    tiers line up in game instead of drifting because the subject grew.
  * Honest retries - a rerun uses the same parameters, so a failure is either deterministic
    (bad params, reported once) or environmental (Blender crash, retried).

    python3 scripts/blender_generate.py            # every blender asset
    python3 scripts/blender_generate.py --assets demo_hut
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parent / "lib")]

from lib.blender import BlenderError, run_blender_script  # noqa: E402
from lib.common import PipelineError, ROOT, STATUS_GENERATED, rel_to_root  # noqa: E402
from lib.stage import Stage, add_common_args  # noqa: E402

DONE_STATUSES = {"generated", "processed", "passed", "review_required", "exported"}

# Style-block generation keys that are lighting/framing rather than resolution. A whole art
# direction shares these, so they belong in the style, not repeated on every asset.
RENDER_PASSTHROUGH = ("view", "key_energy", "fill_energy", "azimuth", "ortho_scale", "frame_target_z")


class BlenderGenerateStage(Stage):
    name = "generate-blender"

    def build_parser(self) -> argparse.ArgumentParser:
        parser = add_common_args(argparse.ArgumentParser(description=__doc__))
        parser.add_argument("--samples", type=int, default=None, help="override render samples")
        parser.add_argument("--size", type=int, default=None, help="override square output size")
        parser.add_argument("--lock-framing", dest="lock_framing", action="store_true", default=True,
                            help="force the first variant's camera framing on its siblings (default)")
        parser.add_argument("--no-lock-framing", dest="lock_framing", action="store_false",
                            help="let every variant auto-frame itself")
        return parser

    def run(self) -> dict:
        self.preflight()
        self.snapshot_manifest()

        jobs = [j for j in self.jobs if j.source == "blender"]
        results: dict[str, object] = {"stage": self.name, "assets": {}}
        if not jobs:
            self.log.warn("no blender assets selected", stage=self.name)
            self.summarize(results)
            return results

        retries = int(self.config.get("retry.generation", 0))
        sink: dict[str, object] = results["assets"]  # type: ignore[assignment]
        # Frame each asset family before rendering any of it: build every sibling's scene, take
        # the union of their world bounds, and hand that one camera to all of them. Framing the
        # first render and reusing it cropped the tallest upgrade tier - its roof and banner fell
        # outside the frame the smaller base tier had chosen.
        framing = self.plan_framing(jobs)
        for job in jobs:
            self.try_job(job, "generation", lambda job=job: self.render_one(job, framing, retries), sink)
        self.save_records()
        self.summarize(results)
        return results

    # ---- one asset ---------------------------------------------------------
    def plan_framing(self, jobs: list) -> dict[str, dict[str, Any]]:
        """One locked camera per asset family, fitted to the union of its siblings' bounds.

        Measuring costs one scene build per job and no rendering at all, and it is exact: the
        camera is fitted to the geometry that actually exists rather than to a size estimate.
        """
        by_asset: dict[str, list] = {}
        for job in jobs:
            by_asset.setdefault(job.asset_id, []).append(job)
        framing: dict[str, dict[str, Any]] = {}

        for asset_id, family in by_asset.items():
            boxes = []
            for job in family:
                box = self.measure_one(job)
                if box:
                    boxes.append(box)
            if not boxes:
                continue
            lo = [min(b[0][i] for b in boxes) for i in range(3)]
            hi = [max(b[1][i] for b in boxes) for i in range(3)]
            fitted = self.fit_bounds([[*lo], [*hi]], family[0])
            if fitted:
                ortho, target_z = fitted
                framing[asset_id] = {"ortho_scale": ortho, "frame_target_z": target_z,
                                     "frame_bounds": {"lo": lo, "hi": hi}}
                self.log.info(f"{asset_id}: framing {len(family)} sibling(s), union height "
                              f"{hi[2] - lo[2]:.2f} -> ortho {ortho:.3f}, target z {target_z:.3f}",
                              stage=self.name, asset=asset_id)
        return framing

    def measure_one(self, job) -> list[list[float]] | None:
        if self.dry_run:
            return None
        anim = job.animation_settings()
        generator = job.spec["blender"]["generator"]
        script = ROOT / "blender" / ("render_animation.py" if anim else generator)
        params = self._base_params(job)
        args = {**params, "measure_only": True}
        if anim:
            args["scene"] = str(generator).removesuffix(".py")
        try:
            summary = run_blender_script(self.config, script, args, log=self.log, stage=self.name,
                                        log_path=self.log.stage_file(f"{job.run_key}-measure.log"),
                                        timeout=300)
        except Exception as exc:  # noqa: BLE001 - measurement is best-effort
            self.log.warn(f"could not measure {job.run_key}: {exc}; falling back to per-asset framing",
                          stage=self.name, asset=job.run_key)
            return None
        bounds = summary.get("bounds")
        if not bounds:
            return None
        return [list(bounds["lo"]), list(bounds["hi"])]

    def fit_bounds(self, bounds: list[list[float]], job) -> tuple[float, float] | None:
        """Ask Blender for the fitted camera, so the projection maths lives in one place."""
        holder = ROOT / "blender" / "lib" / "fit_framing.py"
        args = {"bounds": {"lo": bounds[0], "hi": bounds[1]},
                "view": str(self._base_params(job).get("view", "iso")),
                "azimuth": self._base_params(job).get("azimuth"),
                "res_x": self._base_params(job).get("res_x"),
                "res_y": self._base_params(job).get("res_y")}
        try:
            summary = run_blender_script(self.config, holder, args, log=self.log, stage=self.name,
                                        log_path=self.log.stage_file("framing"), timeout=180)
        except Exception as exc:  # noqa: BLE001
            self.log.warn(f"framing fit failed: {exc}", stage=self.name, asset=job.run_key)
            return None
        if "ortho_scale" not in summary:
            return None
        return float(summary["ortho_scale"]), float(summary["frame_target_z"])

    def _base_params(self, job) -> dict[str, Any]:
        """The render parameters for a job, shared by the measure pass and the render pass."""
        gen = job.generation_settings()
        res = int(self.args.size) if self.args.size else int(gen.get("width", 1024))
        res_y = int(self.args.size) if self.args.size else int(gen.get("height", res))
        samples = int(self.args.samples) if self.args.samples else int(
            gen.get("samples") or self.config.get("blender.default_samples", 64))
        params = dict(job.spec["blender"].get("params") or {})
        params.setdefault("seed", int(gen.get("seed") or 0))
        params.update({"engine": str(gen.get("engine") or self.config.get("blender.engine", "BLENDER_EEVEE_NEXT")),
                       "res_x": res, "res_y": res_y, "samples": samples})
        for key in RENDER_PASSTHROUGH:
            if gen.get(key) is not None and key not in params:
                params[key] = gen[key]
        return params

    def render_one(self, job, framing: dict[str, dict[str, Any]], retries: int) -> dict:
        rec = self.record(job)
        anim = job.animation_settings()
        generator = job.spec["blender"]["generator"]
        if self.dry_run:
            self.log.info(f"would render {generator} ({'animation' if anim else 'still'})",
                          stage=self.name, asset=job.run_key)
            return {"dry_run": True}
        if rec.data.get("status") in DONE_STATUSES and not self.force:
            self.log.info("already generated", stage=self.name, asset=job.run_key)
            return {"skipped": "already generated"}

        params = self._base_params(job)
        # The family camera, measured up front. Explicit, so every sibling renders identically
        # framed and the relative size progression is preserved exactly. Without --no-lock-framing
        # each asset falls back to fitting its own bounds.
        if self.args.lock_framing:
            params.update(framing.get(job.asset_id) or {})

        scene_module = str(generator).removesuffix(".py")
        if anim:
            # An animated job drives the scene through the clip sequencer, which rebuilds
            # the same scene per frame via the named scene generator.
            script = ROOT / "blender" / "render_animation.py"
        else:
            script = ROOT / "blender" / generator
        last_error: str | None = None
        for attempt in range(retries + 1):
            started = time.time()
            try:
                if anim:
                    out_dir = self.animation_dir(job)
                    out_dir.mkdir(parents=True, exist_ok=True)
                    clip_params = dict(anim.get("clip_params") or {})
                    clip_params.setdefault("seed", float(params.get("seed", 0)))
                    args = {**params,
                            "scene": scene_module,
                            "clip": anim["clip"],
                            "clip_params": clip_params,
                            "frame_count": int(anim["frame_count"]),
                            "frame_rate": int(anim["frame_rate"]),
                            "out_dir": str(out_dir)}
                    summary = run_blender_script(self.config, script, args, log=self.log,
                                                 stage=self.name,
                                                 log_path=self.log.stage_file(f"{job.run_key}-blender.log"),
                                                 timeout=1800)
                    frames = sorted(out_dir.glob("frame_*.png"))
                    if len(frames) != int(anim["frame_count"]):
                        raise BlenderError(f"expected {anim['frame_count']} frames, got {len(frames)}")
                    rec.complete_stage("generation", file=rel_to_root(out_dir), frames=len(frames),
                                       clip=anim["clip"], frame_rate=int(anim["frame_rate"]),
                                       frame_count=int(anim["frame_count"]),
                                       ortho_scale=summary.get("ortho_scale"),
                                       frame_target_z=summary.get("frame_target_z"),
                                       generator=generator, seconds=round(time.time() - started, 2),
                                       attempt=attempt, params=params)
                    self.log.info(f"rendered {len(frames)} frames ({anim['clip']}) -> {out_dir}",
                                  stage=self.name, asset=job.run_key)
                else:
                    dest = self.incoming_path(job)
                    args = {**params, "out": str(dest)}
                    summary = run_blender_script(self.config, script, args, log=self.log,
                                                 stage=self.name,
                                                 log_path=self.log.stage_file(f"{job.run_key}-blender.log"),
                                                 timeout=1800)
                    if not dest.exists() or dest.stat().st_size == 0:
                        raise BlenderError(f"Blender reported success but {dest} is missing or empty")
                    rec.complete_stage("generation", file=rel_to_root(dest), bytes=dest.stat().st_size,
                                       generator=generator, ortho_scale=summary.get("ortho_scale"),
                                       frame_target_z=summary.get("frame_target_z"),
                                       vertices=summary.get("vertices"), polygons=summary.get("polygons"),
                                       seconds=round(time.time() - started, 2), attempt=attempt, params=params)
                    self.log.info(f"rendered {dest.name} ({dest.stat().st_size // 1024} KB, "
                                  f"{round(time.time() - started, 1)}s)", stage=self.name, asset=job.run_key)
                rec.set_status(STATUS_GENERATED)
                return {"file": str(rec.stage("generation").get("file")), "attempt": attempt,
                        "ortho_scale": summary.get("ortho_scale")}
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
                rec.bump_retry("generation")
                self.log.warn(f"attempt {attempt + 1}/{retries + 1} failed: {last_error[:300]}",
                              stage=self.name, asset=job.run_key)
                # A bad parameter set fails identically every time; retrying it just wastes
                # GPU time. BLENDER_ERROR is the generators' marker for exactly that.
                if "BLENDER_ERROR" in last_error:
                    self.log.warn("deterministic parameter error; not retrying",
                                  stage=self.name, asset=job.run_key)
                    break
        self.record_error(job, "generation", last_error or "unknown failure")
        return {"error": last_error}


if __name__ == "__main__":
    stage = BlenderGenerateStage()
    try:
        stage.run()
    except PipelineError as exc:
        stage.log.error(str(exc), stage=stage.name)
        raise SystemExit(1)
