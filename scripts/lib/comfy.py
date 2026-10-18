"""ComfyUI HTTP client + workflow binding engine.

The pipeline never drives ComfyUI's UI. It loads an API-format workflow from
`workflows/comfyui/*.json`, injects per-asset parameters through the workflow's own
binding map, POSTs it to /prompt, waits for /history and pulls the result off /view.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from .common import Config, PipelineError, ROOT, atomic_write_bytes, resolve_path


class ComfyError(PipelineError):
    pass


class Workflow:
    """An API-format graph plus the binding map that says where parameters go."""

    def __init__(self, path: Path, graph: dict[str, Any], meta: dict[str, Any]):
        self.path = path
        self.graph = graph
        self.meta = meta

    @property
    def name(self) -> str:
        return self.meta.get("name") or self.path.stem

    @property
    def bindings(self) -> dict[str, dict[str, Any]]:
        return self.meta.get("bindings") or {}

    @property
    def output_node(self) -> str | None:
        return self.meta.get("output_node")

    @property
    def requires(self) -> dict[str, Any]:
        return self.meta.get("requires") or {}

    def apply(self, values: Mapping[str, Any]) -> dict[str, Any]:
        """Return a copy of the graph with bound node inputs replaced."""
        graph = json.loads(json.dumps(self.graph))
        bound = set()
        for key, value in values.items():
            if value is None:
                continue
            binding = self.bindings.get(key)
            if not binding:
                continue
            node_id, input_name = str(binding["node"]), binding["input"]
            if node_id not in graph:
                raise ComfyError(f"{self.name}: binding {key!r} points at missing node {node_id}")
            graph[node_id].setdefault("inputs", {})[input_name] = value
            bound.add(key)
        self._require_bound_output(graph)
        return graph

    def _require_bound_output(self, graph: dict[str, Any]) -> None:
        if self.output_node and self.output_node not in graph:
            raise ComfyError(f"{self.name}: output_node {self.output_node} missing from graph")

    def unbindable(self, values: Mapping[str, Any]) -> list[str]:
        return sorted(k for k, v in values.items() if v is not None and k not in self.bindings)


def load_workflow(path: str | Path) -> Workflow:
    wf_path = resolve_path(path)
    if not wf_path.exists():
        raise ComfyError(f"workflow not found: {wf_path}")
    with open(wf_path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    meta = raw.pop("_artworkflow", {}) if isinstance(raw, dict) else {}
    return Workflow(wf_path, raw, meta)


class ComfyClient:
    """Minimal ComfyUI API client with an optional server autostart."""

    def __init__(self, config: Config, *, log: Any = None):
        self.config = config
        self.url = str(config.get("comfyui.url", "http://127.0.0.1:8188")).rstrip("/")
        home = config.get("comfyui.home")
        self.home = resolve_path(home) if home else None
        self.timeout = float(config.get("comfyui.job_timeout_seconds", 900))
        self.poll = float(config.get("comfyui.poll_interval_seconds", 2))
        self.log = log

    # ---- HTTP ---------------------------------------------------------------
    def _get(self, path: str, timeout: float = 20.0) -> bytes:
        req = urllib.request.Request(self.url + path)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()

    def _post(self, path: str, payload: Mapping[str, Any], timeout: float = 60.0) -> dict[str, Any]:
        req = urllib.request.Request(
            self.url + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            raise ComfyError(f"ComfyUI {path} -> HTTP {exc.code}: {body[:1200]}") from exc

    def is_up(self) -> bool:
        try:
            self._get("/system_stats", timeout=5)
            return True
        except Exception:
            return False

    def system_stats(self) -> dict[str, Any]:
        return json.loads(self._get("/system_stats"))

    def object_info(self, node_class: str | None = None) -> dict[str, Any]:
        return json.loads(self._get(f"/object_info/{node_class}" if node_class else "/object_info", timeout=60))

    # ---- server lifecycle ---------------------------------------------------
    def ensure_server(self) -> bool:
        """Return True if the API is reachable, starting the server when configured."""
        if self.is_up():
            if self.log:
                self.log.info(f"ComfyUI already running at {self.url}", stage="comfyui")
            return True
        if not bool(self.config.get("comfyui.autostart", True)):
            raise ComfyError(f"ComfyUI is not reachable at {self.url} and autostart is disabled")
        return self.start_server()

    def start_server(self) -> bool:
        if not self.home or not (self.home / "main.py").exists():
            raise ComfyError(f"comfyui.home does not look like a ComfyUI checkout: {self.home}")
        python = self.config.get("comfyui.python") or "python3"
        log_dir = resolve_path(self.config.get("paths.logs", "logs"))
        log_dir.mkdir(parents=True, exist_ok=True)
        server_log = log_dir / "comfyui-server.log"
        extra = [str(a) for a in (self.config.get("comfyui.extra_args") or [])]
        argv = [str(python), "main.py", "--listen", "127.0.0.1", "--port",
                str(urllib.parse.urlsplit(self.url).port or 8188), *extra]
        if self.log:
            self.log.info(f"starting ComfyUI: {' '.join(argv)}", stage="comfyui")
        with open(server_log, "ab") as fh:
            fh.write(f"\n$ {' '.join(argv)}\n".encode())
            fh.flush()
            subprocess.Popen(argv, cwd=str(self.home), stdout=fh, stderr=subprocess.STDOUT,
                             start_new_session=True)
        deadline = time.time() + float(self.config.get("comfyui.startup_timeout_seconds", 420))
        while time.time() < deadline:
            if self.is_up():
                if self.log:
                    self.log.info(f"ComfyUI is up ({self.url})", stage="comfyui")
                return True
            time.sleep(3)
        raise ComfyError(f"ComfyUI did not come up within the startup timeout; see {server_log}")

    # ---- job execution ------------------------------------------------------
    def submit(self, graph: Mapping[str, Any]) -> str:
        payload = self._post("/prompt", {"prompt": graph})
        prompt_id = payload.get("prompt_id")
        if not prompt_id:
            raise ComfyError(f"ComfyUI rejected the prompt: {json.dumps(payload)[:1500]}")
        return str(prompt_id)

    def wait(self, prompt_id: str, *, timeout: float | None = None) -> dict[str, Any]:
        deadline = time.time() + float(timeout or self.timeout)
        while time.time() < deadline:
            try:
                history = json.loads(self._get(f"/history/{prompt_id}"))
            except Exception:
                time.sleep(self.poll)
                continue
            if prompt_id in history:
                entry = history[prompt_id]
                status = entry.get("status") or {}
                if status.get("status_str") == "error" or status.get("completed") is False and status.get("status_str") == "error":
                    raise ComfyError(_format_execution_error(entry))
                return entry
            time.sleep(self.poll)
        raise ComfyError(f"job {prompt_id} did not finish within {timeout or self.timeout}s")

    def first_image(self, history_entry: Mapping[str, Any]) -> dict[str, Any]:
        outputs = history_entry.get("outputs") or {}
        for out in outputs.values():
            for img in out.get("images", []) or []:
                if img.get("type") != "temp":
                    return img
        for out in outputs.values():
            for img in out.get("images", []) or []:
                return img
        raise ComfyError("job produced no images")

    def fetch_image(self, image: Mapping[str, Any]) -> bytes:
        query = urllib.parse.urlencode({
            "filename": image.get("filename", ""),
            "subfolder": image.get("subfolder", ""),
            "type": image.get("type", "output"),
        })
        return self._get(f"/view?{query}", timeout=120)

    def fetch_to(self, image: Mapping[str, Any], dest: Path) -> Path:
        data = self.fetch_image(image)
        if not data:
            raise ComfyError("ComfyUI returned an empty image")
        atomic_write_bytes(dest, data)
        return dest

    def upload_image(self, path: Path, *, subfolder: str = "", overwrite: bool = True) -> str:
        """Stage a local file into ComfyUI's input/ so LoadImage can read it."""
        if not path.exists():
            raise ComfyError(f"cannot upload missing file: {path}")
        boundary = "----artworkflow-boundary"
        parts: list[bytes] = []
        for name, value in (("subfolder", subfolder), ("overwrite", "true" if overwrite else "false"),
                            ("type", "input")):
            if value is None:
                continue
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n".encode()
        )
        parts.append(path.read_bytes())
        parts.append(f"\r\n--{boundary}--\r\n".encode())
        body = b"".join(parts)
        req = urllib.request.Request(
            self.url + "/upload/image", data=body, method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                     "Content-Length": str(len(body))},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read() or b"{}")
        name = payload.get("name") or path.name
        sub = payload.get("subfolder") or ""
        return f"{sub}/{name}".lstrip("/")

    def run_workflow(self, workflow: Workflow, values: Mapping[str, Any],
                     dest: Path, *, timeout: float | None = None) -> dict[str, Any]:
        """Submit a bound workflow and save its first image to `dest`."""
        graph = workflow.apply(values)
        prompt_id = self.submit(graph)
        entry = self.wait(prompt_id, timeout=timeout)
        image = self.first_image(entry)
        self.fetch_to(image, dest)
        return {"prompt_id": prompt_id, "image": image, "dest": str(dest),
                "workflow": str(workflow.path), "workflow_name": workflow.name}


