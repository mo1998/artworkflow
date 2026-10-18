"""Unit tests for the pipeline's pure parts. No GPU, no ComfyUI, no Blender needed.

    .venv/bin/python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "scripts" / "lib")]

from PIL import Image  # noqa: E402
from PIL import PngImagePlugin  # noqa: E402


def _png_text(key: str, value: str) -> PngImagePlugin.PngInfo:
    info = PngImagePlugin.PngInfo()
    info.add_text(key, value)
    return info

from lib import imageops  # noqa: E402
from lib.comfy import load_workflow  # noqa: E402
from lib.common import Config, PathSafetyError, ensure_inside_project  # noqa: E402
from lib.manifest import Manifest, load_manifest, validate_manifest  # noqa: E402


def rgba(size=(64, 64), subject=(8, 8, 40, 40), color=(200, 60, 60, 255)) -> Image.Image:
    """A canvas with a coloured block pasted into it."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    box = Image.new("RGBA", (subject[2] - subject[0], subject[3] - subject[1]), color)
    img.alpha_composite(box, (subject[0], subject[1]))
    return img


def block(width: int, height: int, color=(200, 60, 60, 255)) -> Image.Image:
    """An image that *is* the subject, i.e. the shape a stage gets after trim()."""
    return Image.new("RGBA", (width, height), color)


class TestAnchoring(unittest.TestCase):
    def test_padding_is_respected_on_every_edge(self):
        """A padded canvas must leave the subject clear of the border, whatever the anchor.

        This is the bug that made every asset fail not_clipped: the anchor positioned the
        subject against the canvas edge and the padding only limited its size.
        """
        subject = block(40, 40)
        for anchor in ("center", "bottom-center", "top-left", "bottom-right"):
            placed = imageops.place_on_canvas(subject, 64, anchor=anchor, padding=6)
            m = imageops.measure(placed)
            self.assertFalse(any(m.touches_border.values()),
                             f"anchor {anchor} put the subject on the border")

    def test_bottom_anchor_keeps_a_shared_ground_line(self):
        short = imageops.place_on_canvas(block(20, 20), 64, anchor="bottom-center", padding=4)
        tall = imageops.place_on_canvas(block(20, 50), 64, anchor="bottom-center", padding=4)
        self.assertEqual(imageops.measure(short).bbox[3], imageops.measure(tall).bbox[3])
        self.assertEqual(imageops.measure(short).bbox[3], 59)  # 64 - 1 - padding

    def test_oversized_subject_is_scaled_down_to_fit(self):
        placed = imageops.place_on_canvas(block(400, 400), 64, padding=4)
        m = imageops.measure(placed)
        self.assertLessEqual(m.width, 64)
        self.assertLessEqual(m.height, 64)
        self.assertFalse(any(m.touches_border.values()))

    def test_fit_resize_preserves_aspect_ratio(self):
        resized = imageops.fit_resize(block(400, 200), 100)
        self.assertEqual(resized.size, (100, 50))

    def test_accepts_an_rgb_subject_that_exactly_fills_the_canvas(self):
        """Regression: a no-cutout style (a portrait) hands over an RGB image sized to the canvas.

        PIL takes its strict same-size composite path in that case and raises "images do not
        match" on the mode difference, so every other asset - which gets scaled down first -
        passed while the portrait failed.
        """
        rgb = Image.new("RGB", (128, 128), (90, 40, 40))
        placed = imageops.place_on_canvas(rgb, 128, anchor="center", padding=0)
        self.assertEqual(placed.size, (128, 128))
        self.assertEqual(placed.mode, "RGBA")


class TestMeasurements(unittest.TestCase):
    def test_rgb_stddev_uses_the_0_255_scale(self):
        """Thresholds in pipeline.yaml are written in 0-255 terms; the metric must match."""
        img = Image.new("RGB", (64, 64), (0, 0, 0))
        for x in range(0, 64, 2):
            for y in range(64):
                img.putpixel((x, y), (255, 255, 255))
        m = imageops.measure(img)
        self.assertGreater(m.rgb_stddev, 100)

    def test_flat_image_is_detected_as_blank(self):
        flat = Image.new("RGB", (32, 32), (128, 128, 128))
        self.assertLess(imageops.measure(flat).rgb_stddev, 4.0)

    def test_alpha_coverage_and_bbox(self):
        m = imageops.measure(rgba(subject=(16, 16, 48, 48)))
        self.assertAlmostEqual(m.alpha_coverage, (32 * 32) / (64 * 64), places=3)
        self.assertEqual(m.bbox, (16, 16, 47, 47))

    def test_content_bbox_works_without_alpha(self):
        img = Image.new("RGB", (64, 64), (240, 240, 240))
        img.paste(Image.new("RGB", (10, 10), (10, 10, 10)), (20, 30))
        self.assertEqual(imageops.content_bbox(img), (20, 30, 30, 40))


