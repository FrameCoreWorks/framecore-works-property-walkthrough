"""Testy UTF-8 i wymaganych polskich znaków."""

from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TestLanguage(unittest.TestCase):
    def test_dokumentacja_jest_utf8_i_ma_polskie_znaki(self):
        znaki = set("ąćęłńóśźż")
        tekst = ""
        for sciezka in [ROOT / "README.md", ROOT / "AGENTS.md"]:
            tekst += sciezka.read_text(encoding="utf-8").lower()
        self.assertTrue(znaki.issubset(set(tekst)))

    def test_sciezka_z_polskimi_znakami(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory(prefix="test-łazienka-żółta-") as katalog:
            sciezka = Path(katalog) / "ą_ć_ę_ł_ń_ó_ś_ź_ż.txt"
            sciezka.write_text("Zażółć gęślą jaźń", encoding="utf-8")
            self.assertEqual("Zażółć gęślą jaźń", sciezka.read_text(encoding="utf-8"))

    def test_pomoc_cli_jest_w_calosci_po_polsku(self):
        scripts = ROOT / "skills" / "create-property-walkthrough" / "scripts"
        names = (
            "init_project.py",
            "update_manifest.py",
            "extract_listing.py",
            "ingest_images.py",
            "make_contact_sheet.py",
            "apply_image_analysis.py",
            "prepare_generation_package.py",
            "configure_provider.py",
            "validate_provider.py",
            "prepare_upload_derivatives.py",
            "import_clips.py",
            "render_walkthrough.py",
            "validate_output.py",
        )
        for name in names:
            with self.subTest(script=name):
                completed = subprocess.run(
                    [sys.executable, "-B", str(scripts / name), "--help"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertIn("użycie:", completed.stdout)
                self.assertIn("opcje:", completed.stdout)
                self.assertIn("Pokaż tę pomoc i zakończ.", completed.stdout)
                self.assertNotIn("show this help message", completed.stdout)


if __name__ == "__main__":
    unittest.main()
