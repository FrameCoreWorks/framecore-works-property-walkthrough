"""Testy append-only importu syntetycznych klipów i próbek technicznych."""

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
    import_expected_clips,
)
from tests.test_scene_planning import (  # noqa: E402
    make_synthetic_clip,
    prepare_synthetic_project,
    require_ffmpeg,
)


class ClipImportTests(unittest.TestCase):
    """Sprawdza rewizje, hashe, ffprobe, próbki i tombstone'y."""

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

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _candidate(
        self,
        index: int,
        *,
        duration: float = 1.0,
        size: str = "320x180",
    ) -> Path:
        """Tworzy różny klip o wymaganej nazwie sceny."""

        path = self.base / "kandydaci" / f"wersja-{index}" / f"{self.scene_id}.mp4"
        make_synthetic_clip(
            path,
            duration=duration,
            index=index,
            size=size,
        )
        return path

    def test_import_zachowuje_rewizje_hashe_ffprobe_i_piec_probek(self) -> None:
        first_source = self._candidate(1)
        first = import_clip(self.project_root, self.scene_id, first_source)
        first_path = self.project_root / first["path"]
        first_hash = sha256_file(first_path)

        self.assertEqual(first["revision"], 1)
        self.assertEqual(first["sha256"], sha256_file(first_source))
        self.assertEqual(first["sha256"], first_hash)
        self.assertEqual(first["technical_status"], "passed")
        self.assertEqual(first["probe_summary"]["video_stream_count"], 1)
        self.assertEqual(first["probe_summary"]["width"], 320)
        self.assertEqual(first["probe_summary"]["height"], 180)
        self.assertEqual(len(first["sample_frames"]), 5)
        for relative_path in first["sample_frames"]:
            sample = self.project_root / relative_path
            self.assertTrue(sample.is_file(), relative_path)
            self.assertGreater(sample.stat().st_size, 0)

        second_source = self._candidate(2)
        second = import_clip(self.project_root, self.scene_id, second_source)
        second_path = self.project_root / second["path"]

        self.assertEqual(second["revision"], 2)
        self.assertNotEqual(second["clip_id"], first["clip_id"])
        self.assertNotEqual(second["sha256"], first["sha256"])
        self.assertNotEqual(second["path"], first["path"])
        self.assertEqual(sha256_file(first_path), first_hash)
        self.assertEqual(sha256_file(second_path), second["sha256"])

        replay = import_clip(self.project_root, self.scene_id, first_source)
        self.assertEqual(replay["clip_id"], first["clip_id"])
        project = load_json(self.project_root / "project.json")
        scene_clips = [
            record
            for record in project["clips"]
            if record["scene_id"] == self.scene_id
        ]
        self.assertEqual([record["revision"] for record in scene_clips], [1, 2])
        self.assertEqual(project["hashes"][first["path"]], first["sha256"])
        self.assertEqual(project["hashes"][second["path"]], second["sha256"])
        self.assertTrue(
            (
                self.project_root
                / "reports"
                / "qc"
                / self.scene_id
                / "rev-002"
                / "technical.json"
            ).is_file()
        )

    def test_niepoprawny_scene_id_jest_odrzucany_przed_zapisem(self) -> None:
        source = self._candidate(31)
        with self.assertRaisesRegex(ClipImportError, "scene_id"):
            import_clip(self.project_root, "../ucieczka", source)
        self.assertFalse((self.project_root.parent / "ucieczka").exists())

    @unittest.skipIf(sys.platform.startswith("win"), "Symlinki wymagają uprawnień Windows.")
    def test_symlink_klipu_i_katalogu_import_all_sa_odrzucane(self) -> None:
        target = self._candidate(32)
        link = self.base / "linki" / f"{self.scene_id}.mp4"
        link.parent.mkdir(parents=True)
        link.symlink_to(target)
        with self.assertRaisesRegex(ClipImportError, "dowiązaniem symbolicznym"):
            import_clip(self.project_root, self.scene_id, link)

        directory_link = self.base / "katalog-link"
        directory_link.symlink_to(target.parent, target_is_directory=True)
        with self.assertRaisesRegex(ClipImportError, "dowiązaniem symbolicznym"):
            import_expected_clips(self.project_root, directory_link)

    def test_tombstone_blokuje_import_i_nie_publikuje_rewizji(self) -> None:
        project = load_json(self.project_root / "project.json")
        scene = project["scene_plan"]["scenes"].pop()
        project["scene_plan"]["tombstones"].append(
            {
                "scene_id": self.scene_id,
                "source_image_id": scene["source_image_id"],
                "reason": "syntetyczne usunięcie",
            }
        )
        atomic_write_json(self.project_root / "project.json", project)

        with self.assertRaisesRegex(ClipImportError, "tombstone"):
            import_clip(self.project_root, self.scene_id, self._candidate(3))

        persisted = load_json(self.project_root / "project.json")
        self.assertEqual(persisted["clips"], [])
        imported_dir = self.project_root / "scenes" / "imported" / self.scene_id
        self.assertFalse(imported_dir.exists())

    def test_blad_raportu_technicznego_nie_publikuje_manifestu(self) -> None:
        before = load_json(self.project_root / "project.json")
        real_atomic_write = clip_module.atomic_write_json

        def controlled_write(path: Path, data: object) -> None:
            if Path(path).name == "technical.json":
                raise OSError("kontrolowany błąd raportu")
            real_atomic_write(path, data)

        with mock.patch.object(
            clip_module,
            "atomic_write_json",
            side_effect=controlled_write,
        ):
            with self.assertRaisesRegex(OSError, "kontrolowany błąd raportu"):
                import_clip(self.project_root, self.scene_id, self._candidate(4))

        after = load_json(self.project_root / "project.json")
        self.assertEqual(after["manifest_revision"], before["manifest_revision"])
        self.assertEqual(after["clips"], before["clips"])


if __name__ == "__main__":
    unittest.main()