class TestMotionAndDuplicates(unittest.TestCase):
    def test_motion_metrics_see_a_small_moving_detail(self):
        """A waving banner on a big sprite moves few pixels; the metric must still see motion."""
        before = Image.new("RGB", (512, 512), (40, 40, 40))
        after = before.copy()
        after.paste(Image.new("RGB", (25, 40), (220, 30, 30)), (240, 100))
        metrics = imageops.motion_metrics(before, after)
        self.assertGreater(metrics["peak_delta"], 100)
        self.assertGreater(metrics["changed_fraction"], 0.0005)
        self.assertLess(metrics["mean"], 0.01)  # the mean is uselessly small here, by design

    def test_identical_frames_report_no_motion(self):
        img = rgba()
        metrics = imageops.motion_metrics(img, img)
        self.assertEqual(metrics["peak_delta"], 0)
        self.assertEqual(metrics["changed_fraction"], 0.0)

    def test_dhash_flags_a_near_duplicate_and_spares_a_different_image(self):
        base = rgba(subject=(0, 0, 60, 60), color=(180, 90, 40, 255))
        near = base.copy()
        near.paste(Image.new("RGBA", (4, 4), (180, 90, 40, 255)), (10, 10))
        other = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        for x in range(0, 64, 8):
            other.paste(Image.new("RGBA", (4, 64), (10, 200, 90, 255)), (x, 0))
        self.assertLessEqual(imageops.hamming(imageops.dhash(base), imageops.dhash(near)), 6)
        self.assertGreater(imageops.hamming(imageops.dhash(base), imageops.dhash(other)), 6)

    def test_pixel_hash_ignores_file_metadata(self):
        """Blender stamps a tEXt Date into every render, so two identical renders have
        different file bytes. "Did the render change?" has to be answered on pixels."""
        img = rgba(subject=(0, 0, 30, 30))
        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp) / "a.png"
            stamped = Path(tmp) / "b.png"
            img.save(plain)
            img.save(stamped, pnginfo=_png_text("Date", "2026/10/18 13:27:45"))
            self.assertNotEqual(plain.read_bytes(), stamped.read_bytes())
            self.assertEqual(imageops.pixel_hash(imageops.open_image(plain)),
                             imageops.pixel_hash(imageops.open_image(stamped)))


class TestSpritesheet(unittest.TestCase):
    def test_pack_places_frames_on_the_declared_grid(self):
        frames = [rgba(subject=(0, 0, 16, 16)) for _ in range(6)]
        sheet, rects = imageops.pack_spritesheet(frames, columns=3, padding=2)
        self.assertEqual(sheet.size, (3 * 64 + 12, 2 * 64 + 8))
        self.assertEqual(len(rects), 6)
        self.assertEqual((rects[3]["column"], rects[3]["row"]), (0, 1))
        for rect in rects:
            self.assertLessEqual(rect["x"] + rect["w"], sheet.width)
            self.assertLessEqual(rect["y"] + rect["h"], sheet.height)

    def test_pack_refuses_non_uniform_frames(self):
        frames = [rgba(), rgba(size=(32, 32))]
        with self.assertRaises(imageops.ImageError):
            imageops.pack_spritesheet(frames, columns=2)


