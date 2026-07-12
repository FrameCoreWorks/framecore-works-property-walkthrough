#!/usr/bin/env python3
"""Łączy manifest ingestionu i analizę zdjęć z głównym stanem projektu."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Set

from _common import (
    PolishArgumentParser,
    atomic_write_json,
    load_json,
    locked_project_mutation,
    resolve_project_path,
    sha256_file,
    utc_now,
    validate_project_root,
)
from _schema import DocumentValidationError, load_schema, validate_document


ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
IMAGE_ANALYSIS_SCHEMA_PATH = ASSETS_DIR / "image-analysis.schema.json"
PROJECT_SCHEMA_PATH = ASSETS_DIR / "project.schema.json"


class ImageAnalysisApplicationError(ValueError):
    """Oznacza niespójność ingestionu, analizy albo głównego manifestu."""


def _asset_map(project_root: Path, ingestion: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Waliduje assety ingestionu i zwraca kanoniczną mapę według SHA-256."""

    raw_assets = ingestion.get("assets")
    if not isinstance(raw_assets, list) or not raw_assets:
        raise ImageAnalysisApplicationError("Manifest ingestion nie zawiera assetów.")
    assets: Dict[str, Dict[str, Any]] = {}
    for index, raw in enumerate(raw_assets):
        if not isinstance(raw, dict):
            raise ImageAnalysisApplicationError(
                f"Asset ingestion o indeksie {index} nie jest obiektem."
            )
        digest = raw.get("sha256") or raw.get("asset_id")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ImageAnalysisApplicationError("Asset ingestion nie ma poprawnego SHA-256.")
        if digest in assets:
            raise ImageAnalysisApplicationError("Manifest ingestion zawiera powtórzony asset.")
        source = resolve_project_path(
            project_root,
            raw.get("original_path", ""),
            must_exist=True,
        )
        if sha256_file(source) != digest:
            raise ImageAnalysisApplicationError(
                f"Hash pliku assetu {digest} nie zgadza się z manifestem ingestion."
            )
        relative_source = source.relative_to(project_root).as_posix()
        normalized: Dict[str, Any] = {
            "asset_id": digest,
            "image_id": digest,
            "sha256": digest,
            "path": relative_source,
            "original_path": relative_source,
            "preferred": raw.get("preferred") is True,
            "provenance": list(raw.get("provenance", [])),
        }
        thumbnail = raw.get("thumbnail_path")
        if isinstance(thumbnail, str) and thumbnail:
            thumbnail_path = resolve_project_path(project_root, thumbnail, must_exist=True)
            normalized["thumbnail_path"] = thumbnail_path.relative_to(project_root).as_posix()
        assets[digest] = normalized
    return assets


def _normalize_analysis(
    project_root: Path,
    analysis: Mapping[str, Any],
    assets: Mapping[str, Dict[str, Any]],
    *,
    rights_confirmed: bool,
    pii_reviewed: bool,
    pii_image_ids: Set[str],
) -> tuple[Dict[str, Dict[str, Any]], list[str]]:
    """Buduje klasyfikacje oraz stabilną listę wybranych zdjęć."""

    images = analysis.get("images")
    if not isinstance(images, list):
        raise ImageAnalysisApplicationError("Analiza nie zawiera listy images.")
    analysis_ids = {
        image.get("image_id") for image in images if isinstance(image, dict)
    }
    if analysis_ids != set(assets):
        missing = sorted(set(assets) - analysis_ids)
        unknown = sorted(analysis_ids - set(assets))
        raise ImageAnalysisApplicationError(
            "Analiza musi obejmować dokładnie assety ingestion. "
            f"Braki: {missing}; nieznane: {unknown}."
        )
    if not pii_image_ids <= set(assets):
        raise ImageAnalysisApplicationError("Lista PII zawiera nieznany identyfikator obrazu.")
    if pii_image_ids and not pii_reviewed:
        raise ImageAnalysisApplicationError(
            "Oznaczenie PII wymaga potwierdzenia wykonania przeglądu PII."
        )

    classifications: Dict[str, Dict[str, Any]] = {}
    selected: list[str] = []
    for image in images:
        if not isinstance(image, dict):
            raise ImageAnalysisApplicationError("Wpis analizy zdjęcia nie jest obiektem.")
        image_id = str(image["image_id"])
        expected_path = assets[image_id]["path"]
        if image.get("relative_path") != expected_path:
            raise ImageAnalysisApplicationError(
                f"Analiza obrazu {image_id} wskazuje inną ścieżkę niż ingestion."
            )
        record = dict(image)
        record["path"] = expected_path
        record["rights_confirmed"] = rights_confirmed
        record["pii_reviewed"] = pii_reviewed
        record["contains_pii"] = image_id in pii_image_ids
        classifications[image_id] = record
        if image.get("curation_status") == "selected":
            selected.append(image_id)
    return classifications, selected


