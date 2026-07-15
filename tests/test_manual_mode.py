"""Testy kompletnego pakietu ręcznego bez profilu dostawcy."""

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

from _common import load_json  # noqa: E402
from prepare_generation_package import (  # noqa: E402
    _canonical_hash,
    prepare_generation_package,
)
from tests.test_scene_planning import (  # noqa: E402
    create_synthetic_project,
    require_ffmpeg,
)


class ManualModeTests(unittest.TestCase):
    """Sprawdza, że brak dostawcy nie blokuje samodzielnego pakietu."""

    def setUp(self) -> None:
        require_ffmpeg(self)
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @unittest.skipIf(sys.platform.startswith("win"), "Symlinki wymagają uprawnień Windows.")
    def test_symlink_prompts_i_generation_package_blokuja_zapis(self) -> None:
        for child in ("prompts", "generation-package"):
            with self.subTest(child=child):
                project_root = create_synthetic_project(self.base / child, 1)
                blocked = project_root / child
                outside = self.base / ("outside-" + child)
                blocked.rmdir()
                outside.mkdir()
                blocked.symlink_to(outside, target_is_directory=True)

                with self.assertRaisesRegex(ValueError, "dowiązaniem symbolicznym"):
                    prepare_generation_package(project_root, duration_seconds=1.0)
                self.assertEqual(list(outside.iterdir()), [])

    def test_pakiet_reczny_jest_kompletny_i_nie_wywoluje_dostawcy(self) -> None:
        project_root = create_synthetic_project(self.base, 2)
        with mock.patch.object(
            socket,
            "socket",
            side_effect=AssertionError("niedozwolone połączenie sieciowe"),
        ):
            report = prepare_generation_package(project_root, duration_seconds=1.0)

        self.assertEqual(0, report["provider_calls"])
        manifest_path = project_root / "generation-package" / "generation-manifest.json"
        manifest = load_json(manifest_path)
        self.assertEqual("manual", manifest["mode"])
        self.assertFalse(manifest["provider_configured"])
        self.assertFalse(manifest["external_generation_authorized"])
        self.assertEqual(2, len(manifest["entries"]))
        for entry in manifest["entries"]:
            self.assertTrue((project_root / entry["curated_image_path"]).is_file())
            self.assertTrue(entry["prompt"])
            self.assertTrue(entry["expected_filename"].endswith(".mp4"))
        self.assertTrue((project_root / "prompts" / "shot-list.json").is_file())
        self.assertTrue((project_root / "prompts" / "shot-list.md").is_file())
        self.assertTrue((project_root / "prompts" / "shot-list.csv").is_file())
        self.assertFalse(
            (project_root / "generation-package" / "provider-batch-manifest.json").exists()
        )
        project = load_json(project_root / "project.json")
        self.assertEqual("not_configured", project["provider_profile"]["status"])
        self.assertEqual("complete", project["stages"]["generation_package"])
        self.assertEqual("pending", project["stages"]["generation"])

    def test_fingerprint_pakietu_recznego_wiaze_jego_pelny_zakres(self) -> None:
        project_root = create_synthetic_project(self.base, 1)
        prepare_generation_package(project_root, duration_seconds=1.0)
        manifest = load_json(
            project_root / "generation-package" / "generation-manifest.json"
        )
        fingerprint = manifest.pop("package_fingerprint")
        manifest.pop("created_at")

        self.assertEqual(fingerprint, _canonical_hash(manifest))


if __name__ == "__main__":
    unittest.main()
