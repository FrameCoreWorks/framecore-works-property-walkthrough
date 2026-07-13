#!/usr/bin/env python3
"""Ograniczony, jawny walidator JSON Schema i reguł domenowych."""

from __future__ import annotations

import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit

try:
    from ._common import (
        PROJECT_ID_PATTERN,
        SHA256_PATTERN,
        ProjectStateError,
        load_json,
        resolve_project_path,
        sha256_file,
        validate_project_id,
    )
except ImportError:
    from _common import (  # type: ignore
        PROJECT_ID_PATTERN,
        SHA256_PATTERN,
        ProjectStateError,
        load_json,
        resolve_project_path,
        sha256_file,
        validate_project_id,
    )


SUPPORTED_KEYWORDS = frozenset(
    {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "minItems",
        "maxItems",
        "enum",
        "const",
        "minLength",
        "maxLength",
        "pattern",
        "minimum",
        "maximum",
    }
)
SUPPORTED_TYPES = frozenset(
    {"object", "array", "string", "number", "integer", "boolean", "null"}
)
SEMANTIC_KINDS = frozenset(
    {"project", "image-analysis", "scene-plan", "provider-profile"}
)
PROJECT_SCHEMA_VERSION = "1.0"
SCENE_ID_PATTERN = re.compile(r"^scn_[a-z0-9]{12,32}$")
IMAGE_ID_PATTERN = re.compile(r"^(?:img_)?[0-9a-f]{64}$")
SAFE_RELATIVE_PART = re.compile(r"^[^\x00]+$")
SECRET_FIELD_PATTERN = re.compile(
    r"(^|_)(api_?key|access_?token|refresh_?token|password|passwd|authorization|"
    r"credential|secret|client_?secret|private_?key|cookie)(_|$)",
    re.IGNORECASE,
)
SECRET_REFERENCE_PATTERN = re.compile(
    r"^(?:env|keychain|secret-store|mcp-oauth):"
    r"[A-Za-z0-9_.@/:-]{1,240}$"
)


class SchemaDefinitionError(ValueError):
    """Błąd definicji obsługiwanego podzbioru JSON Schema."""


class DocumentValidationError(ValueError):
    """Błąd danych względem schematu albo reguł semantycznych."""


def _schema_error(path: str, message: str) -> SchemaDefinitionError:
    return SchemaDefinitionError(f"Niepoprawny schemat w {path}: {message}")


def _validation_error(path: str, message: str) -> DocumentValidationError:
    return DocumentValidationError(f"Niepoprawne dane w {path}: {message}")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _json_equal(left: Any, right: Any) -> bool:
    """Porównaj wartości zgodnie z typami JSON, rozróżniając bool od liczb."""

    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if _is_number(left) and _is_number(right):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _json_equal(a, b) for a, b in zip(left, right)
        )
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _json_equal(left[key], right[key]) for key in left
        )
    return left == right


def _validate_nonnegative_integer(value: Any, path: str, keyword: str) -> None:
    if not _is_integer(value) or value < 0:
        raise _schema_error(path, f"{keyword} musi być nieujemną liczbą całkowitą.")


