"""Testy atomowego spięcia ingestionu, analizy i głównego manifestu."""

from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "create-property-walkthrough" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _common import atomic_write_json, load_json, utc_now  # noqa: E402
from apply_image_analysis import (  # noqa: E402
    ImageAnalysisApplicationError,
    apply_image_analysis,
)
from init_project import create_project  # noqa: E402
from prepare_generation_package import prepare_generation_package  # noqa: E402


class ApplyImageAnalysisTests(unittest.TestCase):
    """Sprawdza jeden oficjalny zapis assetów, klasyfikacji i selekcji."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.project = create_project(
            self.base / "walkthrough-projects",
            "Projekt analizy",
            source_mode="uploaded-images",
        )
        source = self.project / "source-images" / "originals" / "salon.png"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"syntetyczny-obraz-bez-danych-uzytkownika")
        self.digest = hashlib.sha256(source.read_bytes()).hexdigest()
        thumbnail = self.project / "thumbnails" / f"{self.digest}.jpg"
        thumbnail.write_bytes(b"syntetyczna-miniatura")
        self.relative_source = source.relative_to(self.project).as_posix()
        self.ingestion_path = self.project / "source-images" / "ingestion.json"
        atomic_write_json(
            self.ingestion_path,
            {
                "schema_version": 1,
                "assets": [
                    {
                        "asset_id": self.digest,
                        "sha256": self.digest,
                        "original_path": str(source),
                        "thumbnail_path": str(thumbnail),
                        "preferred": True,
                        "provenance": [{"kind": "synthetic_fixture"}],
                    }
                ],
            },
        )
        self.analysis_path = self.project / "reports" / "image-analysis.json"
        self._write_analysis(self.relative_source)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_analysis(self, relative_path: str) -> None:
        atomic_write_json(
            self.analysis_path,
            {
                "schema_version": "1.0",
                "project_id": self.project.name,
                "generated_at": utc_now(),
                "images": [
                    {
                        "image_id": self.digest,
                        "sha256": self.digest,
                        "relative_path": relative_path,
                        "asset_kind": "photo",
                        "room_type": "living_room",
                        "room_instance_id": "salon-1",
                        "curation_status": "selected",
                        "technical_quality": "high",
                        "animation_utility": "high",
                        "deformation_risk": "low",
                        "visible_spaces": ["salon"],
                        "reasons_pl": ["Czytelna geometria i dobre światło."],
                    }
                ],
                "warnings": [],
            },
        )

    def test_zastosowanie_analizy_domyka_manifest_i_plan_scen(self) -> None:
        result = apply_image_analysis(
            self.project,
            self.ingestion_path,
            self.analysis_path,
            rights_confirmed=True,
            pii_reviewed=True,
        )

        project = load_json(self.project / "project.json")
        self.assertEqual(1, result["asset_count"])
        self.assertEqual(1, result["selected_count"])
        self.assertEqual([self.digest], project["selected_images"])
        self.assertEqual(self.relative_source, project["assets"][self.digest]["path"])
        classification = project["classifications"][self.digest]
        self.assertTrue(classification["rights_confirmed"])
        self.assertTrue(classification["pii_reviewed"])
        self.assertFalse(classification["contains_pii"])
        self.assertEqual("complete", project["stages"]["ingestion"])
        self.assertEqual("complete", project["stages"]["image_analysis"])

        package = prepare_generation_package(self.project, duration_seconds=1.0)
        self.assertEqual(1, package["scene_count"])

    def test_niespojna_sciezka_nie_modyfikuje_projektu(self) -> None:
        before = (self.project / "project.json").read_bytes()
        self._write_analysis("source-images/inny-plik.png")

        with self.assertRaisesRegex(ImageAnalysisApplicationError, "inną ścieżkę"):
            apply_image_analysis(
                self.project,
                self.ingestion_path,
                self.analysis_path,
            )

        self.assertEqual(before, (self.project / "project.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
