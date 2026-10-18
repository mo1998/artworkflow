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
import sys
import time
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parent / "lib")]

from lib.blender import blender_binary, headless_render_check  # noqa: E402
from lib.comfy import ComfyClient, check_workflow_requirements, load_workflow  # noqa: E402
from lib.common import ROOT, Config, PipelineError, atomic_write_json, run_cmd  # noqa: E402
from lib.manifest import load_manifest, validate_manifest  # noqa: E402

# What the pipeline itself imports. Everything else is optional and only reported: a missing cv2
# must not fail a batch that never touches it. tests/test_repo_consistency.py asserts that every
# third-party import in the codebase is declared in one of these two tuples.
REQUIRED_MODULES = ("PIL", "numpy", "yaml")
# Extension point for a genuinely optional integration. Keep it empty otherwise: a module listed
# here is checked for and reported, so listing something nothing imports is just noise.
OPTIONAL_MODULES: tuple[str, ...] = ()


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
    for module in REQUIRED_MODULES + OPTIONAL_MODULES:
        try:
            mod = __import__(module)
            versions[module] = getattr(mod, "__version__", "?")
        except Exception:  # noqa: BLE001
            versions[module] = None
    missing_required = [m for m in REQUIRED_MODULES if versions.get(m) is None]
    missing_optional = [m for m in OPTIONAL_MODULES if versions.get(m) is None]
    record("python_deps", not missing_required,
           {"versions": versions, "missing": missing_required, "optional_missing": missing_optional})

    # ---- paths -------------------------------------------------------------
    dirs = {}
    for key in ("incoming", "processed", "animations", "spritesheets", "approved",
                "records", "manifests", "logs", "reports"):
        path = config.path_for(key)
        dirs[key] = str(path)
    record("project_paths", True, dirs)

    # ---- tool discovery ----------------------------------------------------
    # One place that lists every tool the pipeline needs and why it could not be found, using the
    # same resolvers the stages use. Everything below probes deeper; this is the summary a
    # contributor reads first.
    from lib.tools import resolve_tools

    tools = resolve_tools(config)
    record("tool_paths", not tools["problems"], {
        "comfyui_home": str(tools["comfyui_home"]) if tools["comfyui_home"] else None,
        "comfyui_python": tools["comfyui_python"],
        "blender": str(tools["blender"]) if tools["blender"] else None,
        "godot": tools["godot"],
        "problems": tools["problems"],
    })

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
    # Resolve through lib.tools like every stage does, so env_check cannot report a different
    # binary than the one a stage will actually run.
    from lib.tools import find_godot

    godot_binary = find_godot(config.get("godot.binary") or None)
    project_dir = Path(str(config.get("godot.project_dir", "godot_project")))
    project_path = project_dir if project_dir.is_absolute() else ROOT / project_dir

    detail = {"binary": godot_binary, "project": str(project_path),
              "project_exists": project_path.exists()}
    if not godot_binary:
        record("godot", False, {**detail, "error": "godot not found"})
    elif not project_path.exists():
        record("godot", False, {**detail, "error": "check project not found"})
    else:
        try:
            proc = run_cmd([godot_binary, "--version"], timeout=60)
            detail["version"] = (proc.stdout or "").strip()
            record("godot", True, detail)
        except PipelineError as exc:
            record("godot", False, {**detail, "error": str(exc)})

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
