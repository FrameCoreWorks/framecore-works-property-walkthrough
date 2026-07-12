"""Testy deterministycznych miniaturek i contact sheets FFmpeg."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "create-property-walkthrough" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import _media  # noqa: E402
import ingest_images  # noqa: E402
import make_contact_sheet  # noqa: E402


def _make_image(path: Path, *, source: str = "testsrc2", size: str = "120x80") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if source == "testsrc2":
        expression = "testsrc2=s={}:r=1".format(size)
    else:
        expression = "color=c={}:s={}:r=1".format(source, size)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            expression,
            "-frames:v",
            "1",
            "-update",
            "1",
            str(path),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        timeout=30,
    )


def _inject_orientation(jpeg_path: Path, orientation: int) -> None:
    raw = jpeg_path.read_bytes()
    tiff = (
        b"MM"
        + struct.pack(">H", 42)
        + struct.pack(">I", 8)
        + struct.pack(">H", 1)
        + struct.pack(">HHI", 0x0112, 3, 1)
        + struct.pack(">H", orientation)
        + b"\x00\x00"
        + struct.pack(">I", 0)
    )
    payload = b"Exif\x00\x00" + tiff
    segment = b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    jpeg_path.write_bytes(raw[:2] + segment + raw[2:])


class ContactSheetTests(unittest.TestCase):
    """Contact sheet ma stały układ i osobny indeks bez modyfikacji źródeł."""

    def test_mieszany_jpeg_png_polska_sciezka_i_determinizm(self) -> None:
        with tempfile.TemporaryDirectory(prefix="contact-łódź-") as temporary:
            root = Path(temporary)
            first = root / "źródła" / "łazienka.png"
            second = root / "źródła" / "żółty-salon.jpg"
            output_a = root / "wyniki" / "contact sheet żółty.jpg"
            output_b = root / "wyniki" / "contact sheet powtórka.jpg"
            index = root / "wyniki" / "indeks.json"
            _make_image(first, source="testsrc2", size="120x80")
            _make_image(second, source="blue", size="80x120")
            source_hashes = {
                first: hashlib.sha256(first.read_bytes()).hexdigest(),
                second: hashlib.sha256(second.read_bytes()).hexdigest(),
            }

            result_a = make_contact_sheet.make_contact_sheet(
                [second, first],
                output_a,
                columns=2,
                cell_width=160,
                cell_height=120,
                index_path=index,
            )
            result_b = make_contact_sheet.make_contact_sheet(
                [first, second],
                output_b,
                columns=2,
                cell_width=160,
                cell_height=120,
            )

            self.assertEqual((result_a["width"], result_a["height"]), (320, 120))
            self.assertEqual(_media.probe_image(output_a)["width"], 320)
            self.assertEqual(_media.probe_image(output_a)["height"], 120)
            self.assertEqual(result_a["contact_sheet_sha256"], result_b["contact_sheet_sha256"])
            self.assertEqual([cell["asset_id"] for cell in result_a["cells"]], sorted(source_hashes.values()))
            self.assertEqual(json.loads(index.read_text(encoding="utf-8"))["image_count"], 2)
            for source, digest in source_hashes.items():
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), digest)

    def test_orientation_exif_jest_odczytana_i_ffmpeg_tworzyl_arkusz(self) -> None:
        with tempfile.TemporaryDirectory(prefix="contact-orientacja-") as temporary:
            root = Path(temporary)
            source = root / "pion-po-exif.jpg"
            output = root / "arkusz.png"
            _make_image(source, source="green", size="80x40")
            _inject_orientation(source, 6)

            details = _media.probe_image(source)
            self.assertEqual(details["orientation"], 6)
            self.assertEqual((details["width"], details["height"]), (80, 40))
            result = make_contact_sheet.make_contact_sheet(
                [source], output, columns=1, cell_width=100, cell_height=100
            )

            self.assertEqual((result["width"], result["height"]), (100, 100))
            self.assertEqual(_media.probe_image(output)["format"], "png")
            self.assertEqual(result["cells"][0]["source_sha256"], _media.sha256_file(source))

    def test_ingestion_tworzy_sheet_i_indeks_dla_unikalnych_assetow(self) -> None:
        with tempfile.TemporaryDirectory(prefix="contact-ingestion-") as temporary:
            root = Path(temporary)
            source = root / "zdjęcia"
            output = root / "projekt" / "images"
            _make_image(source / "kuchnia.png", source="red")
            _make_image(source / "salon.jpg", source="testsrc2")

            manifest = ingest_images.ingest_images(source, output)

            self.assertEqual(len(manifest["contact_sheets"]), 1)
            sheet = manifest["contact_sheets"][0]
            self.assertTrue(Path(sheet["path"]).is_file())
            self.assertTrue(Path(sheet["index_path"]).is_file())
            index = json.loads(Path(sheet["index_path"]).read_text(encoding="utf-8"))
            self.assertEqual(index["image_count"], len(manifest["assets"]))
            self.assertEqual(
                {cell["asset_id"] for cell in index["cells"]},
                {asset["asset_id"] for asset in manifest["assets"]},
            )
            self.assertTrue(
                all(
                    Path(cell["source_path"]).parent.resolve()
                    == (output / "originals").resolve()
                    for cell in index["cells"]
                )
            )

    def test_blad_nie_nadpisuje_zrodla_ani_poprzedniego_wyniku(self) -> None:
        with tempfile.TemporaryDirectory(prefix="contact-błąd-") as temporary:
            root = Path(temporary)
            source = root / "obraz.png"
            corrupt = root / "uszkodzony.png"
            output = root / "istniejący.jpg"
            _make_image(source)
            corrupt.write_bytes(b"\x89PNG\r\n\x1a\n" + "ucięte".encode("utf-8"))
            output.write_bytes(b"poprzedni wynik")
            previous = output.read_bytes()

            with self.assertRaises(make_contact_sheet.ContactSheetError):
                make_contact_sheet.make_contact_sheet([corrupt], output)
            self.assertEqual(output.read_bytes(), previous)

            with self.assertRaises(make_contact_sheet.ContactSheetError):
                make_contact_sheet.make_contact_sheet([source], source)
            self.assertTrue(source.is_file())

            index = root / "indeks.json"
            index.write_text('{"old": true}\n', encoding="utf-8")
            with mock.patch.object(
                make_contact_sheet,
                "atomic_write_json",
                side_effect=OSError("kontrolowany błąd indeksu"),
            ):
                with self.assertRaises(OSError):
                    make_contact_sheet.make_contact_sheet(
                        [source],
                        output,
                        index_path=index,
                    )
            self.assertEqual(output.read_bytes(), previous)
            self.assertEqual(index.read_text(encoding="utf-8"), '{"old": true}\n')

    def test_limit_lacznej_liczby_pikseli_blokuje_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory(prefix="contact-pixels-") as temporary:
            root = Path(temporary)
            images = []
            for index in range(16):
                path = root / "source-{}.png".format(index)
                path.write_bytes(b"syntetyczny-placeholder")
                images.append({"asset_id": "{:064x}".format(index), "original_path": str(path)})

            with mock.patch.object(
                make_contact_sheet,
                "probe_image",
                return_value={"width": 1, "height": 1},
            ), mock.patch.object(
                make_contact_sheet,
                "validate_image_decodable",
            ), mock.patch.object(
                make_contact_sheet,
                "run_ffmpeg",
                side_effect=AssertionError("FFmpeg nie powinien zostać uruchomiony"),
            ):
                with self.assertRaisesRegex(
                    make_contact_sheet.ContactSheetError,
                    "100 milionów pikseli",
                ):
                    make_contact_sheet.make_contact_sheet(
                        images,
                        root / "arkusz.png",
                        columns=4,
                        cell_width=4096,
                        cell_height=4096,
                    )

    def test_publikacja_pary_przywraca_poprzednie_pliki(self) -> None:
        with tempfile.TemporaryDirectory(prefix="contact-pair-") as temporary:
            root = Path(temporary)
            staged_sheet = root / ".sheet.tmp.jpg"
            staged_index = root / ".index.tmp.json"
            sheet = root / "sheet.jpg"
            index = root / "index.json"
            staged_sheet.write_bytes(b"nowy arkusz")
            staged_index.write_bytes(b"nowy indeks")
            sheet.write_bytes(b"stary arkusz")
            index.write_bytes(b"stary indeks")
            real_replace = make_contact_sheet.os.replace

            def controlled_replace(source: str, destination: str) -> None:
                if Path(source) == staged_index and Path(destination) == index:
                    raise OSError("kontrolowany błąd publikacji indeksu")
                real_replace(source, destination)

            with mock.patch.object(
                make_contact_sheet.os,
                "replace",
                side_effect=controlled_replace,
            ):
                with self.assertRaises(OSError):
                    make_contact_sheet._publish_staged_outputs(
                        [(staged_sheet, sheet), (staged_index, index)]
                    )

            self.assertEqual(sheet.read_bytes(), b"stary arkusz")
            self.assertEqual(index.read_bytes(), b"stary indeks")


if __name__ == "__main__":
    unittest.main()
