"""Unit tests for the pipeline's pure parts. No GPU, no ComfyUI, no Blender needed.

    .venv/bin/python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
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