@locked_project_mutation
def apply_image_analysis(
    project_root: Path,
    ingestion_path: Path,
    analysis_path: Path,
    *,
    rights_confirmed: bool = False,
    pii_reviewed: bool = False,
    pii_image_ids: Iterable[str] = (),
) -> Dict[str, Any]:
    """Atomowo zastosuj ingestion i analizę bez ręcznej edycji project.json."""

    if not isinstance(rights_confirmed, bool) or not isinstance(pii_reviewed, bool):
        raise ImageAnalysisApplicationError(
            "Potwierdzenia praw i przeglądu PII muszą być wartościami logicznymi."
        )
    root = validate_project_root(project_root)
    ingestion_file = resolve_project_path(root, ingestion_path, must_exist=True)
    analysis_file = resolve_project_path(root, analysis_path, must_exist=True)
    project = load_json(root / "project.json")
    ingestion = load_json(ingestion_file)
    analysis = load_json(analysis_file)
    if not isinstance(project, dict) or not isinstance(ingestion, dict) or not isinstance(analysis, dict):
        raise ImageAnalysisApplicationError("Projekt, ingestion i analiza muszą być obiektami JSON.")
    if analysis.get("project_id") != project.get("project_id"):
        raise ImageAnalysisApplicationError("Analiza dotyczy innego projektu.")
    try:
        validate_document(
            analysis,
            load_schema(IMAGE_ANALYSIS_SCHEMA_PATH),
            semantic_kind="image-analysis",
        )
    except (DocumentValidationError, ValueError) as error:
        raise ImageAnalysisApplicationError(str(error)) from error

    assets = _asset_map(root, ingestion)
    classifications, selected = _normalize_analysis(
        root,
        analysis,
        assets,
        rights_confirmed=rights_confirmed,
        pii_reviewed=pii_reviewed,
        pii_image_ids=set(pii_image_ids),
    )
    project["assets"] = assets
    project["classifications"] = classifications
    project["selected_images"] = selected
    stages = project.setdefault("stages", {})
    if not isinstance(stages, dict):
        raise ImageAnalysisApplicationError("Pole stages musi być obiektem.")
    stages["ingestion"] = "complete"
    stages["image_analysis"] = "complete"
    stages["scene_planning"] = "pending"
    stages["prompt_preparation"] = "pending"
    stages["generation"] = "pending"
    stages["rendering"] = "invalidated" if project.get("output") else "pending"
    output = project.get("output")
    if isinstance(output, dict) and output:
        output["render_status"] = "invalidated"

    hashes = project.setdefault("hashes", {})
    if not isinstance(hashes, dict):
        raise ImageAnalysisApplicationError("Pole hashes musi być obiektem.")
    hashes[ingestion_file.relative_to(root).as_posix()] = sha256_file(ingestion_file)
    hashes[analysis_file.relative_to(root).as_posix()] = sha256_file(analysis_file)
    for asset in assets.values():
        hashes[asset["path"]] = asset["sha256"]

    settings = project.setdefault("settings", {})
    if not isinstance(settings, dict):
        raise ImageAnalysisApplicationError("Pole settings musi być obiektem.")
    settings["ingestion_manifest_path"] = ingestion_file.relative_to(root).as_posix()
    settings["image_analysis_path"] = analysis_file.relative_to(root).as_posix()
    project["manifest_revision"] = int(project.get("manifest_revision", 0)) + 1
    timestamps = project.setdefault("timestamps", {})
    if isinstance(timestamps, dict):
        timestamps["updated_at"] = utc_now()
    try:
        validate_document(
            project,
            load_schema(PROJECT_SCHEMA_PATH),
            semantic_kind="project",
            project_root=root,
        )
    except (DocumentValidationError, ValueError) as error:
        raise ImageAnalysisApplicationError(str(error)) from error
    atomic_write_json(root / "project.json", project)
    return {
        "project_id": project["project_id"],
        "asset_count": len(assets),
        "selected_count": len(selected),
        "rights_confirmed": rights_confirmed,
        "pii_reviewed": pii_reviewed,
        "manifest_revision": project["manifest_revision"],
    }


def build_parser() -> argparse.ArgumentParser:
    """Buduje polski interfejs zastosowania analizy zdjęć."""

    parser = PolishArgumentParser(
        description="Łączy ingestion i analizę zdjęć z głównym manifestem projektu."
    )
    parser.add_argument("--project", required=True, type=Path, help="Katalog projektu.")
    parser.add_argument("--ingestion", required=True, type=Path, help="Manifest ingestion.json.")
    parser.add_argument("--analysis", required=True, type=Path, help="Zweryfikowana analiza zdjęć JSON.")
    parser.add_argument(
        "--rights-confirmed",
        action="store_true",
        help="Potwierdź prawa do użycia wszystkich analizowanych materiałów.",
    )
    parser.add_argument(
        "--pii-reviewed",
        action="store_true",
        help="Potwierdź wykonanie przeglądu danych osobowych.",
    )
    parser.add_argument(
        "--contains-pii",
        action="append",
        default=[],
        metavar="IMAGE_ID",
        help="Oznacz obraz zawierający dane osobowe; opcję można powtórzyć.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Uruchamia atomowe zastosowanie analizy i wypisuje raport JSON."""

    args = build_parser().parse_args(argv)
    try:
        result = apply_image_analysis(
            args.project,
            args.ingestion,
            args.analysis,
            rights_confirmed=args.rights_confirmed,
            pii_reviewed=args.pii_reviewed,
            pii_image_ids=args.contains_pii,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (ImageAnalysisApplicationError, OSError, ValueError) as error:
        print(f"Błąd zastosowania analizy zdjęć: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
