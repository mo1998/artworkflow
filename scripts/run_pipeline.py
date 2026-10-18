#!/usr/bin/env python3
"""Pipeline entry point.

Each stage is a separate script and a separate process, so a stage can be rerun on its own,
a crash is contained to one stage, and every stage keeps its own transcript. This file only
sequences them, shares one run id, and reports the outcome.

Stages, in order:
    generate      comfyui_generate.py + blender_generate.py  -> assets/incoming, assets/animations
    process       process_images.py                          -> assets/processed
    spritesheet   generate_spritesheet.py                    -> assets/spritesheets
    validate      validate_assets.py                         -> statuses on the records
    export        export_assets.py                           -> assets/approved + godot mirror
    godot         godot_check.py                             -> engine-side verification
    report        build_report.py                            -> reports/<run id>.md

    python3 scripts/run_pipeline.py                      # everything
    python3 scripts/run_pipeline.py --stages process,validate,report
    python3 scripts/run_pipeline.py --assets demo_hut --force
    python3 scripts/run_pipeline.py --strict --skip-godot

Exit code is 0 only when there are no failed assets; review_required assets do not fail the
run, they are listed in the report.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parent / "lib")]

from lib.common import Config, PipelineError, ROOT, new_run_id, read_json  # noqa: E402
from lib.manifest import check_paths, load_manifest, validate_manifest  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent

STAGE_PLAN: dict[str, list[list[str]]] = {
    "generate": [["comfyui_generate.py"], ["blender_generate.py"]],
    "process": [["process_images.py"]],
    "spritesheet": [["generate_spritesheet.py"]],
    "validate": [["validate_assets.py"]],
    "export": [["export_assets.py"]],
    "godot": [["godot_check.py"]],
    "report": [["build_report.py"]],
}
STAGE_ORDER = ["generate", "process", "spritesheet", "validate", "export", "godot", "report"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=None)
    parser.add_argument("--manifest", default=None)
    parser.add_argument("--assets", nargs="*", default=None, help="asset ids / run keys to restrict to")
    parser.add_argument("--stages", default="all",
                        help="comma-separated subset of: " + ", ".join(STAGE_ORDER) + " (default all)")
    parser.add_argument("--run-id", default=None, help="reuse an existing run id")
    parser.add_argument("--force", action="store_true", help="redo work even when it looks done")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--strict", action="store_true", help="export only outright-passing assets")
    parser.add_argument("--skip-godot", action="store_true")
    parser.add_argument("--skip-generate", action="store_true",
                        help="alias for --stages process,spritesheet,validate,export,godot,report")
    parser.add_argument("--allow-failures", action="store_true",
                        help="exit 0 even when assets failed (the report still lists them)")
    parser.add_argument("--fail-fast", action="store_true", help="stop at the first failing stage")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = Config.load(args.config)
    check_paths(config)

    if args.stages == "all":
        stages = [s for s in STAGE_ORDER if not (args.skip_godot and s == "godot")]
    else:
        stages = [s.strip() for s in args.stages.split(",") if s.strip()]
        unknown = [s for s in stages if s not in STAGE_PLAN]
        if unknown:
            raise SystemExit(f"unknown stage(s) {unknown}; choose from {STAGE_ORDER}")
        stages = [s for s in STAGE_ORDER if s in stages]
    if args.skip_generate:
        stages = [s for s in stages if s != "generate"]

    manifest = load_manifest(args.manifest, config)
    problems = validate_manifest(manifest, config)
    if problems:
        for problem in problems:
            print(f"error: manifest: {problem}", file=sys.stderr)
        return 2

    run_id = args.run_id or new_run_id()
    print(f"run {run_id}: {len(manifest.jobs(args.assets))} job(s), stages: {', '.join(stages)}")
    started = time.time()
    failures: list[tuple[str, int]] = []

    for stage in stages:
        for command in STAGE_PLAN[stage]:
            argv = [sys.executable, str(SCRIPTS / command[0]),
                    "--config", str(config.path), "--run-id", run_id]
            if args.manifest:
                argv += ["--manifest", str(args.manifest)]
            if args.assets:
                argv += ["--assets", *args.assets]
            if args.force:
                argv += ["--force"]
            if args.dry_run:
                argv += ["--dry-run"]
            if stage == "export" and args.strict:
                argv += ["--strict"]
            print(f"\n=== {stage} :: {command[0]}{' --dry-run' if args.dry_run else ''} ===", flush=True)
            proc = subprocess.run(argv, cwd=str(ROOT))
            if proc.returncode != 0:
                failures.append((f"{stage}:{command[0]}", proc.returncode))
                print(f"stage {stage} ({command[0]}) exited {proc.returncode}", file=sys.stderr)
                if args.fail_fast:
                    break
        if failures and args.fail_fast:
            break

    elapsed = round(time.time() - started, 1)
    report_json = config.path_for("reports") / f"{run_id}.json"
    totals: dict[str, object] = {}
    if report_json.exists():
        try:
            totals = read_json(report_json).get("totals", {})
        except (json.JSONDecodeError, OSError):
            totals = {}

    print("\n" + "=" * 72)
    print(f"run {run_id} finished in {elapsed}s")
    if totals:
        print(f"  assets: {totals.get('assets')}  exported: {totals.get('exported')}  "
              f"failed: {totals.get('failed')}  review_required: {totals.get('review_required')}  "
              f"retried: {totals.get('retried')}")
        for status, count in sorted((totals.get("by_status") or {}).items()):  # type: ignore[union-attr]
            print(f"    {status}: {count}")
    if failures:
        for name, code in failures:
            print(f"  stage failure: {name} (exit {code})")
    report_md = config.path_for("reports") / f"{run_id}.md"
    if report_md.exists():
        print(f"  report: {report_md.relative_to(ROOT)}")
    print("=" * 72)

    failed_assets = int((totals.get("failed") or 0))  # type: ignore[arg-type]
    if failures and not args.allow_failures:
        return 1
    if failed_assets and not args.allow_failures:
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PipelineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