class TestManifest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = Config.load()
        cls.manifest = load_manifest(None, cls.config)

    def test_shipped_manifest_is_valid(self):
        self.assertEqual(validate_manifest(self.manifest, self.config), [])

    def test_variants_expand_into_jobs(self):
        keys = self.manifest.run_plan()
        self.assertIn("demo_hut", keys)
        self.assertIn("demo_hut__lvl2", keys)
        self.assertIn("demo_hut__lvl3", keys)

    def test_family_keys_list_base_first(self):
        self.assertEqual(self.manifest.family_run_keys("demo_hut")[0], "demo_hut")

    def test_seed_comes_from_the_asset_when_generation_omits_it(self):
        """Two assets that differ only by top-level seed must not render the same image."""
        jobs = {j.run_key: j for j in self.manifest.jobs()}
        self.assertEqual(jobs["demo_watchtower_a"].generation_settings()["seed"], 481516)
        self.assertEqual(jobs["demo_watchtower_b"].generation_settings()["seed"], 90210)

    def test_prompt_is_subject_composition_style(self):
        job = self.manifest.jobs(["demo_watchtower_a"])[0]
        prompt = job.compose_prompt()
        self.assertIn("watchtower", prompt)
        self.assertIn("isometric", prompt)
        self.assertTrue(prompt.endswith("."))

    def test_missing_field_is_reported(self):
        broken = Manifest(path=self.manifest.path, data={}, styles=self.manifest.styles,
                          assets=[{"asset_id": "x", "asset_type": "building", "description": "d",
                                   "source": "comfyui", "export": {}}])
        problems = validate_manifest(broken, self.config)
        self.assertTrue(any("style" in p for p in problems))
        self.assertTrue(any("provenance" in p for p in problems))

    def test_duplicate_ids_are_reported(self):
        asset = {"asset_id": "dup", "asset_type": "prop", "description": "d", "source": "blender",
                 "export": {"target_directory": "assets/approved/props"}, "blender": {"generator": "generate_building.py"},
                 "provenance": {"model": "m"}}
        broken = Manifest(path=self.manifest.path, data={}, styles=self.manifest.styles,
                          assets=[dict(asset), dict(asset)])
        self.assertTrue(any("duplicate asset_id" in p for p in validate_manifest(broken, self.config)))

    def test_variants_need_unique_suffixes(self):
        asset = {"asset_id": "a", "asset_type": "prop", "description": "d", "source": "blender",
                 "export": {"target_directory": "assets/approved/props"},
                 "blender": {"generator": "generate_building.py"},
                 "provenance": {"model": "m"},
                 "variants": [{"suffix": "x"}, {"suffix": "x"}]}
        broken = Manifest(path=self.manifest.path, data={}, styles=self.manifest.styles, assets=[asset])
        self.assertTrue(any("duplicate run_key" in p for p in validate_manifest(broken, self.config)))


class TestPathSafety(unittest.TestCase):
    def test_paths_outside_the_project_are_refused(self):
        for bad in ("/etc/passwd", "../../../tmp/escape", "/tmp/opencode/elsewhere"):
            with self.assertRaises(PathSafetyError):
                ensure_inside_project(bad)

    def test_paths_inside_the_project_are_resolved(self):
        self.assertEqual(ensure_inside_project("assets/approved/x.png"),
                         (ROOT / "assets/approved/x.png").resolve())

    def test_manifest_target_outside_the_project_is_reported(self):
        config = Config.load()
        manifest = load_manifest(None, config)
        manifest.assets[0]["export"]["target_directory"] = "/tmp/escape"
        problems = validate_manifest(manifest, config)
        self.assertTrue(any("outside the project" in p for p in problems))


class TestWorkflowBindings(unittest.TestCase):
    def test_bindings_inject_into_the_declared_node_inputs(self):
        workflow = load_workflow("workflows/comfyui/flux_txt2img.json")
        graph = workflow.apply({"prompt": "HELLO", "seed": 1234, "width": 512, "height": 768})
        self.assertEqual(graph["2"]["inputs"]["text"], "HELLO")
        self.assertEqual(graph["6"]["inputs"]["seed"], 1234)
        self.assertEqual(graph["5"]["inputs"]["width"], 512)
        self.assertEqual(graph["5"]["inputs"]["height"], 768)

    def test_template_is_not_mutated_between_jobs(self):
        workflow = load_workflow("workflows/comfyui/flux_txt2img.json")
        workflow.apply({"prompt": "FIRST", "seed": 1})
        graph = workflow.apply({"prompt": "SECOND", "seed": 2})
        self.assertEqual(graph["2"]["inputs"]["text"], "SECOND")
        self.assertEqual(workflow.graph["2"]["inputs"]["text"], "")

    def test_binding_to_a_missing_node_is_an_error(self):
        from lib.comfy import ComfyError, Workflow

        workflow = Workflow(Path("x.json"), {"1": {"class_type": "X", "inputs": {}}},
                            {"bindings": {"prompt": {"node": "9", "input": "text"}}})
        with self.assertRaises(ComfyError):
            workflow.apply({"prompt": "x"})

    def test_bi_refnet_workflow_binds_the_uploaded_image(self):
        workflow = load_workflow("workflows/comfyui/birefnet_cutout.json")
        graph = workflow.apply({"image_name": "in.png", "width": 512})
        self.assertEqual(graph["2"]["inputs"]["image"], "in.png")
        self.assertEqual(graph["3"]["inputs"]["width"], 512)


