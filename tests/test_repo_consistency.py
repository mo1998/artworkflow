"""Repository consistency checks.

These guard the seams *between* files: a clip renamed in Blender but still named in the manifest,
a config key typo that silently returns a default, a doc link pointing at a file that moved, an
undeclared dependency, a tool key that only exists in the manifest. Each one has broken something
in this repo or would break a contributor's change silently.

All of it runs without a GPU, ComfyUI, Blender or Godot.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import os
import subprocess
import sys
import sysconfig
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "scripts" / "lib")]

STAGE_SCRIPTS_EXCLUDED = {
    "env_check.py",       # a diagnostic, not a pipeline stage
    "run_pipeline.py",    # the runner itself
    "make_gallery.py",    # documentation tooling
    "make_branding.py",   # documentation tooling
    "remove_background.py",  # a library used by process_images, with a single-file CLI
    "check.py",           # the contributor convenience wrapper
}
def stdlib_names() -> set[str]:
    """Standard library module names, on any supported interpreter.

    `sys.stdlib_module_names` only exists from 3.10, and this project supports 3.9 - relying on it
    silently made every stdlib import look like a third-party one on 3.9 while passing on 3.11.
    The filesystem fallback is accurate for whichever interpreter is running.
    """
    names = set(getattr(sys, "stdlib_module_names", ()))
    # Builtins are compiled into the interpreter and have no file in the stdlib directory, so the
    # filesystem fallback below would miss sys, os, math and friends without this.
    names |= set(sys.builtin_module_names)
    if getattr(sys, "stdlib_module_names", None):
        return names
    stdlib = sysconfig.get_paths().get("stdlib")
    if not stdlib or not os.path.isdir(stdlib):
        return names
    for entry in os.listdir(stdlib):
        path = Path(stdlib) / entry
        if entry.endswith(".py"):
            names.add(entry[:-3])
        elif path.is_dir() and (path / "__init__.py").exists():
            names.add(entry)
    return names


STDLIB = stdlib_names()


def is_stdlib(name: str) -> bool:
    """Whether an import resolves to the standard library.

    Resolving beats name-matching: `math` is a compiled extension in lib-dynload on some builds
    and a builtin on others, and the earlier filesystem-only scan called it third-party here while
    passing on another interpreter.
    """
    if name in STDLIB:
        return True
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError):
        return False
    origin = getattr(spec, "origin", None) or ""
    if not origin or origin in ("built-in", "frozen"):
        return True
    parts = Path(origin).parts
    # Ask whether the module lives in an install directory, rather than subtracting this
    # interpreter's site-packages: with a venv created --system-site-packages the two differ, and
    # every third-party module then looks like it came from the standard library.
    if "site-packages" in parts or "dist-packages" in parts:
        return False
    stdlib = sysconfig.get_paths().get("stdlib") or ""
    return origin.startswith(stdlib) if stdlib else False


LOCAL_MODULES = {"lib", "scene", "anim_clips", "generate_building", "generate_prop",
                 "remove_background", "comfyui_generate", "blender_generate", "process_images",
                 "generate_spritesheet", "validate_assets", "export_assets", "godot_check",
                 "build_report", "run_pipeline", "env_check", "make_gallery", "check"}


def tracked_files() -> list[Path]:
    """Files under version control, so generated output is not policed."""
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    return [ROOT / line for line in out.stdout.splitlines() if line.strip()]


def python_files(*roots: str) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        files += sorted((ROOT / root).rglob("*.py"))
    return [f for f in files if "__pycache__" not in f.parts]


# --------------------------------------------------------------------------- dependencies

class TestDependencies(unittest.TestCase):
    """An undeclared import is a broken clone for everyone else."""

    def _third_party_imports(self, files: list[Path]) -> dict[str, set[str]]:
        found: dict[str, set[str]] = {}
        for path in files:
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module.split(".")[0]]
                for name in names:
                    if is_stdlib(name) or name in LOCAL_MODULES or name.startswith("lib"):
                        continue
                    found.setdefault(name, set()).add(str(path.relative_to(ROOT)))
        return found

    def test_every_pipeline_import_is_declared(self):
        import env_check

        declared = set(env_check.REQUIRED_MODULES) | set(env_check.OPTIONAL_MODULES)
        used = self._third_party_imports(python_files("scripts", "blender", "mcp_server"))
        undeclared = {name: sorted(where) for name, where in used.items() if name not in declared}
        self.assertEqual(undeclared, {},
                         "undeclared third-party import(s): add them to REQUIRED_MODULES or "
                         "OPTIONAL_MODULES in scripts/env_check.py and to the install docs")

    def test_required_modules_are_actually_imported(self):
        """The reverse: a required dependency nothing uses is dead weight in the install docs."""
        import env_check

        used = set(self._third_party_imports(python_files("scripts", "blender", "mcp_server")))
        declared = set(env_check.REQUIRED_MODULES)
        self.assertTrue(declared <= used,
                        f"required but never imported: {sorted(declared - used)}")

    def test_mcp_server_stays_stdlib_only(self):
        """The server is documented as dependency-free, so it must import nothing at all outside
        the standard library - not even the pipeline's own requirements."""
        used = self._third_party_imports([ROOT / "mcp_server" / "server.py"])
        self.assertEqual(set(used), set(),
                         f"MCP server must stay dependency-free; it imports {sorted(used)}")


