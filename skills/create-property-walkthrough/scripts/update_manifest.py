#!/usr/bin/env python3
"""Bezpiecznie aktualizuj manifest, sceny, tombstone'y i hashe projektu."""

from __future__ import annotations

import argparse
import copy
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, MutableMapping, Optional, Sequence

try:
    from ._common import (
        PolishArgumentParser,
        ProjectStateError,
        atomic_write_json,
        exclusive_project_lock,
        load_json,
        resolve_project_path,
        sha256_file,
        utc_now,
        validate_project_root,
    )
    from ._schema import (
        DocumentValidationError,
        SCENE_ID_PATTERN,
        SchemaDefinitionError,
        load_schema,
        validate_document,
    )
except ImportError:
    from _common import (  # type: ignore
        PolishArgumentParser,
        ProjectStateError,
        atomic_write_json,
        exclusive_project_lock,
        load_json,
        resolve_project_path,
        sha256_file,
        utc_now,
        validate_project_root,
    )
    from _schema import (  # type: ignore
        DocumentValidationError,
        SCENE_ID_PATTERN,
        SchemaDefinitionError,
        load_schema,
        validate_document,
    )


SCRIPT_DIR = Path(__file__).resolve().parent
ASSETS_DIR = SCRIPT_DIR.parent / "assets"
PROJECT_SCHEMA_PATH = ASSETS_DIR / "project.schema.json"
PROVIDER_SCHEMA_PATH = ASSETS_DIR / "provider-profile.schema.json"
IMMUTABLE_ROOT_FIELDS = frozenset({"schema_version", "project_id", "manifest_revision", "timestamps"})
PROVIDER_SNAPSHOT_PATH = "provider/provider-profile.snapshot.json"


class ManifestUpdateError(ValueError):
    """Błąd kontrolowanej aktualizacji manifestu projektu."""


def _project_schema() -> Dict[str, Any]:
    """Wczytaj kanoniczny schemat manifestu."""

    return load_schema(PROJECT_SCHEMA_PATH)


def load_project_manifest(project_root: Path, verify_hashes: bool = False) -> Dict[str, Any]:
    """Wczytaj i zwaliduj manifest projektu.

    Gdy ``verify_hashes`` ma wartość prawdziwą, każdy wpis ``hashes`` jest
    dodatkowo porównywany z plikiem na dysku.
    """

    root = validate_project_root(project_root)
    manifest_path = resolve_project_path(root, "project.json", must_exist=True)
    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict):
        raise ManifestUpdateError("project.json musi zawierać obiekt JSON.")
    validate_document(
        manifest,
        _project_schema(),
        "project",
        project_root=root if verify_hashes else None,
    )
    if manifest["project_id"] != root.name:
        raise ManifestUpdateError(
            "Identyfikator w project.json nie odpowiada nazwie katalogu projektu."
        )
    return manifest


def _save_project_manifest_locked(
    root: Path,
    manifest: Mapping[str, Any],
    current: Mapping[str, Any],
    expected_revision: Optional[int],
    verify_hashes: bool,
) -> Dict[str, Any]:
    """Zapisz następną rewizję, gdy caller posiada blokadę projektu."""

    current_revision = current["manifest_revision"]
    if expected_revision is not None and current_revision != expected_revision:
        raise ManifestUpdateError(
            f"Konflikt rewizji: oczekiwano {expected_revision}, a bieżąca rewizja to {current_revision}."
        )
    if not isinstance(manifest, Mapping):
        raise ManifestUpdateError("Nowy manifest musi być obiektem.")
    base_revision = manifest.get("manifest_revision")
    if base_revision != current_revision:
        raise ManifestUpdateError(
            f"Konflikt rewizji bazowej: kandydat powstał z rewizji {base_revision!r}, "
            f"a bieżąca rewizja to {current_revision}."
        )

    candidate = copy.deepcopy(dict(manifest))
    if candidate.get("schema_version") != current["schema_version"]:
        raise ManifestUpdateError("Nie można zmienić schema_version podczas zwykłej aktualizacji.")
    if candidate.get("project_id") != current["project_id"]:
        raise ManifestUpdateError("Nie można zmienić project_id.")
    candidate_timestamps = candidate.get("timestamps")
    if not isinstance(candidate_timestamps, dict):
        raise ManifestUpdateError("Manifest wymaga obiektu timestamps.")
    if candidate_timestamps.get("created_at") != current["timestamps"]["created_at"]:
        raise ManifestUpdateError("Nie można zmienić czasu utworzenia projektu.")

    candidate["manifest_revision"] = current_revision + 1
    candidate["timestamps"]["updated_at"] = utc_now()
    validate_document(
        candidate,
        _project_schema(),
        "project",
        project_root=root if verify_hashes else None,
    )
    atomic_write_json(resolve_project_path(root, "project.json"), candidate)
    return candidate


