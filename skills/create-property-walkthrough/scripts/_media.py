#!/usr/bin/env python3
"""Bezpieczne, deterministyczne operacje na lokalnych plikach multimedialnych.

Moduł nie wykonuje połączeń sieciowych. Wszystkie procesy zewnętrzne są
uruchamiane bez powłoki, z ograniczeniem czasu i przechwyceniem diagnostyki.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import struct
import subprocess
import tempfile
import threading
import time
from typing import Any, BinaryIO, Dict, List, Optional, Sequence, Union
import uuid
import zlib


DEFAULT_MAX_IMAGE_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_PIXELS = 100_000_000
DEFAULT_MAX_DIMENSION = 32_768
DEFAULT_MAX_HEADER_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_STDOUT_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_STDERR_BYTES = 1024 * 1024

_JPEG_SOF_MARKERS = {
    0xC0,
    0xC1,
    0xC2,
    0xC3,
    0xC5,
    0xC6,
    0xC7,
    0xC9,
    0xCA,
    0xCB,
    0xCD,
    0xCE,
    0xCF,
}


class MediaError(RuntimeError):
    """Błąd bezpiecznej walidacji albo lokalnej operacji multimedialnej."""


def media_tool_paths() -> Dict[str, Optional[str]]:
    """Wykryj lokalne narzędzia bez instalacji, sieci ani zmiany PATH."""

    return {name: shutil.which(name) for name in ("ffmpeg", "ffprobe")}


def require_media_tools() -> Dict[str, str]:
    """Zatrzymaj etap multimedialny z jednoznaczną listą braków."""

    detected = media_tool_paths()
    missing = [name for name, path in detected.items() if path is None]
    if missing:
        raise MediaError(
            "Brakuje wymaganych programów systemowych: {}. "
            "Uruchom preflight i udostępnij je w PATH przed etapem multimedialnym.".format(
                ", ".join(missing)
            )
        )
    return {name: str(path) for name, path in detected.items() if path is not None}


def _regular_file(path: Path) -> os.stat_result:
    """Zwróć metadane zwykłego pliku, nie podążając za dowiązaniami."""

    try:
        metadata = path.lstat()
    except OSError as exc:
        raise MediaError("Nie można odczytać pliku multimedialnego: {}".format(path)) from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise MediaError("Dowiązania symboliczne nie są dozwolone: {}".format(path))
    if not stat.S_ISREG(metadata.st_mode):
        raise MediaError("Oczekiwano zwykłego pliku: {}".format(path))
    return metadata


def sha256_file(path: Union[os.PathLike[str], str], *, max_bytes: Optional[int] = None) -> str:
    """Oblicz SHA-256 zwykłego pliku z opcjonalnym twardym limitem bajtów."""

    source = Path(path)
    metadata = _regular_file(source)
    if max_bytes is not None:
        if max_bytes < 0:
            raise ValueError("Limit bajtów nie może być ujemny.")
        if metadata.st_size > max_bytes:
            raise MediaError(
                "Plik przekracza limit {} bajtów: {}".format(max_bytes, source)
            )

    digest = hashlib.sha256()
    read_bytes = 0
    try:
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                read_bytes += len(chunk)
                if max_bytes is not None and read_bytes > max_bytes:
                    raise MediaError(
                        "Plik urósł podczas odczytu i przekroczył limit: {}".format(source)
                    )
                digest.update(chunk)
    except MediaError:
        raise
    except OSError as exc:
        raise MediaError("Nie można obliczyć SHA-256 pliku: {}".format(source)) from exc
    return digest.hexdigest()


def _validate_dimensions(width: int, height: int, *, max_pixels: int) -> None:
    if width <= 0 or height <= 0:
        raise MediaError("Obraz ma nieprawidłowe wymiary.")
    if width > DEFAULT_MAX_DIMENSION or height > DEFAULT_MAX_DIMENSION:
        raise MediaError("Wymiar obrazu przekracza bezpieczny limit.")
    if width * height > max_pixels:
        raise MediaError("Liczba pikseli obrazu przekracza bezpieczny limit.")


def _exif_orientation(segment: bytes) -> Optional[int]:
    """Odczytaj orientację z ograniczonego segmentu EXIF bez biblioteki obrazowej."""

    if not segment.startswith(b"Exif\x00\x00"):
        return None
    tiff = segment[6:]
    if len(tiff) < 8:
        raise MediaError("Segment EXIF jest ucięty.")
    if tiff[:2] == b"II":
        endian = "<"
    elif tiff[:2] == b"MM":
        endian = ">"
    else:
        raise MediaError("Segment EXIF ma nieznaną kolejność bajtów.")
    if struct.unpack(endian + "H", tiff[2:4])[0] != 42:
        raise MediaError("Segment EXIF ma nieprawidłowy nagłówek TIFF.")
    offset = struct.unpack(endian + "I", tiff[4:8])[0]
    if offset > len(tiff) - 2:
        raise MediaError("Segment EXIF wskazuje poza zakresem danych.")
    count = struct.unpack(endian + "H", tiff[offset : offset + 2])[0]
    if count > 1024:
        raise MediaError("Segment EXIF zawiera zbyt wiele wpisów.")
    cursor = offset + 2
    end = cursor + count * 12
    if end > len(tiff):
        raise MediaError("Tabela EXIF jest ucięta.")
    for index in range(count):
        entry = tiff[cursor + index * 12 : cursor + (index + 1) * 12]
        tag, value_type, value_count = struct.unpack(endian + "HHI", entry[:8])
        if tag != 0x0112:
            continue
        if value_type != 3 or value_count != 1:
            raise MediaError("Pole orientacji EXIF ma nieprawidłowy typ.")
        orientation = struct.unpack(endian + "H", entry[8:10])[0]
        if orientation not in range(1, 9):
            raise MediaError("Pole orientacji EXIF ma wartość spoza zakresu 1-8.")
        return orientation
    return None


def _probe_jpeg(data: bytes, *, complete_header: bool) -> Dict[str, int]:
    if not data.startswith(b"\xff\xd8"):
        raise MediaError("Plik nie ma sygnatury JPEG.")

    cursor = 2
    orientation = 1
    found_orientation = False
    while cursor < len(data):
        if data[cursor] != 0xFF:
            raise MediaError("Struktura markerów JPEG jest nieprawidłowa.")
        while cursor < len(data) and data[cursor] == 0xFF:
            cursor += 1
        if cursor >= len(data):
            break
        marker = data[cursor]
        cursor += 1

        if marker in {0x01, 0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if marker == 0xDA:
            raise MediaError("JPEG nie zawiera nagłówka wymiarów przed danymi obrazu.")
        if cursor + 2 > len(data):
            break
        segment_length = struct.unpack(">H", data[cursor : cursor + 2])[0]
        if segment_length < 2:
            raise MediaError("Segment JPEG ma nieprawidłową długość.")
        segment_end = cursor + segment_length
        if segment_end > len(data):
            break
        payload = data[cursor + 2 : segment_end]

        if marker == 0xE1 and not found_orientation:
            parsed_orientation = _exif_orientation(payload)
            if parsed_orientation is not None:
                orientation = parsed_orientation
                found_orientation = True

        if marker in _JPEG_SOF_MARKERS:
            if len(payload) < 6:
                raise MediaError("Nagłówek wymiarów JPEG jest ucięty.")
            height, width = struct.unpack(">HH", payload[1:5])
            return {"width": width, "height": height, "orientation": orientation}
        cursor = segment_end

    if complete_header:
        raise MediaError("Nie znaleziono wymiarów w pliku JPEG.")
    raise MediaError("Nagłówek JPEG przekracza bezpieczny limit odczytu.")


def _probe_png(data: bytes) -> Dict[str, int]:
    signature = b"\x89PNG\r\n\x1a\n"
    if not data.startswith(signature):
        raise MediaError("Plik nie ma sygnatury PNG.")
    if len(data) < 33:
        raise MediaError("Nagłówek PNG jest ucięty.")
    length = struct.unpack(">I", data[8:12])[0]
    if length != 13 or data[12:16] != b"IHDR":
        raise MediaError("Pierwszy segment PNG nie jest poprawnym IHDR.")
    payload = data[16:29]
    expected_crc = struct.unpack(">I", data[29:33])[0]
    actual_crc = zlib.crc32(b"IHDR" + payload) & 0xFFFFFFFF
    if actual_crc != expected_crc:
        raise MediaError("Suma kontrolna nagłówka PNG jest nieprawidłowa.")
    width, height = struct.unpack(">II", payload[:8])
    bit_depth = payload[8]
    color_type = payload[9]
    if bit_depth not in {1, 2, 4, 8, 16}:
        raise MediaError("PNG ma nieobsługiwaną głębię bitową.")
    if color_type not in {0, 2, 3, 4, 6}:
        raise MediaError("PNG ma nieobsługiwany typ koloru.")
    return {"width": width, "height": height, "orientation": 1}


def probe_image(
    path: Union[os.PathLike[str], str],
    *,
    max_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
    max_pixels: int = DEFAULT_MAX_PIXELS,
    max_header_bytes: int = DEFAULT_MAX_HEADER_BYTES,
) -> Dict[str, Any]:
    """Zweryfikuj rozszerzenie i magic bytes oraz bezpiecznie odczytaj wymiary.

    Funkcja nie dekoduje pikseli. Pełną dekodowalność można sprawdzić funkcją
    :func:`validate_image_decodable`, która korzysta z lokalnego FFmpeg.
    """

    source = Path(path)
    metadata = _regular_file(source)
    if metadata.st_size <= 0:
        raise MediaError("Plik obrazu jest pusty: {}".format(source))
    if metadata.st_size > max_bytes:
        raise MediaError("Obraz przekracza limit {} bajtów: {}".format(max_bytes, source))

    suffix = source.suffix.casefold()
    expected = {
        ".jpg": "jpeg",
        ".jpeg": "jpeg",
        ".png": "png",
    }.get(suffix)
    if expected is None:
        raise MediaError("Obsługiwane są wyłącznie pliki JPEG i PNG: {}".format(source))

    read_limit = min(metadata.st_size, max_header_bytes)
    try:
        with source.open("rb") as handle:
            header = handle.read(read_limit)
    except OSError as exc:
        raise MediaError("Nie można odczytać nagłówka obrazu: {}".format(source)) from exc

    if header.startswith(b"\xff\xd8"):
        detected = "jpeg"
        details = _probe_jpeg(header, complete_header=metadata.st_size <= read_limit)
    elif header.startswith(b"\x89PNG\r\n\x1a\n"):
        detected = "png"
        details = _probe_png(header)
    else:
        raise MediaError("Magic bytes nie wskazują na JPEG ani PNG: {}".format(source))
    if detected != expected:
        raise MediaError("Rozszerzenie pliku nie zgadza się z magic bytes: {}".format(source))

    _validate_dimensions(details["width"], details["height"], max_pixels=max_pixels)
    details.update(
        {
            "format": detected,
            "mime_type": "image/jpeg" if detected == "jpeg" else "image/png",
            "size_bytes": metadata.st_size,
        }
    )
    return details


def _diagnostic(stderr: str) -> str:
    compact = stderr.strip()
    if not compact:
        return "brak diagnostyki"
    return compact[-4000:]


def _minimal_environment() -> Dict[str, str]:
    """Zbuduj środowisko procesu bez sekretów i ustawień providerów."""

    allowed = {
        "COMSPEC",
        "LANG",
        "LC_ALL",
        "NUMBER_OF_PROCESSORS",
        "PATHEXT",
        "PATH",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "WINDIR",
    }
    environment = {
        key: value for key, value in os.environ.items() if key.upper() in allowed
    }
    if os.name != "nt":
        environment["LC_ALL"] = "C"
    return environment


def _read_bounded_stream(
    stream: BinaryIO,
    limit: int,
    chunks: List[bytes],
    exceeded: threading.Event,
) -> None:
    """Odczytuj pipe bez blokady, zachowując najwyżej wskazany limit bajtów."""

    total = 0
    try:
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                break
            remaining = max(0, limit - total)
            if remaining:
                chunks.append(chunk[:remaining])
            total += len(chunk)
            if total > limit:
                exceeded.set()
    finally:
        stream.close()


def _kill_process_tree(process: subprocess.Popen[bytes]) -> None:
    """Przerwij lokalny proces i jego grupę bez używania powłoki."""

    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        try:
            process.kill()
        except OSError:
            pass


def _run_bounded(
    args: Sequence[str],
    *,
    timeout: float,
    cwd: Optional[Union[os.PathLike[str], str]] = None,
    max_stdout_bytes: int = DEFAULT_MAX_STDOUT_BYTES,
    max_stderr_bytes: int = DEFAULT_MAX_STDERR_BYTES,
) -> subprocess.CompletedProcess[bytes]:
    """Uruchom argv-only proces z limitami czasu, środowiska i obu pipe'ów."""

    if not args or not all(isinstance(argument, str) and argument for argument in args):
        raise ValueError("Polecenie musi być niepustą listą niepustych argumentów tekstowych.")
    if timeout <= 0:
        raise ValueError("Limit czasu musi być dodatni.")
    for label, value in (
        ("stdout", max_stdout_bytes),
        ("stderr", max_stderr_bytes),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError("Limit {} musi być dodatnią liczbą całkowitą.".format(label))

    try:
        process = subprocess.Popen(
            list(args),
            cwd=str(cwd) if cwd is not None else None,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_minimal_environment(),
            shell=False,
            start_new_session=os.name != "nt",
        )
    except FileNotFoundError as exc:
        raise MediaError("Nie znaleziono wymaganego programu: {}".format(args[0])) from exc
    except OSError as exc:
        raise MediaError("Nie można uruchomić lokalnego programu: {}".format(args[0])) from exc

    if process.stdout is None or process.stderr is None:
        _kill_process_tree(process)
        raise MediaError("Nie udało się utworzyć ograniczonych pipe'ów procesu.")

    exceeded = threading.Event()
    stdout_chunks: List[bytes] = []
    stderr_chunks: List[bytes] = []
    readers = [
        threading.Thread(
            target=_read_bounded_stream,
            args=(process.stdout, max_stdout_bytes, stdout_chunks, exceeded),
            daemon=True,
        ),
        threading.Thread(
            target=_read_bounded_stream,
            args=(process.stderr, max_stderr_bytes, stderr_chunks, exceeded),
            daemon=True,
        ),
    ]
    for reader in readers:
        reader.start()

    deadline = time.monotonic() + timeout
    timed_out = False
    while process.poll() is None:
        if exceeded.is_set():
            _kill_process_tree(process)
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            _kill_process_tree(process)
            break
        exceeded.wait(min(0.05, remaining))

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _kill_process_tree(process)
        process.wait()
    for reader in readers:
        reader.join(timeout=5)
    if any(reader.is_alive() for reader in readers):
        raise MediaError("Nie udało się zamknąć pipe'ów zakończonego procesu.")
    if timed_out:
        raise MediaError("Polecenie przekroczyło limit czasu: {}".format(args[0]))
    if exceeded.is_set():
        raise MediaError("Polecenie przekroczyło limit danych wyjściowych: {}".format(args[0]))

    return subprocess.CompletedProcess(
        list(args),
        process.returncode,
        stdout=b"".join(stdout_chunks),
        stderr=b"".join(stderr_chunks),
    )


def run_checked(
    args: Sequence[str],
    *,
    timeout: float = 60,
    cwd: Optional[Union[os.PathLike[str], str]] = None,
    max_stdout_bytes: int = DEFAULT_MAX_STDOUT_BYTES,
    max_stderr_bytes: int = DEFAULT_MAX_STDERR_BYTES,
) -> subprocess.CompletedProcess[str]:
    """Uruchom lokalne polecenie bez powłoki i z ograniczonym wynikiem."""

    raw = _run_bounded(
        args,
        timeout=timeout,
        cwd=cwd,
        max_stdout_bytes=max_stdout_bytes,
        max_stderr_bytes=max_stderr_bytes,
    )
    result = subprocess.CompletedProcess(
        raw.args,
        raw.returncode,
        stdout=raw.stdout.decode("utf-8", errors="replace"),
        stderr=raw.stderr.decode("utf-8", errors="replace"),
    )
    if result.returncode != 0:
        raise MediaError(
            "Polecenie {} zakończyło się kodem {}: {}".format(
                args[0], result.returncode, _diagnostic(result.stderr)
            )
        )
    return result


def run_ffmpeg(
    args: Sequence[str], *, timeout: float = 120
) -> subprocess.CompletedProcess[str]:
    """Uruchom systemowy FFmpeg; ``args`` nie zawiera nazwy programu."""

    executable = shutil.which("ffmpeg")
    if executable is None:
        raise MediaError("Nie znaleziono systemowego programu ffmpeg.")
    prefix = [executable, "-hide_banner", "-nostdin"]
    if not any(argument in {"-v", "-loglevel"} for argument in args):
        prefix.extend(["-loglevel", "error"])
    return run_checked(
        prefix + list(args), timeout=timeout
    )


def ffprobe_json(path: Union[os.PathLike[str], str], *, timeout: float = 30) -> Dict[str, Any]:
    """Zwróć ograniczony do lokalnego pliku wynik ffprobe w formacie JSON."""

    source_input = Path(path)
    _regular_file(source_input)
    source = source_input.resolve()
    executable = shutil.which("ffprobe")
    if executable is None:
        raise MediaError("Nie znaleziono systemowego programu ffprobe.")
    result = run_checked(
        [
            executable,
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(source),
        ],
        timeout=timeout,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MediaError("ffprobe zwrócił nieprawidłowy JSON.") from exc
    if not isinstance(payload, dict):
        raise MediaError("ffprobe zwrócił nieoczekiwany typ danych.")
    return payload


def validate_image_decodable(path: Union[os.PathLike[str], str], *, timeout: float = 30) -> None:
    """Sprawdź pełną dekodowalność pierwszej klatki obrazu przez FFmpeg."""

    source_input = Path(path)
    probe_image(source_input)
    source = source_input.resolve()
    run_ffmpeg(
        [
            "-v",
            "error",
            "-xerror",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
            "-f",
            "null",
            "-",
        ],
        timeout=timeout,
    )


def _temporary_output(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination.parent / (
        ".{}.{}.tmp{}".format(destination.stem, uuid.uuid4().hex, destination.suffix)
    )


def create_thumbnail(
    source: Union[os.PathLike[str], str],
    destination: Union[os.PathLike[str], str],
    *,
    width: int = 320,
    height: int = 240,
    timeout: float = 60,
) -> Dict[str, Any]:
    """Utwórz atomowo miniaturę bez rozciągania i bez modyfikacji źródła."""

    if width <= 0 or height <= 0 or width > 4096 or height > 4096:
        raise ValueError("Wymiary miniatury muszą mieścić się w zakresie 1-4096.")
    source_input = Path(source)
    probe_image(source_input)
    source_path = source_input.resolve()
    destination_input = Path(destination)
    if destination_input.exists() and destination_input.is_symlink():
        raise MediaError("Miniatura nie może zastępować dowiązania symbolicznego.")
    destination_path = destination_input.parent.resolve() / destination_input.name
    if source_path == destination_path:
        raise MediaError("Miniatura nie może nadpisać obrazu źródłowego.")
    temporary = _temporary_output(destination_path)
    try:
        run_ffmpeg(
            [
                "-y",
                "-v",
                "error",
                "-xerror",
                "-i",
                str(source_path),
                "-vf",
                (
                    "scale={}:{}:force_original_aspect_ratio=decrease:flags=lanczos,"
                    "pad={}:{}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
                ).format(width, height, width, height),
                "-frames:v",
                "1",
                str(temporary),
            ],
            timeout=timeout,
        )
        probe_image(temporary)
        os.replace(str(temporary), str(destination_path))
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    return {
        "path": str(destination_path),
        "sha256": sha256_file(destination_path),
        "width": width,
        "height": height,
    }


def dhash_image(
    path: Union[os.PathLike[str], str], *, hash_size: int = 8, timeout: float = 60
) -> str:
    """Oblicz deterministyczny dHash obrazu jako kandydaturę near-duplicate."""

    if hash_size < 4 or hash_size > 32:
        raise ValueError("Rozmiar dHash musi mieścić się w zakresie 4-32.")
    source_input = Path(path)
    probe_image(source_input)
    source = source_input.resolve()
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise MediaError("Nie znaleziono systemowego programu ffmpeg.")
    command = [
        executable,
        "-hide_banner",
        "-nostdin",
        "-v",
        "error",
        "-xerror",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-vf",
        "scale={}:{}:flags=area,format=gray".format(hash_size + 1, hash_size),
        "-frames:v",
        "1",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "pipe:1",
    ]
    expected_length = (hash_size + 1) * hash_size
    result = _run_bounded(
        command,
        timeout=timeout,
        max_stdout_bytes=expected_length,
        max_stderr_bytes=DEFAULT_MAX_STDERR_BYTES,
    )
    if result.returncode != 0:
        raise MediaError(
            "FFmpeg nie obliczył dHash: {}".format(
                _diagnostic(result.stderr.decode("utf-8", errors="replace"))
            )
        )
    if len(result.stdout) != expected_length:
        raise MediaError("FFmpeg zwrócił niepełne dane pikseli dla dHash.")

    bits = 0
    bit_count = 0
    row_width = hash_size + 1
    for row in range(hash_size):
        offset = row * row_width
        for column in range(hash_size):
            bits = (bits << 1) | int(
                result.stdout[offset + column] > result.stdout[offset + column + 1]
            )
            bit_count += 1
    width_hex = (bit_count + 3) // 4
    return "{:0{}x}".format(bits, width_hex)


def hamming_distance(left: str, right: str) -> int:
    """Policz odległość Hamminga dwóch szesnastkowych hashy tej samej długości."""

    if len(left) != len(right) or not left:
        raise ValueError("Hashy dHash nie można porównać: różne albo puste długości.")
    try:
        value = int(left, 16) ^ int(right, 16)
    except ValueError as exc:
        raise ValueError("dHash musi być zapisem szesnastkowym.") from exc
    return value.bit_count() if hasattr(int, "bit_count") else bin(value).count("1")


__all__ = [
    "DEFAULT_MAX_IMAGE_BYTES",
    "DEFAULT_MAX_PIXELS",
    "DEFAULT_MAX_STDERR_BYTES",
    "DEFAULT_MAX_STDOUT_BYTES",
    "MediaError",
    "create_thumbnail",
    "dhash_image",
    "ffprobe_json",
    "hamming_distance",
    "probe_image",
    "run_checked",
    "run_ffmpeg",
    "sha256_file",
    "validate_image_decodable",
]
