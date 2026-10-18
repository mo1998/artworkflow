#!/usr/bin/env python3
"""Stage: build the run report.

Written for a human deciding what to ship and for a log that can be re-read later: what was
produced, where it is, what it was made from, what failed, and which assets still need eyes on
them. Nothing is summarized away - failed and review_required assets appear with the reason.

    python3 scripts/build_report.py
    python3 scripts/build_report.py --run-id 20261018-130000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parent / "lib")]

from lib.common import (ROOT, PipelineError, STATUS_EXPORTED, STATUS_FAILED,  # noqa: E402
                        STATUS_PASSED, STATUS_PENDING, STATUS_REVIEW, atomic_write_json,
                        now_iso)
from lib.stage import Stage, add_common_args  # noqa: E402

PROVENANCE_REQUIRED = ("model", "license_url")


class ReportStage(Stage):
    name = "report"

    def build_parser(self) -> argparse.ArgumentParser:
        parser = add_common_args(argparse.ArgumentParser(description=__doc__))
        parser.add_argument("--out", default=None, help="report basename (default: <run id>)")
        return parser

    def run(self) -> dict:
        self.preflight()
        jobs = self.jobs
        rows = []
        for job in jobs:
            rec = self.record(job)
            data = rec.data
            validation = rec.stage("validation")
            generation = rec.stage("generation")
            rows.append({
                "asset_id": job.asset_id,
                "run_key": job.run_key,
                "type": job.spec.get("asset_type"),
                "source": job.source,
                "style": job.style_name,
                "status": data.get("status", STATUS_PENDING),
                "exported_status": data.get("exported_status"),
                "seed": generation.get("seed") if generation else job.generation_settings().get("seed"),
                "model": (job.spec.get("provenance") or {}).get("model"),
                "workflow": generation.get("workflow"),
                "generator": generation.get("generator"),
                "clip": generation.get("clip"),
                "frames": generation.get("frames"),
                "incoming": generation.get("file"),
                "processed": rec.stage("processing").get("file") or rec.stage("processing").get("dir"),
                "exported": rec.stage("export").get("files") or [],
                "failed_checks": validation.get("failed") or [],
                "review_checks": validation.get("review") or [],
                "retries": data.get("retries") or {},
                "errors": data.get("errors") or [],
                "seconds": {k: v.get("seconds") for k, v in (data.get("stages") or {}).items()
                            if isinstance(v, dict) and v.get("seconds") is not None},
            })

        counts: dict[str, int] = {}
        for row in rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        retried = [r["run_key"] for r in rows if any(v for v in (r["retries"] or {}).values())]
        failed = [r["run_key"] for r in rows if r["status"] == STATUS_FAILED]
        review = [r["run_key"] for r in rows if r["status"] in (STATUS_REVIEW,) or r["review_checks"]]
        provenance_gaps = []
        for job in jobs:
            prov = job.spec.get("provenance") or {}
            missing = [f for f in PROVENANCE_REQUIRED if not prov.get(f)]
            if missing:
                provenance_gaps.append({"run_key": job.run_key, "missing": missing})

        duplicates = self._duplicates(job_list=[j.run_key for j in jobs])
        payload = {
            "run_id": self.log.run_id,
            "generated_at": now_iso(),
            "manifest": str(self.manifest.path) if self.manifest else None,
            "totals": {
                "assets": len(rows),
                "by_status": counts,
                "retried": len(retried),
                "failed": len(failed),
                "review_required": len(review),
                "exported": counts.get(STATUS_EXPORTED, 0),
            },
            "assets": rows,
            "retried": retried,
            "duplicates": duplicates,
            "provenance_gaps": provenance_gaps,
            "logs": sorted(str(p.relative_to(ROOT)) for p in self.log.dir.glob("*")),
        }

        out_name = self.args.out or self.log.run_id
        report_dir = self.config.path_for("reports")
        json_path = report_dir / f"{out_name}.json"
        md_path = report_dir / f"{out_name}.md"
        if not self.dry_run:
            report_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_json(json_path, payload)
            md_path.write_text(self.render_markdown(payload), encoding="utf-8")
            self.log.info(f"report -> {md_path.relative_to(ROOT)} and {json_path.relative_to(ROOT)}",
                          stage=self.name)
        self.summarize({"stage": self.name, "report": str(md_path), "totals": payload["totals"]})
        # Statuses are left exactly as the earlier stages set them: the report describes
        # state, it does not decide it.
        return payload

    # ---- helpers -----------------------------------------------------------
    def _duplicates(self, job_list: list[str]) -> list[dict]:
        found = []
        for key in job_list:
            rec = self.records.get(key)
            if not rec:
                continue
            for note in rec.data.get("notes") or []:
                if "near-duplicate" in note:
                    found.append({"run_key": key, "note": note})
        return found

    def render_markdown(self, payload: dict) -> str:
        t = payload["totals"]
        lines = [
            f"# Art pipeline report - {payload['run_id']}",
            "",
            f"Generated {payload['generated_at']} from `{payload['manifest']}`.",
            "",
            "## Totals",
            "",
            f"- assets: **{t['assets']}**",
            f"- exported: **{t['exported']}**",
            f"- failed: **{t['failed']}**",
            f"- review required: **{t['review_required']}**",
            f"- retried at least once: **{t['retried']}**",
            "",
            "| status | count |",
            "| --- | --- |",
        ]
        for status, count in sorted(t["by_status"].items()):
            lines.append(f"| {status} | {count} |")
        lines += ["", "## Assets", "",
                  "| asset | source | status | seed | clip | exported to | notes |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        for row in payload["assets"]:
            notes = []
            if row["failed_checks"]:
                notes.append("failed: " + ", ".join(row["failed_checks"]))
            if row["review_checks"]:
                notes.append("review: " + ", ".join(row["review_checks"]))
            if row["retries"]:
                notes.append("retries: " + ", ".join(f"{k}x{v}" for k, v in row["retries"].items()))
            if row["errors"]:
                notes.append("errors: " + str(len(row["errors"])))
            dest = row["exported"][0] if row["exported"] else (row["processed"] or "-")
            lines.append("| {asset} | {source} | {status} | {seed} | {clip} | `{dest}` | {notes} |".format(
                asset=row["run_key"], source=row["source"], status=row["status"],
                seed=row["seed"] if row["seed"] is not None else "-",
                clip=row["clip"] or "-", dest=dest, notes="; ".join(notes) or "-"))

        lines += ["", "## Provenance", "",
                  "| asset | model | workflow / generator | licence recorded |",
                  "| --- | --- | --- | --- |"]
        for row in payload["assets"]:
            job = next((j for j in self.jobs if j.run_key == row["run_key"]), None)
            prov = (job.spec.get("provenance") or {}) if job else {}
            lines.append(f"| {row['run_key']} | {row['model'] or '-'} | "
                         f"`{row['workflow'] or row['generator'] or '-'}` | "
                         f"{'yes' if prov.get('license_url') else '**missing**'} |")

        if payload["duplicates"]:
            lines += ["", "## Near-duplicates", ""]
            for dup in payload["duplicates"]:
                lines.append(f"- {dup['run_key']}: {dup['note']}")
        if payload["provenance_gaps"]:
            lines += ["", "## Missing provenance fields", ""]
            for gap in payload["provenance_gaps"]:
                lines.append(f"- {gap['run_key']}: missing {', '.join(gap['missing'])}")
        if payload["retried"]:
            lines += ["", "## Retried assets", "",
                      "Retries shift the seed (seed + 1013 per attempt), so these are reproducible "
                      "from the recorded seed, not by rerunning the original prompt.", ""]
            for key in payload["retried"]:
                lines.append(f"- {key}")
        lines += ["", "## Logs", ""]
        for log_path in payload["logs"]:
            lines.append(f"- `{log_path}`")
        lines += ["", "## Notes", "",
                  "- `review_required` means every automatic check passed but a human should look "
                  "before shipping; it is not a pass.", ""]
        return "\n".join(lines) + "\n"


if __name__ == "__main__":
    stage = ReportStage()
    try:
        stage.run()
    except PipelineError as exc:
        stage.log.error(str(exc), stage=stage.name)
        raise SystemExit(1)
