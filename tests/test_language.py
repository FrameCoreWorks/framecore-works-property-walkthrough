"""Testy UTF-8 i wymaganych polskich znaków."""

from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
