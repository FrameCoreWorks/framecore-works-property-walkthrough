"""Wspólne syntetyczne fixture'y multimedialne dla testów."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import unittest
from typing import Optional


def require_media_tools() -> None:
    """Pomiń test, gdy środowisko nie udostępnia narzędzi multimedialnych."""

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise unittest.SkipTest("Test wymaga narzędzi multimedialnych Codexa.")


def make_image(
    path: Path,
    *,
    color: str = "red",
    source: Optional[str] = None,
    size: str = "96x64",
) -> None:
    """Utwórz mały syntetyczny obraz bez danych użytkownika."""

    require_media_tools()
    path.parent.mkdir(parents=True, exist_ok=True)
    if source == "testsrc2":
        expression = "testsrc2=s={}:r=1".format(size)
    else:
        expression = "color=c={}:s={}:r=1".format(source or color, size)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            expression,
            "-frames:v",
            "1",
            "-update",
            "1",
            str(path),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        timeout=30,
    )