def save_project_manifest(
    project_root: Path,
    manifest: Mapping[str, Any],
    expected_revision: Optional[int] = None,
    verify_hashes: bool = False,
) -> Dict[str, Any]:
    """Zapisz kolejną rewizję pod wyłączną blokadą projektu.

    ``schema_version``, ``project_id`` i ``created_at`` pozostają niezmienne.
    Kandydat musi bazować na bieżącej rewizji, także gdy caller nie podał
    jawnie ``expected_revision``.
    """

    root = validate_project_root(project_root)
    with exclusive_project_lock(root):
        current = load_project_manifest(root, verify_hashes=False)
        return _save_project_manifest_locked(
            root,
            manifest,
            current,
            expected_revision,
            verify_hashes,
        )


def mutate_project_manifest(
    project_root: Path,
    mutator: Callable[[Dict[str, Any]], None],
    expected_revision: Optional[int] = None,
    verify_hashes: bool = False,
) -> Dict[str, Any]:
    """Wykonaj pełne read-check-mutate-validate-write pod jedną blokadą."""

    if not callable(mutator):
        raise ManifestUpdateError("Mutator manifestu musi być wywoływalny.")
    root = validate_project_root(project_root)
    with exclusive_project_lock(root):
        current = load_project_manifest(root, verify_hashes=False)
        if expected_revision is not None and current["manifest_revision"] != expected_revision:
            raise ManifestUpdateError(
                f"Konflikt rewizji: oczekiwano {expected_revision}, "
                f"a bieżąca rewizja to {current['manifest_revision']}."
            )
        candidate = copy.deepcopy(current)
        mutator(candidate)
        return _save_project_manifest_locked(
            root,
            candidate,
            current,
            expected_revision,
            verify_hashes,
        )


def _deep_merge(target: MutableMapping[str, Any], patch: Mapping[str, Any]) -> None:
    """Scal zagnieżdżone obiekty bez niejawnego usuwania pól."""

    for key, value in patch.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), MutableMapping):
            _deep_merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def update_manifest(
    project_root: Path,
    patch: Mapping[str, Any],
    expected_revision: Optional[int] = None,
    verify_hashes: bool = False,
) -> Dict[str, Any]:
    """Zastosuj bezpieczny patch obiektowy i zapisz nową rewizję."""

    if not isinstance(patch, Mapping):
        raise ManifestUpdateError("Patch manifestu musi być obiektem JSON.")
    forbidden = sorted(IMMUTABLE_ROOT_FIELDS.intersection(patch.keys()))
    if forbidden:
        raise ManifestUpdateError(
            "Patch nie może zmieniać pól zarządzanych przez stan: " + ", ".join(forbidden)
        )
    def apply_patch(candidate: Dict[str, Any]) -> None:
        _deep_merge(candidate, patch)

    return mutate_project_manifest(
        project_root,
        apply_patch,
        expected_revision=expected_revision,
        verify_hashes=verify_hashes,
    )


def allocate_scene_id(manifest: Mapping[str, Any]) -> str:
    """Wylosuj nieprzezroczysty scene_id, którego nie używa stan ani tombstone."""

    scene_plan = manifest.get("scene_plan", {})
    used = {
        item.get("scene_id")
        for item in list(scene_plan.get("scenes", [])) + list(scene_plan.get("tombstones", []))
    }
    for _ in range(128):
        candidate = "scn_" + uuid.uuid4().hex[:16]
        if candidate not in used:
            return candidate
    raise ManifestUpdateError("Nie udało się przydzielić unikalnego scene_id.")


