#!/usr/bin/env python3
"""ArtWorkflow MCP server — the pipeline exposed as tools for any MCP-capable agent.

Dependency-free: a small JSON-RPC 2.0 stdio server, so it runs anywhere the pipeline runs and
does not require the `mcp` SDK or any other package. Start it with an MCP client:

    claude mcp add artworkflow -- python3 /path/to/artworkflow/mcp_server/server.py
    opencode mcp add artworkflow -- python3 /path/to/artworkflow/mcp_server/server.py

or configure it by hand (see mcp_server/README.md for client snippets).

Protocol notes that matter here:
  * stdout is the transport, so every human-readable line a stage would print is redirected to
    stderr for the duration of a tool call. A stray print would corrupt the stream.
  * Long tools (generation, full runs) block until finished. MCP clients apply their own tool
    timeouts; set MCP_TIMEOUT (Claude Code) or the equivalent generously for real batches.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO_ROOT / "scripts"), str(REPO_ROOT / "scripts" / "lib")]

SERVER_NAME = "artworkflow"
SERVER_VERSION = "1.0.0"
DEFAULT_PROTOCOL = "2025-06-18"
SUPPORTED_PROTOCOLS = {"2024-11-05", "2025-03-26", "2025-06-18"}

# The transport. Everything else goes to stderr.
PROTOCOL_OUT = sys.stdout


# --------------------------------------------------------------------------- tools
ASSETS_SCHEMA = {
    "type": "array",
    "items": {"type": "string"},
    "description": "Asset ids or run keys, e.g. ['vampire_keep', 'vampire_keep__lvl2']. "
                   "Omit to act on every asset in the manifest.",
}


def tool_specs() -> list[dict[str, Any]]:
    """Tool definitions. Descriptions are written for a model deciding whether to call them."""
    return [
        {
            "name": "artworkflow_env_check",
            "description": "Check that the pipeline can run: resolves ComfyUI, its python, Blender and "
                           "Godot, reports versions, whether ComfyUI is reachable, whether each "
                           "workflow's checkpoint and custom nodes are installed, and whether the "
                           "Blender render path works. Call this first on a new machine, and before "
                           "blaming the pipeline for a failure.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "skip_smoke": {"type": "boolean", "description": "Skip the Blender test render."},
                    "start_comfyui": {"type": "boolean", "description": "Allow starting ComfyUI. Default true."},
                },
            },
        },
        {
            "name": "artworkflow_manifest",
            "description": "Validate config/manifest.json and list what it would produce: every job "
                           "(asset plus its upgrade-tier variants) with its source, style, size and "
                           "animation clip. Returns the validator's problems, if any. Read-only and "
                           "instant; use it to understand a manifest before running it.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "artworkflow_styles",
            "description": "List the art directions in config/styles.yaml: each style's prompt "
                           "fragments, generation defaults and processing defaults. Read-only. Use it "
                           "to see which look an asset would get, or to pick a style for a new asset.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "artworkflow_asset_status",
            "description": "Per-asset state from the durable records: status, seed, prompt, workflow, "
                           "measurements, which checks passed or failed, retries and errors. This is "
                           "the honest answer to 'did it work'; a generated file is not a finished "
                           "asset. Read-only.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "assets": ASSETS_SCHEMA,
                    "include_checks": {"type": "boolean", "description": "Include every check with its detail string."},
                    "status": {"type": "string", "description": "Only assets with this status, e.g. 'failed'."},
                },
            },
        },
        {
            "name": "artworkflow_inspect",
            "description": "Measure an asset's actual pixels and report its provenance: dimensions, "
                           "alpha coverage, subject bounding box, whether it touches the canvas edge, "
                           "file size, and where the file is. Use this to check output without "
                           "loading images yourself.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "assets": ASSETS_SCHEMA,
                    "stage": {
                        "type": "string",
                        "enum": ["incoming", "processed", "approved"],
                        "description": "Which copy to measure. Default processed.",
                    },
                },
            },
        },
        {
            "name": "artworkflow_generate",
            "description": "Stage 1: render raw artwork. ComfyUI/FLUX assets go to assets/incoming/, "
                           "Blender assets are rendered procedurally (upgrade-tier families are "
                           "measured first so every tier shares one camera). Slow: seconds per "
                           "procedural render, tens of seconds per diffusion image. Failures retry "
                           "with a shifted seed.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "assets": ASSETS_SCHEMA,
                    "force": {"type": "boolean", "description": "Regenerate even if a record says it is done."},
                    "samples": {"type": "integer", "description": "Override Blender render samples."},
                    "size": {"type": "integer", "description": "Override square output resolution."},
                },
            },
        },
        {
            "name": "artworkflow_process",
            "description": "Stage 2: turn raw renders into game-ready PNGs - background removal via "
                           "ComfyUI+BiRefNet, trim to subject, scale, and place on a fixed canvas at a "
                           "fixed anchor so sprite sets share a ground line. Sources are never "
                           "overwritten.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "assets": ASSETS_SCHEMA,
                    "force": {"type": "boolean"},
                    "no_background_removal": {"type": "boolean", "description": "Skip the cutout stage entirely."},
                },
            },
        },
        {
            "name": "artworkflow_spritesheet",
            "description": "Stage 3: pack animation frame sequences into spritesheets plus JSON frame "
                           "metadata (frame rects, fps, loop flag, per-step motion). Only touches "
                           "assets whose animation block is enabled.",
            "inputSchema": {
                "type": "object",
                "properties": {"assets": ASSETS_SCHEMA, "columns": {"type": "integer"}},
            },
        },
        {
            "name": "artworkflow_validate",
            "description": "Stage 4: run the checks and set each asset's status. Hard checks fail an "
                           "asset; aesthetic guesses set review_required instead. Also scans for "
                           "near-duplicates. Trust this over 'the file exists'.",
            "inputSchema": {
                "type": "object",
                "properties": {"assets": ASSETS_SCHEMA, "no_dedupe": {"type": "boolean"}},
            },
        },
        {
            "name": "artworkflow_export",
            "description": "Stage 5: copy passing assets to their target directories and mirror them "
                           "into the Godot test project, each with a JSON sidecar carrying its status "
                           "and provenance. Failed assets are not exported.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "assets": ASSETS_SCHEMA,
                    "strict": {"type": "boolean", "description": "Export only assets that passed outright."},
                },
            },
        },
        {
            "name": "artworkflow_godot_check",
            "description": "Stage 6: engine-side verification. Runs headless Godot import and then loads "
                           "every exported texture and every spritesheet's frame rects inside Godot. A "
                           "green Python validator plus a red check here means the engine cannot "
                           "consume the file.",
            "inputSchema": {"type": "object", "properties": {"skip_import": {"type": "boolean"}}},
        },
        {
            "name": "artworkflow_report",
            "description": "Stage 7: build the run report (markdown + JSON) with totals, a per-asset "
                           "table, provenance including missing licences, near-duplicates, retries and "
                           "the log inventory. Returns the report path and the totals.",
            "inputSchema": {"type": "object", "properties": {"name": {"type": "string", "description": "Report basename."}}},
        },
        {
            "name": "artworkflow_run",
            "description": "Run the whole pipeline for the selected assets: generate, process, "
                           "spritesheet, validate, export, Godot check, report. This is the normal "
                           "way to produce assets end to end. Slow - allow a generous tool timeout. "
                           "Returns per-stage results and the report totals.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "assets": ASSETS_SCHEMA,
                    "stages": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["generate", "process", "spritesheet", "validate", "export", "godot", "report"]},
                        "description": "Subset of stages to run. Default: all of them.",
                    },
                    "force": {"type": "boolean"},
                    "strict": {"type": "boolean", "description": "Export only outright passes."},
                    "skip_godot": {"type": "boolean"},
                },
            },
        },
    ]


# --------------------------------------------------------------------------- tool implementation

def _stage_argv(args: dict[str, Any], *, quiet: bool = True) -> list[str]:
    argv: list[str] = []
    assets = args.get("assets")
    if assets:
        argv += ["--assets", *[str(a) for a in assets]]
    if args.get("run_id"):
        argv += ["--run-id", str(args["run_id"])]
    if args.get("force"):
        argv.append("--force")
    if quiet:
        argv.append("--quiet")
    return argv


def _run_stage(module_name: str, class_name: str, argv: list[str], extra: Callable[[Any], None] | None = None) -> dict:
    """Import a stage, run it, and return its results dict."""
    import importlib

    module = importlib.import_module(module_name)
    stage_class = getattr(module, class_name)
    stage = stage_class(argv=argv)
    if extra:
        extra(stage)
    return stage.run()


def t_manifest(args: dict[str, Any]) -> dict:
    from lib.common import Config, rel_to_root
    from lib.manifest import load_manifest, validate_manifest

    config = Config.load()
    manifest = load_manifest(None, config)
    problems = validate_manifest(manifest, config)
    jobs = []
    for job in manifest.jobs():
        gen = job.generation_settings()
        jobs.append({
            "run_key": job.run_key,
            "asset_id": job.asset_id,
            "variant": job.variant_suffix,
            "source": job.source,
            "type": job.spec.get("asset_type"),
            "style": job.style_name,
            "size": [gen.get("width"), gen.get("height")],
            "seed": gen.get("seed"),
            "animation": job.animation_settings(),
            "export": job.export_settings().get("target_directory"),
        })
    return {"ok": not problems, "manifest": rel_to_root(manifest.path), "job_count": len(jobs),
            "jobs": jobs, "problems": problems}


def t_styles(args: dict[str, Any]) -> dict:
    from lib.common import Config
    from lib.manifest import load_styles

    config = Config.load()
    styles = load_styles(config)
    return {"count": len(styles), "styles": {
        name: {"generation": spec.get("generation"), "processing": spec.get("processing"),
               "composition": (spec.get("composition") or "")[:400],
               "style": (spec.get("style") or "")[:400],
               "negative": (spec.get("negative") or "")[:300]}
        for name, spec in styles.items()}}


def t_asset_status(args: dict[str, Any]) -> dict:
    from lib.common import AssetRecord, Config
    from lib.manifest import load_manifest

    config = Config.load()
    manifest = load_manifest(None, config)
    wanted = args.get("assets")
    jobs = manifest.jobs(wanted)
    out = []
    for job in jobs:
        rec = AssetRecord.load(job.run_key)
        data = rec.data
        entry: dict[str, Any] = {
            "run_key": job.run_key,
            "source": job.source,
            "status": data.get("status", "pending"),
            "exported_status": data.get("exported_status"),
            "stages_completed": sorted(data.get("stages", {})),
            "retries": data.get("retries") or {},
            "errors": [e.get("error") for e in (data.get("errors") or [])][:3],
        }
        generation = rec.stage("generation")
        for key in ("seed", "clip", "frames", "workflow", "generator", "ortho_scale", "frame_target_z"):
            if generation.get(key) is not None:
                entry[key] = generation[key]
        validation = rec.stage("validation")
        entry["failed_checks"] = validation.get("failed") or []
        entry["review_checks"] = validation.get("review") or []
        if args.get("include_checks"):
            entry["checks"] = validation.get("checks") or []
        if args.get("status") and entry["status"] != args["status"]:
            continue
        out.append(entry)
    totals: dict[str, int] = {}
    for entry in out:
        totals[entry["status"]] = totals.get(entry["status"], 0) + 1
    return {"count": len(out), "totals": totals, "assets": out}


def t_inspect(args: dict[str, Any]) -> dict:
    from lib.common import ROOT, Config, rel_to_root
    from lib.imageops import measure, open_image
    from lib.manifest import load_manifest

    stage = args.get("stage", "processed")
    config = Config.load()
    manifest = load_manifest(None, config)
    out = []
    for job in manifest.jobs(args.get("assets")):
        candidates: list[Path] = []
        if stage == "incoming":
            candidates = list((ROOT / "assets" / "incoming").glob(f"{job.run_key}.*"))
        elif stage == "approved":
            target = ROOT / str(job.export_settings()["target_directory"])
            candidates = list(target.glob(f"{job.run_key}*"))
        else:
            candidates = [ROOT / "assets" / "processed" / f"{job.run_key}.png"]
            frames = ROOT / "assets" / "processed" / job.run_key
            if frames.is_dir():
                candidates = sorted(frames.glob("frame_*.png"))[:1]
        for path in candidates:
            if not path.exists() or path.is_dir():
                continue
            try:
                img = open_image(path)
            except Exception as exc:  # noqa: BLE001
                out.append({"run_key": job.run_key, "file": rel_to_root(path), "error": str(exc)})
                continue
            m = measure(img)
            out.append({
                "run_key": job.run_key,
                "file": rel_to_root(path),
                "bytes": path.stat().st_size,
                "width": m.width, "height": m.height, "mode": m.mode,
                "has_alpha": m.has_alpha,
                "alpha_coverage": round(m.alpha_coverage, 4),
                "subject_bbox": list(m.bbox) if m.bbox else None,
                "touches_border": [k for k, v in m.touches_border.items() if v],
                "rgb_stddev_0_255": m.rgb_stddev,
            })
    return {"stage": stage, "count": len(out), "assets": out}


def t_generate(args: dict[str, Any]) -> dict:
    from lib.common import Config
    from lib.manifest import load_manifest

    # Only run the source that is actually needed: returning an empty result for the other one
    # reads like a failure to an agent that asked for a Blender asset.
    jobs = load_manifest(None, Config.load()).jobs(args.get("assets"))
    sources = {job.source for job in jobs}
    results: dict[str, Any] = {"sources": sorted(sources), "assets": len(jobs)}
    argv = _stage_argv(args)
    if args.get("samples"):
        argv += ["--samples", str(args["samples"])]
    if args.get("size"):
        argv += ["--size", str(args["size"])]
    runners = [("comfyui", "comfyui_generate", "ComfyGenerateStage"),
               ("blender", "blender_generate", "BlenderGenerateStage")]
    for source, module, cls in runners:
        if source not in sources:
            continue
        try:
            results[cls] = _run_stage(module, cls, argv)
        except Exception as exc:  # noqa: BLE001 - one source failing must not hide the other
            results[cls] = {"error": f"{type(exc).__name__}: {exc}"}
    return results


def t_process(args: dict[str, Any]) -> dict:
    argv = _stage_argv(args)
    if args.get("no_background_removal"):
        argv.append("--no-background-removal")
    return _run_stage("process_images", "ProcessStage", argv)


def t_spritesheet(args: dict[str, Any]) -> dict:
    argv = _stage_argv(args)
    if args.get("columns"):
        argv += ["--columns", str(args["columns"])]
    return _run_stage("generate_spritesheet", "SpritesheetStage", argv)


def t_validate(args: dict[str, Any]) -> dict:
    argv = _stage_argv(args)
    if args.get("no_dedupe"):
        argv.append("--no-dedupe")
    return _run_stage("validate_assets", "ValidateStage", argv)


def t_export(args: dict[str, Any]) -> dict:
    argv = _stage_argv(args)
    if args.get("strict"):
        argv.append("--strict")
    return _run_stage("export_assets", "ExportStage", argv)


def t_godot_check(args: dict[str, Any]) -> dict:
    argv = _stage_argv(args)
    if args.get("skip_import"):
        argv.append("--skip-import")
    return _run_stage("godot_check", "GodotCheckStage", argv)


def t_report(args: dict[str, Any]) -> dict:
    from lib.common import ROOT, Config, rel_to_root

    argv = _stage_argv({})
    if args.get("name"):
        argv += ["--out", str(args["name"])]
    payload = _run_stage("build_report", "ReportStage", argv)
    config = Config.load()
    reports = config.path_for("reports")
    names = [p.name for p in sorted(reports.glob("*.md"))] if reports.exists() else []
    return {"totals": payload.get("totals"), "assets": len(payload.get("assets") or []),
            "report_dir": rel_to_root(reports), "reports": names,
            "duplicates": payload.get("duplicates") or [],
            "provenance_gaps": payload.get("provenance_gaps") or []}


def t_run(args: dict[str, Any]) -> dict:
    from lib.common import new_run_id

    run_id = new_run_id()
    stages = args.get("stages") or ["generate", "process", "spritesheet", "validate", "export", "godot", "report"]
    if args.get("skip_godot"):
        stages = [s for s in stages if s != "godot"]
    order = ["generate", "process", "spritesheet", "validate", "export", "godot", "report"]
    stages = [s for s in order if s in stages]

    results: dict[str, Any] = {"run_id": run_id, "stages": {}}
    for stage in stages:
        try:
            if stage == "generate":
                results["stages"][stage] = t_generate({**args, "run_id": run_id})
            elif stage == "process":
                results["stages"][stage] = t_process({**args, "run_id": run_id})
            elif stage == "spritesheet":
                results["stages"][stage] = t_spritesheet({**args, "run_id": run_id})
            elif stage == "validate":
                results["stages"][stage] = t_validate({**args, "run_id": run_id})
            elif stage == "export":
                results["stages"][stage] = t_export({**args, "run_id": run_id})
            elif stage == "godot":
                results["stages"][stage] = t_godot_check({"run_id": run_id})
            elif stage == "report":
                results["stages"][stage] = t_report({"name": run_id})
        except Exception as exc:  # noqa: BLE001 - report which stage died and keep going
            results["stages"][stage] = {"error": f"{type(exc).__name__}: {exc}",
                                        "traceback": traceback.format_exc(limit=4)}
    results["status"] = t_asset_status({})
    return results


def t_env_check_impl(args: dict[str, Any]) -> dict:
    """Resolve every tool and report what is and is not runnable, without failing the call."""
    from lib.common import Config, run_cmd
    from lib.tools import resolve_tools

    config = Config.load()
    tools = resolve_tools(config)
    out: dict[str, Any] = {
        "comfyui_home": str(tools["comfyui_home"]) if tools["comfyui_home"] else None,
        "comfyui_python": tools["comfyui_python"],
        "blender": str(tools["blender"]) if tools["blender"] else None,
        "godot": tools["godot"],
        "problems": tools["problems"],
    }
    if tools["blender"] and not args.get("skip_smoke"):
        try:
            from lib.blender import headless_render_check

            out["blender_render"] = headless_render_check(config)
        except Exception as exc:  # noqa: BLE001
            out["blender_render"] = {"ok": False, "error": str(exc)}
    if tools["godot"]:
        try:
            proc = run_cmd([str(tools["godot"]), "--version"], timeout=60)
            out["godot_version"] = (proc.stdout or "").strip()
        except Exception as exc:  # noqa: BLE001
            out["godot_version"] = f"error: {exc}"
    if tools["comfyui_home"]:
        from lib.comfy import ComfyClient

        client = ComfyClient(config)
        out["comfyui_url"] = client.url
        if args.get("start_comfyui", True):
            try:
                client.ensure_server()
                stats = client.system_stats()
                out["comfyui_version"] = stats.get("system", {}).get("comfyui_version")
                out["comfyui_running"] = True
            except Exception as exc:  # noqa: BLE001
                out["comfyui_running"] = False
                out["comfyui_error"] = str(exc)
    out["ok"] = not out["problems"]
    return out


TOOLS: dict[str, Callable[[dict[str, Any]], dict]] = {
    "artworkflow_env_check": t_env_check_impl,
    "artworkflow_manifest": t_manifest,
    "artworkflow_styles": t_styles,
    "artworkflow_asset_status": t_asset_status,
    "artworkflow_inspect": t_inspect,
    "artworkflow_generate": t_generate,
    "artworkflow_process": t_process,
    "artworkflow_spritesheet": t_spritesheet,
    "artworkflow_validate": t_validate,
    "artworkflow_export": t_export,
    "artworkflow_godot_check": t_godot_check,
    "artworkflow_report": t_report,
    "artworkflow_run": t_run,
}


# --------------------------------------------------------------------------- protocol

def _write(message: dict[str, Any]) -> None:
    PROTOCOL_OUT.write(json.dumps(message))
    PROTOCOL_OUT.write("\n")
    PROTOCOL_OUT.flush()


def _result(request_id: Any, result: dict[str, Any]) -> None:
    _write({"jsonrpc": "2.0", "id": request_id, "result": result})


def _error(request_id: Any, code: int, message: str, data: Any = None) -> None:
    payload: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        payload["data"] = data
    _write({"jsonrpc": "2.0", "id": request_id, "error": payload})


def _tool_result(request_id: Any, payload: dict[str, Any], *, is_error: bool = False) -> None:
    text = json.dumps(payload, indent=2, default=str)
    _result(request_id, {"content": [{"type": "text", "text": text}], "isError": is_error})


def handle(request: dict[str, Any]) -> None:
    method = request.get("method")
    request_id = request.get("id")
    params = request.get("params") or {}

    if method == "initialize":
        requested = str(params.get("protocolVersion") or "")
        _result(request_id, {
            "protocolVersion": requested if requested in SUPPORTED_PROTOCOLS else DEFAULT_PROTOCOL,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": (
                "Local game-art pipeline: ComfyUI/FLUX for painted assets, Blender for procedural "
                "buildings, props, upgrade tiers and animation, then cutout, validation, export and "
                "a headless Godot import check. Start with artworkflow_env_check or "
                "artworkflow_manifest; produce assets with artworkflow_run. Generation is slow "
                "(seconds to minutes) - allow a generous tool timeout. Statuses are honest: "
                "review_required means a human should look, and it is not a pass."
            ),
        })
    elif method in ("notifications/initialized", "initialized"):
        pass  # notification, no response
    elif method == "ping":
        _result(request_id, {})
    elif method == "tools/list":
        _result(request_id, {"tools": tool_specs()})
    elif method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        handler = TOOLS.get(name)
        if handler is None:
            _tool_result(request_id, {"error": f"unknown tool {name!r}", "available": sorted(TOOLS)},
                         is_error=True)
            return
        try:
            # stdout is the transport: silence stage chatter for the duration of the call.
            with contextlib.redirect_stdout(sys.stderr):
                payload = handler(arguments)
            _tool_result(request_id, payload)
        except Exception as exc:  # noqa: BLE001 - a failing tool is data, not a protocol error
            _tool_result(request_id, {"error": f"{type(exc).__name__}: {exc}",
                                      "traceback": traceback.format_exc(limit=8)}, is_error=True)
    elif method is None:
        pass
    else:
        if request_id is not None:
            _error(request_id, -32601, f"method not found: {method}")


def main() -> int:
    os.chdir(REPO_ROOT)
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            request = json.loads(raw)
        except json.JSONDecodeError:
            _error(None, -32700, "parse error")
            continue
        if isinstance(request, list):
            for item in request:
                handle(item)
        else:
            handle(request)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
