"""Testy selekcji i ponownych prób kontroli jakości klipów."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "create-property-walkthrough" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _common import atomic_write_json, load_json, sha256_file  # noqa: E402
import import_clips as clip_module  # noqa: E402
from import_clips import (  # noqa: E402
    ClipImportError,
    import_clip,
    record_quality_control,
)
from render_walkthrough import compute_render_dependency_hash  # noqa: E402
from tests.test_scene_planning import (  # noqa: E402
    make_synthetic_clip,
    prepare_synthetic_project,
    require_ffmpeg,
)


class QualityControlTests(unittest.TestCase):
    """Sprawdza blokady geometrii i stabilność aktywnej selekcji."""

    def setUp(self) -> None:
        require_ffmpeg(self)
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.project_root = prepare_synthetic_project(
            self.base,
            count=1,
            duration=1.0,
        )
        project = load_json(self.project_root / "project.json")
        self.scene_id = project["scene_plan"]["scenes"][0]["scene_id"]
        self.first = import_clip(
            self.project_root,
            self.scene_id,
            self._candidate(1),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _candidate(self, index: int) -> Path:
        """Tworzy syntetyczną rewizję o kanonicznej nazwie."""

        path = self.base / "kandydaci" / f"wersja-{index}" / f"{self.scene_id}.mp4"
        make_synthetic_clip(path, duration=1.0, index=index)
        return path

    def _clip_record(self, clip_id: str) -> dict:
        """Odczytuje wskazany rekord z utrwalonego manifestu."""

        project = load_json(self.project_root / "project.json")
        return next(record for record in project["clips"] if record["clip_id"] == clip_id)

    def test_morphing_i_drift_geometrii_blokuja_akceptacje(self) -> None:
        for issue in ("morphing", "geometry_drift"):
            with self.subTest(issue=issue):
                with self.assertRaisesRegex(ClipImportError, "Krytyczne błędy geometrii"):
                    record_quality_control(
                        self.project_root,
                        self.scene_id,
                        1,
                        "approved",
                        issues=[issue],
                    )

        project = load_json(self.project_root / "project.json")
        self.assertNotIn(self.scene_id, project["qc"])
        self.assertEqual(self._clip_record(self.first["clip_id"])["qc_status"], "needs-manual-review")

    def test_akceptacja_publikuje_kopie_i_wybiera_dokladna_rewizje(self) -> None:
        record_quality_control(
            self.project_root,
            self.scene_id,
            1,
            "approved",
            notes_pl="Geometria i ruch są stabilne.",
        )

        project = load_json(self.project_root / "project.json")
        selection = project["qc"][self.scene_id]
        persisted = self._clip_record(self.first["clip_id"])
        approved_copy = self.project_root / persisted["approved_copy_path"]

        self.assertEqual(selection["status"], "approved")
        self.assertEqual(selection["selected_clip_id"], self.first["clip_id"])
        self.assertEqual(selection["selected_revision"], 1)
        self.assertEqual(selection["selected_sha256"], self.first["sha256"])
        self.assertEqual(persisted["qc_status"], "approved")
        self.assertTrue(approved_copy.is_file())
        self.assertEqual(sha256_file(approved_copy), self.first["sha256"])
        self.assertEqual(project["hashes"][persisted["approved_copy_path"]], self.first["sha256"])
        self.assertEqual(project["stages"]["quality_control"], "complete")
        self.assertEqual(project["stages"]["rendering"], "invalidated")
        self.assertEqual(project["output"]["render_status"], "invalidated")

    def test_zmiana_pliku_po_imporcie_blokuje_akceptacje(self) -> None:
        imported = self.project_root / self.first["path"]
        imported.write_bytes(imported.read_bytes() + b"syntetyczna-zmiana")

        with self.assertRaisesRegex(ClipImportError, "zmienił się od importu"):
            record_quality_control(
                self.project_root,
                self.scene_id,
                1,
                "approved",
            )

        project = load_json(self.project_root / "project.json")
        self.assertNotIn(self.scene_id, project["qc"])

    def test_retry_nie_zastepuje_aktywnej_selekcji_przed_akceptacja(self) -> None:
        record_quality_control(
            self.project_root,
            self.scene_id,
            1,
            "approved",
        )
        project = load_json(self.project_root / "project.json")
        project["output"] = {
            "render_status": "complete",
            "invalidated_scene_ids": [],
            "synthetic_artifact": "final/walkthrough-16x9.mp4",
        }
        project["stages"]["rendering"] = "complete"
        atomic_write_json(self.project_root / "project.json", project)
        render_dependency_before = compute_render_dependency_hash(
            self.project_root,
            project,
            "16x9",
        )

        second = import_clip(
            self.project_root,
            self.scene_id,
            self._candidate(2),
        )
        self.assertEqual(second["revision"], 2)

        for status in ("regenerate", "rejected"):
            with self.subTest(status=status):
                record_quality_control(
                    self.project_root,
                    self.scene_id,
                    2,
                    status,
                    issues=["morphing"] if status == "regenerate" else ["geometry_drift"],
                )
                persisted = load_json(self.project_root / "project.json")
                selection = persisted["qc"][self.scene_id]
                self.assertEqual(selection["status"], "approved")
                self.assertEqual(selection["selected_clip_id"], self.first["clip_id"])
                self.assertEqual(selection["selected_revision"], 1)
                self.assertEqual(selection["candidate_status"], status)
                self.assertEqual(selection["candidate_clip_id"], second["clip_id"])
                self.assertEqual(selection["candidate_revision"], 2)
                self.assertEqual(persisted["output"]["render_status"], "complete")
                self.assertEqual(persisted["output"]["invalidated_scene_ids"], [])
                self.assertEqual(persisted["stages"]["rendering"], "complete")
                self.assertEqual(persisted["stages"]["quality_control"], "complete")
                self.assertEqual(
                    compute_render_dependency_hash(
                        self.project_root,
                        persisted,
                        "16x9",
                    ),
                    render_dependency_before,
                )

        record_quality_control(
            self.project_root,
            self.scene_id,
            2,
            "approved",
        )
        approved = load_json(self.project_root / "project.json")
        new_selection = approved["qc"][self.scene_id]
        self.assertEqual(new_selection["status"], "approved")
        self.assertEqual(new_selection["selected_clip_id"], second["clip_id"])
        self.assertEqual(new_selection["selected_revision"], 2)
        self.assertEqual(approved["output"]["render_status"], "invalidated")
        self.assertEqual(approved["output"]["invalidated_scene_ids"], [self.scene_id])
        self.assertEqual(approved["stages"]["rendering"], "invalidated")
        self.assertEqual(approved["stages"]["quality_control"], "complete")

    def test_blad_raportu_qc_nie_publikuje_manifestu(self) -> None:
        before = load_json(self.project_root / "project.json")
        real_atomic_write = clip_module.atomic_write_json

        def controlled_write(path: Path, data: object) -> None:
            if Path(path).name == "review.json":
                raise OSError("kontrolowany błąd raportu QC")
            real_atomic_write(path, data)

        with mock.patch.object(
            clip_module,
            "atomic_write_json",
            side_effect=controlled_write,
        ):
            with self.assertRaisesRegex(OSError, "kontrolowany błąd raportu QC"):
                record_quality_control(
                    self.project_root,
                    self.scene_id,
                    1,
                    "approved",
                )

        after = load_json(self.project_root / "project.json")
        self.assertEqual(after["manifest_revision"], before["manifest_revision"])
        self.assertEqual(after["qc"], before["qc"])


if __name__ == "__main__":
    unittest.main()
