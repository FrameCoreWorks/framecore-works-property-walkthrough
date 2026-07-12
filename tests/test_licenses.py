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
        deklaracja = (
            "FrameCore Works Property Walkthrough to niezależnie opracowany skill Codexa, "
            "koncepcyjnie i architektonicznie inspirowany projektem RE Walkthrough Pro "
            "autorstwa Charlesa J. Dove'a. Projekt nie jest forkiem i nie zachowuje ani "
            "nie modyfikuje historii Git oryginalnego repozytorium."
        )
        tekst = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(deklaracja, tekst)
        self.assertIn("Podziękowania dla Charlesa J. Dove'a", tekst)


if __name__ == "__main__":
    unittest.main()
