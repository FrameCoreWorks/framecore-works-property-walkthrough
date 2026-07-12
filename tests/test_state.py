"""Testy atomowego, wersjonowanego stanu projektu."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "create-property-walkthrough" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _common import (  # noqa: E402
    ProjectStateError,
    ProjectStatePostCommitError,
    atomic_write_json,
    load_json,
    resolve_project_path,
    safe_slug,
    sha256_file,
    utc_now,
    validate_project_id,
)
import _common as common_module  # noqa: E402
import init_project as project_initialization  # noqa: E402
import update_manifest as manifest_updates  # noqa: E402
from init_project import (  # noqa: E402
    PROJECT_DIRECTORIES,
    ProjectInitializationError,
    ProjectInitializationPostCommitError,
    create_project,
)
from update_manifest import (  # noqa: E402
    ManifestUpdateError,
    add_scene,
    load_project_manifest,
    record_file_hash,
    reorder_scenes,
    tombstone_scene,
    update_manifest,
)


IMAGE_A = "a" * 64
IMAGE_B = "b" * 64


class CommonStateTests(unittest.TestCase):
    """Sprawdza wspólne operacje bez zależności od projektu."""

    def test_safe_slug_obsluguje_polskie_znaki(self) -> None:
        self.assertEqual(safe_slug(" Łazienka żółta 2026 "), "lazienka-zolta-2026")
        self.assertEqual(validate_project_id("lazienka-zolta-2026"), "lazienka-zolta-2026")
        with self.assertRaisesRegex(ProjectStateError, "Identyfikator projektu"):
            validate_project_id("../ucieczka")

    def test_utc_now_ma_jawne_utc(self) -> None:
        self.assertRegex(utc_now(), r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_atomic_write_json_zachowuje_unicode_i_nie_zostawia_tmp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stan.json"
            atomic_write_json(path, {"pokój": "łazienka żółta"})
            self.assertEqual(load_json(path), {"pokój": "łazienka żółta"})
            self.assertEqual(list(path.parent.glob(".stan.json.*.tmp")), [])
            raw = path.read_bytes()
            self.assertIn("łazienka żółta".encode("utf-8"), raw)
            self.assertTrue(raw.endswith(b"\n"))

    def test_nieudany_replace_zachowuje_poprzedni_stan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stan.json"
            atomic_write_json(path, {"revision": 1})
            with mock.patch("_common.os.replace", side_effect=OSError("awaria")):
                with self.assertRaisesRegex(ProjectStateError, "atomowo"):
                    atomic_write_json(path, {"revision": 2})
            self.assertEqual(load_json(path), {"revision": 1})
            self.assertEqual(list(path.parent.glob(".stan.json.*.tmp")), [])

    def test_blad_fsync_po_replace_raportuje_opublikowany_stan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stan.json"
            atomic_write_json(path, {"revision": 1})
            with mock.patch(
                "_common._fsync_directory",
                side_effect=ProjectStateError("kontrolowany błąd fsync"),
            ):
                with self.assertRaises(ProjectStatePostCommitError) as raised:
                    atomic_write_json(path, {"revision": 2})
            self.assertTrue(raised.exception.committed)
            self.assertTrue(raised.exception.published)
            self.assertEqual(raised.exception.destination, path)
            self.assertEqual(load_json(path), {"revision": 2})
            self.assertEqual(list(path.parent.glob(".stan.json.*.tmp")), [])

    def test_load_json_odrzuca_duplikaty_kluczy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplikat.json"
            path.write_text('{"a": 1, "a": 2}\n', encoding="utf-8")
            with self.assertRaisesRegex(ProjectStateError, "powtórzony klucz"):
                load_json(path)

    def test_sha256_file_ma_znany_wynik(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "zażółć.bin"
            payload = "zażółć gęślą jaźń".encode("utf-8")
            path.write_bytes(payload)
            self.assertEqual(sha256_file(path), hashlib.sha256(payload).hexdigest())

    def test_resolve_project_path_odrzuca_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "bezpieczny-projekt"
            root.mkdir()
            self.assertEqual(
                resolve_project_path(root, "reports/wynik.json"),
                root.resolve() / "reports" / "wynik.json",
            )
            with self.assertRaisesRegex(ProjectStateError, "poza katalog"):
                resolve_project_path(root, "../sekret.txt")

    def test_natywna_blokada_windows_ma_backend_standard_library(self) -> None:
        class FakeMsvcrt:
            LK_LOCK = 1
            LK_UNLCK = 2

            def __init__(self) -> None:
                self.operations = []

            def locking(self, descriptor: int, operation: int, size: int) -> None:
                self.operations.append((operation, size))

        backend = FakeMsvcrt()
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "projekt-testowy"
            project.mkdir()
            with mock.patch.object(common_module, "fcntl", None), mock.patch.object(
                common_module, "msvcrt", backend
            ):
                with common_module.exclusive_project_lock(project):
                    self.assertTrue((project / ".project.lock").is_file())

        self.assertEqual(
            [(backend.LK_LOCK, 1), (backend.LK_UNLCK, 1)],
            backend.operations,
        )

    def test_windows_nie_wymaga_fsync_katalogu(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with mock.patch.object(common_module.os, "name", "nt"), mock.patch.object(
                common_module.os,
                "open",
                side_effect=AssertionError("Katalog nie powinien być otwierany na Windows."),
            ):
                common_module._fsync_directory(path)


class ProjectLifecycleTests(unittest.TestCase):
    """Sprawdza inicjalizację, rewizje, hashe i trwałe identyfikatory scen."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.projects_root = Path(self.temporary.name) / "walkthrough-projects"
        self.project = create_project(
            self.projects_root,
            "Łazienka żółta",
            source_mode="manual",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_inicjalizacja_tworzyl_pelne_drzewo_i_snapshot(self) -> None:
        self.assertEqual(self.project.name, "lazienka-zolta")
        for relative_directory in PROJECT_DIRECTORIES:
            self.assertTrue((self.project / relative_directory).is_dir(), relative_directory)
        self.assertTrue((self.project / "project.json").is_file())
        self.assertTrue((self.project / "SOURCE.md").is_file())
        snapshot = self.project / "provider" / "provider-profile.snapshot.json"
        self.assertTrue(snapshot.is_file())
        self.assertEqual(load_json(snapshot)["generation_authorized"], False)

        manifest = load_project_manifest(self.project, verify_hashes=True)
        self.assertEqual(manifest["schema_version"], "1.0")
        self.assertEqual(manifest["manifest_revision"], 1)
        self.assertEqual(manifest["project_id"], "lazienka-zolta")
        self.assertEqual(manifest["provider_profile"]["status"], "not_configured")

    def test_inicjalizacja_nie_nadpisuje_projektu(self) -> None:
        with self.assertRaisesRegex(ProjectInitializationError, "już istnieje"):
            create_project(self.projects_root, "Łazienka żółta")

    def test_inicjalizacja_rozroznia_blad_po_publikacji_katalogu(self) -> None:
        expected = self.projects_root / "projekt-po-commit"
        with mock.patch.object(
            project_initialization,
            "_fsync_directory",
            side_effect=OSError("kontrolowany błąd fsync"),
        ):
            with self.assertRaises(ProjectInitializationPostCommitError) as raised:
                create_project(self.projects_root, "Projekt po commit")
        self.assertTrue(raised.exception.committed)
        self.assertEqual(raised.exception.project_path, expected.resolve())
        self.assertTrue((expected / "project.json").is_file())
        self.assertTrue((expected / "SOURCE.md").is_file())
        self.assertTrue((expected / "provider" / "provider-profile.snapshot.json").is_file())
        load_project_manifest(expected, verify_hashes=True)

    def test_inicjalizacja_odrzuca_secret_reference_w_metadanych(self) -> None:
        target = self.projects_root / "projekt-z-canary"
        with self.assertRaisesRegex(ProjectInitializationError, "secret_reference"):
            create_project(
                self.projects_root,
                "Projekt z canary",
                source_metadata={
                    "nested": {"secret_reference": "SYNTHETIC_CANARY_VALUE"}
                },
            )
        self.assertFalse(target.exists())

    def test_patch_zwieksza_rewizje_i_wykrywa_konflikt(self) -> None:
        updated = update_manifest(
            self.project,
            {"warnings": ["Brakuje zdjęcia elewacji."]},
            expected_revision=1,
        )
        self.assertEqual(updated["manifest_revision"], 2)
        self.assertEqual(updated["warnings"], ["Brakuje zdjęcia elewacji."])
        with self.assertRaisesRegex(ManifestUpdateError, "Konflikt rewizji"):
            update_manifest(self.project, {"warnings": []}, expected_revision=1)

    def test_dwa_writery_nie_gubia_rozlacznych_zmian(self) -> None:
        real_atomic_write = manifest_updates.atomic_write_json
        first_write_entered = threading.Event()
        release_first_write = threading.Event()
        second_write_entered = threading.Event()
        second_worker_started = threading.Event()
        counter_lock = threading.Lock()
        call_count = 0
        errors = []

        def controlled_atomic_write(path: Path, data: object) -> None:
            nonlocal call_count
            with counter_lock:
                call_count += 1
                number = call_count
            if number == 1:
                first_write_entered.set()
                if not release_first_write.wait(5):
                    raise RuntimeError("Test nie zwolnił pierwszego writera.")
            else:
                second_write_entered.set()
            real_atomic_write(path, data)

        def writer(relative_path: str, digest: str, started: threading.Event) -> None:
            started.set()
            try:
                update_manifest(self.project, {"hashes": {relative_path: digest}})
            except Exception as exc:  # pragma: no cover - raportowane przez asercję poniżej.
                errors.append(exc)

        first_started = threading.Event()
        with mock.patch.object(
            manifest_updates,
            "atomic_write_json",
            side_effect=controlled_atomic_write,
        ):
            first = threading.Thread(
                target=writer,
                args=("reports/a.txt", "a" * 64, first_started),
            )
            second = threading.Thread(
                target=writer,
                args=("reports/b.txt", "b" * 64, second_worker_started),
            )
            first.start()
            self.assertTrue(first_started.wait(1))
            self.assertTrue(first_write_entered.wait(2))
            second.start()
            self.assertTrue(second_worker_started.wait(1))
            self.assertFalse(second_write_entered.wait(0.25))
            release_first_write.set()
            first.join(5)
            second.join(5)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        final = load_project_manifest(self.project)
        self.assertEqual(final["manifest_revision"], 3)
        self.assertEqual(final["hashes"]["reports/a.txt"], "a" * 64)
        self.assertEqual(final["hashes"]["reports/b.txt"], "b" * 64)

    def test_dwa_writery_z_ta_sama_oczekiwana_rewizja_daja_jeden_konflikt(self) -> None:
        barrier = threading.Barrier(2)
        successes = []
        errors = []

        def writer(label: str) -> None:
            barrier.wait(timeout=2)
            try:
                successes.append(
                    update_manifest(
                        self.project,
                        {"warnings": [label]},
                        expected_revision=1,
                    )
                )
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=writer, args=("A",)),
            threading.Thread(target=writer, args=("B",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)

        self.assertEqual(len(successes), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ManifestUpdateError)
        self.assertIn("Konflikt rewizji", str(errors[0]))
        final = load_project_manifest(self.project)
        self.assertEqual(final["manifest_revision"], 2)
        self.assertIn(final["warnings"], (["A"], ["B"]))

    def test_secret_reference_jest_zabronione_we_wszystkich_polach_swobodnych(self) -> None:
        canary = "SYNTHETIC_CANARY_VALUE"
        patches = (
            {"source": {"metadata": {"secret_reference": canary}}},
            {"settings": {"nested": {"secret-reference": canary}}},
            {"settings": {"backup_secret_reference": canary}},
            {"classifications": {"img": {"secret_reference": canary}}},
            {"prompts": {"scene": {"secret_reference": canary}}},
            {"model": {"secret_reference": canary}},
            {"jobs": [{"secret_reference": canary}]},
            {"clips": [{"secret_reference": canary}]},
            {"qc": {"scene": {"secret_reference": canary}}},
            {"output": {"secret_reference": canary}},
            {"warnings": [{"secret_reference": canary}]},
            {"errors": [{"secret_reference": canary}]},
        )
        for patch in patches:
            with self.subTest(patch=patch):
                with self.assertRaisesRegex(ValueError, "secret_reference"):
                    update_manifest(self.project, patch, expected_revision=1)
        self.assertEqual(load_project_manifest(self.project)["manifest_revision"], 1)

    def test_hash_pliku_unicode_jest_zapisywany_i_weryfikowany(self) -> None:
        report = self.project / "reports" / "łazienka_żółta.txt"
        report.write_text("syntetyczny raport\n", encoding="utf-8")
        updated = record_file_hash(self.project, "reports/łazienka_żółta.txt")
        expected = hashlib.sha256(report.read_bytes()).hexdigest()
        self.assertEqual(updated["hashes"]["reports/łazienka_żółta.txt"], expected)
        load_project_manifest(self.project, verify_hashes=True)
        report.write_text("zmieniony raport\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "skrót pliku"):
            load_project_manifest(self.project, verify_hashes=True)

    def test_hash_odrzuca_wyjscie_poza_projekt(self) -> None:
        with self.assertRaisesRegex(ProjectStateError, "poza katalog"):
            record_file_hash(self.project, "../poza.txt")

    def test_scene_id_pozostaje_stabilne_a_usuniecie_tworzyl_tombstone(self) -> None:
        first = add_scene(self.project, {"source_image_id": IMAGE_A})
        first_id = first["scene_plan"]["scenes"][0]["scene_id"]
        second = add_scene(self.project, {"source_image_id": IMAGE_B})
        second_id = second["scene_plan"]["scenes"][1]["scene_id"]
        self.assertNotEqual(first_id, second_id)

        reordered = reorder_scenes(self.project, [second_id, first_id])
        self.assertEqual(
            [item["scene_id"] for item in reordered["scene_plan"]["scenes"]],
            [second_id, first_id],
        )
        removed = tombstone_scene(self.project, second_id, "Źródło odrzucone po QC.")
        self.assertEqual(removed["scene_plan"]["scenes"][0]["scene_id"], first_id)
        self.assertEqual(removed["scene_plan"]["scenes"][0]["sequence_index"], 0)
        self.assertEqual(removed["scene_plan"]["tombstones"][0]["scene_id"], second_id)
        with self.assertRaisesRegex(ManifestUpdateError, "tombstone"):
            add_scene(
                self.project,
                {"scene_id": second_id, "source_image_id": IMAGE_B},
            )


if __name__ == "__main__":
    unittest.main()