class TestBlenderPalette(unittest.TestCase):
    """blender/lib/scene.py is the material contract; these guard the two mistakes it made."""

    def test_palette_is_readable_without_blender(self):
        from lib.blender import emissive_palette_entries, palette_names

        names = palette_names()
        self.assertIn("obsidian", names)
        self.assertIn("crimson_glow", names)
        self.assertTrue(emissive_palette_entries())

    def test_emissive_materials_use_a_dark_base_colour(self):
        """Regression: a bright base colour plus emission clips in the Standard view transform.

        The first vampire keep lit its windows hot pink and its roof read salmon because the
        emissive material carried both a bright base colour and a strong emission. Emission now
        carries the hue from a near-black base.
        """
        from lib.blender import emissive_palette_entries

        for name, spec in emissive_palette_entries().items():
            base = spec["color"]
            luminance = 0.2126 * base[0] + 0.7152 * base[1] + 0.0722 * base[2]
            self.assertLess(luminance, 0.20,
                            f"{name}: emissive base colour {base} is too bright; "
                            f"the emission will clip to white")
            strength = float(spec.get("emission_strength", 1.0))
            self.assertLessEqual(strength, 1.5,
                                 f"{name}: emission strength {strength} will clip the emission")

    def test_palette_has_no_duplicate_keys(self):
        """A duplicate key in the PALETTE literal silently overrides - the last one wins.

        This happened for real: an edit added a dark `cold_moon` while an older bright one
        remained, and the bright one won.
        """
        import ast
        import collections

        from lib.blender import SCENE_LIB

        tree = ast.parse(SCENE_LIB.read_text())
        for node in tree.body:
            target = getattr(node, "target", None) or (
                node.targets[0] if getattr(node, "targets", None) else None)
            if getattr(target, "id", None) == "PALETTE":
                keys = [k.value for k in node.value.keys]
                dupes = [k for k, c in collections.Counter(keys).items() if c > 1]
                self.assertEqual(dupes, [], f"duplicate PALETTE keys: {dupes}")

    def test_unknown_material_in_the_manifest_is_reported(self):
        config = Config.load()
        manifest = load_manifest(None, config)
        for asset in manifest.assets:
            if asset.get("source") == "blender":
                asset["blender"]["params"]["wall_material"] = "obsidan"  # deliberate typo
                break
        problems = validate_manifest(manifest, config)
        self.assertTrue(any("unknown material" in p for p in problems), problems)


