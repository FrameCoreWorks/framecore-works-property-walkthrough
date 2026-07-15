"""Testy licencji własnej i opisowej atrybucji projektu referencyjnego."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
class TestLicenses(unittest.TestCase):
    def test_root_license_framecore(self):
        tekst = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("Copyright (c) 2026 FrameCore Works", tekst)
        self.assertNotIn("Charles J Dove", tekst)

    def test_repo_nie_kopiuje_licencji_projektu_referencyjnego(self):
        self.assertFalse((ROOT / "licenses" / "re-walkthrough-pro-MIT.txt").exists())
        self.assertFalse((ROOT / "THIRD_PARTY_NOTICES.md").exists())

    def test_deklaracja_relacji(self):
        tekst = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("niezależną implementacją", tekst)
        self.assertIn("RE Walkthrough Pro", tekst)
        self.assertIn("Charlesa J. Dove'a", tekst)
        self.assertIn("nie jest forkiem", tekst)
        self.assertIn("nie kopiuje kodu", tekst)
        self.assertIn("nie kopiuje kodu,\nhistorii Git, licencji ani materiałów", tekst)


if __name__ == "__main__":
    unittest.main()
