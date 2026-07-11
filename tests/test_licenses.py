"""Testy rozdzielenia i integralności licencji."""

from hashlib import sha256
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_SHA256 = "b90a73d4456be28b8f67e1389ca9c7aa63d7662352b95c1dcc03df311d5c0faa"
UPSTREAM_BLOB = "32afdb15575f01b5ffb471ecceb2a8d88855e7e7"


class TestLicenses(unittest.TestCase):
    def test_root_license_framecore(self):
        tekst = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("Copyright (c) 2026 FrameCore Works", tekst)
        self.assertNotIn("Charles J Dove", tekst)

    def test_upstream_license_verbatim(self):
        dane = (ROOT / "licenses" / "re-walkthrough-pro-MIT.txt").read_bytes()
        self.assertEqual(1071, len(dane))
        self.assertEqual(UPSTREAM_SHA256, sha256(dane).hexdigest())
        self.assertIn(b"Copyright (c) 2026 Charles J Dove", dane)

    def test_upstream_git_blob(self):
        sciezka = ROOT / "licenses" / "re-walkthrough-pro-MIT.txt"
        wynik = subprocess.run(
            ["git", "hash-object", str(sciezka)],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(UPSTREAM_BLOB, wynik.stdout.strip())

    def test_deklaracja_relacji(self):
        deklaracja = (
            "FrameCore Works Property Walkthrough to niezależnie opracowany skill Codexa, "
            "koncepcyjnie i architektonicznie inspirowany projektem RE Walkthrough Pro "
            "autorstwa Charlesa J. Dove'a. Projekt nie jest forkiem i nie zachowuje ani "
            "nie modyfikuje historii Git oryginalnego repozytorium."
        )
        for nazwa in ["README.md", "THIRD_PARTY_NOTICES.md"]:
            tekst = (ROOT / nazwa).read_text(encoding="utf-8")
            self.assertIn(deklaracja, tekst, nazwa)


if __name__ == "__main__":
    unittest.main()
