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
SCENE_LIB = ROOT / "blender" / "lib" / "scene.py"


def palette_names() -> set[str]:
    """Material names declared in blender/lib/scene.py.

    Read with `ast` instead of importing: scene.py imports bpy, so only Blender can import it.
    Having the names here lets manifest validation reject a typo like `obsidan` at validation
    time, instead of the render silently falling back to grey and the art direction quietly
    going wrong.
    """
    import ast

    if not SCENE_LIB.exists():
        return set()
    tree = ast.parse(SCENE_LIB.read_text())
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == "PALETTE":
            return set(ast.literal_eval(node.value).keys())
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == "PALETTE" for t in node.targets
        ):
            return set(ast.literal_eval(node.value).keys())
    return set()


def emissive_palette_entries() -> dict[str, dict[str, Any]]:
    import ast

    tree = ast.parse(SCENE_LIB.read_text())
    palette: dict[str, dict[str, Any]] = {}
    for node in tree.body:
        target = getattr(node, "target", None) or (node.targets[0] if getattr(node, "targets", None) else None)
        if getattr(target, "id", None) == "PALETTE":
            palette = ast.literal_eval(node.value)
    return {name: spec for name, spec in palette.items() if spec.get("emission")}


def camera_moving_clips() -> set[str]:
    """Clip names that move the camera, read from blender/lib/anim_clips.py.

    Same reasoning as `palette_names`: the clip registry lives in a Blender-only module, so the
    pipeline reads the literal it needs rather than importing bpy.
    """
    import ast

    path = ROOT / "blender" / "lib" / "anim_clips.py"
    if not path.exists():
        return set()
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == "CAMERA_MOVING_CLIPS":
            return set(ast.literal_eval(node.value))
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == "CAMERA_MOVING_CLIPS" for t in node.targets
        ):
            return set(ast.literal_eval(node.value))
    return set()


class BlenderError(PipelineError):
    pass


def blender_binary(config: Config) -> Path:
    from .tools import find_blender

    path = find_blender(config.get("blender.binary") or None)
    if not path:
        raise BlenderError("Blender not found. Set blender.binary in config/pipeline.local.yaml "
                           "(or the BLENDER_BIN environment variable), or put blender on PATH.")
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
