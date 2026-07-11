"""Testy intencji aktywacji i braku aktywacji."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TestActivationContract(unittest.TestCase):
    def setUp(self):
        self.skill = (
            ROOT / "skills" / "create-property-walkthrough" / "SKILL.md"
        ).read_text(encoding="utf-8")

    def test_opis_zawiera_pozytywne_intencje(self):
        for fraza in [
            "linku do polskiego ogłoszenia",
            "wgranych zdjęć",
            "archiwum ZIP",
            "wznowić projekt",
            "regenerować wybrane sceny",
            "16:9 i 9:16",
        ]:
            self.assertIn(fraza, self.skill)

    def test_negatywne_intencje_sa_wykluczone(self):
        for fraza in ["Nie wyszukuj ofert", "Nie nazywaj wyniku rekonstrukcją 3D"]:
            self.assertIn(fraza, self.skill)


if __name__ == "__main__":
    unittest.main()
