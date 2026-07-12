"""Testy struktury i metadanych skilla."""

import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "create-property-walkthrough"


class TestSkillStructure(unittest.TestCase):
    def test_wymagane_pliki_istnieja(self):
        wymagane = [
            SKILL / "SKILL.md",
            SKILL / "agents" / "openai.yaml",
            ROOT / ".codex-plugin" / "plugin.json",
            ROOT / "README.md",
            ROOT / "LICENSE",
            ROOT / "CONTRIBUTING.md",
            ROOT / "SECURITY.md",
            ROOT / ".github" / "workflows" / "ci.yml",
            ROOT / ".github" / "pull_request_template.md",
            ROOT / "docs" / "design-synthesis.md",
            ROOT / "docs" / "build-plan.md",
        ]
        for sciezka in wymagane:
            self.assertTrue(sciezka.is_file(), str(sciezka))

    def test_frontmatter_ma_tylko_name_i_description(self):
        tekst = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        match = re.match(r"\A---\n(.*?)\n---\n", tekst, re.DOTALL)
        self.assertIsNotNone(match)
        klucze = [
            line.split(":", 1)[0]
            for line in match.group(1).splitlines()
            if line and not line.startswith(" ")
        ]
        self.assertEqual(["name", "description"], klucze)

    def test_brak_placeholderow(self):
        for sciezka in SKILL.rglob("*"):
            if sciezka.is_file() and sciezka.suffix in {".md", ".yaml", ".json", ".py"}:
                tekst = sciezka.read_text(encoding="utf-8")
                self.assertNotIn("TODO", tekst, str(sciezka))
                self.assertNotIn("[TODO", tekst, str(sciezka))

    def test_skill_md_ponizej_500_linii(self):
        linie = (SKILL / "SKILL.md").read_text(encoding="utf-8").splitlines()
        self.assertLess(len(linie), 500)

    def test_implicit_invocation_wlaczone(self):
        tekst = (SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("allow_implicit_invocation: true", tekst)
        self.assertIn("$create-property-walkthrough", tekst)

    def test_readme_ma_wylacznie_instalacje_chatgpt_codex_native(self):
        tekst = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("## Instalacja w ChatGPT i Codexie", tekst)
        self.assertIn(
            "https://github.com/FrameCoreWorks/framecore-works-property-walkthrough",
            tekst,
        )
        for niedozwolone in ("$CODEX_HOME/skills", "git clone", "setup.sh", "WSL", "apt install", "brew install"):
            self.assertNotIn(niedozwolone, tekst)

    def test_plugin_manifest_wskazuje_skill_i_nie_bundluje_providera(self):
        manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "framecore-works-property-walkthrough")
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertIn("interface", manifest)
        self.assertIn("defaultPrompt", manifest["interface"])
        serialized = json.dumps(manifest, ensure_ascii=False)
        self.assertIn("Najpierw zapytaj mnie o dostawcę MCP/API", serialized)
        self.assertNotIn("mcpServers", manifest)
        self.assertNotIn("apps", manifest)

    def test_pierwsze_uzycie_pyta_o_dostawce(self):
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        onboarding = (SKILL / "references" / "provider-onboarding.md").read_text(encoding="utf-8")
        metadata = (SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("Przy pierwszym użyciu po instalacji", skill)
        self.assertIn("zadaj dokładnie pytanie o dostawcę MCP/API", skill)
        self.assertIn("Jakiego dostawcę MCP lub API chcesz skonfigurować", onboarding)
        self.assertIn("Najpierw zapytaj mnie o dostawcę MCP/API", metadata)

    def test_link_mode_probuje_publiczne_zdjecia_bez_obejsc(self):
        ingestion = (SKILL / "references" / "input-ingestion.md").read_text(encoding="utf-8")
        portals = (SKILL / "references" / "polish-portals.md").read_text(encoding="utf-8")
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("listing.images", ingestion)
        self.assertIn("ChatGPT/Codex web/browser/file", ingestion)
        self.assertIn("ingest_images.py", ingestion)
        self.assertIn("Otodom", portals)
        self.assertIn("nie używaj cookies, stealth, proxy", portals)
        self.assertIn("Nie buduj adaptera konkretnego portalu", portals)
        self.assertIn("spróbuj pobrać te zdjęcia przez zaufaną powierzchnię", skill)

    def test_ci_obejmuje_windows_i_macos(self):
        tekst = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("windows-latest", tekst)
        self.assertIn("macos-latest", tekst)
        self.assertIn("permissions:\n  contents: read", tekst)


if __name__ == "__main__":
    unittest.main()
