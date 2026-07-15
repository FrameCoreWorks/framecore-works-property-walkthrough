"""Testy read-only wykrywania możliwości środowiska."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "create-property-walkthrough" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import preflight_environment as preflight  # noqa: E402


def _version_result(path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        [path, "-version"],
        0,
        stdout=f"{Path(path).name} version test\n",
        stderr="",
    )


class PreflightEnvironmentTests(unittest.TestCase):
    def test_plan_only_nie_wymaga_narzedzi_multimedialnych(self) -> None:
        with mock.patch.object(
            preflight, "media_tool_paths", return_value={"ffmpeg": None, "ffprobe": None}
        ):
            report = preflight.preflight_environment("plan_only")
        self.assertTrue(report["ready"])
        self.assertFalse(report["media_required"])
        self.assertEqual(0, report["network_calls"])
        self.assertEqual(0, report["installation_attempts"])
        self.assertEqual([], report["actions_performed"])

    def test_full_production_wymaga_ffmpeg_i_ffprobe(self) -> None:
        with mock.patch.object(
            preflight, "media_tool_paths", return_value={"ffmpeg": None, "ffprobe": None}
        ):
            report = preflight.preflight_environment("full_production")
        self.assertFalse(report["ready"])
        self.assertIn("ffmpeg", report["blockers"][0])
        self.assertIn("ffprobe", report["blockers"][0])

    def test_wykryte_narzedzia_sa_sprawdzane_bez_powloki(self) -> None:
        paths = {"ffmpeg": "/tools/ffmpeg", "ffprobe": "/tools/ffprobe"}
        with mock.patch.object(preflight, "media_tool_paths", return_value=paths), mock.patch.object(
            preflight, "run_checked", side_effect=lambda args, **_: _version_result(args[0])
        ) as runner:
            report = preflight.preflight_environment("manual_clips")
        self.assertTrue(report["ready"])
        self.assertEqual(2, runner.call_count)
        self.assertEqual(["/tools/ffmpeg", "-version"], runner.call_args_list[0].args[0])

    def test_blad_wersji_narzedzia_jest_fail_closed(self) -> None:
        paths = {"ffmpeg": "/tools/ffmpeg", "ffprobe": "/tools/ffprobe"}
        with mock.patch.object(preflight, "media_tool_paths", return_value=paths), mock.patch.object(
            preflight, "run_checked", side_effect=preflight.MediaError("timeout")
        ):
            report = preflight.preflight_environment("manual_clips")
        self.assertFalse(report["ready"])
        self.assertEqual("timeout", report["tools"]["ffmpeg"]["error"])

    def test_cli_json_ma_stabilny_kod_wyjscia(self) -> None:
        fake = {
            "schema_version": 1,
            "mode": "plan_only",
            "ready": True,
            "blockers": [],
        }
        with mock.patch.object(preflight, "preflight_environment", return_value=fake), mock.patch(
            "builtins.print"
        ) as printer:
            code = preflight.main(["--mode", "plan_only", "--json"])
        self.assertEqual(0, code)
        self.assertEqual(fake, json.loads(printer.call_args.args[0]))


if __name__ == "__main__":
    unittest.main()
