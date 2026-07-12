#!/usr/bin/env python3
"""Bezpieczny ingestion lokalnych JPEG/PNG, katalogów i archiwów ZIP.

Wejścia są kopiowane do centralnej kwarantanny. Archiwum jest walidowane w
całości przed wyodrębnieniem kandydatów, a originals są publikowane dopiero po
zakończeniu wszystkich kontroli bezpieczeństwa danego batcha.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
from typing import Any, BinaryIO, Dict, Iterable, List, Optional, Sequence, Tuple, Union
import unicodedata
import uuid
import zipfile

try:
    from _common import (
        PolishArgumentParser,
        ProjectStatePostCommitError,
        atomic_write_json,
        load_json,
    )
except ImportError:  # Bezpieczny fallback dla izolowanego uruchomienia helpera.
    PolishArgumentParser = argparse.ArgumentParser

    class ProjectStatePostCommitError(ValueError):
        """Fallback kontraktu zapisu opublikowanego przed błędem trwałości."""

        committed = True
        published = True

    def load_json(path: Union[os.PathLike[str], str]) -> Any:
        """Wczytaj JSON UTF-8, gdy wspólny moduł projektu nie jest dostępny."""

        with Path(path).open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def atomic_write_json(path: Union[os.PathLike[str], str], data: Any) -> None:
        """Zapisz JSON atomowo, gdy wspólny moduł projektu nie jest dostępny."""

        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=str(destination.parent))
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

from _media import (
    DEFAULT_MAX_IMAGE_BYTES,
    MediaError,
    create_thumbnail,
    dhash_image,
    hamming_distance,
    probe_image,
    sha256_file,
    validate_image_decodable,
)
from make_contact_sheet import ContactSheetError, make_contact_sheet


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
ARCHIVE_SUFFIXES = {".zip"}
NESTED_ARCHIVE_SUFFIXES = {".zip", ".7z", ".rar", ".tar", ".gz", ".tgz"}
ZIP_MAGIC_PREFIXES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


class IngestionError(ValueError):
    """Błąd bezpiecznego przyjęcia lokalnych zdjęć."""


@dataclass(frozen=True)
class IngestionLimits:
    """Twarde limity bezpieczeństwa jednego batcha ingestion."""

    max_entries: int = 256
    max_images: int = 100
    max_file_bytes: int = DEFAULT_MAX_IMAGE_BYTES
    max_total_uncompressed_bytes: int = 512 * 1024 * 1024
    max_archive_bytes: int = 256 * 1024 * 1024
    max_compression_ratio: float = 200.0
    near_duplicate_distance: int = 6

    def __post_init__(self) -> None:
        integer_fields = (
            self.max_entries,
            self.max_images,
            self.max_file_bytes,
            self.max_total_uncompressed_bytes,
            self.max_archive_bytes,
            self.near_duplicate_distance,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in integer_fields):
            raise IngestionError("Limity całkowite muszą być liczbami całkowitymi.")
        if not 1 <= self.max_entries <= 10_000:
            raise IngestionError("Limit wpisów musi mieścić się w zakresie 1-10000.")
        if not 1 <= self.max_images <= self.max_entries:
            raise IngestionError("Limit obrazów musi być dodatni i nie większy od limitu wpisów.")
        if self.max_file_bytes < 1024:
            raise IngestionError("Limit pojedynczego pliku jest zbyt mały.")
        if self.max_total_uncompressed_bytes < self.max_file_bytes:
            raise IngestionError("Limit sumy bajtów nie może być mniejszy od limitu pliku.")
        if self.max_archive_bytes < 1024:
            raise IngestionError("Limit archiwum jest zbyt mały.")
        if not 1.0 <= self.max_compression_ratio <= 10_000.0:
            raise IngestionError("Limit współczynnika kompresji jest poza zakresem 1-10000.")
        if not 0 <= self.near_duplicate_distance <= 64:
            raise IngestionError("Próg near-duplicate musi mieścić się w zakresie 0-64.")


@dataclass(frozen=True)
class _Candidate:
    path: Path
    relative_path: str
    archive_member: Optional[str]
    quarantine_path: Path


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _ensure_directory(path: Path) -> None:
    if path.exists() and path.is_symlink():
        raise IngestionError("Katalog roboczy nie może być dowiązaniem symbolicznym.")
    if path.exists() and not path.is_dir():
        raise IngestionError("Ścieżka robocza nie jest katalogiem: {}".format(path))
    path.mkdir(parents=True, exist_ok=True)


def _safe_relative_name(name: str, *, is_directory: bool = False) -> str:
    if not isinstance(name, str) or not name or "\x00" in name:
        raise IngestionError("Archiwum zawiera pustą albo nieprawidłową nazwę.")
    if "\\" in name:
        raise IngestionError("Backslash w ścieżce archiwum jest niedozwolony: {}".format(name))
    if name.startswith("/") or WINDOWS_DRIVE.match(name):
        raise IngestionError("Archiwum zawiera ścieżkę absolutną: {}".format(name))
    trimmed = name[:-1] if is_directory and name.endswith("/") else name
    if not trimmed or "//" in trimmed:
        raise IngestionError("Archiwum zawiera niejednoznaczną ścieżkę: {}".format(name))
    path = PurePosixPath(trimmed)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise IngestionError("Archiwum zawiera path traversal: {}".format(name))
    for part in path.parts:
        if len(part) > 255 or part != part.rstrip(" ."):
            raise IngestionError("Archiwum zawiera niebezpieczny segment nazwy: {}".format(name))
        if any(ord(character) < 32 for character in part):
            raise IngestionError("Archiwum zawiera znak sterujący w nazwie.")
    normalized = unicodedata.normalize("NFC", "/".join(path.parts))
    if len(normalized) > 1024:
        raise IngestionError("Ścieżka wejściowa przekracza limit długości.")
    return normalized


def _collision_key(name: str) -> str:
    return unicodedata.normalize("NFC", name).casefold()


def _open_regular(path: Path) -> BinaryIO:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise IngestionError("Nie można odczytać wejścia: {}".format(path)) from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise IngestionError("Dowiązania symboliczne nie są dozwolone: {}".format(path))
    if not stat.S_ISREG(metadata.st_mode):
        raise IngestionError("Oczekiwano zwykłego pliku: {}".format(path))
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(str(path), flags)
        opened = os.fdopen(descriptor, "rb")
    except OSError as exc:
        raise IngestionError("Nie można bezpiecznie otworzyć pliku: {}".format(path)) from exc
    opened_metadata = os.fstat(opened.fileno())
    if not stat.S_ISREG(opened_metadata.st_mode):
        opened.close()
        raise IngestionError("Wejście zmieniło typ podczas otwierania: {}".format(path))
    return opened


def _copy_stream(source: BinaryIO, destination: Path, max_bytes: int) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / ".{}.{}.tmp".format(destination.name, uuid.uuid4().hex)
    total = 0
    try:
        with temporary.open("xb") as target:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise IngestionError("Plik przekroczył limit {} bajtów.".format(max_bytes))
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        if destination.exists():
            if destination.is_symlink() or sha256_file(destination) != sha256_file(temporary):
                raise IngestionError("Kolizja istniejącego pliku kwarantanny: {}".format(destination))
            temporary.unlink()
        else:
            os.replace(str(temporary), str(destination))
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    return total


def _copy_regular(source: Path, destination: Path, max_bytes: int) -> int:
    with _open_regular(source) as handle:
        return _copy_stream(handle, destination, max_bytes)


def _scan_directory(source: Path, limits: IngestionLimits) -> Tuple[List[Tuple[Path, str]], List[Dict[str, str]]]:
    files: List[Tuple[Path, str]] = []
    rejected: List[Dict[str, str]] = []
    collision_keys: Dict[str, str] = {}
    entry_count = 0
    total_bytes = 0

    def visit(directory: Path, relative_parts: Tuple[str, ...], depth: int) -> None:
        nonlocal entry_count, total_bytes
        if depth > 32:
            raise IngestionError("Katalog wejściowy jest zbyt głęboko zagnieżdżony.")
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise IngestionError("Nie można odczytać katalogu: {}".format(directory)) from exc
        entries.sort(key=lambda entry: (_collision_key(entry.name), entry.name))
        for entry in entries:
            entry_count += 1
            if entry_count > limits.max_entries:
                raise IngestionError("Katalog przekracza limit {} wpisów.".format(limits.max_entries))
            relative = _safe_relative_name("/".join(relative_parts + (entry.name,)))
            key = _collision_key(relative)
            previous = collision_keys.get(key)
            if previous is not None:
                raise IngestionError(
                    "Kolizja nazw po normalizacji Unicode/case: {} i {}".format(previous, relative)
                )
            collision_keys[key] = relative
            if entry.is_symlink():
                raise IngestionError("Katalog zawiera dowiązanie symboliczne: {}".format(relative))
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise IngestionError("Nie można odczytać wpisu katalogu: {}".format(relative)) from exc
            if stat.S_ISDIR(metadata.st_mode):
                visit(Path(entry.path), relative_parts + (entry.name,), depth + 1)
            elif stat.S_ISREG(metadata.st_mode):
                total_bytes += metadata.st_size
                if total_bytes > limits.max_total_uncompressed_bytes:
                    raise IngestionError("Suma bajtów katalogu wejściowego przekracza limit.")
                suffix = Path(entry.name).suffix.casefold()
                if suffix in IMAGE_SUFFIXES:
                    if metadata.st_size > limits.max_file_bytes:
                        raise IngestionError("Obraz przekracza limit bajtów: {}".format(relative))
                    files.append((Path(entry.path), relative))
                elif suffix in NESTED_ARCHIVE_SUFFIXES:
                    raise IngestionError("Katalog wejściowy zawiera zagnieżdżone archiwum: {}".format(relative))
                else:
                    rejected.append({"relative_path": relative, "reason": "nieobsługiwane rozszerzenie"})
            else:
                raise IngestionError("Katalog zawiera plik specjalny: {}".format(relative))

    visit(source, (), 0)
    if len(files) > limits.max_images:
        raise IngestionError("Katalog przekracza limit {} obrazów.".format(limits.max_images))
    return files, rejected


def _directory_fingerprint(files: Sequence[Tuple[Path, str]], limits: IngestionLimits) -> str:
    digest = hashlib.sha256()
    for path, relative in files:
        digest.update(unicodedata.normalize("NFC", relative).encode("utf-8"))
        digest.update(b"\x00")
        digest.update(sha256_file(path, max_bytes=limits.max_file_bytes).encode("ascii"))
        digest.update(b"\x00")
    return digest.hexdigest()


def _zip_file_type(info: zipfile.ZipInfo) -> str:
    mode = (info.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(mode)
    if file_type == stat.S_IFLNK:
        return "symlink"
    if file_type == stat.S_IFDIR:
        return "directory"
    if file_type == stat.S_IFREG or file_type == 0:
        return "regular"
    return "special"


def _validate_zip_entries(
    archive: zipfile.ZipFile, limits: IngestionLimits
) -> Tuple[List[Tuple[zipfile.ZipInfo, str]], List[Dict[str, str]]]:
    infos = archive.infolist()
    if len(infos) > limits.max_entries:
        raise IngestionError("ZIP przekracza limit {} wpisów.".format(limits.max_entries))
    accepted: List[Tuple[zipfile.ZipInfo, str]] = []
    rejected: List[Dict[str, str]] = []
    seen: Dict[str, Tuple[str, str]] = {}
    total = 0

    for info in infos:
        if info.flag_bits & 0x1:
            raise IngestionError("ZIP zawiera zaszyfrowany wpis: {}".format(info.filename))
        kind = _zip_file_type(info)
        if kind == "symlink":
            raise IngestionError("ZIP zawiera dowiązanie symboliczne: {}".format(info.filename))
        if kind == "special":
            raise IngestionError("ZIP zawiera plik specjalny: {}".format(info.filename))
        declared_directory = info.is_dir() or kind == "directory"
        relative = _safe_relative_name(info.filename, is_directory=declared_directory)
        key = _collision_key(relative)
        if key in seen:
            raise IngestionError(
                "ZIP zawiera kolizję nazw Unicode/case: {} i {}".format(
                    seen[key][0], relative
                )
            )
        seen[key] = (relative, "directory" if declared_directory else "file")
        if declared_directory:
            continue
        if info.file_size < 0 or info.compress_size < 0:
            raise IngestionError("ZIP zawiera nieprawidłowe rozmiary wpisu.")
        if info.file_size > limits.max_file_bytes:
            raise IngestionError("Wpis ZIP przekracza limit pliku: {}".format(relative))
        total += info.file_size
        if total > limits.max_total_uncompressed_bytes:
            raise IngestionError("Suma rozpakowanych danych ZIP przekracza limit.")
        if info.file_size:
            if info.compress_size == 0:
                raise IngestionError("Wpis ZIP ma podejrzany zerowy rozmiar skompresowany.")
            ratio = info.file_size / info.compress_size
            if ratio > limits.max_compression_ratio:
                raise IngestionError(
                    "Współczynnik kompresji wpisu ZIP przekracza limit: {}".format(relative)
                )

    file_keys = {key for key, (_, kind) in seen.items() if kind == "file"}
    for key, (relative, _) in seen.items():
        parts = key.split("/")
        for index in range(1, len(parts)):
            if "/".join(parts[:index]) in file_keys:
                raise IngestionError("ZIP zawiera konflikt pliku i katalogu: {}".format(relative))

    for info in infos:
        kind = _zip_file_type(info)
        if info.is_dir() or kind == "directory":
            continue
        relative = _safe_relative_name(info.filename)
        suffix = PurePosixPath(relative).suffix.casefold()
        try:
            with archive.open(info, "r") as handle:
                prefix = handle.read(8)
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            raise IngestionError("Nie można bezpiecznie odczytać wpisu ZIP: {}".format(relative)) from exc
        if suffix in NESTED_ARCHIVE_SUFFIXES or prefix.startswith(ZIP_MAGIC_PREFIXES):
            raise IngestionError("ZIP zawiera zagnieżdżone archiwum: {}".format(relative))
        if suffix in IMAGE_SUFFIXES:
            accepted.append((info, relative))
        else:
            rejected.append({"relative_path": relative, "reason": "nieobsługiwane rozszerzenie"})

    if len(accepted) > limits.max_images:
        raise IngestionError("ZIP przekracza limit {} obrazów.".format(limits.max_images))
    try:
        damaged = archive.testzip()
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise IngestionError("ZIP jest uszkodzony albo nie przechodzi kontroli CRC.") from exc
    if damaged is not None:
        raise IngestionError("ZIP ma uszkodzony wpis CRC: {}".format(damaged))
    return accepted, rejected


def _extract_zip_candidates(
    archive_path: Path,
    quarantine_candidates: Path,
    limits: IngestionLimits,
) -> Tuple[List[_Candidate], List[Dict[str, str]]]:
    try:
        archive = zipfile.ZipFile(archive_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise IngestionError("Plik nie jest poprawnym archiwum ZIP.") from exc
    with archive:
        accepted, rejected = _validate_zip_entries(archive, limits)
        candidates: List[_Candidate] = []
        for index, (info, relative) in enumerate(accepted):
            suffix = PurePosixPath(relative).suffix.casefold()
            destination = quarantine_candidates / "{:04d}{}".format(index, suffix)
            try:
                with archive.open(info, "r") as source:
                    copied = _copy_stream(source, destination, limits.max_file_bytes)
            except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                raise IngestionError("Nie można rozpakować wpisu ZIP: {}".format(relative)) from exc
            if copied != info.file_size:
                raise IngestionError("Rozmiar rozpakowanego wpisu nie zgadza się z ZIP: {}".format(relative))
            candidates.append(
                _Candidate(
                    path=destination,
                    relative_path=relative,
                    archive_member=relative,
                    quarantine_path=destination,
                )
            )
    return candidates, rejected


def _prepare_input(
    source: Path,
    destination: Path,
    limits: IngestionLimits,
) -> Tuple[str, str, Path, List[_Candidate], List[Dict[str, str]]]:
    try:
        metadata = source.lstat()
    except OSError as exc:
        raise IngestionError("Źródło ingestion nie istnieje albo jest niedostępne.") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise IngestionError("Źródło ingestion nie może być dowiązaniem symbolicznym.")

    quarantine_root = destination / "quarantine"
    _ensure_directory(quarantine_root)
    rejected: List[Dict[str, str]] = []

    if stat.S_ISDIR(metadata.st_mode):
        source_kind = "directory"
        files, rejected = _scan_directory(source, limits)
        if not files:
            raise IngestionError("Katalog nie zawiera obsługiwanych obrazów JPEG/PNG.")
        fingerprint = _directory_fingerprint(files, limits)
        run_quarantine = quarantine_root / fingerprint[:24]
        candidates_dir = run_quarantine / "candidates"
        _ensure_directory(candidates_dir)
        candidates: List[_Candidate] = []
        for index, (path, relative) in enumerate(files):
            suffix = path.suffix.casefold()
            quarantined = candidates_dir / "{:04d}{}".format(index, suffix)
            _copy_regular(path, quarantined, limits.max_file_bytes)
            candidates.append(
                _Candidate(
                    path=quarantined,
                    relative_path=relative,
                    archive_member=None,
                    quarantine_path=quarantined,
                )
            )
        return source_kind, fingerprint, run_quarantine, candidates, rejected

    if not stat.S_ISREG(metadata.st_mode):
        raise IngestionError("Źródło ingestion musi być plikiem albo katalogiem.")
    suffix = source.suffix.casefold()
    if suffix in ARCHIVE_SUFFIXES:
        source_kind = "zip"
        fingerprint = sha256_file(source, max_bytes=limits.max_archive_bytes)
        run_quarantine = quarantine_root / fingerprint[:24]
        _ensure_directory(run_quarantine)
        archived = run_quarantine / "input.zip"
        _copy_regular(source, archived, limits.max_archive_bytes)
        candidates_dir = run_quarantine / "candidates"
        _ensure_directory(candidates_dir)
        candidates, rejected = _extract_zip_candidates(archived, candidates_dir, limits)
        if not candidates:
            raise IngestionError("ZIP nie zawiera obsługiwanych obrazów JPEG/PNG.")
        return source_kind, fingerprint, run_quarantine, candidates, rejected

    if suffix not in IMAGE_SUFFIXES:
        raise IngestionError("Plik wejściowy musi być obrazem JPEG/PNG albo archiwum ZIP.")
    source_kind = "file"
    fingerprint = sha256_file(source, max_bytes=limits.max_file_bytes)
    run_quarantine = quarantine_root / fingerprint[:24]
    candidates_dir = run_quarantine / "candidates"
    _ensure_directory(candidates_dir)
    safe_name = _safe_relative_name(source.name)
    quarantined = candidates_dir / "0000{}".format(suffix)
    _copy_regular(source, quarantined, limits.max_file_bytes)
    candidate = _Candidate(
        path=quarantined,
        relative_path=safe_name,
        archive_member=None,
        quarantine_path=quarantined,
    )
    return source_kind, fingerprint, run_quarantine, [candidate], rejected


def _empty_manifest(destination: Path) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "root": str(destination),
        "assets": [],
        "near_duplicate_candidates": [],
        "contact_sheets": [],
        "batches": [],
    }


def _load_manifest(destination: Path) -> Dict[str, Any]:
    manifest_path = destination / "ingestion.json"
    if not manifest_path.exists():
        return _empty_manifest(destination)
    try:
        payload = load_json(manifest_path)
    except Exception as exc:
        raise IngestionError("Nie można bezpiecznie wczytać istniejącego manifestu ingestion.") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise IngestionError("Istniejący manifest ingestion ma nieobsługiwaną wersję.")
    for key in ("assets", "near_duplicate_candidates", "contact_sheets", "batches"):
        if not isinstance(payload.get(key), list):
            raise IngestionError("Istniejący manifest ingestion ma nieprawidłowe pole {}.".format(key))
    return payload


def _validate_existing_assets(manifest: Dict[str, Any], destination: Path) -> Dict[str, Dict[str, Any]]:
    by_hash: Dict[str, Dict[str, Any]] = {}
    for asset in manifest["assets"]:
        if not isinstance(asset, dict):
            raise IngestionError("Istniejący manifest zawiera nieprawidłowy asset.")
        asset_hash = asset.get("sha256")
        asset_id = asset.get("asset_id")
        path_value = asset.get("original_path")
        if (
            not isinstance(asset_hash, str)
            or not re.fullmatch(r"[0-9a-f]{64}", asset_hash)
            or asset_id != asset_hash
            or not isinstance(path_value, str)
        ):
            raise IngestionError("Istniejący asset ma nieprawidłowy identyfikator albo ścieżkę.")
        original = Path(path_value).resolve()
        if not _is_within(original, destination) or not original.exists():
            raise IngestionError("Ścieżka istniejącego original wychodzi poza katalog ingestion.")
        if sha256_file(original) != asset_hash:
            raise IngestionError("Hash istniejącego original nie zgadza się z manifestem.")
        if asset_hash in by_hash:
            raise IngestionError("Manifest zawiera powtórzony asset SHA-256.")
        by_hash[asset_hash] = asset
    return by_hash


def _provenance_record(
    candidate: _Candidate,
    *,
    source: Path,
    source_kind: str,
    provenance_kind: Optional[str],
    preferred: bool,
    listing_url: Optional[str],
) -> Dict[str, Any]:
    return {
        "kind": provenance_kind or source_kind,
        "source_path": str(source),
        "relative_path": candidate.relative_path,
        "archive_member": candidate.archive_member,
        "quarantine_path": str(candidate.quarantine_path),
        "listing_url": listing_url,
        "preferred": preferred,
    }


def _append_unique(items: List[Dict[str, Any]], item: Dict[str, Any]) -> None:
    encoded = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    existing = {
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for value in items
    }
    if encoded not in existing:
        items.append(item)
        items.sort(
            key=lambda value: json.dumps(
                value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
        )


def _publish_file(source: Path, destination: Path, created: List[Path]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.is_symlink() or sha256_file(destination) != sha256_file(source):
            raise IngestionError("Kolizja publikowanego pliku: {}".format(destination))
        return
    temporary = destination.parent / ".{}.{}.tmp".format(destination.name, uuid.uuid4().hex)
    try:
        _copy_regular(source, temporary, max(source.stat().st_size, 1))
        os.replace(str(temporary), str(destination))
        created.append(destination)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _near_duplicates(assets: Sequence[Dict[str, Any]], threshold: int) -> List[Dict[str, Any]]:
    ordered = sorted(assets, key=lambda asset: asset["asset_id"])
    candidates: List[Dict[str, Any]] = []
    for left_index, left in enumerate(ordered):
        for right in ordered[left_index + 1 :]:
            distance = hamming_distance(left["dhash"], right["dhash"])
            if distance <= threshold:
                candidates.append(
                    {
                        "left_asset_id": left["asset_id"],
                        "right_asset_id": right["asset_id"],
                        "distance": distance,
                        "status": "candidate_for_manual_review",
                    }
                )
    return candidates


def ingest_images(
    source_path: Union[os.PathLike[str], str],
    destination_path: Union[os.PathLike[str], str],
    *,
    preferred: bool = False,
    provenance_kind: Optional[str] = None,
    listing_url: Optional[str] = None,
    limits: Optional[IngestionLimits] = None,
    create_contact_sheet: bool = True,
) -> Dict[str, Any]:
    """Przyjmij plik, katalog albo ZIP i atomowo zaktualizuj manifest assetów.

    ``listing_url`` jest wyłącznie provenance. Funkcja nie pobiera obrazów i
    nie wykonuje żadnych połączeń sieciowych.
    """

    active_limits = limits or IngestionLimits()
    source = Path(os.path.abspath(os.fspath(source_path)))
    destination_input = Path(destination_path)
    if destination_input.exists() and destination_input.is_symlink():
        raise IngestionError("Katalog docelowy nie może być dowiązaniem symbolicznym.")
    destination = destination_input.resolve()
    _ensure_directory(destination)
    if _is_within(destination, source) and source.is_dir():
        raise IngestionError("Katalog docelowy nie może znajdować się wewnątrz źródła.")
    if listing_url is not None:
        try:
            from extract_listing import validate_http_url

            listing_url = validate_http_url(listing_url)
        except Exception as exc:
            raise IngestionError("URL listingu użyty jako provenance jest nieprawidłowy.") from exc
    if provenance_kind is not None:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", provenance_kind):
            raise IngestionError("Rodzaj provenance ma nieprawidłowy format.")

    source_kind, fingerprint, run_quarantine, candidates, rejected = _prepare_input(
        source, destination, active_limits
    )
    manifest = _load_manifest(destination)
    by_hash = _validate_existing_assets(manifest, destination)

    valid_groups: Dict[str, Dict[str, Any]] = {}
    for candidate in candidates:
        try:
            details = probe_image(
                candidate.path,
                max_bytes=active_limits.max_file_bytes,
            )
            validate_image_decodable(candidate.path)
            digest = sha256_file(candidate.path, max_bytes=active_limits.max_file_bytes)
            visual_hash = dhash_image(candidate.path)
        except (MediaError, OSError, ValueError) as exc:
            rejected.append(
                {
                    "relative_path": candidate.relative_path,
                    "reason": "obraz uszkodzony albo niezgodny: {}".format(exc),
                    "quarantine_path": str(candidate.quarantine_path),
                }
            )
            continue
        group = valid_groups.setdefault(
            digest,
            {
                "candidate": candidate,
                "details": details,
                "dhash": visual_hash,
                "provenance": [],
            },
        )
        if group["dhash"] != visual_hash:
            raise IngestionError("Exact duplicate SHA-256 ma niespójny dHash.")
        _append_unique(
            group["provenance"],
            _provenance_record(
                candidate,
                source=source,
                source_kind=source_kind,
                provenance_kind=provenance_kind,
                preferred=preferred,
                listing_url=listing_url,
            ),
        )
    if not valid_groups:
        raise IngestionError(
            "Batch nie zawiera żadnego poprawnego, dekodowalnego obrazu JPEG/PNG."
        )

    staging = Path(tempfile.mkdtemp(prefix=".ingestion-", dir=str(destination)))
    created_files: List[Path] = []
    manifest_committed = False
    try:
        staged_new: Dict[str, Dict[str, Path]] = {}
        for digest, group in sorted(valid_groups.items()):
            if digest in by_hash:
                asset = by_hash[digest]
                provenance = asset.setdefault("provenance", [])
                if not isinstance(provenance, list):
                    raise IngestionError("Istniejący asset ma nieprawidłowe provenance.")
                for record in group["provenance"]:
                    _append_unique(provenance, record)
                asset["preferred"] = bool(asset.get("preferred")) or preferred
                asset["exact_duplicate_count"] = max(0, len(provenance) - 1)
                if not isinstance(asset.get("dhash"), str):
                    asset["dhash"] = dhash_image(asset["original_path"])
                continue

            details = group["details"]
            extension = ".jpg" if details["format"] == "jpeg" else ".png"
            original_relative = Path("originals") / (digest + extension)
            thumbnail_relative = Path("thumbnails") / (digest + ".jpg")
            staged_original = staging / original_relative
            staged_thumbnail = staging / thumbnail_relative
            _copy_regular(group["candidate"].path, staged_original, active_limits.max_file_bytes)
            create_thumbnail(group["candidate"].path, staged_thumbnail)
            staged_new[digest] = {
                "original": staged_original,
                "thumbnail": staged_thumbnail,
            }
            asset = {
                "asset_id": digest,
                "sha256": digest,
                "original_path": str((destination / original_relative).resolve()),
                "original_relative_path": original_relative.as_posix(),
                "thumbnail_path": str((destination / thumbnail_relative).resolve()),
                "thumbnail_relative_path": thumbnail_relative.as_posix(),
                "format": details["format"],
                "mime_type": details["mime_type"],
                "width": details["width"],
                "height": details["height"],
                "orientation": details["orientation"],
                "size_bytes": details["size_bytes"],
                "dhash": group["dhash"],
                "preferred": preferred,
                "provenance": group["provenance"],
                "exact_duplicate_count": max(0, len(group["provenance"]) - 1),
                "quarantine_status": "validated",
            }
            manifest["assets"].append(asset)
            by_hash[digest] = asset

        manifest["assets"].sort(key=lambda asset: asset["asset_id"])
        manifest["near_duplicate_candidates"] = _near_duplicates(
            manifest["assets"], active_limits.near_duplicate_distance
        )

        sheet_entry: Optional[Dict[str, Any]] = None
        if create_contact_sheet:
            sheet_fingerprint = hashlib.sha256(
                ("\n".join(asset["asset_id"] for asset in manifest["assets"]) + "\n320x240").encode(
                    "ascii"
                )
            ).hexdigest()
            staged_sheet = staging / "contact-sheets" / (
                "contact-sheet-{}.jpg".format(sheet_fingerprint[:16])
            )
            staged_index = staging / "contact-sheets" / (
                "contact-sheet-{}.json".format(sheet_fingerprint[:16])
            )
            sheet_inputs: List[Dict[str, str]] = []
            for asset in manifest["assets"]:
                digest = asset["asset_id"]
                path = (
                    staged_new[digest]["original"]
                    if digest in staged_new
                    else Path(asset["original_path"])
                )
                sheet_inputs.append({"asset_id": digest, "original_path": str(path)})
            sheet_result = make_contact_sheet(sheet_inputs, staged_sheet)
            final_paths = {asset["asset_id"]: asset["original_path"] for asset in manifest["assets"]}
            for cell in sheet_result["cells"]:
                cell["source_path"] = final_paths[cell["asset_id"]]
            sheet_result["contact_sheet_path"] = str(
                (destination / "contact-sheets" / staged_sheet.name).resolve()
            )
            sheet_result["index_path"] = str(
                (destination / "contact-sheets" / staged_index.name).resolve()
            )
            atomic_write_json(staged_index, sheet_result)
            sheet_entry = {
                "fingerprint": sheet_fingerprint,
                "path": sheet_result["contact_sheet_path"],
                "index_path": sheet_result["index_path"],
                "sha256": sheet_result["contact_sheet_sha256"],
                "asset_ids": [asset["asset_id"] for asset in manifest["assets"]],
            }
            manifest["contact_sheets"] = [
                entry
                for entry in manifest["contact_sheets"]
                if entry.get("fingerprint") != sheet_fingerprint
            ]
            manifest["contact_sheets"].append(sheet_entry)
            manifest["contact_sheets"].sort(key=lambda entry: entry["fingerprint"])

        batch = {
            "batch_id": fingerprint,
            "source_kind": source_kind,
            "source_path": str(source),
            "quarantine_path": str(run_quarantine),
            "preferred": preferred,
            "listing_url": listing_url,
            "accepted_asset_ids": sorted(valid_groups),
            "rejected": sorted(
                rejected,
                key=lambda item: (item.get("relative_path", ""), item.get("reason", "")),
            ),
        }
        manifest["batches"] = [
            entry for entry in manifest["batches"] if entry.get("batch_id") != fingerprint
        ]
        manifest["batches"].append(batch)
        manifest["batches"].sort(key=lambda entry: entry["batch_id"])

        for digest, paths in sorted(staged_new.items()):
            asset = by_hash[digest]
            _publish_file(paths["original"], Path(asset["original_path"]), created_files)
            _publish_file(paths["thumbnail"], Path(asset["thumbnail_path"]), created_files)
        if sheet_entry is not None:
            staged_sheet = staging / "contact-sheets" / Path(sheet_entry["path"]).name
            staged_index = staging / "contact-sheets" / Path(sheet_entry["index_path"]).name
            _publish_file(staged_sheet, Path(sheet_entry["path"]), created_files)
            _publish_file(staged_index, Path(sheet_entry["index_path"]), created_files)

        try:
            atomic_write_json(destination / "ingestion.json", manifest)
            manifest_committed = True
        except ProjectStatePostCommitError as exc:
            manifest_committed = True
            raise IngestionError(
                "Manifest ingestion został opublikowany, ale nie potwierdzono "
                "trwałości katalogu; opublikowane pliki pozostawiono na miejscu."
            ) from exc
        except Exception as exc:
            raise IngestionError("Nie udało się atomowo zapisać manifestu ingestion.") from exc
    except Exception:
        if not manifest_committed:
            for path in reversed(created_files):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    """Zbuduj polski interfejs poleceń ingestion."""

    parser = PolishArgumentParser(
        description="Przyjmij lokalne JPEG/PNG, katalog albo ZIP do centralnej kwarantanny."
    )
    parser.add_argument("source", help="Lokalny plik, katalog albo ZIP.")
    parser.add_argument("destination", help="Katalog obrazów projektu.")
    parser.add_argument("--preferred", action="store_true", help="Oznacz pliki przesłane przez użytkownika jako preferowane.")
    parser.add_argument("--provenance-kind", help="Krótki identyfikator rodzaju pochodzenia danych.")
    parser.add_argument("--listing-url", help="URL HTTP/HTTPS wyłącznie jako pochodzenie danych w trybie hybrydowym.")
    parser.add_argument("--no-contact-sheet", action="store_true", help="Nie twórz arkusza kontaktowego tego przebiegu.")
    parser.add_argument("--max-entries", type=int, default=256)
    parser.add_argument("--max-images", type=int, default=100)
    parser.add_argument("--max-file-bytes", type=int, default=DEFAULT_MAX_IMAGE_BYTES)
    parser.add_argument("--max-total-bytes", type=int, default=512 * 1024 * 1024)
    parser.add_argument("--max-archive-bytes", type=int, default=256 * 1024 * 1024)
    parser.add_argument("--max-compression-ratio", type=float, default=200.0)
    parser.add_argument("--near-duplicate-distance", type=int, default=6)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Uruchom ingestion CLI i wypisz wynikowy manifest JSON."""

    args = build_parser().parse_args(argv)
    try:
        limits = IngestionLimits(
            max_entries=args.max_entries,
            max_images=args.max_images,
            max_file_bytes=args.max_file_bytes,
            max_total_uncompressed_bytes=args.max_total_bytes,
            max_archive_bytes=args.max_archive_bytes,
            max_compression_ratio=args.max_compression_ratio,
            near_duplicate_distance=args.near_duplicate_distance,
        )
        result = ingest_images(
            args.source,
            args.destination,
            preferred=args.preferred,
            provenance_kind=args.provenance_kind,
            listing_url=args.listing_url,
            limits=limits,
            create_contact_sheet=not args.no_contact_sheet,
        )
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    except (IngestionError, MediaError, ContactSheetError, OSError, ValueError) as exc:
        sys.stderr.write("Błąd ingestion zdjęć: {}\n".format(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["IngestionError", "IngestionLimits", "ingest_images"]