# --------------------------------------------------------------------------- tracked files

class TestTrackedFileHygiene(unittest.TestCase):
    """What must never land in a public repository, checked instead of trusted."""

    HOME_PATH = re.compile(r"/(?:home|Users)/[A-Za-z0-9_.-]{2,}/")
    SECRET = re.compile(
        r"(?:ghp_|gho_|ghu_|github_pat_|sk-[A-Za-z0-9]{10,}|AKIA[0-9A-Z]{16}"
        r"|BEGIN [A-Z ]*PRIVATE KEY"
        r"|(?:password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)\s*[:=]\s*[\"'][^\"']{8,})"
    )
    MAX_BYTES = 3 * 1024 * 1024
    # This module necessarily contains the patterns it searches for, so it scans itself out.
    # Everything else in the repo is fair game, including other tests and the docs.
    SCANNER = Path(__file__).resolve()

    def setUp(self):
        self.files = tracked_files()
        if not self.files:
            self.skipTest("not a git working tree")

    def _scan(self, pattern: re.Pattern) -> list[str]:
        hits = []
        for path in self.files:
            if not path.is_file() or path.resolve() == self.SCANNER:
                continue
            try:
                text = path.read_text(errors="ignore")
            except OSError:
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    hits.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()[:100]}")
        return hits

    def test_no_absolute_home_paths(self):
        """Records and config must stay portable; a committed /home/<user>/ path leaks a layout."""
        hits = self._scan(self.HOME_PATH)
        self.assertEqual(hits, [], "absolute home paths in tracked files:\n" + "\n".join(hits))

    def test_no_credentials(self):
        hits = self._scan(self.SECRET)
        self.assertEqual(hits, [], "credential-shaped strings in tracked files:\n" + "\n".join(hits))

    def test_no_oversized_files(self):
        big = [(str(p.relative_to(ROOT)), p.stat().st_size) for p in self.files
               if p.is_file() and p.stat().st_size > self.MAX_BYTES]
        self.assertEqual(big, [], f"tracked files over {self.MAX_BYTES // 1024 // 1024}MB: {big}")

    def test_generated_output_is_not_tracked(self):
        """assets/ and logs/ are reproducible; committing them bloats the repo forever."""
        offenders = [str(p.relative_to(ROOT)) for p in self.files
                     if p.parts[len(ROOT.parts)] in {"logs"}]
        self.assertEqual(offenders, [])

    def test_no_python_caches_tracked(self):
        offenders = [str(p.relative_to(ROOT)) for p in self.files
                     if "__pycache__" in p.parts or p.suffix == ".pyc"]
        self.assertEqual(offenders, [])


# --------------------------------------------------------------------------- manifest

