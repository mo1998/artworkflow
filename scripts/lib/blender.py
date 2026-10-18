"""Invoke Blender in background mode and read back its JSON summary.

Blender is driven only through `blender -b --factory-startup --python <script> -- <args>`,
which keeps renders reproducible: no user preferences, no add-ons, no UI state.
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any, Mapping, Sequence

from .common import Config, PipelineError, ROOT, resolve_path, run_cmd

SUMMARY_MARKER = "ARTWORKFLOW_JSON"


class BlenderError(PipelineError):
    pass


def blender_binary(config: Config) -> Path:
    raw = config.get("blender.binary")
    if not raw:
        raise BlenderError("blender.binary is not configured")
    path = resolve_path(raw)
    if not path.exists():
        raise BlenderError(f"Blender not found at {path}; set blender.binary in config/pipeline.yaml")
    return path


def run_blender_script(config: Config, script: str | Path, args: Mapping[str, Any] | Sequence[str],
                       *, log: Any = None, stage: str = "blender", timeout: float | None = None,
                       log_path: Path | None = None) -> dict[str, Any]:
    """Run a Blender python script; return its parsed ARTWORKFLOW_JSON summary."""
    binary = blender_binary(config)
    script_path = resolve_path(script) if not isinstance(script, Path) or not script.is_absolute() else script
    if not script_path.is_absolute():
        script_path = ROOT / str(script)
    if not script_path.exists():
        raise BlenderError(f"blender script not found: {script_path}")

    if isinstance(args, Mapping):
        argv_args = [part for key, value in args.items() for part in _flatten_arg(key, value)]
    else:
        argv_args = [str(a) for a in args]

    argv = [str(binary), "-b", "--factory-startup", "--python", str(script_path), "--", *argv_args]
    if log:
        log.log("blender", stage=stage, msg=f"blender {script_path.name} {shlex.join(argv_args[:8])}",
                argv=argv)
    proc = run_cmd(argv, timeout=timeout, log_path=log_path, log=log, stage=stage)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-2500:]
        raise BlenderError(f"blender exited {proc.returncode} for {script_path.name}: {tail}")
    return parse_summary(proc.stdout)


def _flatten_arg(key: str, value: Any) -> list[str]:
    flag = "--" + key.replace("_", "-")
    if value is None:
        return []
    if isinstance(value, bool):
        return [flag, "true" if value else "false"]
    if isinstance(value, (dict, list)):
        return [flag, json.dumps(value)]
    return [flag, str(value)]


def parse_summary(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        if SUMMARY_MARKER in line:
            payload = line.split(SUMMARY_MARKER, 1)[1].strip()
            try:
                return json.loads(payload)
            except json.JSONDecodeError as exc:
                raise BlenderError(f"could not parse Blender summary: {payload[:400]}") from exc
    return {}


def headless_render_check(config: Config, *, log: Any = None) -> dict[str, Any]:
    """Render a tiny frame to prove Blender can render headlessly on this machine."""
    expr_script = ROOT / "blender" / "lib" / "smoke_render.py"
    return run_blender_script(config, expr_script, {}, log=log, stage="blender-smoke", timeout=240)
