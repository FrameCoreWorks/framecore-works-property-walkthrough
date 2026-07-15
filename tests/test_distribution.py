"""Testy kontraktu dystrybucji pluginu i marketplace."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_PATH = ROOT / ".codex-plugin" / "plugin.json"
MARKETPLACE_PATH = ROOT / ".agents" / "plugins" / "marketplace.json"


class DistributionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plugin = json.loads(PLUGIN_PATH.read_text(encoding="utf-8"))
        self.marketplace = json.loads(MARKETPLACE_PATH.read_text(encoding="utf-8"))

    def test_marketplace_ma_jeden_plugin_zdalny_przypiety_do_wydania(self) -> None:
        self.assertEqual("framecore-works", self.marketplace["name"])
        self.assertEqual(1, len(self.marketplace["plugins"]))
        entry = self.marketplace["plugins"][0]
        self.assertEqual(self.plugin["name"], entry["name"])
        self.assertEqual("url", entry["source"]["source"])
        self.assertEqual(
            "https://github.com/FrameCoreWorks/framecore-works-property-walkthrough.git",
            entry["source"]["url"],
        )
        self.assertEqual("v1.1.0", entry["source"]["ref"])
        self.assertEqual("AVAILABLE", entry["policy"]["installation"])
        self.assertEqual("ON_USE", entry["policy"]["authentication"])

    def test_wersja_i_metadane_sa_spojne(self) -> None:
        self.assertEqual("1.1.0", self.plugin["version"])
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("## 1.1.0 - 2026-07-15", changelog)
        self.assertIn("--ref v1.1.0", readme)
        self.assertNotIn("Najpierw zapytaj mnie o dostawcę", json.dumps(self.plugin))

    def test_plugin_nie_bundluje_providera_mcp_ani_aplikacji(self) -> None:
        self.assertNotIn("mcpServers", self.plugin)
        self.assertNotIn("apps", self.plugin)
        self.assertEqual("./skills/", self.plugin["skills"])
        skill_directories = [
            path for path in (ROOT / "skills").iterdir() if path.is_dir()
        ]
        self.assertEqual(["create-property-walkthrough"], [path.name for path in skill_directories])

    def test_readme_nie_obiecuje_instalacji_przez_samo_wklejenie_url(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("nie jest\ngwarantowaną ścieżką instalacji", readme)
        self.assertIn("katalog Plugins", readme)
        self.assertIn("codex plugin marketplace add", readme)


if __name__ == "__main__":
    unittest.main()