class TestManifestIntegrity(unittest.TestCase):
    """Cross-file agreements the manifest depends on."""

    @classmethod
    def setUpClass(cls):
        from lib.common import Config
        from lib.manifest import load_manifest

        cls.config = Config.load()
        cls.manifest = load_manifest(None, cls.config)

    def test_referenced_clips_exist_in_the_registry(self):
        """A clip renamed in Blender and not in the manifest used to fail at render time, minutes in."""
        registry = self._clip_names()
        for job in self.manifest.jobs():
            anim = job.animation_settings()
            if anim:
                self.assertIn(anim["clip"], registry, f"{job.run_key}: unknown clip {anim['clip']!r}")

    def _clip_names(self) -> set[str]:
        tree = ast.parse((ROOT / "blender" / "lib" / "anim_clips.py").read_text())
        for node in ast.walk(tree):
            target = getattr(node, "target", None) or (
                node.targets[0] if getattr(node, "targets", None) else None)
            if getattr(target, "id", None) == "CLIPS":
                return {key.value for key in node.value.keys}
        return set()

    def test_animation_assets_do_not_trim_frames(self):
        """Per-frame trimming breaks frame registration; the clip loops would jitter."""
        for job in self.manifest.jobs():
            if job.animation_settings():
                steps = job.processing_settings()
                self.assertFalse(steps.get("trim"), f"{job.run_key}: trim must be off for sequences")
                self.assertIsNone(steps.get("resize"),
                                  f"{job.run_key}: resize must be null for sequences")

    def test_spritesheet_names_are_unique(self):
        """Two sheets with the same name overwrite each other in assets/spritesheets/."""
        names = {}
        for job in self.manifest.jobs():
            if not job.animation_settings():
                continue
            export = job.export_settings()
            name = str((export.get("spritesheet") or {}).get("name") or job.run_key)
            self.assertNotIn(name, names, f"{job.run_key} and {names.get(name)} both export {name!r}")
            names[name] = job.run_key

    def test_comfyui_assets_name_a_prompt_and_blender_assets_name_params(self):
        for job in self.manifest.jobs():
            if job.source == "comfyui":
                self.assertTrue(job.spec.get("prompt"), f"{job.run_key}: comfyui asset needs a prompt")
                self.assertTrue((job.spec.get("generation") or {}).get("workflow"),
                                f"{job.run_key}: comfyui asset needs a workflow")
            else:
                self.assertTrue(job.spec.get("blender", {}).get("params") is not None,
                                f"{job.run_key}: blender asset needs params")

    def test_committed_records_match_the_manifest(self):
        """A record for an asset that no longer exists, or missing for one that does, means the
        committed provenance no longer describes the repo."""
        records = {p.stem for p in (ROOT / "metadata" / "asset_records").glob("*.json")}
        if not records:
            self.skipTest("no committed records")
        expected = {job.run_key for job in self.manifest.jobs()}
        self.assertEqual(records ^ expected, set(),
                         f"records and manifest disagree; only in records: "
                         f"{sorted(records - expected)}, only in manifest: {sorted(expected - records)}")


# --------------------------------------------------------------------------- workflows

