#!/usr/bin/env python3
"""Stage: validate processed assets and set their status honestly.

Three outcomes, and the difference matters:
  passed          - every configured check ran and the asset is engine-ready
  review_required - technically clean, but something a human should look at (aesthetic
                    guesses the validator cannot make, e.g. the subject fills too little of
                    the canvas); these are exported but flagged, never silently blessed
  failed          - a check failed; the asset is not exported

Checks, per asset type:
  still     file/format, dimensions, alpha presence, blankness, subject coverage,
            edge clipping, subject size, near-duplicates across the set
  sequence  frame count, uniform frame size, blankness, per-frame subject presence,
            registration drift (centroid jitter), actual motion, loop continuity

    python3 scripts/validate_assets.py
    python3 scripts/validate_assets.py --assets demo_hut demo_watchtower_a
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parent / "lib")]

from lib.common import (PipelineError, STATUS_FAILED, STATUS_PASSED,  # noqa: E402
                        STATUS_REVIEW, rel_to_root)
from lib.imageops import (content_bbox, detect_format, dhash,  # noqa: E402
                          frames_differ, hamming,
                          measure, motion_metrics, open_image)
from lib.stage import Stage, add_common_args  # noqa: E402


class Check:
    __slots__ = ("name", "ok", "detail", "severity")

    def __init__(self, name: str, ok: bool, detail: str, *, severity: str = "error"):
        self.name = name
        self.ok = ok
        self.detail = detail
        self.severity = severity

    def as_dict(self) -> dict:
        return {"check": self.name, "ok": self.ok, "detail": self.detail, "severity": self.severity}


class ValidateStage(Stage):
    name = "validate"

    def build_parser(self) -> argparse.ArgumentParser:
        parser = add_common_args(argparse.ArgumentParser(description=__doc__))
        parser.add_argument("--no-dedupe", action="store_true", help="skip the near-duplicate scan")
        return parser

    def run(self) -> dict:
        self.preflight()
        results: dict[str, object] = {"stage": self.name, "assets": {}, "duplicates": []}
        fingerprints: list[tuple[str, int]] = []

        for job in self.jobs:
            checks = self.try_job(job, "validation", lambda job=job: self.check_asset(job), {})
            if checks is None:
                continue
            errors = [c for c in checks if not c.ok and c.severity == "error"]
            reviews = [c for c in checks if not c.ok and c.severity == "review"]
            status = STATUS_FAILED if errors else (STATUS_REVIEW if reviews else STATUS_PASSED)
            rec = self.record(job)
            if not self.dry_run:
                rec.complete_stage("validation", status=status,
                                   checks=[c.as_dict() for c in checks],
                                   failed=[c.name for c in errors],
                                   review=[c.name for c in reviews])
                rec.set_status(status)
            results["assets"][job.run_key] = {
                "status": status,
                "failed": [c.name for c in errors],
                "review": [c.name for c in reviews],
                "checks": [c.as_dict() for c in checks],
            }
            level = self.log.warn if status != STATUS_PASSED else self.log.info
            level(f"{status}" + (f" (failed: {', '.join(c.name for c in errors)})" if errors else "")
                  + (f" (review: {', '.join(c.name for c in reviews)})" if reviews else ""),
                  stage=self.name, asset=job.run_key)

            path = self.processed_path(job)
            if path.exists():
                try:
                    fingerprints.append((job.run_key, dhash(open_image(path))))
                except Exception:  # noqa: BLE001 - already reported by the file check
                    pass

        if not self.args.no_dedupe and len(fingerprints) > 1:
            limit = int(self.config.get("validation.duplicate_hamming_distance", 6))
            for i in range(len(fingerprints)):
                for k in range(i + 1, len(fingerprints)):
                    a_id, a_hash = fingerprints[i]
                    b_id, b_hash = fingerprints[k]
                    distance = hamming(a_hash, b_hash)
                    if distance <= limit:
                        note = {"a": a_id, "b": b_id, "hamming": distance, "limit": limit}
                        results["duplicates"].append(note)
                        self.log.warn(f"near-duplicate of {b_id} (dHash distance {distance} <= {limit})",
                                      stage=self.name, asset=a_id)
                        rec = self.records[a_id]
                        if not self.dry_run and rec.data.get("status") == STATUS_PASSED:
                            rec.set_status(STATUS_REVIEW)
                            rec.data.setdefault("notes", []).append(
                                f"near-duplicate of {b_id} (hamming {distance})")
        self.save_records()
        self.summarize(results)
        return results

    # ---- source-level checks ------------------------------------------------
    def check_source_clipping(self, job) -> list[Check]:
        """Did the generator frame its subject, or cut it off?

        This is the check that would have caught the level-3 keep losing its banner to the
        family framing lock. Procedural only: the pipeline owns the Blender camera, so content
        touching the render border there means the camera was wrong. Painted renders are the
        diffusion model's composition, and a portrait is *supposed* to crop its subject at the
        bottom edge, so the same rule would fail good art.
        """
        if job.source != "blender":
            return []
        src = self.find_incoming(job)
        if src is None:
            return []
        try:
            img = open_image(src)
        except Exception as exc:  # noqa: BLE001
            return [Check("source_opens", False, f"{rel_to_root(src)}: {exc}")]
        box = content_bbox(img)
        if box is None:
            return [Check("source_not_clipped", False, f"{src.name} has no subject pixels")]
        margin = int(self.config.get("validation.source_border_margin_px", 2))
        width, height = img.size
        edges = []
        if box[0] <= margin:
            edges.append("left")
        if box[1] <= margin:
            edges.append("top")
        if box[2] >= width - margin:
            edges.append("right")
        if box[3] >= height - margin:
            edges.append("bottom")
        return [Check("source_not_clipped", not edges,
                      f"{src.name} content box {box} within {width}x{height}"
                      + (f"; subject touches {', '.join(edges)} - the camera cropped it" if edges else ""))]

    # ---- per asset ---------------------------------------------------------
    def check_asset(self, job) -> list[Check]:
        anim = job.animation_settings()
        if anim:
            return self.check_sequence(job, anim)
        return self.check_still(job)

    def check_still(self, job) -> list[Check]:
        checks: list[Check] = []
        steps = job.processing_settings()
        path = self.processed_path(job)
        checks.append(Check("file_exists", path.exists(), rel_to_root(path)))
        if not path.exists():
            return checks

        # Check the *render* for clipping, before trim and padding can hide it. Trimming crops to
        # the content, so the padded canvas always has an inset subject: `not_clipped` on the
        # processed file cannot fail, and a roof cut off by the camera passes silently.
        checks.extend(self.check_source_clipping(job))

        data = path.read_bytes()
        fmt = detect_format(data)
        checks.append(Check("format_is_png", fmt == "png", f"detected {fmt}"))
        checks.append(Check("not_empty", len(data) > 1024, f"{len(data)} bytes"))

        try:
            img = open_image(path)
        except Exception as exc:  # noqa: BLE001
            checks.append(Check("opens", False, str(exc)))
            return checks
        checks.append(Check("opens", True, f"{img.width}x{img.height} {img.mode}"))
        m = measure(img)

        canvas = steps.get("resize")
        if canvas:
            expected = (int(canvas), int(canvas))
            checks.append(Check("dimensions", (m.width, m.height) == expected,
                                f"{m.width}x{m.height} expected {expected[0]}x{expected[1]}"))
        else:
            min_side = int(self.config.get("validation.min_subject_short_side_px", 48))
            checks.append(Check("dimensions", min(m.width, m.height) >= min_side,
                                f"{m.width}x{m.height} min side {min_side}"))

        blank_min = float(self.config.get("validation.blank_stddev_min", 4.0))
        checks.append(Check("not_blank", m.rgb_stddev >= blank_min,
                            f"rgb stddev {m.rgb_stddev} (min {blank_min})"))

        expect_alpha = bool(steps.get("remove_background")) or job.source == "blender"
        if expect_alpha:
            checks.append(Check("has_alpha", m.has_alpha, f"mode {m.mode}"))
            lo = float(self.config.get("validation.alpha_coverage.min", 0.02))
            hi = float(self.config.get("validation.alpha_coverage.max", 0.97))
            checks.append(Check("subject_present", lo <= m.alpha_coverage <= hi,
                                f"alpha coverage {m.alpha_coverage:.4f} in [{lo}, {hi}]"))
            if m.bbox:
                short = min(m.bbox[2] - m.bbox[0], m.bbox[3] - m.bbox[1])
                min_subject = int(self.config.get("validation.min_subject_short_side_px", 48))
                checks.append(Check("subject_size", short >= min_subject,
                                    f"subject short side {short}px (min {min_subject})"))
            else:
                checks.append(Check("subject_size", False, "no subject pixels found"))
            # An isolated sprite must not be flush with the canvas edge; padding or the
            # trim step guarantees that, so touching an edge means the render was clipped.
            touching = [edge for edge, hit in m.touches_border.items() if hit]
            checks.append(Check("not_clipped", not touching,
                                "subject touches " + ", ".join(touching) if touching else "subject clear of edges"))

            # Aesthetic guesses: cheap to measure, impossible to judge automatically.
            if m.bbox and (m.width * m.height):
                fill = ((m.bbox[2] - m.bbox[0]) * (m.bbox[3] - m.bbox[1])) / (m.width * m.height)
                lo_fill = float(self.config.get("review.min_subject_fill_ratio", 0.15))
                hi_fill = float(self.config.get("review.max_subject_fill_ratio", 0.92))
                checks.append(Check("subject_fill", lo_fill <= fill <= hi_fill,
                                    f"subject fills {fill:.2%} of the canvas (want {lo_fill:.0%}-{hi_fill:.0%})",
                                    severity="review"))
        else:
            checks.append(Check("has_alpha", True, "alpha not required for this style",
                                severity="review"))
        return checks

    def check_sequence(self, job, anim: dict) -> list[Check]:
        checks: list[Check] = []
        frames_dir = self.processed_path(job).parent / job.run_key
        frames = sorted(frames_dir.glob("frame_*.png"))
        expected = int(anim["frame_count"])
        checks.append(Check("frames_present", len(frames) == expected,
                            f"found {len(frames)} frames, expected {expected}"))
        if not frames:
            return checks

        images = []
        for path in frames:
            try:
                images.append(open_image(path))
            except Exception as exc:  # noqa: BLE001
                checks.append(Check("frame_opens", False, f"{path.name}: {exc}"))
                return checks
        checks.append(Check("frame_opens", True, f"{len(images)} frames readable"))

        sizes = {img.size for img in images}
        checks.append(Check("frames_uniform", len(sizes) == 1, f"sizes {sorted(sizes)}"))

        measurements = [measure(img) for img in images]
        blank_min = float(self.config.get("validation.blank_stddev_min", 4.0))
        flat = [i for i, m in enumerate(measurements) if m.rgb_stddev < blank_min]
        checks.append(Check("frames_not_blank", not flat, f"flat frames: {flat}"))

        lo = float(self.config.get("validation.alpha_coverage.min", 0.02))
        empty = [i for i, m in enumerate(measurements) if m.bbox is None or m.alpha_coverage < lo]
        checks.append(Check("frames_have_subject", not empty, f"frames without subject: {empty}"))

        centroids = [m.centroid for m in measurements]
        if all(c is not None for c in centroids):
            xs = [c[0] for c in centroids]  # type: ignore[index]
            ys = [c[1] for c in centroids]  # type: ignore[index]
            jitter = max(max(xs) - min(xs), max(ys) - min(ys))
            limit = float(self.config.get("validation.frame.centroid_jitter_max_px", 24))
            from lib.blender import camera_moving_clips

            if str(anim.get("clip")) in camera_moving_clips():
                # A turntable is *supposed* to move the subject across the frame; demanding a
                # stable centroid would fail every correct turntable.
                checks.append(Check("registration_stable", True,
                                    f"not applicable: clip {anim.get('clip')!r} moves the camera "
                                    f"(centroid drift {jitter:.1f}px)"))
            else:
                checks.append(Check("registration_stable", jitter <= limit,
                                    f"centroid drift {jitter:.1f}px (max {limit})"))

        steps = [motion_metrics(images[i], images[i + 1]) for i in range(len(images) - 1)]
        if steps:
            changed = max(s["changed_fraction"] for s in steps)
            peak = max(s["peak_delta"] for s in steps)
            min_changed = float(self.config.get("validation.frame.min_changed_pixel_fraction", 0.0005))
            min_peak = int(self.config.get("validation.frame.min_peak_delta", 8))
            checks.append(Check("has_motion", changed >= min_changed and peak >= min_peak,
                                f"peak delta {peak} (min {min_peak}), max changed fraction "
                                f"{changed:.6f} (min {min_changed}); a still loop means the clip did nothing"))
            if anim.get("loop"):
                closure = frames_differ(images[-1], images[0])
                average = sum(s["mean"] for s in steps) / len(steps)
                slack = max(0.002, average * 3.0)
                checks.append(Check("loop_continuous", closure <= slack,
                                    f"loop step {closure:.5f} vs average step {average:.5f} (max {slack:.5f})"))
        return checks


if __name__ == "__main__":
    stage = ValidateStage()
    try:
        stage.run()
    except PipelineError as exc:
        stage.log.error(str(exc), stage=stage.name)
        raise SystemExit(1)
