"""Shared plumbing: config, path safety, run logging, asset records, subprocess.

Every stage script imports from here so that paths, logging and record handling
behave identically no matter which entry point is used.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = ROOT / "config" / "pipeline.yaml"
DEFAULT_MANIFEST_PATH = ROOT / "config" / "manifest.json"

# Statuses recorded per asset. Ordered by pipeline progress.
STATUS_PENDING = "pending"
STATUS_GENERATED = "generated"
STATUS_PROCESSED = "processed"
STATUS_PASSED = "passed"
STATUS_REVIEW = "review_required"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"
STATUS_EXPORTED = "exported"

EXPORTABLE = (STATUS_PASSED, STATUS_REVIEW, STATUS_EXPORTED)
"""Statuses an asset may be exported from. STATUS_EXPORTED is included so re-running the
export stage is idempotent instead of refusing to re-copy what it already copied."""


class PipelineError(RuntimeError):
    """Any pipeline-level failure that should surface as a clean CLI error."""


class ConfigError(PipelineError):
    pass


class PathSafetyError(PipelineError):
    """Raised when a manifest or config tries to write outside the project."""


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_run_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def resolve_path(value: str | os.PathLike[str]) -> Path:
    """Expand ~ and env vars; relative paths resolve against the project root."""
    p = Path(os.path.expandvars(str(value))).expanduser()
    return p if p.is_absolute() else (ROOT / p)


def ensure_inside_project(path: str | os.PathLike[str], *, what: str = "path") -> Path:
    """Resolve a path and refuse anything that escapes the project directory."""
    resolved = resolve_path(path).resolve()
    if resolved != ROOT and ROOT not in resolved.parents:
        raise PathSafetyError(f"{what} {path!r} resolves outside the project ({resolved}); refusing")
    return resolved


def rel_to_root(path: str | os.PathLike[str] | None) -> str | None:
    """Project-relative path for records and reports.

    Records are committed as provenance, so they have to be portable: an absolute
    An absolute home path in a record is noise on another machine and leaks a username into
    a public repository.
    """
    if path is None:
        return None
    try:
        resolved = resolve_path(path).resolve()
        return str(resolved.relative_to(ROOT))
    except (ValueError, OSError):
        return str(path)


def atomic_write_bytes(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as fh:
        fh.write(data)
        tmp = Path(fh.name)
    tmp.replace(path)
    return path


def atomic_write_json(path: Path, payload: Any) -> Path:
    return atomic_write_bytes(path, json.dumps(payload, indent=2, sort_keys=False).encode() + b"\n")


def read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursive merge: dicts merge key-wise, everything else is replaced by the override."""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


class Config:
    """Dot-path access over pipeline.yaml with a few typed conveniences."""

    def __init__(self, data: Mapping[str, Any], path: Path):
        self.data = dict(data)
        self.path = path

    @classmethod
    def load(cls, path: str | os.PathLike[str] | None = None) -> "Config":
        import yaml

        cfg_path = resolve_path(path or os.environ.get("ARTWORKFLOW_CONFIG") or DEFAULT_CONFIG_PATH)
        if not cfg_path.exists():
            raise ConfigError(f"config not found: {cfg_path}")
        with open(cfg_path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if not isinstance(data, dict):
            raise ConfigError(f"config must be a mapping: {cfg_path}")
        # Machine-specific overrides live beside the tracked config, untracked. This is what
        # keeps absolute tool paths out of the repository.
        for local in (cfg_path.with_name(f"{cfg_path.stem}.local{cfg_path.suffix}"),
                      ROOT / "config" / "pipeline.local.yaml"):
            if local.exists() and local != cfg_path:
                with open(local, "r", encoding="utf-8") as fh:
                    override = yaml.safe_load(fh) or {}
                if isinstance(override, dict):
                    data = _deep_merge(data, override)
        return cls(data, cfg_path)

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, Mapping) or part not in node:
                return default
            node = node[part]
        return node

    def path_for(self, key: str) -> Path:
        """Resolve a key under `paths:` to an absolute path inside the project."""
        rel = self.get(f"paths.{key}")
        if not rel:
            raise ConfigError(f"paths.{key} is not set in {self.path}")
        return ensure_inside_project(rel, what=f"paths.{key}")


