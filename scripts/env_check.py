#!/usr/bin/env python3
"""Environment check: prove the toolchain works before a batch depends on it.

Reports versions, resolved paths, whether ComfyUI is reachable (starting it if allowed),
whether the checkpoints and custom nodes each workflow needs are installed, whether Blender
can render headlessly, and whether Godot can import into the check project.

    python3 scripts/env_check.py
    python3 scripts/env_check.py --json reports/env-check.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parent / "lib")]

from lib.blender import blender_binary, headless_render_check  # noqa: E402
from lib.comfy import ComfyClient, check_workflow_requirements, load_workflow  # noqa: E402
from lib.common import ROOT, Config, PipelineError, atomic_write_json, run_cmd  # noqa: E402
from lib.manifest import load_manifest, validate_manifest  # noqa: E402


def ok(value: bool) -> str:
    return "ok" if value else "FAIL"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None)
    parser.add_argument("--json", default=None, help="write the full result set here")
    parser.add_argument("--no-start-comfyui", action="store_true")
    parser.add_argument("--skip-smoke", action="store_true", help="skip the Blender render smoke test")
    args = parser.parse_args()

    config = Config.load(args.config)
    report: dict[str, object] = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                 "project_root": str(ROOT), "checks": {}}
    checks: dict[str, object] = report["checks"]  # type: ignore[assignment]
    problems: list[str] = []

    def record(name: str, passed: bool, detail: object, *, fatal: bool = True) -> None:
        checks[name] = {"ok": passed, "detail": detail}
        if not passed and fatal:
            problems.append(f"{name}: {detail}")

    # ---- python ------------------------------------------------------------
    versions = {"python": sys.version.split()[0], "executable": sys.executable}
    for module in ("PIL", "numpy", "yaml", "cv2", "requests"):
        try:
            mod = __import__(module)
            versions[module] = getattr(mod, "__version__", "?")
        except Exception:  # noqa: BLE001
            versions[module] = None
    missing = [k for k, v in versions.items() if v is None]
    record("python_deps", not missing, {"versions": versions, "missing": missing})

    # ---- paths -------------------------------------------------------------
    dirs = {}
    for key in ("incoming", "processed", "animations", "spritesheets", "approved",
                "records", "manifests", "logs", "reports"):
        path = config.path_for(key)
        dirs[key] = str(path)
    record("project_paths", True, dirs)

    # ---- comfyui -----------------------------------------------------------
    client = ComfyClient(config, log=None)
    if args.no_start_comfyui:
        config.data.setdefault("comfyui", {})["autostart"] = False
    comfy_detail: dict[str, object] = {"url": client.url, "home": str(client.home)}
    try:
        client.ensure_server()
        stats = client.system_stats()
        comfy_detail["version"] = stats.get("system", {}).get("comfyui_version")
        device = stats.get("devices") or []
        comfy_detail["devices"] = [d.get("name") for d in device]
        object_info = client.object_info()
        comfy_detail["node_classes"] = len(object_info)
        record("comfyui_reachable", True, comfy_detail)
    except PipelineError as exc:
        object_info = None
        comfy_detail["error"] = str(exc)
        record("comfyui_reachable", False, comfy_detail)

    # workflow requirements, per workflow file
    wf_dir = ROOT / "workflows" / "comfyui"
    for wf_path in sorted(wf_dir.glob("*.json")):
        try:
            workflow = load_workflow(wf_path)
        except PipelineError as exc:
            record(f"workflow[{wf_path.name}]", False, str(exc))
            continue
        wf_problems = check_workflow_requirements(workflow, config, object_info=object_info)
        record(f"workflow[{workflow.name}]", not wf_problems,
               {"problems": wf_problems, "bindings": sorted(workflow.bindings)})

    # ---- blender -----------------------------------------------------------
    try:
        binary = blender_binary(config)
        version = ""

        proc = run_cmd([str(binary), "--version"], timeout=60)
        version = (proc.stdout or "").splitlines()[0] if proc.stdout else ""
        detail = {"binary": str(binary), "version": version.strip()}
        if not args.skip_smoke:
            try:
                summary = headless_render_check(config)
                detail["smoke_render"] = summary
                record("blender_render", bool(summary.get("ok")), detail)
            except PipelineError as exc:
                detail["smoke_render_error"] = str(exc)
                record("blender_render", False, detail)
        else:
            record("blender_render", True, {**detail, "skipped": True}, fatal=False)
    except PipelineError as exc:
        record("blender_render", False, str(exc))

    # ---- godot -------------------------------------------------------------
    godot_binary = shutil.which(str(config.get("godot.binary", "godot"))) or str(config.get("godot.binary"))
    project_dir = Path(str(config.get("godot.project_dir", "godot_project")))
    project_path = project_dir if project_dir.is_absolute() else ROOT / project_dir

    detail = {"binary": godot_binary, "project": str(project_path)}
    try:
        proc = run_cmd([godot_binary, "--version"], timeout=60)
        detail["version"] = (proc.stdout or "").strip()
        record("godot", project_path.exists(), {**detail, "project_exists": project_path.exists()})
    except PipelineError as exc:
        record("godot", False, str(exc))

    # ---- manifest ----------------------------------------------------------
    try:
        manifest = load_manifest(None, config)
        manifest_problems = validate_manifest(manifest, config)
        record("manifest", not manifest_problems,
               {"path": str(manifest.path), "assets": len(manifest.assets),
                "jobs": len(manifest.jobs()), "problems": manifest_problems})
    except PipelineError as exc:
        record("manifest", False, str(exc))

    report["problems"] = problems
    report["ok"] = not problems

    width = max(len(k) for k in checks) + 2
    print(f"\n{'check'.ljust(width)}result  detail")
    print("-" * (width + 40))
    for name, entry in checks.items():
        detail_str = json.dumps(entry["detail"], default=str)
        print(f"{name.ljust(width)}{ok(entry['ok']):6s}  {detail_str[:150]}")
    print()
    if problems:
        print(f"{len(problems)} problem(s):")
        for problem in problems:
            print(f"  - {problem}")
    else:
        print("environment ok")

    if args.json:
        dest = Path(args.json) if Path(args.json).is_absolute() else ROOT / args.json
        atomic_write_json(dest, report)
        print(f"wrote {dest}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
