"""Pełny provider-free E2E na syntetycznych obrazach i klipach."""

from __future__ import annotations

import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPOSITORY_ROOT / "skills" / "create-property-walkthrough" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _common import load_json, sha256_file  # noqa: E402
from import_clips import import_clip, record_quality_control  # noqa: E402
from prepare_generation_package import prepare_generation_package  # noqa: E402
from render_walkthrough import render_walkthrough  # noqa: E402
from validate_output import analyze_resume  # noqa: E402
from tests.test_scene_planning import (  # noqa: E402
    create_synthetic_project,
    make_synthetic_clip,
    require_ffmpeg,
)


class ProviderFreeEndToEndTests(unittest.TestCase):
    """Przechodzi od projektu do dwóch finalnych renderów bez sieci i dostawcy."""

    def setUp(self) -> None:
        require_ffmpeg(self)
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_full_local_pipeline_finishes_with_zero_provider_calls(self) -> None:
        with mock.patch.object(
            socket,
            "socket",
            side_effect=AssertionError("E2E próbował otworzyć połączenie sieciowe."),
        ):
            project_root = create_synthetic_project(self.base, count=2)
            package_report = prepare_generation_package(
                project_root,
                duration_seconds=1.0,
            )
            project = load_json(project_root / "project.json")
            imported_ids = []
            for index, scene in enumerate(project["scene_plan"]["scenes"]):
                clip_path = project_root / "manual-clips" / f"{scene['scene_id']}.mp4"
                make_synthetic_clip(
                    clip_path,
                    duration=1.0,
                    index=index,
                    size="640x360",
                    with_audio=True,
                )
                record = import_clip(project_root, scene["scene_id"], clip_path)
                imported_ids.append(record["clip_id"])
                record_quality_control(
                    project_root,
                    scene["scene_id"],
                    int(record["revision"]),
                    "approved",
                    notes_pl="Syntetyczna kontrola E2E.",
                    source_comparison_performed=True,
                    comparison_evidence_pl="Porównano syntetyczne próbki ze źródłem.",
                )
            render_report = render_walkthrough(project_root, include_vertical=True)
            resume_report = analyze_resume(project_root)

        self.assertEqual(0, package_report["provider_calls"])
        self.assertEqual(0, render_report["provider_calls"])
        self.assertEqual(0, resume_report["provider_calls"])
        self.assertEqual(2, package_report["scene_count"])
        self.assertEqual(2, len(imported_ids))
        self.assertEqual("complete", resume_report["first_incomplete_stage"])
        self.assertTrue(resume_report["valid"])
        self.assertFalse(resume_report["automatic_submission_allowed"])

        project = load_json(project_root / "project.json")
        self.assertEqual("not_configured", project["provider_profile"]["status"])
        self.assertEqual([], project["jobs"])
        self.assertEqual("complete", project["stages"]["quality_control"])
        self.assertEqual("complete", project["stages"]["rendering"])
        self.assertEqual(
            {scene["scene_id"] for scene in project["scene_plan"]["scenes"]},
            {
                scene_id
                for scene_id, selection in project["qc"].items()
                if selection["status"] == "approved"
            },
        )

        manual_manifest = load_json(
            project_root / "generation-package" / "generation-manifest.json"
        )
        self.assertFalse(manual_manifest["provider_configured"])
        self.assertFalse(manual_manifest["external_generation_authorized"])
        self.assertEqual("manual", manual_manifest["mode"])

        for target, dimensions in {"16x9": (1920, 1080), "9x16": (1080, 1920)}.items():
            result = render_report["targets"][target]
            output_path = project_root / result["path"]
            self.assertTrue(output_path.is_file())
            self.assertGreater(output_path.stat().st_size, 0)
            self.assertEqual(result["sha256"], sha256_file(output_path))
            self.assertEqual(dimensions, (result["probe"]["width"], result["probe"]["height"]))
            self.assertEqual("h264", result["probe"]["codec_name"])
            self.assertEqual("yuv420p", result["probe"]["pixel_format"])
            self.assertIn(result["probe"]["sample_aspect_ratio"], ("1:1", None))
            self.assertEqual(0, result["probe"]["audio_stream_count"])
            self.assertFalse(result["audio_added"])
            self.assertFalse(result["pii_overlays_added"])

        for clip in project["clips"]:
            self.assertEqual(5, len(clip["sample_frames"]))
            self.assertEqual("approved", clip["qc_status"])
            self.assertTrue((project_root / clip["approved_copy_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
