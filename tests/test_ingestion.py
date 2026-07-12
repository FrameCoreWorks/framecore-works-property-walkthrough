"""Testy bezpiecznej kwarantanny, ZIP i deduplikacji obrazów."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
import shutil
import stat
import struct
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "create-property-walkthrough" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import ingest_images as ingestion  # noqa: E402
from _common import ProjectStateError  # noqa: E402
from tests._media_fixtures import make_image as _make_image  # noqa: E402


def _zip(path: Path, entries: list[tuple[str, bytes]], *, compression: int = zipfile.ZIP_DEFLATED) -> None:
    with zipfile.ZipFile(path, "w", compression=compression) as archive:
        for name, payload in entries:
            archive.writestr(name, payload)


def _mark_zip_encrypted(path: Path) -> None:
    data = bytearray(path.read_bytes())
    positions = ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8))
    for signature, flag_offset in positions:
        start = 0
        while True:
            index = data.find(signature, start)
            if index < 0:
                break
            flags = struct.unpack_from("<H", data, index + flag_offset)[0] | 0x1
            struct.pack_into("<H", data, index + flag_offset, flags)
            start = index + 4
    path.write_bytes(data)


def _zip_with_backslash(path: Path, payload: bytes) -> None:
    """Utwórz ZIP z backslashem niezależnie od normalizacji hosta Windows."""

    portable_name = b"folder/atak.png"
    unsafe_name = b"folder\\atak.png"
    _zip(path, [(portable_name.decode("ascii"), payload)])
    data = path.read_bytes()
    if data.count(portable_name) != 2:
        raise AssertionError("Fixture ZIP nie ma oczekiwanych dwóch nagłówków nazwy.")
    path.write_bytes(data.replace(portable_name, unsafe_name))


class IngestionTests(unittest.TestCase):
    """Każde wejście przechodzi przez kwarantannę i limity fail-closed."""

    def test_pojedynczy_plik_i_polska_sciezka_zachowuja_original(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ingest-łódź-") as temporary:
            root = Path(temporary)
            source = root / "źródła" / "łazienka_żółta.png"
            destination = root / "projekt" / "images"
            _make_image(source, color="yellow")
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()

            manifest = ingestion.ingest_images(
                source,
                destination,
                preferred=True,
                provenance_kind="user_upload",
                create_contact_sheet=False,
            )

            self.assertEqual(len(manifest["assets"]), 1)
            asset = manifest["assets"][0]
            self.assertEqual(asset["asset_id"], source_hash)
            self.assertEqual(asset["sha256"], source_hash)
            self.assertEqual(Path(asset["original_path"]).read_bytes(), source.read_bytes())
            self.assertTrue(Path(asset["thumbnail_path"]).is_file())
            self.assertTrue(asset["preferred"])
            self.assertEqual(asset["provenance"][0]["relative_path"], "łazienka_żółta.png")
            self.assertEqual(asset["provenance"][0]["kind"], "user_upload")
            self.assertTrue(Path(asset["provenance"][0]["quarantine_path"]).is_file())
            self.assertTrue((destination / "ingestion.json").is_file())

    def test_katalog_exact_near_duplicate_i_hybrid_provenance(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ingest-hybrid-") as temporary:
            root = Path(temporary)
            source = root / "zdjęcia użytkownika"
            destination = root / "projekt" / "images"
            first = source / "Salon.png"
            exact = source / "salon-kopia.png"
            near = source / "salon-inny-kodek.jpg"
            _make_image(first, color="blue")
            shutil.copyfile(first, exact)
            _make_image(near, color="blue")

            manifest = ingestion.ingest_images(
                source,
                destination,
                listing_url="https://example.pl/oferta/123",
                provenance_kind="hybrid_upload",
                create_contact_sheet=False,
            )

            self.assertEqual(len(manifest["assets"]), 2)
            duplicated = next(asset for asset in manifest["assets"] if asset["exact_duplicate_count"] == 1)
            self.assertEqual(len(duplicated["provenance"]), 2)
            self.assertTrue(
                all(
                    record["listing_url"] == "https://example.pl/oferta/123"
                    for record in duplicated["provenance"]
                )
            )
            self.assertEqual(len(manifest["near_duplicate_candidates"]), 1)
            candidate = manifest["near_duplicate_candidates"][0]
            self.assertEqual(candidate["distance"], 0)
            self.assertLess(candidate["left_asset_id"], candidate["right_asset_id"])

            updated = ingestion.ingest_images(
                exact,
                destination,
                preferred=True,
                provenance_kind="preferred_upload",
                create_contact_sheet=False,
            )
            self.assertEqual(len(updated["assets"]), 2)
            same = next(asset for asset in updated["assets"] if asset["asset_id"] == duplicated["asset_id"])
            self.assertTrue(same["preferred"])
            self.assertEqual(same["exact_duplicate_count"], 2)
            self.assertEqual(len(updated["near_duplicate_candidates"]), 1)

    def test_safe_zip_oraz_uszkodzony_obraz_w_kwarantannie(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ingest-zip-") as temporary:
            root = Path(temporary)
            image = root / "pokój.png"
            archive = root / "zdjęcia.zip"
            destination = root / "projekt" / "images"
            _make_image(image, color="green")
            _zip(
                archive,
                [
                    ("Mieszkanie/Żółty pokój.png", image.read_bytes()),
                    ("Mieszkanie/uszkodzony.jpg", b"to nie jest jpeg"),
                    ("README.txt", "fixture syntetyczny".encode("utf-8")),
                ],
            )

            manifest = ingestion.ingest_images(archive, destination, create_contact_sheet=False)

            self.assertEqual(len(manifest["assets"]), 1)
            batch = manifest["batches"][0]
            reasons = " ".join(item["reason"] for item in batch["rejected"])
            self.assertIn("nieobsługiwane rozszerzenie", reasons)
            self.assertIn("obraz uszkodzony albo niezgodny", reasons)
            self.assertEqual(
                manifest["assets"][0]["provenance"][0]["archive_member"],
                "Mieszkanie/Żółty pokój.png",
            )
            self.assertEqual(
                Path(manifest["assets"][0]["original_path"]).read_bytes(), image.read_bytes()
            )

    def test_niebezpieczne_zipy_nie_publikuja_czesciowych_outputow(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ingest-złe-zipy-") as temporary:
            root = Path(temporary)
            safe = root / "bezpieczny.png"
            _make_image(safe, color="white")
            safe_bytes = safe.read_bytes()

            inner_buffer = io.BytesIO()
            with zipfile.ZipFile(inner_buffer, "w") as inner:
                inner.writestr("obraz.png", safe_bytes)

            archives: list[tuple[str, callable]] = []

            def normal(name: str, entries: list[tuple[str, bytes]]) -> callable:
                def build(path: Path) -> None:
                    _zip(path, entries)
                return build

            archives.extend(
                [
                    ("traversal", normal("traversal", [("dobry.png", safe_bytes), ("../ucieczka.png", safe_bytes)])),
                    ("absolute", normal("absolute", [("/tmp/atak.png", safe_bytes)])),
                    ("backslash", lambda path: _zip_with_backslash(path, safe_bytes)),
                    ("nested", normal("nested", [("dobry.png", safe_bytes), ("inner.zip", inner_buffer.getvalue())])),
                    ("case", normal("case", [("Łazienka.png", safe_bytes), ("łazienka.PNG", safe_bytes)])),
                    ("ratio", normal("ratio", [("duzy.txt", b"0" * 100_000)])),
                ]
            )

            def symlink(path: Path) -> None:
                with zipfile.ZipFile(path, "w") as archive:
                    info = zipfile.ZipInfo("link.png")
                    info.create_system = 3
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    archive.writestr(info, "cel.png")

            def special(path: Path) -> None:
                with zipfile.ZipFile(path, "w") as archive:
                    info = zipfile.ZipInfo("fifo.png")
                    info.create_system = 3
                    info.external_attr = (stat.S_IFIFO | 0o644) << 16
                    archive.writestr(info, b"")

            def encrypted(path: Path) -> None:
                _zip(path, [("tajny.png", safe_bytes)])
                _mark_zip_encrypted(path)

            archives.extend([("symlink", symlink), ("special", special), ("encrypted", encrypted)])

            for name, builder in archives:
                with self.subTest(name=name):
                    archive = root / (name + ".zip")
                    output = root / ("output-" + name)
                    builder(archive)
                    limits = ingestion.IngestionLimits(max_compression_ratio=2.0) if name == "ratio" else None
                    with self.assertRaises(ingestion.IngestionError):
                        ingestion.ingest_images(
                            archive, output, limits=limits, create_contact_sheet=False
                        )
                    self.assertFalse((output / "originals").exists())
                    self.assertFalse((output / "thumbnails").exists())
                    self.assertFalse((output / "contact-sheets").exists())
                    self.assertFalse((output / "ingestion.json").exists())

    def test_limity_entry_count_i_size_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ingest-limity-") as temporary:
            root = Path(temporary)
            image = root / "obraz.png"
            _make_image(image, color="purple", size="1024x1024")
            payload = image.read_bytes()

            count_zip = root / "count.zip"
            _zip(count_zip, [("a.png", payload), ("b.png", payload)])
            count_output = root / "count-output"
            with self.assertRaises(ingestion.IngestionError):
                ingestion.ingest_images(
                    count_zip,
                    count_output,
                    limits=ingestion.IngestionLimits(max_entries=1, max_images=1),
                    create_contact_sheet=False,
                )
            self.assertFalse((count_output / "ingestion.json").exists())

            size_zip = root / "size.zip"
            _zip(size_zip, [("duzy.png", payload)], compression=zipfile.ZIP_STORED)
            size_output = root / "size-output"
            with self.assertRaises(ingestion.IngestionError):
                ingestion.ingest_images(
                    size_zip,
                    size_output,
                    limits=ingestion.IngestionLimits(
                        max_file_bytes=1024,
                        max_total_uncompressed_bytes=1024,
                    ),
                    create_contact_sheet=False,
                )
            self.assertFalse((size_output / "ingestion.json").exists())

    def test_magic_bytes_i_symlink_sa_odrzucane(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ingest-magic-") as temporary:
            root = Path(temporary)
            png = root / "prawdziwy.png"
            _make_image(png)
            fake = root / "fałszywy.jpg"
            fake.write_bytes(png.read_bytes())
            output = root / "output"

            with self.assertRaises(ingestion.IngestionError):
                ingestion.ingest_images(fake, output, create_contact_sheet=False)
            self.assertTrue((output / "quarantine").is_dir())
            self.assertFalse((output / "ingestion.json").exists())

            link = root / "link.png"
            try:
                link.symlink_to(png)
            except (OSError, NotImplementedError):
                return
            with self.assertRaises(ingestion.IngestionError):
                ingestion.ingest_images(link, root / "link-output", create_contact_sheet=False)

    def test_blad_contact_sheet_nie_publikuje_originals(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ingest-transakcja-") as temporary:
            root = Path(temporary)
            image = root / "salon.png"
            output = root / "output"
            _make_image(image)

            with mock.patch.object(
                ingestion,
                "make_contact_sheet",
                side_effect=ingestion.ContactSheetError("kontrolowany błąd"),
            ):
                with self.assertRaises(ingestion.ContactSheetError):
                    ingestion.ingest_images(image, output)
            self.assertFalse((output / "originals").exists())
            self.assertFalse((output / "thumbnails").exists())
            self.assertFalse((output / "ingestion.json").exists())

    def test_blad_fsync_po_publikacji_manifestu_nie_usuwa_assetow(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ingest-post-commit-") as temporary:
            root = Path(temporary)
            image = root / "salon.png"
            output = root / "output"
            _make_image(image)

            with mock.patch(
                "_common._fsync_directory",
                side_effect=ProjectStateError("kontrolowany błąd fsync"),
            ):
                with self.assertRaisesRegex(
                    ingestion.IngestionError,
                    "Manifest ingestion został opublikowany",
                ):
                    ingestion.ingest_images(
                        image,
                        output,
                        create_contact_sheet=False,
                    )

            manifest = ingestion.load_json(output / "ingestion.json")
            self.assertEqual(len(manifest["assets"]), 1)
            asset = manifest["assets"][0]
            self.assertTrue(Path(asset["original_path"]).is_file())
            self.assertTrue(Path(asset["thumbnail_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