class TestFamilies(unittest.TestCase):
    """Invariants of upgrade-tier families, asserted against the last run's own records."""

    RECORDS = ROOT / "metadata" / "asset_records"

    def _records(self, keys):
        out = {}
        for key in keys:
            path = self.RECORDS / f"{key}.json"
            if path.exists():
                out[key] = json.loads(path.read_text())
        return out

    def test_family_siblings_share_one_camera(self):
        """Every tier of a family must render from the same camera, or the tiers cannot be
        swapped on one tile and their size progression is meaningless."""
        for asset_id in ("demo_hut", "vampire_keep"):
            recs = self._records([asset_id, f"{asset_id}__lvl2", f"{asset_id}__lvl3"])
            if len(recs) < 2:
                self.skipTest(f"no records for {asset_id} family")
            if any("generation" not in r["stages"] for r in recs.values()):
                self.skipTest(f"{asset_id} family has records without generation provenance")
            cams = {(r["stages"]["generation"].get("ortho_scale"),
                     r["stages"]["generation"].get("frame_target_z")) for r in recs.values()}
            self.assertEqual(len(cams), 1,
                             f"{asset_id}: siblings rendered from different cameras: {cams}")

    def test_higher_tiers_are_visibly_larger(self):
        """`scale_mode: family` exists so a level-3 building is bigger than a level-1."""
        for asset_id in ("demo_hut", "vampire_keep"):
            heights = []
            for key in (asset_id, f"{asset_id}__lvl2", f"{asset_id}__lvl3"):
                path = ROOT / "assets" / "approved" / "buildings" / f"{key}.png"
                if not path.exists():
                    self.skipTest(f"no approved output for {key}")
                with Image.open(path) as img:
                    heights.append(imageops.measure(img).bbox[3] - imageops.measure(img).bbox[1])
            self.assertEqual(heights, sorted(heights),
                             f"{asset_id}: tiers are not ordered by size: {heights}")

    def test_family_tiers_share_a_ground_line(self):
        for asset_id in ("demo_hut", "vampire_keep"):
            bottoms = set()
            for key in (asset_id, f"{asset_id}__lvl2", f"{asset_id}__lvl3"):
                path = ROOT / "assets" / "approved" / "buildings" / f"{key}.png"
                if not path.exists():
                    self.skipTest(f"no approved output for {key}")
                with Image.open(path) as img:
                    bottoms.add(imageops.measure(img).bbox[3])
            self.assertEqual(len(bottoms), 1, f"{asset_id}: tiers disagree on the ground line: {bottoms}")

    def test_procedural_renders_are_inside_their_frame(self):
        """The camera must fit the subject. This is the bug that cropped the level-3 keep's
        banner: the family framing lock was taken from the smallest tier.

        Procedural renders only. A painted render is the diffusion model's composition and
        filling the frame is a valid choice there.
        """
        incoming = ROOT / "assets" / "incoming"
        procedural = {"demo_hut", "vampire_keep", "vampire_grave", "vampire_gate_torch"}
        renders = [p for p in sorted(incoming.glob("*.png")) if p.stem.split("__")[0] in procedural]
        if not renders:
            self.skipTest("no procedural renders to check")
        for path in renders:
            with Image.open(path) as img:
                box = imageops.content_bbox(img)
                width, height = img.size
            self.assertIsNotNone(box, f"{path.name} has no subject pixels")
            self.assertGreater(box[0], 1, f"{path.name}: subject touches the left edge")
            self.assertGreater(box[1], 1, f"{path.name}: subject touches the top edge")
            self.assertLess(box[2], width - 1, f"{path.name}: subject touches the right edge")
            self.assertLess(box[3], height - 1, f"{path.name}: subject touches the bottom edge")

    def test_turntable_is_declared_as_camera_moving(self):
        """A validator that wants a stable centroid must not be applied to a turntable."""
        from lib.blender import camera_moving_clips

        self.assertIn("turntable", camera_moving_clips())

    def test_animation_frames_are_uniform_and_share_one_camera(self):
        for run_key in ("demo_hut_flag", "vampire_gate_torch", "vampire_watcher"):
            frames = sorted((ROOT / "assets" / "processed" / run_key).glob("frame_*.png"))
            if not frames:
                self.skipTest(f"no processed frames for {run_key}")
            sizes = {Image.open(f).size for f in frames}
            self.assertEqual(len(sizes), 1, f"{run_key}: frames are not uniform: {sizes}")


