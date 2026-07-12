"""Testy kontraktu pętli doprowadzającej projekt do wyniku."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TestGoalCompletionLoop(unittest.TestCase):
    def test_plan_definiuje_petle_i_prawdziwy_blocker(self):
        plan = (ROOT / "docs" / "build-plan.md").read_text(encoding="utf-8")
        self.assertIn("Status `blocked` nie jest równoważny `complete`", plan)
        self.assertIn("pełny suite", plan)
        self.assertIn("bez fałszywego PASS", plan)

    def test_skill_wznawia_pierwszy_niekompletny_etap(self):
        skill = (
            ROOT / "skills" / "create-property-walkthrough" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("pierwszy niekompletny etap", skill)
        self.assertIn("Pomijaj poprawne etapy", skill)
        self.assertIn("nie wysyłaj go ponownie automatycznie", skill.lower())

    def test_matrix_ma_wszystkie_id(self):
        plan = (ROOT / "docs" / "build-plan.md").read_text(encoding="utf-8")
        for numer in range(1, 52):
            self.assertIn(f"R{numer:03d}", plan)


if __name__ == "__main__":
    unittest.main()