class TestWorkflows(unittest.TestCase):
    """The binding map is the pipeline's contract with a ComfyUI graph."""

    def setUp(self):
        from lib.comfy import load_workflow

        self.workflows = [(p, load_workflow(p)) for p in sorted((ROOT / "workflows" / "comfyui").glob("*.json"))]
        self.assertTrue(self.workflows, "no workflows found")

    def test_metadata_is_complete(self):
        for path, workflow in self.workflows:
            self.assertTrue(workflow.name, f"{path.name}: missing meta.name")
            self.assertTrue(workflow.meta.get("version"), f"{path.name}: missing meta.version")
            self.assertIn("requires", workflow.meta, f"{path.name}: missing meta.requires")

    def test_bindings_point_at_real_nodes_and_inputs(self):
        for path, workflow in self.workflows:
            for key, binding in workflow.bindings.items():
                node_id = str(binding["node"])
                self.assertIn(node_id, workflow.graph,
                              f"{path.name}: binding {key!r} points at missing node {node_id}")
                inputs = workflow.graph[node_id].get("inputs", {})
                self.assertIn(binding["input"], inputs,
                              f"{path.name}: binding {key!r} targets {binding['input']!r}, "
                              f"which node {node_id} does not have (has {sorted(inputs)})")

    def test_output_node_exists_and_is_a_save_node(self):
        for path, workflow in self.workflows:
            self.assertIsNotNone(workflow.output_node, f"{path.name}: no output_node")
            self.assertIn(workflow.output_node, workflow.graph,
                          f"{path.name}: output_node {workflow.output_node} not in the graph")
            class_type = workflow.graph[workflow.output_node]["class_type"]
            self.assertIn("Save", class_type, f"{path.name}: output node is {class_type}, not a Save node")

    def test_declared_checkpoint_is_the_one_the_graph_loads(self):
        """`requires.checkpoint` is what env_check looks for on disk; it must match the graph."""
        for path, workflow in self.workflows:
            declared = workflow.requires.get("checkpoint")
            if not declared:
                continue
            loaders = [node for node in workflow.graph.values()
                       if node.get("class_type") in ("CheckpointLoaderSimple", "CheckpointLoader")]
            self.assertTrue(loaders, f"{path.name}: declares a checkpoint but loads none")
            loaded = {node["inputs"].get("ckpt_name") for node in loaders}
            self.assertIn(declared, loaded, f"{path.name}: declares {declared!r}, graph loads {loaded}")

    def test_custom_nodes_declared_and_named(self):
        """A custom node pack must be declared so env_check can verify it is installed."""
        for path, workflow in self.workflows:
            packs = workflow.requires.get("custom_nodes") or []
            classes = {node.get("class_type") for node in workflow.graph.values()}
            if any(name and "BiRefNet" in str(name) for name in classes):
                self.assertTrue(packs, f"{path.name}: uses custom nodes but declares none")

    def test_filename_prefix_is_bindable(self):
        """The prefix is how an output is matched back to its asset; it cannot be hardcoded."""
        for path, workflow in self.workflows:
            self.assertIn("filename_prefix", workflow.bindings,
                          f"{path.name}: filename_prefix must be bindable per asset")


# --------------------------------------------------------------------------- config

class TestConfigKeys(unittest.TestCase):
    """A typo'd config key silently returns the default, so nothing fails and nothing works."""

    def _keys_read_in_code(self) -> dict[str, set[str]]:
        keys: dict[str, set[str]] = {}
        for path in python_files("scripts", "blender", "mcp_server"):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr in ("get", "path_for") and node.args):
                    arg = node.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        keys.setdefault(arg.value, set()).add(str(path.relative_to(ROOT)))
        return keys

    def test_every_literal_config_key_exists(self):
        from lib.common import Config

        config = Config.load()
        problems = []
        for key, where in self._keys_read_in_code().items():
            if "." not in key:
                continue  # plain mapping lookups like args.get("force")
            if config.get(key, "__missing__") == "__missing__" and not key.startswith("paths."):
                problems.append(f"{key!r} read in {sorted(where)} is not in {config.path.name}")
        self.assertEqual(problems, [], "config keys read but not defined:\n" + "\n".join(problems))

    def test_paths_section_covers_what_the_stages_ask_for(self):
        from lib.common import Config

        config = Config.load()
        for key, where in self._keys_read_in_code().items():
            if key.startswith("paths."):
                self.assertIsNotNone(config.get(key), f"{key!r} read in {sorted(where)} is unset")

    def test_validation_thresholds_are_numeric(self):
        from lib.common import Config

        config = Config.load()
        for section in ("validation", "review", "retry", "concurrency"):
            for key, value in (config.get(section) or {}).items():
                if isinstance(value, dict):
                    for sub, sub_value in value.items():
                        self.assertIsInstance(sub_value, (int, float),
                                              f"{section}.{key}.{sub} should be numeric")
                else:
                    self.assertIsInstance(value, (int, float), f"{section}.{key} should be numeric")


# --------------------------------------------------------------------------- wiring

