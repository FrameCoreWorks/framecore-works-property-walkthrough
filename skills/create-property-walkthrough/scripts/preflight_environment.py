#!/usr/bin/env python3
"""Read-only preflight lokalnego środowiska skilla walkthrough."""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from _common import PolishArgumentParser
from _media import MediaError, media_tool_paths, run_checked


MODES = ("plan_only", "manual_clips", "full_production")
MINIMUM_PYTHON = (3, 9)


def _tool_status(name: str, path: Optional[str]) -> Dict[str, Any]:
    """Sprawdź tylko wykryty plik wykonywalny i jego lokalny wynik -version."""

    if path is None:
        return {
            "available": False,
            "path": None,
            "version": None,
            "error": f"Nie znaleziono {name} w PATH.",
        }
    try:
        result = run_checked(
            [path, "-version"],
            timeout=10,
            max_stdout_bytes=128 * 1024,
            max_stderr_bytes=128 * 1024,
        )
        first_line = next(
            (line.strip() for line in result.stdout.splitlines() if line.strip()),
            "",
        )
        if not first_line:
            raise MediaError(f"{name} nie zwrócił informacji o wersji.")
        return {
            "available": True,
            "path": str(Path(path)),
            "version": first_line,
            "error": None,
        }
    except (MediaError, OSError, ValueError) as exc:
        return {
            "available": False,
            "path": str(Path(path)),
            "version": None,
            "error": str(exc),
        }


def preflight_environment(mode: str = "full_production") -> Dict[str, Any]:
    """Zwróć deterministyczny raport możliwości bez zmiany środowiska."""

    if mode not in MODES:
        raise ValueError("Nieobsługiwany tryb preflight: " + str(mode))
    python_ready = sys.version_info[:2] >= MINIMUM_PYTHON
    detected = media_tool_paths()
    tools = {
        name: _tool_status(name, detected.get(name))
        for name in ("ffmpeg", "ffprobe")
    }
    media_required = mode in {"manual_clips", "full_production"}
    missing = [name for name, status in tools.items() if not status["available"]]
    blockers = []
    if not python_ready:
        blockers.append("Wymagany jest Python 3.9 lub nowszy.")
    if media_required and missing:
        blockers.append(
            "Brakuje narzędzi wymaganych dla wybranego trybu: " + ", ".join(missing) + "."
        )
    return {
        "schema_version": 1,
        "mode": mode,
        "ready": not blockers,
        "platform": {
            "system": platform.system() or "unknown",
            "release": platform.release() or "unknown",
            "machine": platform.machine() or "unknown",
        },
        "python": {
            "version": platform.python_version(),
            "minimum": "3.9",
            "ready": python_ready,
        },
        "media_required": media_required,
        "tools": tools,
        "blockers": blockers,
        "actions_performed": [],
        "network_calls": 0,
        "installation_attempts": 0,
    }


def build_parser() -> argparse.ArgumentParser:
    """Zbuduj polski interfejs preflightu."""

    parser = PolishArgumentParser(
        description=(
            "Sprawdź lokalny Python, system, FFmpeg i ffprobe bez instalacji, "
            "sieci ani modyfikowania PATH."
        )
    )
    parser.add_argument("--mode", choices=MODES, default="full_production")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Wypisz pełny raport JSON zamiast krótkiego podsumowania.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Uruchom read-only preflight i zwróć 0 tylko dla gotowego trybu."""

    args = build_parser().parse_args(argv)
    report = preflight_environment(args.mode)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    elif report["ready"]:
        print(f"Środowisko jest gotowe dla trybu {args.mode}.")
    else:
        print("Środowisko nie jest gotowe: " + " ".join(report["blockers"]))
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