class RunLog:
    """JSONL event log plus a human-readable transcript for one pipeline run."""

    def __init__(self, run_id: str, log_root: Path, *, echo: bool = True):
        self.run_id = run_id
        self.dir = log_root / run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.jsonl = self.dir / "events.jsonl"
        self.echo = echo
        self._events: list[dict[str, Any]] = []

    def log(self, event: str, *, stage: str = "-", asset: str | None = None,
            level: str = "info", msg: str = "", **fields: Any) -> dict[str, Any]:
        entry = {"ts": now_iso(), "run_id": self.run_id, "stage": stage, "level": level,
                 "event": event, "asset": asset, "msg": msg}
        entry.update({k: v for k, v in fields.items() if v is not None})
        self._events.append(entry)
        with open(self.jsonl, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
        if self.echo:
            tag = f"[{stage}]" if stage != "-" else ""
            who = f" {asset}" if asset else ""
            print(f"{level.upper():5s} {tag}{who} {msg or event}", flush=True)
        return entry

    def info(self, msg: str, **kw: Any) -> None:
        self.log("info", level="info", msg=msg, **kw)

    def warn(self, msg: str, **kw: Any) -> None:
        self.log("warning", level="warn", msg=msg, **kw)

    def error(self, msg: str, **kw: Any) -> None:
        self.log("error", level="error", msg=msg, **kw)

    @property
    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    def stage_file(self, name: str) -> Path:
        return self.dir / f"{name}.log"


def run_cmd(argv: Iterable[str], *, cwd: Path | None = None, timeout: float | None = None,
            log_path: Path | None = None, log: RunLog | None = None,
            stage: str = "cmd", env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run a subprocess, tee its output to a log file, and raise on failure."""
    argv = [str(a) for a in argv]
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    merged_env = dict(os.environ)
    if env:
        merged_env.update({k: str(v) for k, v in env.items()})
    try:
        proc = subprocess.run(argv, cwd=str(cwd) if cwd else None, timeout=timeout,
                              capture_output=True, text=True, env=merged_env)
    except FileNotFoundError as exc:
        raise PipelineError(f"command not found: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise PipelineError(f"command timed out after {timeout}s: {' '.join(argv[:3])} ...") from exc

    if log_path is not None:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(f"\n$ {' '.join(argv)}\n")
            fh.write(f"# exit={proc.returncode}\n")
            fh.write(proc.stdout or "")
            if proc.stderr:
                fh.write("\n--- stderr ---\n" + proc.stderr)
    if log is not None:
        log.log("subprocess", stage=stage, msg=f"{Path(argv[0]).name} exit={proc.returncode}",
                argv=argv[:6], returncode=proc.returncode)
    return proc


@dataclass
class AssetRecord:
    """Durable per-asset state, stored as metadata/asset_records/<key>.json."""

    run_key: str
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def path(self) -> Path:
        return ROOT / "metadata" / "asset_records" / f"{self.run_key}.json"

    @classmethod
    def load(cls, run_key: str) -> "AssetRecord":
        path = ROOT / "metadata" / "asset_records" / f"{run_key}.json"
        if path.exists():
            return cls(run_key, read_json(path))
        return cls(run_key, {"asset_id": run_key.split("__")[0], "run_key": run_key,
                             "status": STATUS_PENDING, "stages": {}, "errors": [], "retries": {}})

    def stage(self, name: str) -> dict[str, Any]:
        return self.data.setdefault("stages", {}).setdefault(name, {})

    def complete_stage(self, name: str, **fields: Any) -> None:
        st = self.stage(name)
        st.update(fields)
        st["completed_at"] = now_iso()
        st.setdefault("attempts", 0)
        st["attempts"] = int(st.get("attempts", 0)) + 1

    def fail_stage(self, name: str, error: str, **fields: Any) -> None:
        st = self.stage(name)
        st.setdefault("attempts", 0)
        st["attempts"] = int(st.get("attempts", 0)) + 1
        st["failed_at"] = now_iso()
        st.setdefault("errors", []).append(error[:2000])
        st.update(fields)
        self.data.setdefault("errors", []).append({"stage": name, "error": error[:2000], "ts": now_iso()})

    def set_status(self, status: str, **fields: Any) -> None:
        self.data["status"] = status
        self.data["status_at"] = now_iso()
        self.data.update({k: v for k, v in fields.items() if v is not None})

    def bump_retry(self, stage: str) -> int:
        r = self.data.setdefault("retries", {})
        r[stage] = int(r.get(stage, 0)) + 1
        return r[stage]

    def save(self) -> Path:
        self.data["updated_at"] = now_iso()
        return atomic_write_json(self.path, self.data)


def fail(msg: str, code: int = 2) -> "NoReturn":  # type: ignore[valid-type]
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)
