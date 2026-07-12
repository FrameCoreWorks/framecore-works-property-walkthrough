#!/usr/bin/env python3
"""Deterministyczne contact sheets JPEG/PNG tworzone lokalnie przez FFmpeg."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union
import uuid

try:
    from _common import PolishArgumentParser, atomic_write_json
except ImportError:  # Bezpieczny fallback dla izolowanego uruchomienia helpera.
    import tempfile

    PolishArgumentParser = argparse.ArgumentParser

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
    DEFAULT_MAX_PIXELS,
    MediaError,
    probe_image,
    run_ffmpeg,
    sha256_file,
    validate_image_decodable,
)


DEFAULT_CELL_WIDTH = 320
DEFAULT_CELL_HEIGHT = 240
DEFAULT_MAX_IMAGES = 100


class ContactSheetError(ValueError):
    """Błąd walidacji albo generowania technicznego contact sheet."""


def _entry(item: Any) -> Tuple[str, Path]:
    if isinstance(item, Mapping):
        raw_path = item.get("original_path") or item.get("path")
        raw_id = item.get("asset_id") or item.get("image_id") or item.get("sha256")
        if not isinstance(raw_path, str) or not raw_path:
            raise ContactSheetError("Wpis assetu nie zawiera ścieżki obrazu.")
        path_input = Path(raw_path)
        if path_input.is_symlink():
            raise ContactSheetError("Obraz contact sheet nie może być dowiązaniem symbolicznym.")
        path = path_input.resolve()
        asset_id = str(raw_id) if raw_id is not None else sha256_file(path_input)
    elif isinstance(item, (str, os.PathLike)):
        path_input = Path(item)
        if path_input.is_symlink():
            raise ContactSheetError("Obraz contact sheet nie może być dowiązaniem symbolicznym.")
        path = path_input.resolve()
        asset_id = sha256_file(path_input)
    else:
        raise ContactSheetError("Obraz contact sheet musi być ścieżką albo wpisem manifestu.")
    if not asset_id or len(asset_id) > 256:
        raise ContactSheetError("Identyfikator obrazu jest pusty albo zbyt długi.")
    return asset_id, path


def _temporary_output(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination.parent / (
        ".{}.{}.tmp{}".format(destination.stem, uuid.uuid4().hex, destination.suffix)
    )


def _publish_staged_outputs(pairs: Sequence[Tuple[Path, Path]]) -> None:
    """Opublikuj powiązane pliki z przywróceniem poprzednich wersji po błędzie."""

    backups: Dict[Path, Path] = {}
    published: List[Path] = []
    try:
        for _, destination in pairs:
            if destination.exists():
                backup = _temporary_output(destination)
                os.replace(str(destination), str(backup))
                backups[destination] = backup
        for staged, destination in pairs:
            os.replace(str(staged), str(destination))
            published.append(destination)
    except Exception:
        for destination in reversed(published):
            try:
                destination.unlink()
            except FileNotFoundError:
                pass
        for destination, backup in reversed(list(backups.items())):
            if backup.exists():
                os.replace(str(backup), str(destination))
        raise
    else:
        for backup in backups.values():
            try:
                backup.unlink()
            except FileNotFoundError:
                pass


def make_contact_sheet(
    images: Sequence[Any],
    output_path: Union[os.PathLike[str], str],
    *,
    columns: Optional[int] = None,
    cell_width: int = DEFAULT_CELL_WIDTH,
    cell_height: int = DEFAULT_CELL_HEIGHT,
    max_images: int = DEFAULT_MAX_IMAGES,
    index_path: Optional[Union[os.PathLike[str], str]] = None,
    timeout: float = 120,
) -> Dict[str, Any]:
    """Utwórz atomowy contact sheet i opcjonalny indeks komórek JSON.

    Kolejność komórek jest deterministyczna: najpierw ``asset_id``, następnie
    pełna ścieżka źródłowa. Obraz wynikowy nie zawiera tekstowych nakładek.
    """

    if not images:
        raise ContactSheetError("Do contact sheet wymagany jest co najmniej jeden obraz.")
    if not 1 <= max_images <= 500:
        raise ContactSheetError("Limit obrazów musi mieścić się w zakresie 1-500.")
    if len(images) > max_images:
        raise ContactSheetError("Liczba obrazów przekracza limit {}.".format(max_images))
    if not 16 <= cell_width <= 4096 or not 16 <= cell_height <= 4096:
        raise ContactSheetError("Wymiary komórki muszą mieścić się w zakresie 16-4096.")

    destination_input = Path(output_path)
    if destination_input.exists() and destination_input.is_symlink():
        raise ContactSheetError("Plik wynikowy nie może być dowiązaniem symbolicznym.")
    destination = destination_input.parent.resolve() / destination_input.name
    if destination.suffix.casefold() not in {".jpg", ".jpeg", ".png"}:
        raise ContactSheetError("Contact sheet musi mieć rozszerzenie JPEG albo PNG.")
    entries = sorted((_entry(item) for item in images), key=lambda pair: (pair[0], str(pair[1])))
    seen_paths: Dict[Path, str] = {}
    seen_ids: Dict[str, Path] = {}
    unique_entries: List[Tuple[str, Path]] = []
    for asset_id, source in entries:
        if source == destination:
            raise ContactSheetError("Contact sheet nie może nadpisać obrazu źródłowego.")
        if source in seen_paths:
            if seen_paths[source] != asset_id:
                raise ContactSheetError("Jedna ścieżka obrazu ma dwa różne identyfikatory.")
            continue
        if asset_id in seen_ids and seen_ids[asset_id] != source:
            raise ContactSheetError("Jeden identyfikator obrazu wskazuje dwie różne ścieżki.")
        seen_paths[source] = asset_id
        seen_ids[asset_id] = source
        try:
            probe_image(source)
            validate_image_decodable(source, timeout=min(timeout, 30))
        except MediaError as exc:
            raise ContactSheetError("Nieprawidłowy obraz contact sheet: {}".format(source)) from exc
        unique_entries.append((asset_id, source))
    if not unique_entries:
        raise ContactSheetError("Po deduplikacji nie pozostał żaden obraz.")

    count = len(unique_entries)
    if columns is None:
        columns = max(1, int(math.ceil(math.sqrt(count))))
    if not 1 <= columns <= 50:
        raise ContactSheetError("Liczba kolumn musi mieścić się w zakresie 1-50.")
    columns = min(columns, count)
    rows = int(math.ceil(count / columns))
    expected_width = cell_width * columns
    expected_height = cell_height * rows
    if expected_width > 16_384 or expected_height > 16_384:
        raise ContactSheetError("Wynikowy contact sheet przekracza limit 16384 pikseli na bok.")
    if expected_width * expected_height > DEFAULT_MAX_PIXELS:
        raise ContactSheetError("Wynikowy contact sheet przekracza limit 100 milionów pikseli.")

    arguments: List[str] = ["-y", "-v", "error", "-xerror"]
    for _, source in unique_entries:
        arguments.extend(["-i", str(source)])

    filters: List[str] = []
    for index in range(count):
        filters.append(
            (
                "[{0}:v]scale={1}:{2}:force_original_aspect_ratio=decrease:flags=lanczos,"
                "pad={1}:{2}:(ow-iw)/2:(oh-ih)/2:color=black,format=rgb24,setsar=1[v{0}]"
            ).format(index, cell_width, cell_height)
        )
    if count == 1:
        filters.append("[v0]null[sheet]")
    else:
        layout = []
        for index in range(count):
            row, column = divmod(index, columns)
            layout.append("{}_{}".format(column * cell_width, row * cell_height))
        inputs = "".join("[v{}]".format(index) for index in range(count))
        filters.append(
            "{}xstack=inputs={}:layout={}:fill=black[sheet]".format(
                inputs, count, "|".join(layout)
            )
        )

    temporary = _temporary_output(destination)
    arguments.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[sheet]",
            "-frames:v",
            "1",
        ]
    )
    if destination.suffix.casefold() in {".jpg", ".jpeg"}:
        arguments.extend(["-q:v", "2"])
    arguments.append(str(temporary))

    try:
        run_ffmpeg(arguments, timeout=timeout)
        output_details = probe_image(temporary)
        if (
            output_details["width"] != expected_width
            or output_details["height"] != expected_height
        ):
            raise ContactSheetError("FFmpeg utworzył contact sheet o nieoczekiwanych wymiarach.")
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise

    cells: List[Dict[str, Any]] = []
    for index, (asset_id, source) in enumerate(unique_entries):
        row, column = divmod(index, columns)
        cells.append(
            {
                "index": index,
                "row": row,
                "column": column,
                "x": column * cell_width,
                "y": row * cell_height,
                "asset_id": asset_id,
                "source_path": str(source),
                "source_sha256": sha256_file(source),
            }
        )
    result: Dict[str, Any] = {
        "schema_version": 1,
        "contact_sheet_path": str(destination),
        "contact_sheet_sha256": sha256_file(temporary),
        "columns": columns,
        "rows": rows,
        "cell_width": cell_width,
        "cell_height": cell_height,
        "width": columns * cell_width,
        "height": rows * cell_height,
        "image_count": count,
        "cells": cells,
    }
    index_temporary: Optional[Path] = None
    index_destination: Optional[Path] = None
    if index_path is not None:
        try:
            index_input = Path(index_path)
            if index_input.exists() and index_input.is_symlink():
                raise ContactSheetError("Indeks nie może być dowiązaniem symbolicznym.")
            index_destination = index_input.parent.resolve() / index_input.name
            if index_destination == destination or index_destination in seen_paths:
                raise ContactSheetError(
                    "Indeks nie może nadpisać obrazu źródłowego ani contact sheet."
                )
            result["index_path"] = str(index_destination)
            index_temporary = _temporary_output(index_destination)
            atomic_write_json(index_temporary, result)
        except Exception:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            try:
                index_temporary.unlink()
            except FileNotFoundError:
                pass
            raise
    else:
        result["index_path"] = None

    publication = [(temporary, destination)]
    if index_temporary is not None and index_destination is not None:
        publication.append((index_temporary, index_destination))
    try:
        _publish_staged_outputs(publication)
    finally:
        for staged, _ in publication:
            try:
                staged.unlink()
            except FileNotFoundError:
                pass
    return result


def build_parser() -> argparse.ArgumentParser:
    """Zbuduj polski interfejs poleceń generatora contact sheet."""

    parser = PolishArgumentParser(
        description="Utwórz lokalny arkusz kontaktowy FFmpeg i osobny indeks JSON."
    )
    parser.add_argument("images", nargs="+", help="Lokalne obrazy JPEG/PNG.")
    parser.add_argument("--output", required=True, help="Docelowy plik JPEG/PNG.")
    parser.add_argument("--index", help="Opcjonalny plik indeksu JSON.")
    parser.add_argument("--columns", type=int, help="Liczba kolumn; domyślnie automatyczna.")
    parser.add_argument("--cell-width", type=int, default=DEFAULT_CELL_WIDTH)
    parser.add_argument("--cell-height", type=int, default=DEFAULT_CELL_HEIGHT)
    parser.add_argument("--max-images", type=int, default=DEFAULT_MAX_IMAGES)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Uruchom generator CLI i wypisz indeks contact sheet jako JSON."""

    args = build_parser().parse_args(argv)
    try:
        result = make_contact_sheet(
            args.images,
            args.output,
            columns=args.columns,
            cell_width=args.cell_width,
            cell_height=args.cell_height,
            max_images=args.max_images,
            index_path=args.index,
        )
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    except (ContactSheetError, MediaError, OSError, ValueError) as exc:
        sys.stderr.write("Błąd contact sheet: {}\n".format(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["ContactSheetError", "make_contact_sheet"]
