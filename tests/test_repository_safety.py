"""Statyczne testy bezpieczeństwa repozytorium i pakietu skilla."""

import ast
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "create-property-walkthrough" / "scripts"
DOZWOLONE_ASSETY_DOKUMENTACYJNE = {
    "docs/assets/property-walkthrough-hero.png",
}


class TestRepositorySafety(unittest.TestCase):
    def test_brak_zakazanych_assetow_i_appledouble(self):
        zakazane = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".env"}
        znalezione = []
        for sciezka in ROOT.rglob("*"):
            if not sciezka.is_file():
                continue
            relatywna = str(sciezka.relative_to(ROOT))
            if sciezka.name.startswith("._"):
                znalezione.append(relatywna)
            if (
                sciezka.suffix.lower() in zakazane
                and sciezka.name != ".env.example"
                and relatywna not in DOZWOLONE_ASSETY_DOKUMENTACYJNE
            ):
                znalezione.append(relatywna)
        self.assertEqual([], znalezione)

    def test_helpery_nie_importuja_powierzchni_sieciowych(self):
        zakazane = {"socket", "requests", "http.client", "urllib.request", "aiohttp"}
        naruszenia = []
        for sciezka in SCRIPTS.glob("*.py"):
            drzewo = ast.parse(sciezka.read_text(encoding="utf-8"), filename=str(sciezka))
            for wezel in ast.walk(drzewo):
                if isinstance(wezel, ast.Import):
                    for alias in wezel.names:
                        if alias.name in zakazane:
                            naruszenia.append(f"{sciezka.name}:{alias.name}")
                elif isinstance(wezel, ast.ImportFrom):
                    modul = wezel.module or ""
                    if modul in zakazane:
                        naruszenia.append(f"{sciezka.name}:{modul}")
        self.assertEqual([], naruszenia)

    def test_brak_shell_true_eval_i_exec(self):
        naruszenia = []
        for sciezka in SCRIPTS.glob("*.py"):
            drzewo = ast.parse(sciezka.read_text(encoding="utf-8"), filename=str(sciezka))
            for wezel in ast.walk(drzewo):
                if isinstance(wezel, ast.Call):
                    if isinstance(wezel.func, ast.Name) and wezel.func.id in {"eval", "exec"}:
                        naruszenia.append(f"{sciezka.name}:{wezel.lineno}:{wezel.func.id}")
                    for argument in wezel.keywords:
                        if (
                            argument.arg == "shell"
                            and isinstance(argument.value, ast.Constant)
                            and argument.value.value is True
                        ):
                            naruszenia.append(f"{sciezka.name}:{wezel.lineno}:shell=True")
        self.assertEqual([], naruszenia)

    def test_brak_prawdopodobnych_sekretow(self):
        wzorce = [
            re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
            re.compile(r"(?i)(?:api[_-]?key|token|secret)\s*[:=]\s*['\"][^'\"]{12,}['\"]"),
        ]
        naruszenia = []
        for sciezka in ROOT.rglob("*"):
            if not sciezka.is_file() or ".git" in sciezka.parts:
                continue
            if sciezka.suffix.lower() not in {".py", ".md", ".json", ".yaml", ".yml", ".example"}:
                continue
            tekst = sciezka.read_text(encoding="utf-8", errors="replace")
            for wzorzec in wzorce:
                if wzorzec.search(tekst):
                    naruszenia.append(str(sciezka.relative_to(ROOT)))
                    break
        self.assertEqual([], naruszenia)

    def test_brak_upstream_remote_w_dokumentach_konfiguracyjnych_git(self):
        git_dir = ROOT / ".git"
        if not git_dir.exists():
            self.skipTest("Repo Git nie zostało jeszcze zainicjalizowane")
        config = (git_dir / "config").read_text(encoding="utf-8")
        self.assertNotIn("charlesdove977/re-walkthrough-pro.git", config)


if __name__ == "__main__":
    unittest.main()