def validate_schema(schema: Any, path: str = "$schema") -> None:
    """Sprawdź definicję obsługiwanego podzbioru JSON Schema.

    Każde nieobsługiwane słowo kluczowe powoduje błąd. Walidator nie ignoruje
    rozszerzeń ani konstrukcji spoza jawnej listy.
    """

    if not isinstance(schema, dict):
        raise _schema_error(path, "schemat musi być obiektem JSON.")

    for keyword in schema:
        if keyword not in SUPPORTED_KEYWORDS:
            raise _schema_error(path, f"nieobsługiwane słowo kluczowe: {keyword}")

    declared_type = schema.get("type")
    if declared_type is not None:
        types = [declared_type] if isinstance(declared_type, str) else declared_type
        if not isinstance(types, list) or not types:
            raise _schema_error(path, "type musi być nazwą typu albo niepustą listą typów.")
        if any(not isinstance(item, str) or item not in SUPPORTED_TYPES for item in types):
            raise _schema_error(path, "type zawiera nieobsługiwany typ JSON.")
        if len(set(types)) != len(types):
            raise _schema_error(path, "type nie może zawierać powtórzonych typów.")

    properties = schema.get("properties")
    if properties is not None:
        if not isinstance(properties, dict):
            raise _schema_error(path, "properties musi być obiektem.")
        for name, child in properties.items():
            if not isinstance(name, str):
                raise _schema_error(path, "nazwa właściwości musi być tekstem.")
            validate_schema(child, f"{path}.properties[{name!r}]")

    required = schema.get("required")
    if required is not None:
        if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
            raise _schema_error(path, "required musi być listą nazw właściwości.")
        if len(set(required)) != len(required):
            raise _schema_error(path, "required nie może zawierać powtórzeń.")
        if properties is not None:
            missing_definitions = [item for item in required if item not in properties]
            if missing_definitions:
                raise _schema_error(
                    path,
                    "required wskazuje niezdefiniowane właściwości: "
                    + ", ".join(missing_definitions),
                )

    additional = schema.get("additionalProperties")
    if additional is not None and not isinstance(additional, (bool, dict)):
        raise _schema_error(path, "additionalProperties musi być wartością logiczną albo schematem.")
    if isinstance(additional, dict):
        validate_schema(additional, f"{path}.additionalProperties")

    if "items" in schema:
        validate_schema(schema["items"], f"{path}.items")

    for keyword in ("minItems", "maxItems", "minLength", "maxLength"):
        if keyword in schema:
            _validate_nonnegative_integer(schema[keyword], path, keyword)

    if "minItems" in schema and "maxItems" in schema:
        if schema["minItems"] > schema["maxItems"]:
            raise _schema_error(path, "minItems nie może być większe od maxItems.")
    if "minLength" in schema and "maxLength" in schema:
        if schema["minLength"] > schema["maxLength"]:
            raise _schema_error(path, "minLength nie może być większe od maxLength.")

    if "pattern" in schema:
        pattern = schema["pattern"]
        if not isinstance(pattern, str):
            raise _schema_error(path, "pattern musi być tekstem.")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise _schema_error(path, f"pattern nie jest poprawnym wyrażeniem: {exc}") from exc

    for keyword in ("minimum", "maximum"):
        if keyword in schema and not _is_number(schema[keyword]):
            raise _schema_error(path, f"{keyword} musi być skończoną liczbą.")
    if "minimum" in schema and "maximum" in schema:
        if schema["minimum"] > schema["maximum"]:
            raise _schema_error(path, "minimum nie może być większe od maximum.")

    if "enum" in schema:
        enum = schema["enum"]
        if not isinstance(enum, list) or not enum:
            raise _schema_error(path, "enum musi być niepustą listą.")
        for index, value in enumerate(enum):
            if any(_json_equal(value, prior) for prior in enum[:index]):
                raise _schema_error(path, "enum nie może zawierać równoważnych wartości.")


