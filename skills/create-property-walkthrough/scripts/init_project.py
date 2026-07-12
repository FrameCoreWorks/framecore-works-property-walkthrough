#!/usr/bin/env python3
"""Utwórz kompletne, lokalne drzewo projektu walkthrough nieruchomości."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence
from urllib.parse import urlsplit

try:
    from ._common import (
        PolishArgumentParser,
        ProjectStateError,
        atomic_write_json,
        load_json,
        safe_slug,
        sha256_file,
        utc_now,
        validate_project_id,
    )
    from ._schema import (
        DocumentValidationError,
        SchemaDefinitionError,
        load_schema,
        validate_document,
    )
except ImportError:
    from _common import (  # type: ignore
        PolishArgumentParser,
        ProjectStateError,
        atomic_write_json,
        load_json,
        safe_slug,
        sha256_file,
        utc_now,
        validate_project_id,
    )
    from _schema import (  # type: ignore
        DocumentValidationError,
        SchemaDefinitionError,
        load_schema,
        validate_document,
    )


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
ASSETS_DIR = SKILL_DIR / "assets"
TEMPLATES_DIR = ASSETS_DIR / "project-templates"
PROJECT_SCHEMA_PATH = ASSETS_DIR / "project.schema.json"
PROVIDER_SCHEMA_PATH = ASSETS_DIR / "provider-profile.schema.json"

PROJECT_DIRECTORIES = (
    "source-images",
    "thumbnails",
    "contact-sheets",
    "rejected",
    "prompts",
    "generation-package",
    "scenes",
    "scenes/imported",
    "scenes/approved",
    "scenes/rejected",
    "final",
    "reports",
    "provider",
)

SOURCE_MODES = (
    "listing-url",
    "uploaded-images",
    "directory",
    "zip",
    "hybrid",
    "manual",
    "synthetic",
)


class ProjectInitializationError(ValueError):
    """Błąd bezpiecznej inicjalizacji projektu."""


class ProjectInitializationPostCommitError(ProjectInitializationError):
    """Projekt opublikowano, lecz nie potwierdzono trwałości katalogu nadrzędnego."""

    def __init__(self, project_path: Path, message: str) -> None:
        super().__init__(message)
        self.project_path = project_path
        self.committed = True
        self.published = True


def _fsync_directory(directory: Path) -> None:
    """Utrwal publikację katalogu projektu na obsługiwanym filesystemie."""

    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(str(directory), flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _source_domain(source_url: Optional[str]) -> Optional[str]:
    """Sprawdź opcjonalny URL i zwróć jego znormalizowaną domenę."""

    if source_url is None:
        return None
    if not isinstance(source_url, str) or not source_url.strip():
        raise ProjectInitializationError("URL źródłowy musi być niepustym tekstem.")
    parsed = urlsplit(source_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ProjectInitializationError("URL źródłowy musi używać HTTP albo HTTPS i zawierać host.")
    if parsed.username or parsed.password:
        raise ProjectInitializationError("URL źródłowy nie może zawierać danych logowania.")
    return parsed.hostname.lower()


def _write_source_note(path: Path, name: str, mode: str, url: Optional[str]) -> None:
    """Zapisz lokalną notę źródłową w nieopublikowanym katalogu stagingowym."""

    template_path = TEMPLATES_DIR / "SOURCE.md"
    try:
        base = template_path.read_text(encoding="utf-8").rstrip()
    except (OSError, UnicodeDecodeError) as exc:
        raise ProjectInitializationError(
            f"Nie można odczytać szablonu SOURCE.md: {exc}"
        ) from exc

    safe_name = " ".join(name.split())
    safe_url = url if url is not None else "brak"
    escaped_name = safe_name.replace("`", "'")
    escaped_url = safe_url.replace("`", "'")
    content = (
        f"{base}\n\n"
        "## Dane inicjalne\n\n"
        f"- Nazwa: `{escaped_name}`\n"
        f"- Tryb wejścia: `{mode}`\n"
        f"- URL: `{escaped_url}`\n"
    )
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise ProjectInitializationError(f"Nie można zapisać SOURCE.md: {exc}") from exc


def _initial_manifest(
    project_id: str,
    name: str,
    source_mode: str,
    source_url: Optional[str],
    source_domain: Optional[str],
    source_metadata: Optional[Mapping[str, Any]],
    snapshot_hash: str,
    source_note_hash: str,
) -> Dict[str, Any]:
    """Zbuduj pierwszą wersję manifestu bez danych zewnętrznych i sekretów."""

    timestamp = utc_now()
    return {
        "schema_version": "1.0",
        "manifest_revision": 1,
        "project_id": project_id,
        "source": {
            "name": name,
            "mode": source_mode,
            "url": source_url,
            "domain": source_domain,
            "metadata": dict(source_metadata or {}),
            "provenance": [],
        },
        "settings": {
            "language": "pl",
            "prompt_language": "en",
            "target_aspect_ratios": ["16:9"],
            "target_scene_count": 8,
            "default_scene_duration_seconds": 5,
            "automatic_audio": False,
            "personal_data_overlays": False,
        },
        "stages": {
            "ingestion": "pending",
            "image_analysis": "pending",
            "scene_planning": "pending",
            "prompt_preparation": "pending",
            "provider_configuration": "pending",
            "generation": "pending",
            "clip_import": "pending",
            "quality_control": "pending",
            "rendering": "pending",
            "validation": "pending",
        },
        "hashes": {
            "SOURCE.md": source_note_hash,
            "provider/provider-profile.snapshot.json": snapshot_hash,
        },
        "classifications": {},
        "selected_images": [],
        "scene_plan": {"revision": 0, "scenes": [], "tombstones": []},
        "prompts": {},
        "provider_profile": {
            "status": "not_configured",
            "snapshot_path": "provider/provider-profile.snapshot.json",
            "snapshot_sha256": snapshot_hash,
        },
        "model": {},
        "jobs": [],
        "clips": [],
        "qc": {},
        "output": {},
        "warnings": [],
        "errors": [],
        "timestamps": {"created_at": timestamp, "updated_at": timestamp},
    }


def create_project(
    projects_root: Path,
    name: str,
    project_id: Optional[str] = None,
    source_mode: str = "manual",
    source_url: Optional[str] = None,
    source_metadata: Optional[Mapping[str, Any]] = None,
) -> Path:
    """Utwórz pełny projekt w stagingu i opublikuj go jednym rename.

    Funkcja nie wykonuje sieci, nie konfiguruje providera i nie nadpisuje
    istniejącego katalogu projektu.
    """

    if not isinstance(name, str) or not name.strip():
        raise ProjectInitializationError("Nazwa projektu musi być niepustym tekstem.")
    normalized_name = " ".join(name.split())
    if len(normalized_name) > 200:
        raise ProjectInitializationError("Nazwa projektu nie może przekraczać 200 znaków.")
    if source_mode not in SOURCE_MODES:
        raise ProjectInitializationError(
            "Nieobsługiwany tryb źródła. Dozwolone wartości: " + ", ".join(SOURCE_MODES)
        )
    if source_mode in ("listing-url", "hybrid") and source_url is None:
        raise ProjectInitializationError(f"Tryb {source_mode} wymaga URL źródłowego.")
    if source_url is not None and source_mode not in ("listing-url", "hybrid"):
        raise ProjectInitializationError("URL można podać tylko dla trybu listing-url albo hybrid.")
    if source_metadata is not None and not isinstance(source_metadata, Mapping):
        raise ProjectInitializationError("Metadane źródła muszą być obiektem.")

    identifier = safe_slug(normalized_name) if project_id is None else validate_project_id(project_id)
    source_domain = _source_domain(source_url)
    root = Path(projects_root).expanduser()
    if root.is_symlink():
        raise ProjectInitializationError("Katalog nadrzędny projektów nie może być dowiązaniem symbolicznym.")
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ProjectInitializationError(f"Nie można utworzyć katalogu projektów: {exc}") from exc
    root = root.resolve(strict=True)
    target = root / identifier
    if target.exists() or target.is_symlink():
        raise ProjectInitializationError(f"Projekt o identyfikatorze {identifier!r} już istnieje.")

    try:
        project_schema = load_schema(PROJECT_SCHEMA_PATH)
        provider_schema = load_schema(PROVIDER_SCHEMA_PATH)
        snapshot_template = load_json(
            TEMPLATES_DIR / "provider-profile.snapshot.json"
        )
        validate_document(snapshot_template, provider_schema, "provider-profile")
    except (ProjectStateError, SchemaDefinitionError, DocumentValidationError) as exc:
        raise ProjectInitializationError(f"Niepoprawny asset inicjalizacyjny: {exc}") from exc

    staging = Path(tempfile.mkdtemp(prefix=f".{identifier}.", suffix=".tmp", dir=str(root)))
    published = False
    try:
        for relative_directory in PROJECT_DIRECTORIES:
            (staging / relative_directory).mkdir(parents=True, exist_ok=False)

        snapshot_path = staging / "provider" / "provider-profile.snapshot.json"
        atomic_write_json(snapshot_path, snapshot_template)
        _write_source_note(staging / "SOURCE.md", normalized_name, source_mode, source_url)

        manifest = _initial_manifest(
            project_id=identifier,
            name=normalized_name,
            source_mode=source_mode,
            source_url=source_url,
            source_domain=source_domain,
            source_metadata=source_metadata,
            snapshot_hash=sha256_file(snapshot_path),
            source_note_hash=sha256_file(staging / "SOURCE.md"),
        )
        validate_document(manifest, project_schema, "project", project_root=staging)
        atomic_write_json(staging / "project.json", manifest)

        if target.exists() or target.is_symlink():
            raise ProjectInitializationError(
                f"Projekt o identyfikatorze {identifier!r} powstał równolegle."
            )
        os.replace(staging, target)
        published = True
        try:
            _fsync_directory(root)
        except (OSError, ProjectStateError) as exc:
            raise ProjectInitializationPostCommitError(
                target,
                f"Projekt został opublikowany w {target}, ale nie udało się "
                "potwierdzić trwałości katalogu nadrzędnego.",
            ) from exc
        return target
    except (OSError, ProjectStateError, SchemaDefinitionError, DocumentValidationError) as exc:
        if isinstance(exc, ProjectInitializationError):
            raise
        raise ProjectInitializationError(f"Nie udało się utworzyć projektu: {exc}") from exc
    finally:
        if not published and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


initialize_project = create_project


def build_parser() -> argparse.ArgumentParser:
    """Zbuduj polski interfejs wiersza poleceń."""

    parser = PolishArgumentParser(
        description="Utwórz lokalny projekt filmowej prezentacji bez sieci i dostawcy."
    )
    parser.add_argument("nazwa", help="Czytelna nazwa projektu.")
    parser.add_argument(
        "--projects-root",
        type=Path,
        default=Path.cwd() / "walkthrough-projects",
        help="Katalog nadrzędny projektów (domyślnie ./walkthrough-projects).",
    )
    parser.add_argument(
        "--project-id",
        help="Opcjonalny gotowy identyfikator zamiast identyfikatora utworzonego z nazwy.",
    )
    parser.add_argument(
        "--source-mode",
        choices=SOURCE_MODES,
        default="manual",
        help="Tryb wejścia projektu.",
    )
    parser.add_argument("--source-url", help="Publiczny URL dla listing-url albo hybrid.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Uruchom inicjalizację z argumentów CLI."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        project_path = create_project(
            projects_root=args.projects_root,
            name=args.nazwa,
            project_id=args.project_id,
            source_mode=args.source_mode,
            source_url=args.source_url,
        )
    except (ProjectInitializationError, ProjectStateError) as exc:
        print(f"Błąd: {exc}", file=sys.stderr)
        return 2
    print(f"Utworzono projekt: {project_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PROJECT_DIRECTORIES",
    "ProjectInitializationError",
    "SOURCE_MODES",
    "create_project",
    "initialize_project",
    "main",
]