def _format_execution_error(entry: Mapping[str, Any]) -> str:
    status = entry.get("status") or {}
    messages = status.get("messages") or []
    flat = []
    for item in messages:
        if isinstance(item, (list, tuple)) and len(item) == 2 and item[0] in ("execution_error", "execution_interrupted"):
            detail = item[1] or {}
            if isinstance(detail, Mapping):
                flat.append(f"{detail.get('node_type')} #{detail.get('node_id')}: "
                            f"{detail.get('exception_type')}: {str(detail.get('exception_message'))[:400]}")
                traceback = detail.get("traceback")
                if traceback:
                    flat.append("".join(traceback)[-600:])
    if not flat:
        flat.append(json.dumps(status)[:1200])
    return "ComfyUI execution error -> " + " | ".join(flat)


def check_workflow_requirements(workflow: Workflow, config: Config, log: Any = None,
                                object_info: Mapping[str, Any] | None = None) -> list[str]:
    """Best-effort preflight: are the checkpoint and custom nodes actually installed?"""
    problems: list[str] = []
    requires = workflow.requires
    home = resolve_path(config.get("comfyui.home", "")) if config.get("comfyui.home") else None

    ckpt = requires.get("checkpoint")
    if ckpt and home:
        ckpt_dir = home / "models" / "checkpoints"
        if ckpt_dir.exists() and not (ckpt_dir / ckpt).exists():
            problems.append(f"checkpoint {ckpt!r} not found in {ckpt_dir}")
    for node_pack in requires.get("custom_nodes") or []:
        if home and not (home / "custom_nodes" / node_pack).exists():
            problems.append(f"custom node pack {node_pack!r} not found in {home / 'custom_nodes'}")

    if object_info:
        for node_class in _graph_node_classes(workflow):
            if node_class not in object_info:
                problems.append(f"ComfyUI has no node class {node_class!r} (missing custom node pack?)")
    return problems


def _graph_node_classes(workflow: Workflow) -> list[str]:
    seen: list[str] = []
    for node in workflow.graph.values():
        if isinstance(node, Mapping) and node.get("class_type"):
            if node["class_type"] not in seen:
                seen.append(node["class_type"])
    return seen