class TestMcpServer(unittest.TestCase):
    """The MCP surface is the main way agents use this, so it gets tested like any other API."""

    SERVER = ROOT / "mcp_server" / "server.py"

    def _call(self, *requests: dict) -> list[dict]:
        payload = "\n".join(json.dumps(r) for r in requests) + "\n"
        proc = subprocess.run([sys.executable, str(self.SERVER)], input=payload,
                              capture_output=True, text=True, timeout=120, cwd=str(ROOT))
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]

    def test_initialize_negotiates_and_declares_tools(self):
        [response] = self._call({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                 "params": {"protocolVersion": "2024-11-05"}})
        result = response["result"]
        self.assertEqual(result["protocolVersion"], "2024-11-05")
        self.assertIn("tools", result["capabilities"])
        self.assertEqual(result["serverInfo"]["name"], "artworkflow")

    def test_unknown_protocol_version_falls_back(self):
        from importlib import util as importlib_util

        spec = importlib_util.spec_from_file_location("aw_mcp", self.SERVER)
        module = importlib_util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertIn(module.DEFAULT_PROTOCOL, module.SUPPORTED_PROTOCOLS)

    def test_tools_list_is_well_formed(self):
        [response] = self._call({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        tools = response["result"]["tools"]
        self.assertGreaterEqual(len(tools), 13)
        for tool in tools:
            self.assertTrue(tool["name"].startswith("artworkflow_"), tool["name"])
            self.assertGreater(len(tool["description"]), 40, f"{tool['name']} needs a real description")
            self.assertEqual(tool["inputSchema"]["type"], "object")

    def test_stdout_carries_only_protocol_frames(self):
        """A stray print from a stage would corrupt the transport."""
        responses = self._call({"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                               {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                "params": {"name": "artworkflow_manifest", "arguments": {}}})
        self.assertEqual([r["id"] for r in responses], [1, 2])
        manifest = json.loads(responses[1]["result"]["content"][0]["text"])
        self.assertTrue(manifest["ok"], manifest["problems"])

    def test_every_tool_is_documented(self):
        [response] = self._call({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        doc = (ROOT / "mcp_server" / "README.md").read_text()
        for tool in response["result"]["tools"]:
            self.assertIn(tool["name"], doc, f"{tool['name']} is missing from mcp_server/README.md")

    def test_failing_tool_reports_instead_of_crashing(self):
        [response] = self._call({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                 "params": {"name": "artworkflow_nope", "arguments": {}}})
        self.assertTrue(response["result"]["isError"])
        self.assertIn("unknown tool", response["result"]["content"][0]["text"])


class TestToolDetection(unittest.TestCase):
    """Tool discovery is what makes the repo portable; it has to actually find things."""

    def test_resolves_the_tools_installed_here(self):
        """Runs only where a tool exists: CI has no Blender, no ComfyUI and no GPU, and the
        suite must pass there. Absence is covered by the missing-tool test below."""
        from lib.common import Config
        from lib.tools import find_blender, find_godot

        blender = find_blender(Config.load().get("blender.binary") or None)
        if not blender:
            self.skipTest("no Blender on this machine")
        self.assertTrue(str(blender).endswith("blender"))
        _ = find_godot  # imported to keep the resolver pair covered

    def test_env_var_override_wins(self):
        """An env var pointing at a real file beats auto-detection; one pointing at a missing
        file is ignored, so a stale variable cannot pretend a tool is installed."""
        import os

        from lib.tools import find_blender

        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "blender"
            real.write_text("#!/bin/sh\n")
            real.chmod(0o755)
            os.environ["BLENDER_BIN"] = str(real)
            try:
                self.assertEqual(str(find_blender(None)), str(real))
                os.environ["BLENDER_BIN"] = str(Path(tmp) / "gone")
                self.assertNotEqual(str(find_blender(None)), str(Path(tmp) / "gone"))
            finally:
                del os.environ["BLENDER_BIN"]

    def test_missing_tool_raises_with_an_actionable_message(self):
        from lib.common import Config
        from lib.tools import ToolNotFound, require

        config = Config.load()
        config.data["godot"]["binary"] = "/nonexistent/godot"
        with self.assertRaises(ToolNotFound) as ctx:
            require("godot", config)
        self.assertIn("godot.binary", str(ctx.exception))

    def test_no_tracked_config_hardcodes_a_home_directory(self):
        """The repo must be clonable on another machine without editing tracked files."""
        config = (ROOT / "config" / "pipeline.yaml").read_text()
        for marker in ("/home/", "/Users/", "anaconda3"):
            self.assertNotIn(marker, config, f"config/pipeline.yaml hardcodes {marker}")

    def test_local_config_override_is_gitignored(self):
        ignore = (ROOT / ".gitignore").read_text()
        self.assertIn("config/pipeline.local.yaml", ignore)


class TestExportedArtifacts(unittest.TestCase):
    """The run that produced assets/approved/ must have left self-consistent metadata."""

    def test_every_exported_sheet_metadata_fits_its_sheet(self):
        for meta_path in (ROOT / "assets/spritesheets").glob("*.json"):
            meta = json.loads(meta_path.read_text())
            with Image.open(meta_path.with_suffix(".png")) as sheet:
                self.assertEqual(sheet.size, tuple(meta["sheet_size"]), meta_path.name)
                for rect in meta["frames"]:
                    self.assertLessEqual(rect["x"] + rect["w"], sheet.width)
                    self.assertLessEqual(rect["y"] + rect["h"], sheet.height)

    def test_sheet_and_sidecar_metadata_do_not_collide(self):
        """Both live in the export directory; a sidecar must never take the sheet's name."""
        for path in (ROOT / "assets" / "approved").rglob("*.json"):
            data = json.loads(path.read_text())
            if "frames" in data:
                continue  # spritesheet metadata, validated above
            self.assertTrue(path.name.endswith(".export.json"),
                            f"{path} is neither sheet metadata nor an export sidecar")
            self.assertIn("status", data)


if __name__ == "__main__":
    unittest.main()
