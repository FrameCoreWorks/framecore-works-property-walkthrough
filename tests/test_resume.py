"""Testy bezpiecznego i idempotentnego wznowienia projektu."""

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

from _common import atomic_write_json, load_json  # noqa: E402
from prepare_generation_package import prepare_generation_package  # noqa: E402
from render_walkthrough import render_walkthrough  # noqa: E402
from validate_output import analyze_resume  # noqa: E402
from tests.test_rendering import prepare_approved_project  # noqa: E402
from tests.test_scene_planning import (  # noqa: E402
    prepare_synthetic_project,
    require_ffmpeg,
)


class ResumeTests(unittest.TestCase):
    """Sprawdza pomijanie ukończonych etapów i selektywną invalidację."""

    def setUp(self) -> None:
        require_ffmpeg(self)
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_complete_project_resumes_at_complete_and_preserves_approved(self) -> None:
        project_root = prepare_approved_project(self.base, scene_count=2)
        render_walkthrough(project_root, include_vertical=True)

        report = analyze_resume(project_root)

        project = load_json(project_root / "project.json")
        scene_ids = sorted(scene["scene_id"] for scene in project["scene_plan"]["scenes"])
        self.assertTrue(report["valid"])
        self.assertEqual("complete", report["first_incomplete_stage"])
        self.assertEqual(scene_ids, report["valid_approved_scene_ids"])
        self.assertEqual([], report["invalidated_scene_ids"])
        self.assertEqual(["16x9", "9x16"], report["render_validation"]["valid_targets"])
        self.assertEqual(0, report["provider_calls"])
        self.assertFalse(report["automatic_submission_allowed"])

    def test_render_z_niestandardowym_fps_pozostaje_aktualny(self) -> None:
        project_root = prepare_approved_project(self.base, scene_count=1)
        rendered = render_walkthrough(project_root, fps=24)

        report = analyze_resume(project_root)

        self.assertEqual(24, rendered["targets"]["16x9"]["fps"])
        self.assertEqual(["16x9"], report["render_validation"]["valid_targets"])
        self.assertEqual([], report["render_validation"]["stale_targets"])

    def test_changed_scene_invalidates_only_its_clip_and_preserves_other_approval(self) -> None:
        project_root = prepare_approved_project(self.base, scene_count=2)
        before = load_json(project_root / "project.json")
        changed_scene = before["scene_plan"]["scenes"][0]
        preserved_scene = before["scene_plan"]["scenes"][1]
        preserved_selection = dict(before["qc"][preserved_scene["scene_id"]])

        changed_image_id = changed_scene["source_image_id"]
        before["classifications"][changed_image_id]["camera_move"] = "static_hold"
        atomic_write_json(project_root / "project.json", before)
        package_report = prepare_generation_package(project_root, duration_seconds=1.0)

        self.assertEqual([changed_scene["scene_id"]], package_report["changed_scene_ids"])
        report = analyze_resume(project_root)
        after = load_json(project_root / "project.json")
        self.assertEqual("quality_control", report["first_incomplete_stage"])
        self.assertEqual([changed_scene["scene_id"]], report["invalidated_scene_ids"])
        self.assertEqual([preserved_scene["scene_id"]], report["valid_approved_scene_ids"])
        self.assertEqual(
            preserved_selection["selected_sha256"],
            report["preserved_approved_hashes"][preserved_scene["scene_id"]],
        )
        self.assertEqual(preserved_selection, after["qc"][preserved_scene["scene_id"]])
        changed_records = [
            clip
            for clip in after["clips"]
            if clip["scene_id"] == changed_scene["scene_id"]
        ]
        preserved_records = [
            clip
            for clip in after["clips"]
            if clip["scene_id"] == preserved_scene["scene_id"]
        ]
        self.assertTrue(changed_records)
        self.assertTrue(all(clip["input_dependency_valid"] is False for clip in changed_records))
        self.assertTrue(preserved_records)
        self.assertTrue(all(clip["input_dependency_valid"] is True for clip in preserved_records))
        self.assertIn("quality_control_for_approved_scenes", report["preserved_stages"])

    def test_submission_pending_requires_manual_reconciliation_without_resubmit(self) -> None:
        project_root = prepare_synthetic_project(self.base, 1, duration=1.0)
        project = load_json(project_root / "project.json")
        scene_id = project["scene_plan"]["scenes"][0]["scene_id"]
        project["jobs"] = [
            {
                "scene_id": scene_id,
                "job_id": None,
                "status": "submission_pending",
                "batch_fingerprint": "a" * 64,
            }
        ]
        atomic_write_json(project_root / "project.json", project)
        manifest_before = (project_root / "project.json").read_bytes()

        with mock.patch.object(
            socket,
            "socket",
            side_effect=AssertionError("Próba otwarcia sieci podczas resume."),
        ):
            report = analyze_resume(project_root)

        self.assertEqual(manifest_before, (project_root / "project.json").read_bytes())
        self.assertEqual(0, report["provider_calls"])
        self.assertFalse(report["automatic_submission_allowed"])
        self.assertTrue(report["new_submission_requires_fresh_consent"])
        self.assertEqual(
            [
                {
                    "scene_id": scene_id,
                    "job_id": None,
                    "status": "submission_pending",
                    "action": "reconcile_manually",
                    "automatic_submission_allowed": False,
                }
            ],
            report["job_actions"],
        )


if __name__ == "__main__":
    unittest.main()
