"""Manifest loading, validation, and job expansion.

The manifest is the single source of truth for what the pipeline should produce.
Everything else (prompts, workflow parameters, processing steps, export targets)
is derived from it plus the style block it names.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .common import (DEFAULT_MANIFEST_PATH, ROOT, Config, ConfigError, PipelineError,
                     ensure_inside_project, read_json, resolve_path)
SOURCE_TYPES = ("comfyui", "blender")

REQUIRED_ASSET_FIELDS = ("asset_id", "asset_type", "description", "source", "export")

# Fields that must be present for a given generation source.
REQUIRED_BY_SOURCE = {
    "comfyui": ("style", "prompt"),
    "blender": ("blender",),
}

PROVENANCE_FIELDS = ("model",)


class ManifestError(PipelineError):
    pass


@dataclass
class Job:
    """One concrete renderable unit: an asset, or one of its variants."""

    asset_id: str
    variant_suffix: str | None
    spec: dict[str, Any]
    style: dict[str, Any]
    style_name: str
    source: str

    @property
    def run_key(self) -> str:
        return self.asset_id if not self.variant_suffix else f"{self.asset_id}__{self.variant_suffix}"

    @property
    def is_variant(self) -> bool:
        return self.variant_suffix is not None

    # ---- prompt composition -------------------------------------------------
    def compose_prompt(self) -> str:
        if self.source == "blender":
            return self.spec.get("prompt") or f"procedural {self.spec.get('asset_type', 'asset')}"
        subject = (self.spec.get("prompt") or "").strip().rstrip(".")
        append = (self.spec.get("prompt_append") or "").strip().rstrip(".")
        if append:
            subject = f"{subject}, {append}"
        parts = [subject, self.style.get("composition", "").strip(), self.style.get("style", "").strip()]
        return ". ".join(p.strip().rstrip(".") for p in parts if p and p.strip()) + "."

    def compose_negative(self) -> str:
        explicit = (self.spec.get("negative_prompt") or "").strip()
        base = (self.style.get("negative") or "").strip()
        if explicit and base:
            return f"{explicit}, {base}"
        return explicit or base

    # ---- generation settings ------------------------------------------------
    def generation_settings(self) -> dict[str, Any]:
        """Merge style generation defaults under the asset's own settings.

        Seed resolution: generation.seed (an explicit per-asset or per-variant override) wins,
        then the asset's top-level `seed`, then 0. Getting this wrong is how two assets end up
        silently rendering the same image, so it is resolved in one place only.
        """
        merged = dict(self.style.get("generation") or {})
        merged.update({k: v for k, v in (self.spec.get("generation") or {}).items() if v is not None})
        if merged.get("seed") is None and self.spec.get("seed") is not None:
            merged["seed"] = int(self.spec["seed"])
        merged.setdefault("width", 1024)
        merged.setdefault("height", 1024)
        merged.setdefault("steps", 24)
        merged.setdefault("seed", 0)
        return merged

    def processing_settings(self) -> dict[str, Any]:
        merged = dict(self.style.get("processing") or {})
        merged.update({k: v for k, v in (self.spec.get("processing") or {}).items() if v is not None})
        merged.setdefault("remove_background", False)
        merged.setdefault("trim", False)
        merged.setdefault("padding", 0)
        merged.setdefault("resize", None)
        merged.setdefault("anchor", "center")
        return merged

    def animation_settings(self) -> dict[str, Any] | None:
        anim = self.spec.get("animation") or {}
        if not anim.get("enabled"):
            return None
        merged = {"clip": "banner_wave", "frame_count": 12, "frame_rate": 12, "loop": True}
        merged.update({k: v for k, v in anim.items() if v is not None})
        if int(merged["frame_count"]) < 2:
            raise ManifestError(f"{self.run_key}: animation.frame_count must be >= 2")
        return merged

    def output_dir(self, config: Config, stage: str) -> Path:
        return config.path_for(stage)

    def export_settings(self) -> dict[str, Any]:
        exp = dict(self.spec.get("export") or {})
        exp.setdefault("format", "png")
        if not exp.get("target_directory"):
            raise ManifestError(f"{self.run_key}: export.target_directory is required")
        return exp

    def provenance(self) -> dict[str, Any]:
        prov = dict(self.spec.get("provenance") or {})
        gen = self.generation_settings()
        prov.setdefault("model", "unknown")
        prov["width"] = gen.get("width")
        prov["height"] = gen.get("height")
        prov["steps"] = gen.get("steps")
        prov["seed"] = gen.get("seed")
        prov["prompt"] = self.compose_prompt()
        prov["negative_prompt"] = self.compose_negative()
        prov["style"] = self.style_name
        if self.source == "comfyui":
            wf = (self.spec.get("generation") or {}).get("workflow")
            prov["workflow"] = wf
            prov["workflow_sha256"] = workflow_digest(wf) if wf else None
        return {k: v for k, v in prov.items() if v is not None}


def workflow_digest(rel_path: str | None) -> str | None:
    if not rel_path:
        return None
    path = resolve_path(rel_path)
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


@dataclass
class Manifest:
    path: Path
    data: dict[str, Any]
    styles: dict[str, Any]
    assets: list[dict[str, Any]] = field(default_factory=list)

    @property
    def schema_version(self) -> int:
        return int(self.data.get("schema_version", 0))

    def by_id(self, asset_id: str) -> dict[str, Any]:
        for a in self.assets:
            if a["asset_id"] == asset_id:
                return a
        raise ManifestError(f"unknown asset_id {asset_id!r}")

    def jobs(self, only: Iterable[str] | None = None) -> list[Job]:
        """Expand assets (and their variants) into concrete jobs."""
        wanted = set(only) if only else None
        out: list[Job] = []
        for asset in self.assets:
            asset_id = asset["asset_id"]
            variants = asset.get("variants") or []
            keys = {asset_id} | {f"{asset_id}__{v.get('suffix', '')}" for v in variants}
            if wanted and not (keys & wanted):
                continue
            if not wanted or asset_id in wanted or not variants:
                out.append(self._job(asset, None))
            for variant in variants:
                suffix = variant.get("suffix")
                job_key = f"{asset_id}__{suffix}"
                if wanted and job_key not in wanted and asset_id not in wanted:
                    continue
                out.append(self._job(asset, variant))
        return out

    def _job(self, asset: dict[str, Any], variant: Mapping[str, Any] | None) -> Job:
        spec = json.loads(json.dumps(asset))  # deep copy, keeps the manifest on disk pristine
        suffix = None
        if variant is not None:
            suffix = variant.get("suffix")
            if not suffix:
                raise ManifestError(f"{asset['asset_id']}: variant is missing a 'suffix'")
            # Variant overrides replace this asset's own settings, they do not merge
            # field-by-field with them, except for blender params which merge.
            for key in ("prompt", "prompt_append", "negative_prompt", "seed", "processing",
                        "generation", "export", "provenance"):
                if key in variant and variant[key] is not None:
                    spec[key] = variant[key]
            if "seed" in variant and variant["seed"] is not None:
                spec.setdefault("generation", {})["seed"] = variant["seed"]
            if variant.get("blender_params"):
                spec.setdefault("blender", {}).setdefault("params", {}).update(variant["blender_params"])
        style_name = spec.get("style") or DEFAULT_STYLE
        if spec["source"] == "blender" and not spec.get("style"):
            style_name = spec.get("style", "blender-procedural-v1")
        style = self.styles.get(style_name) if style_name in self.styles else {}
        return Job(asset_id=asset["asset_id"], variant_suffix=suffix, spec=spec,
                   style=style, style_name=style_name, source=spec["source"])

    def run_plan(self, only: Iterable[str] | None = None) -> list[str]:
        return [j.run_key for j in self.jobs(only)]

    def family_run_keys(self, asset_id: str) -> list[str]:
        """The base asset plus every variant run key, in manifest order.

        Used by the processing stage to scale an upgrade-tier family by one shared factor
        instead of normalising each tier to fill its own canvas, which would make a level-3
        building the same on-screen size as a level-1.
        """
        asset = self.by_id(asset_id)
        keys = [asset_id]
        for variant in asset.get("variants") or []:
            suffix = variant.get("suffix")
            if suffix:
                keys.append(f"{asset_id}__{suffix}")
        return keys


DEFAULT_STYLE = "dark-fantasy-isometric-v1"


def load_styles(config: Config) -> dict[str, Any]:
    import yaml

    path = resolve_path(config.get("styles_file", "config/styles.yaml"))
    if not path.exists():
        raise ManifestError(f"styles file not found: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data.get("styles", {})


def load_manifest(path: str | Path | None = None, config: Config | None = None) -> Manifest:
    mpath = ensure_inside_project(path or DEFAULT_MANIFEST_PATH, what="manifest")
    if not mpath.exists():
        raise ManifestError(f"manifest not found: {mpath}")
    data = read_json(mpath)
    styles = load_styles(config) if config else load_styles(Config.load())
    manifest = Manifest(path=mpath, data=data, styles=styles,
                        assets=list(data.get("assets") or []))
    return manifest


def validate_manifest(manifest: Manifest, config: Config) -> list[str]:
    """Return a list of problems; an empty list means the manifest is runnable."""
    problems: list[str] = []
    if manifest.schema_version < 1:
        problems.append("schema_version must be >= 1")
    if not manifest.assets:
        problems.append("manifest contains no assets")

    seen: dict[str, int] = {}
    for i, asset in enumerate(manifest.assets):
        where = f"assets[{i}]"
        for field_name in REQUIRED_ASSET_FIELDS:
            if not asset.get(field_name):
                problems.append(f"{where}: missing required field {field_name!r}")
        asset_id = asset.get("asset_id")
        if not asset_id:
            continue
        where = f"assets[{asset_id}]"
        seen[asset_id] = seen.get(asset_id, 0) + 1
        source = asset.get("source")
        if source not in SOURCE_TYPES:
            problems.append(f"{where}: source must be one of {SOURCE_TYPES}, got {source!r}")
            continue
        for field_name in REQUIRED_BY_SOURCE.get(source, ()):
            if not asset.get(field_name):
                problems.append(f"{where}: source {source!r} requires field {field_name!r}")
        if source == "comfyui":
            style = asset.get("style")
            if style and style not in manifest.styles:
                problems.append(f"{where}: unknown style {style!r}; "
                                f"known: {sorted(manifest.styles)}")
            workflow = (asset.get("generation") or {}).get("workflow")
            if not workflow:
                problems.append(f"{where}: comfyui asset needs generation.workflow")
            elif not resolve_path(workflow).exists():
                problems.append(f"{where}: workflow file not found: {workflow}")
        if source == "blender":
            generator = (asset.get("blender") or {}).get("generator")
            if not generator:
                problems.append(f"{where}: blender.generator is required")
            else:
                gen_path = ROOT / "blender" / generator
                if not gen_path.exists():
                    problems.append(f"{where}: blender generator not found: blender/{generator}")
            # Material names are a cross-language contract: they are declared in scene.py and
            # referenced by string from the manifest. A typo would otherwise render a whole
            # asset in the fallback colour, so it is caught here instead.
            from .blender import palette_names

            known = palette_names()
            if known:
                params = (asset.get("blender") or {}).get("params") or {}
                for key, value in params.items():
                    if key.endswith("_material") and isinstance(value, str) and value not in known:
                        problems.append(f"{where}: unknown material {value!r} for blender param "
                                        f"{key!r}; known: {sorted(known)}")
        prov = asset.get("provenance") or {}
        for field_name in PROVENANCE_FIELDS:
            if not prov.get(field_name):
                problems.append(f"{where}: provenance.{field_name} is required")

        export = asset.get("export") or {}
        target = export.get("target_directory")
        if target:
            try:
                ensure_inside_project(target, what=f"{where} export.target_directory")
            except Exception as exc:  # PathSafetyError and friends
                problems.append(f"{where}: {exc}")

        seed = (asset.get("generation") or {}).get("seed", asset.get("seed"))
        if source == "comfyui" and seed is None:
            problems.append(f"{where}: comfyui asset should pin a seed for reproducibility")

        for v_i, variant in enumerate(asset.get("variants") or []):
            if not variant.get("suffix"):
                problems.append(f"{where}: variants[{v_i}] is missing 'suffix'")

        anim = asset.get("animation") or {}
        if anim.get("enabled"):
            if int(anim.get("frame_count") or 0) < 2:
                problems.append(f"{where}: animation.frame_count must be >= 2")
            if not anim.get("frame_rate"):
                problems.append(f"{where}: animation.frame_rate is required when animation is enabled")

    for asset_id, count in seen.items():
        if count > 1:
            problems.append(f"duplicate asset_id {asset_id!r} ({count} entries)")

    # duplicate run keys (svg-variants collapsing to the same suffix)
    keys: dict[str, int] = {}
    try:
        for job in manifest.jobs():
            keys[job.run_key] = keys.get(job.run_key, 0) + 1
    except ManifestError as exc:
        problems.append(str(exc))
    for key, count in keys.items():
        if count > 1:
            problems.append(f"duplicate run_key {key!r} ({count} jobs); variants need unique suffixes")

    return problems


def check_paths(config: Config) -> None:
    """Fail early if any configured path would escape the project."""
    for key in ("incoming", "processed", "animations", "spritesheets", "approved", "records", "logs", "reports"):
        if config.get(f"paths.{key}"):
            config.path_for(key)