class TestPipelineWiring(unittest.TestCase):
    """The stages, the runner and the MCP server have to agree on what the stages are."""

    def _stage_scripts(self) -> list[Path]:
        return [p for p in sorted((ROOT / "scripts").glob("*.py"))
                if p.name not in STAGE_SCRIPTS_EXCLUDED]

    def test_runner_knows_every_stage_script(self):
        import run_pipeline

        wired = {script for commands in run_pipeline.STAGE_PLAN.values() for script in commands for script in script}
        scripts = {p.name for p in self._stage_scripts()}
        self.assertEqual(scripts - wired, set(), "stage script missing from STAGE_PLAN")
        self.assertEqual(wired - scripts, set(), "STAGE_PLAN references a script that does not exist")

    def test_every_stage_script_is_executable_on_its_own(self):
        for path in self._stage_scripts():
            text = path.read_text()
            self.assertIn('__name__ == "__main__"', text, f"{path.name} has no main guard")

    def test_every_stage_script_defines_a_stage_subclass(self):
        import importlib

        from lib.stage import Stage

        for path in self._stage_scripts():
            module = importlib.import_module(path.stem)
            classes = [value for value in vars(module).values()
                       if isinstance(value, type) and issubclass(value, Stage) and value is not Stage]
            self.assertTrue(classes, f"{path.name} defines no Stage subclass")

    def test_stage_dependencies_use_the_shared_library(self):
        """A stage that reimplements path resolution or logging drifts from every other stage."""
        import run_pipeline

        for commands in run_pipeline.STAGE_PLAN.values():
            for command in commands:
                text = (ROOT / "scripts" / command[0]).read_text()
                self.assertIn("from lib.", text, f"{command[0]} does not import from lib/")

    def test_mcp_tool_names_match_the_cli_stages(self):
        """Every stage the CLI exposes should be reachable through MCP too."""
        import run_pipeline

        server = (ROOT / "mcp_server" / "server.py").read_text()
        for stage in run_pipeline.STAGE_ORDER:
            self.assertIn(f"artworkflow_{stage}", server, f"MCP has no tool for stage {stage!r}")


# --------------------------------------------------------------------------- docs

class TestDocs(unittest.TestCase):
    """Docs that point at nothing are worse than no docs: they cost a contributor time."""

    LINK = re.compile(r"\]\(([^)\s]+)\)")

    def test_readme_relative_links_resolve(self):
        readme = (ROOT / "README.md").read_text()
        missing = []
        for target in self.LINK.findall(readme):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            path = (ROOT / target.split("#")[0]).resolve()
            if not path.exists():
                missing.append(target)
        self.assertEqual(missing, [], f"README links to missing paths: {missing}")

    def test_reference_docs_are_linked_from_the_skill(self):
        skill = (ROOT / "skills" / "artworkflow" / "SKILL.md").read_text()
        for path in sorted((ROOT / "skills" / "artworkflow" / "references").glob("*.md")):
            self.assertIn(path.name, skill, f"{path.name} is not linked from SKILL.md")

    def test_skill_frontmatter_is_valid(self):
        import yaml

        text = (ROOT / "skills" / "artworkflow" / "SKILL.md").read_text()
        self.assertTrue(text.startswith("---\n"), "SKILL.md must open with YAML frontmatter")
        block = text.split("---", 2)[1]
        meta = yaml.safe_load(block)
        self.assertEqual(meta.get("name"), "artworkflow", "skill name must match its directory")
        description = str(meta.get("description") or "")
        self.assertGreater(len(description), 60, "description must say when the skill applies")
        self.assertLessEqual(len(description), 1024, "skill descriptions are capped at 1024 characters")
        self.assertNotIn("\t", block, "frontmatter must not contain tabs")

    def test_docs_do_not_advertise_unused_dependencies(self):
        """The install line must match what the pipeline actually imports."""
        import env_check

        readme = (ROOT / "README.md").read_text()
        install_lines = [line for line in readme.splitlines() if "pip install" in line]
        self.assertTrue(install_lines, "README should document how to install the pipeline")
        for line in install_lines:
            for package in ("opencv", "requests", "scipy"):
                self.assertNotIn(package, line,
                                 f"README asks for {package}, which nothing imports")


if __name__ == "__main__":
    unittest.main()