def add_scene(
    project_root: Path,
    scene: Mapping[str, Any],
    expected_revision: Optional[int] = None,
) -> Dict[str, Any]:
    """Dodaj scenę, zachowując istniejące ID i przydzielając nowe tylko raz."""

    if not isinstance(scene, Mapping):
        raise ManifestUpdateError("Scena musi być obiektem.")
    def append_scene(candidate: Dict[str, Any]) -> None:
        scene_plan = candidate["scene_plan"]
        new_scene = copy.deepcopy(dict(scene))
        scene_id = new_scene.get("scene_id") or allocate_scene_id(candidate)
        if not isinstance(scene_id, str) or SCENE_ID_PATTERN.fullmatch(scene_id) is None:
            raise ManifestUpdateError("scene_id nie jest bezpiecznym stabilnym identyfikatorem.")
        used = {
            item["scene_id"]
            for item in scene_plan["scenes"] + scene_plan["tombstones"]
        }
        if scene_id in used:
            raise ManifestUpdateError("scene_id już istnieje albo pozostawiło tombstone.")
        if "source_image_id" not in new_scene:
            raise ManifestUpdateError("Nowa scena wymaga source_image_id.")

        new_scene["scene_id"] = scene_id
        new_scene["sequence_index"] = len(scene_plan["scenes"])
        scene_plan["scenes"].append(new_scene)
        scene_plan["revision"] += 1

    return mutate_project_manifest(
        project_root, append_scene, expected_revision=expected_revision
    )


def tombstone_scene(
    project_root: Path,
    scene_id: str,
    reason: str,
    expected_revision: Optional[int] = None,
) -> Dict[str, Any]:
    """Usuń aktywną scenę, zachowując trwały tombstone i stabilne pozostałe ID."""

    if not isinstance(reason, str) or not reason.strip():
        raise ManifestUpdateError("Powód usunięcia sceny musi być niepustym tekstem.")
    def remove_scene(candidate: Dict[str, Any]) -> None:
        scene_plan = candidate["scene_plan"]
        matching = [item for item in scene_plan["scenes"] if item["scene_id"] == scene_id]
        if len(matching) != 1:
            raise ManifestUpdateError("Nie znaleziono dokładnie jednej aktywnej sceny o podanym ID.")
        removed = matching[0]
        scene_plan["scenes"] = [
            item for item in scene_plan["scenes"] if item["scene_id"] != scene_id
        ]
        scene_plan["tombstones"].append(
            {
                "scene_id": scene_id,
                "removed_at": utc_now(),
                "reason": " ".join(reason.split()),
                "last_sequence_index": removed["sequence_index"],
                "source_image_id": removed["source_image_id"],
            }
        )
        for index, item in enumerate(scene_plan["scenes"]):
            item["sequence_index"] = index
        scene_plan["revision"] += 1

    return mutate_project_manifest(
        project_root, remove_scene, expected_revision=expected_revision
    )


def reorder_scenes(
    project_root: Path,
    ordered_scene_ids: Sequence[str],
    expected_revision: Optional[int] = None,
) -> Dict[str, Any]:
    """Zmień wyłącznie sequence_index; nigdy nie zmieniaj scene_id."""

    def apply_order(candidate: Dict[str, Any]) -> None:
        scenes = candidate["scene_plan"]["scenes"]
        existing_ids = [item["scene_id"] for item in scenes]
        if len(ordered_scene_ids) != len(set(ordered_scene_ids)):
            raise ManifestUpdateError("Lista kolejności zawiera powtórzone scene_id.")
        if set(ordered_scene_ids) != set(existing_ids) or len(ordered_scene_ids) != len(existing_ids):
            raise ManifestUpdateError(
                "Lista kolejności musi zawierać dokładnie wszystkie aktywne scene_id."
            )

        by_id = {item["scene_id"]: item for item in scenes}
        reordered = []
        for index, ordered_id in enumerate(ordered_scene_ids):
            item = by_id[ordered_id]
            item["sequence_index"] = index
            reordered.append(item)
        candidate["scene_plan"]["scenes"] = reordered
        candidate["scene_plan"]["revision"] += 1

    return mutate_project_manifest(
        project_root, apply_order, expected_revision=expected_revision
    )