def _matches_type(instance: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(instance, dict)
    if expected == "array":
        return isinstance(instance, list)
    if expected == "string":
        return isinstance(instance, str)
    if expected == "number":
        return _is_number(instance)
    if expected == "integer":
        return _is_integer(instance)
    if expected == "boolean":
        return isinstance(instance, bool)
    if expected == "null":
        return instance is None
    return False


def _display_types(types: Sequence[str]) -> str:
    names = {
        "object": "obiekt",
        "array": "tablica",
        "string": "tekst",
        "number": "liczba",
        "integer": "liczba całkowita",
        "boolean": "wartość logiczna",
        "null": "null",
    }
    return " lub ".join(names[item] for item in types)


def _validate_instance(instance: Any, schema: Mapping[str, Any], path: str) -> None:
    declared_type = schema.get("type")
    if declared_type is not None:
        types = [declared_type] if isinstance(declared_type, str) else declared_type
        if not any(_matches_type(instance, item) for item in types):
            raise _validation_error(path, f"oczekiwany typ: {_display_types(types)}.")

    if "enum" in schema and not any(_json_equal(instance, item) for item in schema["enum"]):
        raise _validation_error(path, "wartość nie należy do dozwolonego enum.")
    if "const" in schema and not _json_equal(instance, schema["const"]):
        raise _validation_error(path, "wartość nie jest zgodna z const.")

    if isinstance(instance, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        for name in required:
            if name not in instance:
                raise _validation_error(path, f"brakuje wymaganej właściwości {name!r}.")
        for name, value in instance.items():
            child_path = f"{path}[{name!r}]"
            if name in properties:
                _validate_instance(value, properties[name], child_path)
                continue
            additional = schema.get("additionalProperties", True)
            if additional is False:
                raise _validation_error(path, f"niedozwolona dodatkowa właściwość {name!r}.")
            if isinstance(additional, dict):
                _validate_instance(value, additional, child_path)

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            raise _validation_error(path, f"tablica ma mniej niż {schema['minItems']} elementów.")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            raise _validation_error(path, f"tablica ma więcej niż {schema['maxItems']} elementów.")
        if "items" in schema:
            for index, value in enumerate(instance):
                _validate_instance(value, schema["items"], f"{path}[{index}]")

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            raise _validation_error(path, f"tekst ma mniej niż {schema['minLength']} znaków.")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            raise _validation_error(path, f"tekst ma więcej niż {schema['maxLength']} znaków.")
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            raise _validation_error(path, "tekst nie spełnia wymaganego wzorca.")

    if _is_number(instance):
        if "minimum" in schema and instance < schema["minimum"]:
            raise _validation_error(path, f"liczba jest mniejsza niż {schema['minimum']}.")
        if "maximum" in schema and instance > schema["maximum"]:
            raise _validation_error(path, f"liczba jest większa niż {schema['maximum']}.")


def validate_instance(instance: Any, schema: Mapping[str, Any]) -> None:
    """Sprawdź dane względem wcześniej lub równocześnie sprawdzanego schematu."""

    validate_schema(schema)
    _validate_instance(instance, schema, "$")


def load_schema(path: Path) -> Dict[str, Any]:
    """Wczytaj lokalny schemat i sprawdź obsługiwany podzbiór."""

    try:
        schema = load_json(path)
    except ProjectStateError as exc:
        raise SchemaDefinitionError(f"Nie można wczytać schematu {path}: {exc}") from exc
    validate_schema(schema)
    return schema


def _parse_utc_timestamp(value: Any, path: str, allow_null: bool = False) -> Optional[datetime]:
    if value is None and allow_null:
        return None
    if not isinstance(value, str) or not value.endswith("Z"):
        raise _validation_error(path, "znacznik czasu musi być tekstem ISO 8601 w UTC zakończonym Z.")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise _validation_error(path, "znacznik czasu nie jest poprawnym ISO 8601.") from exc
    return parsed


def _validate_relative_path(value: Any, path: str) -> None:
    if not isinstance(value, str) or not value or not SAFE_RELATIVE_PART.fullmatch(value):
        raise _validation_error(path, "ścieżka względna musi być niepustym tekstem bez NUL.")
    candidate = Path(value)
    if candidate.is_absolute() or any(part in ("", ".", "..") for part in candidate.parts):
        raise _validation_error(path, "ścieżka musi być bezpieczna i względna.")


def _validate_sha256(value: Any, path: str) -> None:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise _validation_error(path, "oczekiwany małymi literami skrót SHA-256.")


def _validate_scene_state(scene_plan: Mapping[str, Any], path: str) -> None:
    scenes = scene_plan.get("scenes", [])
    tombstones = scene_plan.get("tombstones", [])
    active_ids: List[str] = []
    indexes: List[int] = []

    for index, scene in enumerate(scenes):
        scene_path = f"{path}.scenes[{index}]"
        scene_id = scene.get("scene_id")
        if not isinstance(scene_id, str) or SCENE_ID_PATTERN.fullmatch(scene_id) is None:
            raise _validation_error(scene_path, "scene_id nie jest bezpiecznym stabilnym identyfikatorem.")
        active_ids.append(scene_id)
        indexes.append(scene.get("sequence_index"))

    if len(active_ids) != len(set(active_ids)):
        raise _validation_error(path, "aktywne scene_id muszą być unikalne.")
    if any(not _is_integer(item) or item < 0 for item in indexes):
        raise _validation_error(path, "sequence_index musi być nieujemną liczbą całkowitą.")
    if sorted(indexes) != list(range(len(indexes))):
        raise _validation_error(path, "sequence_index musi tworzyć ciąg 0..n-1 bez luk.")

    tombstone_ids: List[str] = []
    for index, tombstone in enumerate(tombstones):
        tombstone_path = f"{path}.tombstones[{index}]"
        scene_id = tombstone.get("scene_id")
        if not isinstance(scene_id, str) or SCENE_ID_PATTERN.fullmatch(scene_id) is None:
            raise _validation_error(tombstone_path, "scene_id tombstone'a jest niepoprawne.")
        tombstone_ids.append(scene_id)
        _parse_utc_timestamp(tombstone.get("removed_at"), f"{tombstone_path}.removed_at")

    if len(tombstone_ids) != len(set(tombstone_ids)):
        raise _validation_error(path, "scene_id tombstone'ów muszą być unikalne.")
    reused = sorted(set(active_ids).intersection(tombstone_ids))
    if reused:
        raise _validation_error(path, "scene_id z tombstone'a nie może zostać użyte ponownie: " + ", ".join(reused))


def _scan_for_secret_fields(
    value: Any,
    path: str = "$",
    *,
    allowed_secret_reference_paths: FrozenSet[str] = frozenset(),
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}[{key!r}]"
            normalized = str(key).replace("-", "_")
            if normalized == "secret_reference":
                if child_path not in allowed_secret_reference_paths:
                    raise _validation_error(
                        child_path,
                        "secret_reference jest dozwolone wyłącznie w kanonicznym profilu dostawcy.",
                    )
            elif SECRET_FIELD_PATTERN.search(normalized):
                raise _validation_error(path, f"dokument zawiera niedozwolone pole sekretu {key!r}.")
            _scan_for_secret_fields(
                child,
                child_path,
                allowed_secret_reference_paths=allowed_secret_reference_paths,
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_for_secret_fields(
                child,
                f"{path}[{index}]",
                allowed_secret_reference_paths=allowed_secret_reference_paths,
            )


def validate_project_semantics(
    document: Mapping[str, Any], project_root: Optional[Path] = None
) -> None:
    """Sprawdź wersję, integralność stanu, tombstone'y i opcjonalne hashe plików."""

    if document.get("schema_version") != PROJECT_SCHEMA_VERSION:
        raise _validation_error("$.schema_version", "nieobsługiwana wersja manifestu projektu.")
    try:
        validate_project_id(document.get("project_id"))
    except ProjectStateError as exc:
        raise _validation_error("$.project_id", str(exc)) from exc

    if not _is_integer(document.get("manifest_revision")) or document["manifest_revision"] < 1:
        raise _validation_error("$.manifest_revision", "rewizja musi być dodatnią liczbą całkowitą.")

    timestamps = document.get("timestamps", {})
    created = _parse_utc_timestamp(timestamps.get("created_at"), "$.timestamps.created_at")
    updated = _parse_utc_timestamp(timestamps.get("updated_at"), "$.timestamps.updated_at")
    if created is not None and updated is not None and updated < created:
        raise _validation_error("$.timestamps.updated_at", "aktualizacja nie może poprzedzać utworzenia.")

    source = document.get("source", {})
    url = source.get("url")
    domain = source.get("domain")
    if url is not None:
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise _validation_error("$.source.url", "URL źródłowy musi być publicznym adresem HTTP albo HTTPS bez danych logowania.")
        if domain != parsed.hostname.lower():
            raise _validation_error("$.source.domain", "domena musi odpowiadać hostowi URL.")
    elif domain is not None:
        raise _validation_error("$.source.domain", "domena bez URL nie jest dozwolona.")

    _validate_scene_state(document.get("scene_plan", {}), "$.scene_plan")
    _scan_for_secret_fields(document)

    hashes = document.get("hashes", {})
    for relative_path, expected_hash in hashes.items():
        _validate_relative_path(relative_path, f"$.hashes[{relative_path!r}]")
        _validate_sha256(expected_hash, f"$.hashes[{relative_path!r}]")
        if project_root is not None:
            file_path = resolve_project_path(project_root, relative_path, must_exist=True)
            actual_hash = sha256_file(file_path)
            if actual_hash != expected_hash:
                raise _validation_error(
                    f"$.hashes[{relative_path!r}]", "skrót pliku nie zgadza się z manifestem."
                )

    provider_profile = document.get("provider_profile", {})
    if provider_profile.get("snapshot_path") != "provider/provider-profile.snapshot.json":
        raise _validation_error("$.provider_profile.snapshot_path", "wymagana jest kanoniczna ścieżka snapshotu.")
    snapshot_hash = provider_profile.get("snapshot_sha256")
    _validate_sha256(snapshot_hash, "$.provider_profile.snapshot_sha256")
    if hashes.get("provider/provider-profile.snapshot.json") != snapshot_hash:
        raise _validation_error("$.provider_profile.snapshot_sha256", "hash snapshotu musi występować także w hashes.")


def validate_image_analysis_semantics(document: Mapping[str, Any]) -> None:
    """Sprawdź unikalność analiz i zgodność selekcji z fotografiami."""

    if document.get("schema_version") != PROJECT_SCHEMA_VERSION:
        raise _validation_error("$.schema_version", "nieobsługiwana wersja analizy zdjęć.")
    _parse_utc_timestamp(document.get("generated_at"), "$.generated_at")
    identifiers: List[str] = []
    paths: List[str] = []
    for index, item in enumerate(document.get("images", [])):
        item_path = f"$.images[{index}]"
        image_id = item.get("image_id")
        if not isinstance(image_id, str) or IMAGE_ID_PATTERN.fullmatch(image_id) is None:
            raise _validation_error(item_path, "image_id musi wynikać z SHA-256 zawartości.")
        image_sha256 = item.get("sha256")
        _validate_sha256(image_sha256, f"{item_path}.sha256")
        if image_id not in (image_sha256, f"img_{image_sha256}"):
            raise _validation_error(
                item_path,
                "image_id musi dokładnie odpowiadać zadeklarowanemu SHA-256 zawartości.",
            )
        identifiers.append(image_id)
        relative_path = item.get("relative_path")
        _validate_relative_path(relative_path, f"{item_path}.relative_path")
        paths.append(relative_path)
        if item.get("curation_status") == "selected":
            if item.get("asset_kind") != "photo":
                raise _validation_error(item_path, "wybrany asset do animacji musi być fotografią.")
            if not item.get("room_type") or not item.get("room_instance_id"):
                raise _validation_error(item_path, "wybrane zdjęcie wymaga room_type i room_instance_id.")

    if len(identifiers) != len(set(identifiers)):
        raise _validation_error("$.images", "image_id muszą być unikalne.")
    if len(paths) != len(set(paths)):
        raise _validation_error("$.images", "relative_path muszą być unikalne.")


def validate_scene_plan_semantics(document: Mapping[str, Any]) -> None:
    """Sprawdź stabilność scen, źródła, pojedynczy ruch i tombstone'y."""

    if document.get("schema_version") != PROJECT_SCHEMA_VERSION:
        raise _validation_error("$.schema_version", "nieobsługiwana wersja planu scen.")
    _parse_utc_timestamp(document.get("generated_at"), "$.generated_at")
    _validate_scene_state(document, "$")

    source_ids: List[str] = []
    for index, scene in enumerate(document.get("scenes", [])):
        scene_path = f"$.scenes[{index}]"
        source_id = scene.get("source_image_id")
        if not isinstance(source_id, str) or IMAGE_ID_PATTERN.fullmatch(source_id) is None:
            raise _validation_error(scene_path, "source_image_id musi wynikać z SHA-256.")
        source_sha256 = scene.get("source_sha256")
        _validate_sha256(source_sha256, f"{scene_path}.source_sha256")
        if source_id not in (source_sha256, f"img_{source_sha256}"):
            raise _validation_error(
                scene_path,
                "source_image_id musi dokładnie odpowiadać source_sha256.",
            )
        source_ids.append(source_id)
        movement = scene.get("camera_motion")
        if not isinstance(movement, str) or not movement.strip():
            raise _validation_error(scene_path, "scena wymaga dokładnie jednego ruchu kamery.")
        if any(separator in movement for separator in (",", "+", ";", " then ", " and ", " oraz ")):
            raise _validation_error(scene_path, "camera_motion opisuje więcej niż jeden ruch.")
        _validate_relative_path(scene.get("source_path"), f"{scene_path}.source_path")
        _validate_sha256(scene.get("dependency_hash"), f"{scene_path}.dependency_hash")

    if len(source_ids) != len(set(source_ids)):
        raise _validation_error("$.scenes", "jedno zdjęcie źródłowe może należeć tylko do jednej aktywnej sceny.")
    if len(document.get("scenes", [])) > 10:
        raise _validation_error("$.scenes", "plan może zawierać najwyżej 10 aktywnych scen.")
    if document.get("scenes") and len(document["scenes"]) < 6 and not document.get("short_plan_reason"):
        raise _validation_error("$.short_plan_reason", "plan krótszy niż 6 scen wymaga uzasadnienia.")


def validate_provider_profile_semantics(document: Mapping[str, Any]) -> None:
    """Sprawdź profil named-only oraz bezpieczną referencję do sekretu."""

    if document.get("schema_version") != 1:
        raise _validation_error("$.schema_version", "profil providera wymaga wersji 1.")
    status = document.get("status")
    name = document.get("provider_name")
    method = document.get("connection_method")
    secret_reference = document.get("secret_reference")
    verified_at = document.get("verified_at")
    generation_authorized = document.get("generation_authorized")

    if status == "not_configured":
        if any(value != "" for value in (name, method, secret_reference, verified_at)):
            raise _validation_error("$", "profil not_configured nie może zawierać danych providera.")
    else:
        if not isinstance(name, str) or not name.strip():
            raise _validation_error("$.provider_name", "skonfigurowany profil wymaga dokładnej nazwy providera.")
        if method not in ("MCP", "API"):
            raise _validation_error("$.connection_method", "metoda musi mieć wartość MCP albo API.")
        if status in ("pending_validation", "validated", "stale"):
            if not isinstance(secret_reference, str) or SECRET_REFERENCE_PATTERN.fullmatch(secret_reference) is None:
                raise _validation_error("$.secret_reference", "wymagana jest bezpieczna referencja do sekretu, nigdy sekret.")
        elif secret_reference:
            if not isinstance(secret_reference, str) or SECRET_REFERENCE_PATTERN.fullmatch(secret_reference) is None:
                raise _validation_error("$.secret_reference", "referencja do sekretu ma niedozwolony format.")
        if verified_at:
            _parse_utc_timestamp(verified_at, "$.verified_at")

    if generation_authorized is not False:
        raise _validation_error("$.generation_authorized", "profil nigdy nie może autoryzować generowania.")
    if status == "validated":
        if not verified_at:
            raise _validation_error("$.verified_at", "zwalidowany profil wymaga czasu weryfikacji.")
        if not document.get("official_sources"):
            raise _validation_error("$.official_sources", "zwalidowany profil wymaga oficjalnych źródeł.")
        required_true = ("image_to_video", "submission", "polling", "download")
        capabilities = document.get("capabilities", {})
        missing = [key for key in required_true if capabilities.get(key) is not True]
        if missing:
            raise _validation_error("$.capabilities", "niezweryfikowane możliwości: " + ", ".join(missing))
        if not capabilities.get("ratios") or not capabilities.get("durations_seconds"):
            raise _validation_error("$.capabilities", "brakuje zweryfikowanych formatów albo czasów trwania.")
    if status == "stale":
        if not verified_at:
            raise _validation_error("$.verified_at", "nieaktualny profil wymaga czasu poprzedniej weryfikacji.")
        if not document.get("official_sources"):
            raise _validation_error("$.official_sources", "nieaktualny profil wymaga poprzednich oficjalnych źródeł.")
        if not document.get("verification_errors"):
            raise _validation_error("$.verification_errors", "status stale wymaga informacji o ponownej walidacji.")
    if status == "blocked" and not document.get("verification_errors"):
        raise _validation_error("$.verification_errors", "status blocked wymaga konkretnego błędu weryfikacji.")

    for index, source in enumerate(document.get("official_sources", [])):
        parsed = urlsplit(source.get("url", ""))
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise _validation_error(f"$.official_sources[{index}].url", "oficjalne źródło musi być adresem HTTPS bez danych logowania.")
        _parse_utc_timestamp(source.get("checked_at"), f"$.official_sources[{index}].checked_at")
    _scan_for_secret_fields(
        document,
        allowed_secret_reference_paths=frozenset({"$['secret_reference']"}),
    )


SEMANTIC_VALIDATORS: Dict[str, Callable[..., None]] = {
    "project": validate_project_semantics,
    "image-analysis": validate_image_analysis_semantics,
    "scene-plan": validate_scene_plan_semantics,
    "provider-profile": validate_provider_profile_semantics,
}


def validate_document(
    instance: Any,
    schema: Mapping[str, Any],
    semantic_kind: Optional[str] = None,
    project_root: Optional[Path] = None,
) -> None:
    """Uruchom walidację strukturalną, a potem osobną semantyczną."""

    validate_instance(instance, schema)
    if semantic_kind is None:
        return
    if semantic_kind not in SEMANTIC_VALIDATORS:
        raise DocumentValidationError(
            "Nieznany rodzaj walidacji semantycznej: " + str(semantic_kind)
        )
    if not isinstance(instance, dict):
        raise DocumentValidationError("Walidacja semantyczna wymaga obiektu JSON.")
    validator = SEMANTIC_VALIDATORS[semantic_kind]
    if semantic_kind == "project":
        validator(instance, project_root=project_root)
    else:
        validator(instance)


__all__ = [
    "DocumentValidationError",
    "PROJECT_SCHEMA_VERSION",
    "SCENE_ID_PATTERN",
    "SEMANTIC_KINDS",
    "SUPPORTED_KEYWORDS",
    "SUPPORTED_TYPES",
    "SchemaDefinitionError",
    "load_schema",
    "validate_document",
    "validate_image_analysis_semantics",
    "validate_instance",
    "validate_project_semantics",
    "validate_provider_profile_semantics",
    "validate_scene_plan_semantics",
    "validate_schema",
]