def record_file_hash(
    project_root: Path,
    relative_path: str,
    expected_revision: Optional[int] = None,
) -> Dict[str, Any]:
    """Oblicz SHA-256 pliku wewnątrz projektu i zapisz go w manifeście."""

    root = validate_project_root(project_root)
    if relative_path == "project.json":
        raise ManifestUpdateError("project.json nie może zawierać własnego hasha.")
    file_path = resolve_project_path(root, relative_path, must_exist=True)
    canonical_relative = file_path.relative_to(root).as_posix()

    def store_hash(candidate: Dict[str, Any]) -> None:
        digest = sha256_file(file_path)
        candidate["hashes"][canonical_relative] = digest

        if canonical_relative == PROVIDER_SNAPSHOT_PATH:
            snapshot = load_json(file_path)
            if not isinstance(snapshot, dict):
                raise ManifestUpdateError("Snapshot profilu providera musi być obiektem JSON.")
            validate_document(snapshot, load_schema(PROVIDER_SCHEMA_PATH), "provider-profile")
            candidate["provider_profile"] = {
                "status": snapshot["status"],
                "snapshot_path": PROVIDER_SNAPSHOT_PATH,
                "snapshot_sha256": digest,
            }

    return mutate_project_manifest(
        root,
        store_hash,
        expected_revision=expected_revision,
        verify_hashes=False,
    )


load_manifest = load_project_manifest
save_manifest = save_project_manifest


def build_parser() -> argparse.ArgumentParser:
    """Zbuduj polski interfejs aktualizacji manifestu."""

    parser = PolishArgumentParser(
        description="Zaktualizuj project.json atomowo, bez sieci i bez sekretów."
    )
    parser.add_argument("projekt", type=Path, help="Katalog konkretnego projektu.")
    operations = parser.add_mutually_exclusive_group(required=True)
    operations.add_argument("--patch", type=Path, help="Plik JSON z patchem obiektowym.")
    operations.add_argument(
        "--hash-file",
        action="append",
        metavar="ŚCIEŻKA",
        help="Względna ścieżka pliku do zapisania SHA-256; opcję można powtórzyć.",
    )
    operations.add_argument("--tombstone-scene", metavar="SCENE_ID", help="Usuń scenę z tombstone'em.")
    operations.add_argument(
        "--reorder-scenes",
        nargs="+",
        metavar="SCENE_ID",
        help="Pełna nowa kolejność aktywnych scen.",
    )
    parser.add_argument("--reason", help="Powód wymagany dla --tombstone-scene.")
    parser.add_argument(
        "--expected-revision",
        type=int,
        help="Opcjonalna oczekiwana rewizja do wykrycia konfliktu.",
    )
    parser.add_argument(
        "--verify-hashes",
        action="store_true",
        help="Po patchu sprawdź wszystkie zapisane hashe plików.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Uruchom wybraną operację aktualizacji z CLI."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.patch is not None:
            patch = load_json(args.patch)
            result = update_manifest(
                args.projekt,
                patch,
                expected_revision=args.expected_revision,
                verify_hashes=args.verify_hashes,
            )
        elif args.hash_file is not None:
            result = None
            expected = args.expected_revision
            for relative_path in args.hash_file:
                result = record_file_hash(args.projekt, relative_path, expected_revision=expected)
                expected = result["manifest_revision"]
            if result is None:
                raise ManifestUpdateError("Nie podano pliku do haszowania.")
        elif args.tombstone_scene is not None:
            if not args.reason:
                raise ManifestUpdateError("Opcja --tombstone-scene wymaga --reason.")
            result = tombstone_scene(
                args.projekt,
                args.tombstone_scene,
                args.reason,
                expected_revision=args.expected_revision,
            )
        else:
            result = reorder_scenes(
                args.projekt,
                args.reorder_scenes,
                expected_revision=args.expected_revision,
            )
    except (
        DocumentValidationError,
        ManifestUpdateError,
        ProjectStateError,
        SchemaDefinitionError,
    ) as exc:
        print(f"Błąd: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "project_id": result["project_id"],
                "manifest_revision": result["manifest_revision"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ManifestUpdateError",
    "add_scene",
    "allocate_scene_id",
    "load_manifest",
    "load_project_manifest",
    "main",
    "mutate_project_manifest",
    "record_file_hash",
    "reorder_scenes",
    "save_manifest",
    "save_project_manifest",
    "tombstone_scene",
    "update_manifest",
]
