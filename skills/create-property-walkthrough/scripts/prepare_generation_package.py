#!/usr/bin/env python3
"""Buduje stabilny plan scen, prompty I2V i kompletny pakiet manualny."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import secrets
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

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


SCENE_SCHEMA_VERSION = "1.0"
SCENE_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "assets" / "scene-plan.schema.json"
SUPPORTED_RATIOS = ("16:9", "9:16")
MIN_DURATION_SECONDS = 1.0
MAX_DURATION_SECONDS = 20.0
MIN_RECOMMENDED_SCENES = 6
MAX_SCENES = 10

ASSET_KINDS = {
    "photo",
    "floor_plan",
    "map",
    "screenshot",
    "portrait",
    "logo",
    "other",
}
CURATION_STATUSES = {"selected", "reserve", "rejected"}
ROOM_TYPES = {
    "exterior",
    "entrance",
    "hallway",
    "living_room",
    "dining_room",
    "kitchen",
    "bedroom",
    "child_room",
    "office",
    "bathroom",
    "toilet",
    "wardrobe",
    "utility_room",
    "garage",
    "balcony",
    "terrace",
    "garden",
    "view",
    "specialty_room",
    "other",
}
ROOM_ORDER = {
    room_type: index
    for index, room_type in enumerate(
        (
            "exterior",
            "entrance",
            "hallway",
            "living_room",
            "dining_room",
            "kitchen",
            "bedroom",
            "child_room",
            "office",
            "specialty_room",
            "wardrobe",
            "utility_room",
            "bathroom",
            "toilet",
            "garage",
            "balcony",
            "terrace",
            "garden",
            "view",
            "other",
        )
    )
}
CAMERA_MOVES = {
    "slow_push_in": {
        "pl": "powolny najazd do przodu",
        "en": "a single slow push-in, moving forward by approximately three percent of the frame depth",
    },
    "slow_pull_back": {
        "pl": "powolny odjazd do tyłu",
        "en": "a single slow pull-back, moving backward by approximately three percent of the frame depth",
    },
    "gentle_pan_left": {
        "pl": "łagodna panorama w lewo",
        "en": "a single gentle pan to the left, rotating no more than four degrees",
    },
    "gentle_pan_right": {
        "pl": "łagodna panorama w prawo",
        "en": "a single gentle pan to the right, rotating no more than four degrees",
    },
    "subtle_slide_left": {
        "pl": "subtelny przejazd w lewo",
        "en": "a single subtle lateral slide to the left, travelling no more than three percent of frame width",
    },
    "subtle_slide_right": {
        "pl": "subtelny przejazd w prawo",
        "en": "a single subtle lateral slide to the right, travelling no more than three percent of frame width",
    },
    "static_hold": {
        "pl": "statyczne ujęcie z minimalnym naturalnym oddechem kamery",
        "en": "a single locked-off hold with only imperceptible natural camera breathing and no translation",
    },
}


class ScenePlanningError(ValueError):
    """Oznacza naruszenie kontraktu planu scen lub promptu."""


def _canonical_hash(value: Any) -> str:
    """Oblicza stabilny hash kanonicznego dokumentu JSON."""

    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _atomic_write_text(path: Path, text: str) -> None:
    """Zapisuje tekst atomowo na tym samym systemie plików."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _records_by_id(records: Any) -> Dict[str, Dict[str, Any]]:
    """Indeksuje listę lub słownik rekordów po stabilnym identyfikatorze obrazu."""

    indexed: Dict[str, Dict[str, Any]] = {}
    if isinstance(records, dict) and isinstance(records.get("images"), list):
        records = records["images"]
    if isinstance(records, dict):
        iterable: Iterable[Tuple[Any, Any]] = records.items()
    elif isinstance(records, list):
        iterable = ((None, record) for record in records)
    else:
        return indexed
    for fallback_id, raw_record in iterable:
        if not isinstance(raw_record, dict):
            continue
        record = dict(raw_record)
        record_id = (
            record.get("image_id")
            or record.get("asset_id")
            or record.get("sha256")
            or fallback_id
        )
        if isinstance(record_id, str) and record_id:
            indexed[record_id] = record
    return indexed


def _merge_selected_assets(project: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Łączy selekcję P5 z rekordami P4 bez mieszania taksonomii."""

    assets = _records_by_id(project.get("assets"))
    classifications = _records_by_id(project.get("classifications"))
    selected = project.get("selected_images")
    if not isinstance(selected, list):
        raise ScenePlanningError("Pole selected_images musi być listą.")

    merged_records: List[Dict[str, Any]] = []
    seen_ids = set()
    for item in selected:
        if isinstance(item, str):
            selected_record: Dict[str, Any] = {"image_id": item}
            image_id = item
        elif isinstance(item, dict):
            selected_record = dict(item)
            image_id = (
                selected_record.get("image_id")
                or selected_record.get("asset_id")
                or selected_record.get("sha256")
            )
        else:
            raise ScenePlanningError("Każda pozycja selected_images musi być ID albo obiektem.")
        if not isinstance(image_id, str) or not image_id:
            raise ScenePlanningError("Wybrany obraz nie ma stabilnego image_id.")
        if image_id in seen_ids:
            raise ScenePlanningError(f"Obraz {image_id} występuje w selekcji więcej niż raz.")
        seen_ids.add(image_id)

        record: Dict[str, Any] = {}
        record.update(assets.get(image_id, {}))
        record.update(classifications.get(image_id, {}))
        record.update(selected_record)
        record["image_id"] = image_id
        record.setdefault("sha256", record.get("asset_id") or image_id)
        record.setdefault(
            "path",
            record.get("relative_path") or record.get("original_path"),
        )
        merged_records.append(record)
    return merged_records


def _validate_selected_asset(project_root: Path, asset: Dict[str, Any]) -> Dict[str, Any]:
    """Waliduje wybrany obraz, trzy osie taksonomii i integralność pliku."""

    image_id = asset.get("image_id")
    asset_kind = asset.get("asset_kind")
    room_type = asset.get("room_type")
    curation_status = asset.get("curation_status")
    if asset_kind not in ASSET_KINDS:
        raise ScenePlanningError(f"Obraz {image_id} ma niepoprawny asset_kind.")
    if room_type not in ROOM_TYPES:
        raise ScenePlanningError(f"Obraz {image_id} ma niepoprawny room_type.")
    if curation_status not in CURATION_STATUSES:
        raise ScenePlanningError(f"Obraz {image_id} ma niepoprawny curation_status.")
    if curation_status != "selected":
        raise ScenePlanningError(f"Obraz {image_id} nie ma statusu selected.")
    if asset_kind != "photo":
        raise ScenePlanningError(
            f"Obraz {image_id} typu {asset_kind} nie może być źródłem sceny I2V."
        )

    candidate = asset.get("path") or asset.get("original_path")
    if not isinstance(candidate, str) or not candidate:
        raise ScenePlanningError(f"Obraz {image_id} nie ma ścieżki źródłowej.")
    source_path = resolve_project_path(project_root, candidate, must_exist=True)
    actual_hash = sha256_file(source_path)
    expected_hash = asset.get("sha256")
    if isinstance(expected_hash, str) and expected_hash and expected_hash != actual_hash:
        raise ScenePlanningError(f"Hash obrazu {image_id} nie zgadza się z plikiem.")

    normalized = dict(asset)
    normalized["path"] = source_path.relative_to(project_root).as_posix()
    normalized["sha256"] = actual_hash
    normalized["room_instance_id"] = str(
        asset.get("room_instance_id") or f"{room_type}:{image_id}"
    )
    return normalized


def _sort_assets(assets: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Układa materiały według jawnej kolejności lub bezpiecznego łuku redakcyjnego."""

    def key(asset: Dict[str, Any]) -> Tuple[int, int, str]:
        explicit = asset.get("sequence_index")
        if isinstance(explicit, int) and explicit >= 0:
            return (0, explicit, str(asset["image_id"]))
        return (1, ROOM_ORDER.get(str(asset.get("room_type")), 999), str(asset["image_id"]))

    ordered = sorted(assets, key=key)
    room_instances: Dict[str, Dict[str, Any]] = {}
    for asset in ordered:
        room_instance = asset["room_instance_id"]
        if room_instance in room_instances and not asset.get("additional_angle_value"):
            raise ScenePlanningError(
                "Dodatkowy kąt dla tej samej przestrzeni wymaga pola additional_angle_value."
            )
        room_instances[room_instance] = asset
    return ordered[:MAX_SCENES]


def _new_scene_id(forbidden_ids: set) -> str:
    """Tworzy nieprzezroczysty identyfikator, który nie koliduje z tombstone."""

    while True:
        scene_id = f"scn_{secrets.token_hex(10)}"
        if scene_id not in forbidden_ids:
            forbidden_ids.add(scene_id)
            return scene_id


def _select_camera_move(asset: Mapping[str, Any]) -> str:
    """Wybiera dokładnie jeden kontrolowany ruch bez compound motion."""

    requested = asset.get("camera_move")
    if requested is not None:
        if not isinstance(requested, str) or requested not in CAMERA_MOVES:
            raise ScenePlanningError("camera_move musi wskazywać jeden dozwolony ruch.")
        return requested
    risk = str(asset.get("deformation_risk", "medium")).lower()
    if risk == "high":
        return "static_hold"
    if asset.get("room_type") in {"exterior", "garden", "view", "terrace", "balcony"}:
        return "gentle_pan_right"
    return "slow_push_in"


def build_i2v_prompt(scene: Mapping[str, Any]) -> str:
    """Buduje kompletny angielski prompt z blokadą źródła i geometrii."""

    movement = CAMERA_MOVES[str(scene["camera_motion"])]["en"]
    duration = float(scene["duration_seconds"])
    ratio = scene["aspect_ratio"]
    return (
        "Use the provided source image as the only visual source of truth for this shot. "
        "Preserve exactly the visible architecture, spatial geometry, composition, walls, "
        "doors, windows, floors, ceilings, furniture, decorations, materials, colors, and "
        "lighting. Keep all source objects present, stable, and in their original positions. "
        f"Execute one camera movement only: {movement}, at a restrained cinematic speed, "
        f"for exactly {duration:g} seconds. Produce realistic, physically plausible parallax "
        f"and keep the output framing at {ratio}. Do not redesign or replace the room. "
        "Do not create unseen rooms, new doors, new windows, openings, passages, objects, "
        "reflections, or unsupported areas beyond the source frame. Prevent disappearance, "
        "duplication, morphing, melting, bending, geometry drift, scene replacement, camera "
        "teleportation, unsupported doorway travel, and impossible reveals. Maintain locked "
        "source geometry and visual continuity within this single shot from first frame to last."
    )


def _build_scene(
    scene_id: str,
    sequence_index: int,
    asset: Dict[str, Any],
    *,
    duration_seconds: float,
    ratio: str,
) -> Dict[str, Any]:
    """Tworzy pojedynczą scenę o jednym źródle, ruchu, czasie i formacie."""

    scene: Dict[str, Any] = {
        "scene_id": scene_id,
        "sequence_index": sequence_index,
        "source_image_id": asset["image_id"],
        "source_path": asset["path"],
        "source_sha256": asset["sha256"],
        "room_type": asset["room_type"],
        "room_instance_id": asset["room_instance_id"],
        "camera_motion": _select_camera_move(asset),
        "duration_seconds": duration_seconds,
        "aspect_ratio": ratio,
        "deformation_risk": asset.get("deformation_risk", "medium"),
        "vertical_strategy": asset.get("vertical_strategy", "contain"),
        "vertical_anchor": asset.get("vertical_anchor", "center"),
        "status": "ready",
    }
    scene["prompt_en"] = build_i2v_prompt(scene)
    scene["metadata_pl"] = {
        "title": f"Scena {sequence_index + 1}: {asset['room_type']}",
        "status_note": "Pakiet manualny gotowy; generowanie zewnętrzne nie jest autoryzowane.",
        "id_sceny": scene_id,
        "typ_pomieszczenia": scene["room_type"],
        "ruch_kamery": CAMERA_MOVES[scene["camera_motion"]]["pl"],
        "czas_trwania_sekundy": duration_seconds,
        "format": ratio,
        "status_generowania": "nie_uruchomiono",
        "status_kontroli_jakosci": "wymaga_kontroli_manualnej",
    }
    scene["dependency_hash"] = _canonical_hash(
        {
            "source_image_id": scene["source_image_id"],
            "source_sha256": scene["source_sha256"],
            "camera_motion": scene["camera_motion"],
            "duration_seconds": scene["duration_seconds"],
            "aspect_ratio": scene["aspect_ratio"],
            "prompt_en": scene["prompt_en"],
        }
    )
    return scene


def _plan_dependency_inputs(
    assets: Sequence[Mapping[str, Any]], duration_seconds: float, ratio: str
) -> Dict[str, Any]:
    """Zwraca minimalne wejścia wpływające na sceny i prompty."""

    return {
        "assets": [
            {
                "image_id": asset["image_id"],
                "sha256": asset["sha256"],
                "asset_kind": asset["asset_kind"],
                "room_type": asset["room_type"],
                "room_instance_id": asset["room_instance_id"],
                "curation_status": asset["curation_status"],
                "camera_move": asset.get("camera_move"),
                "deformation_risk": asset.get("deformation_risk", "medium"),
                "vertical_strategy": asset.get("vertical_strategy", "contain"),
                "vertical_anchor": asset.get("vertical_anchor", "center"),
            }
            for asset in assets
        ],
        "duration_seconds": duration_seconds,
        "ratio": ratio,
        "prompt_contract_version": SCENE_SCHEMA_VERSION,
    }


def plan_scenes(
    project_root: Path,
    project: Dict[str, Any],
    *,
    duration_seconds: float = 5.0,
    ratio: str = "16:9",
    short_plan_reason: Optional[str] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[str]]:
    """Planuje sceny, zachowując ID po reorderze i tworząc tombstone po usunięciu."""

    if ratio not in SUPPORTED_RATIOS:
        raise ScenePlanningError("Format sceny musi mieć wartość 16:9 albo 9:16.")
    if not isinstance(duration_seconds, (int, float)) or isinstance(duration_seconds, bool):
        raise ScenePlanningError("Czas trwania musi być liczbą.")
    duration = float(duration_seconds)
    if not MIN_DURATION_SECONDS <= duration <= MAX_DURATION_SECONDS:
        raise ScenePlanningError("Czas trwania sceny musi mieścić się od 1 do 20 sekund.")

    selected = [_validate_selected_asset(project_root, item) for item in _merge_selected_assets(project)]
    if not selected:
        raise ScenePlanningError("Brak wybranych fotografii do planu scen.")
    warnings: List[str] = []
    if len(selected) > MAX_SCENES:
        warnings.append(
            f"Plan ograniczono do {MAX_SCENES} najmocniejszych ujęć; pozostałe nie są fillerami."
        )
    ordered = _sort_assets(selected)

    previous_plan = project.get("scene_plan")
    if not isinstance(previous_plan, dict):
        previous_plan = {}
    previous_scenes = previous_plan.get("scenes")
    if not isinstance(previous_scenes, list):
        previous_scenes = []
    previous_active = {
        scene.get("source_image_id"): scene
        for scene in previous_scenes
        if isinstance(scene, dict)
        and isinstance(scene.get("source_image_id"), str)
        and isinstance(scene.get("scene_id"), str)
    }
    tombstones = [
        dict(item)
        for item in previous_plan.get("tombstones", [])
        if isinstance(item, dict)
    ]
    forbidden_ids = {
        str(item.get("scene_id"))
        for item in list(previous_scenes) + tombstones
        if isinstance(item, dict) and item.get("scene_id")
    }

    scenes: List[Dict[str, Any]] = []
    selected_ids = {asset["image_id"] for asset in ordered}
    for sequence_index, asset in enumerate(ordered):
        previous = previous_active.get(asset["image_id"])
        if previous is not None:
            scene_id = str(previous["scene_id"])
        else:
            scene_id = _new_scene_id(forbidden_ids)
        scenes.append(
            _build_scene(
                scene_id,
                sequence_index,
                asset,
                duration_seconds=duration,
                ratio=ratio,
            )
        )

    tombstoned_ids = {item.get("scene_id") for item in tombstones}
    for old_scene in previous_scenes:
        if not isinstance(old_scene, dict):
            continue
        if old_scene.get("source_image_id") in selected_ids:
            continue
        if old_scene.get("scene_id") in tombstoned_ids:
            continue
        tombstones.append(
            {
                "scene_id": old_scene.get("scene_id"),
                "source_image_id": old_scene.get("source_image_id"),
                "last_sequence_index": old_scene.get("sequence_index"),
                "removed_at": utc_now(),
                "reason": "Źródło nie należy już do aktywnej selekcji.",
            }
        )

    reason = short_plan_reason
    if len(scenes) < MIN_RECOMMENDED_SCENES:
        if reason is None:
            reason = (
                f"Dostępne zaakceptowane materiały pozwalają na {len(scenes)} "
                "unikalne sceny bez duplikowania ujęć ani wymyślania przestrzeni."
            )
        if not isinstance(reason, str) or not reason.strip():
            raise ScenePlanningError("Krótszy plan wymaga niepustego uzasadnienia.")
    elif reason is not None and not reason.strip():
        reason = None

    plan = {
        "schema_version": SCENE_SCHEMA_VERSION,
        "project_id": project.get("project_id"),
        "revision": int(previous_plan.get("revision", 0)) + 1,
        "generated_at": utc_now(),
        "short_plan_reason": reason,
        "scenes": scenes,
        "tombstones": tombstones,
        "warnings": warnings,
    }
    try:
        validate_document(
            plan,
            load_schema(SCENE_SCHEMA_PATH),
            semantic_kind="scene-plan",
        )
    except (DocumentValidationError, ValueError) as error:
        raise ScenePlanningError(str(error)) from error
    return plan, ordered, warnings


def _shot_list_document(project: Mapping[str, Any], plan: Mapping[str, Any]) -> Dict[str, Any]:
    """Buduje spójny dokument JSON promptów i metadanych."""

    return {
        "schema_version": SCENE_SCHEMA_VERSION,
        "project_id": project.get("project_id"),
        "plan_revision": plan["revision"],
        "scenes": [
            {
                "scene_id": scene["scene_id"],
                "sequence_index": scene["sequence_index"],
                "source_image_id": scene["source_image_id"],
                "source_path": scene["source_path"],
                "prompt": scene["prompt_en"],
                "metadata_pl": scene["metadata_pl"],
            }
            for scene in plan["scenes"]
        ],
    }


def _markdown_shot_list(project: Mapping[str, Any], plan: Mapping[str, Any]) -> str:
    """Renderuje polską listę ujęć z angielskimi promptami."""

    lines = [
        "# Lista ujęć walkthrough",
        "",
        f"Projekt: `{project.get('project_id', '')}`",
        "",
    ]
    if plan.get("short_plan_reason"):
        lines.extend([f"Uzasadnienie krótszego planu: {plan['short_plan_reason']}", ""])
    for scene in plan["scenes"]:
        metadata = scene["metadata_pl"]
        lines.extend(
            [
                f"## {scene['sequence_index'] + 1}. {scene['scene_id']}",
                "",
                f"- Typ pomieszczenia: `{metadata['typ_pomieszczenia']}`",
                f"- Ruch kamery: {metadata['ruch_kamery']}",
                f"- Czas trwania: {metadata['czas_trwania_sekundy']:g} s",
                f"- Format: `{metadata['format']}`",
                f"- Status generowania: `{metadata['status_generowania']}`",
                f"- Status kontroli jakości: `{metadata['status_kontroli_jakosci']}`",
                "",
                "```text",
                scene["prompt_en"],
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def _csv_shot_list(plan: Mapping[str, Any]) -> str:
    """Renderuje opcjonalny przenośny CSV z promptami i metadanymi."""

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=(
            "sequence_index",
            "scene_id",
            "source_image_id",
            "room_type",
            "camera_move",
            "duration_seconds",
            "ratio",
            "generation_status",
            "qc_status",
            "expected_filename",
            "prompt",
        ),
    )
    writer.writeheader()
    for scene in plan["scenes"]:
        writer.writerow(
            {
                "sequence_index": scene["sequence_index"],
                "scene_id": scene["scene_id"],
                "source_image_id": scene["source_image_id"],
                "room_type": scene["room_type"],
                "camera_move": scene["camera_motion"],
                "duration_seconds": scene["duration_seconds"],
                "ratio": scene["aspect_ratio"],
                "generation_status": "nie_uruchomiono",
                "qc_status": "wymaga_kontroli_manualnej",
                "expected_filename": f"{scene['scene_id']}.mp4",
                "prompt": scene["prompt_en"],
            }
        )
    return buffer.getvalue()


def _copy_curated_image(project_root: Path, scene: Mapping[str, Any]) -> str:
    """Kopiuje wybrany obraz do pakietu manualnego bez modyfikowania oryginału."""

    source = resolve_project_path(project_root, scene["source_path"], must_exist=True)
    suffix = source.suffix.lower() or ".img"
    destination = project_root / "generation-package" / "curated-images" / (
        f"{scene['scene_id']}{suffix}"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and sha256_file(destination) == scene["source_sha256"]:
        return destination.relative_to(project_root).as_posix()
    temporary = destination.with_name(f".{destination.name}.{secrets.token_hex(6)}.tmp")
    try:
        with source.open("rb") as source_handle, temporary.open("wb") as target_handle:
            shutil.copyfileobj(source_handle, target_handle)
            target_handle.flush()
            os.fsync(target_handle.fileno())
        if sha256_file(temporary) != scene["source_sha256"]:
            raise ScenePlanningError("Kopia obrazu w pakiecie manualnym ma inny hash.")
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination.relative_to(project_root).as_posix()


def _scene_content_signature(scene: Mapping[str, Any]) -> str:
    """Oblicza zależność sceny bez sequence_index, aby reorder nie unieważniał klipu."""

    return _canonical_hash(
        {
            "source_image_id": scene["source_image_id"],
            "source_sha256": scene["source_sha256"],
            "camera_move": scene["camera_motion"],
            "duration_seconds": scene["duration_seconds"],
            "ratio": scene["aspect_ratio"],
            "prompt": scene["prompt_en"],
        }
    )


def _apply_selective_invalidation(
    project: Dict[str, Any],
    old_scenes: Sequence[Mapping[str, Any]],
    new_scenes: Sequence[Mapping[str, Any]],
) -> List[str]:
    """Unieważnia wyłącznie zmienione sceny i zależny render."""

    old_by_id = {
        str(scene.get("scene_id")): scene
        for scene in old_scenes
        if isinstance(scene, Mapping) and scene.get("scene_id")
    }
    new_by_id = {str(scene["scene_id"]): scene for scene in new_scenes}
    changed = {
        scene_id
        for scene_id, new_scene in new_by_id.items()
        if scene_id not in old_by_id
        or _scene_content_signature(old_by_id[scene_id])
        != _scene_content_signature(new_scene)
    }
    changed.update(set(old_by_id) - set(new_by_id))
    clips = project.get("clips")
    if isinstance(clips, list):
        for scene_id in changed:
            for record in clips:
                if isinstance(record, dict) and record.get("scene_id") == scene_id:
                    record["input_dependency_valid"] = False
                    record["invalidated_at"] = utc_now()
    if changed or [scene.get("scene_id") for scene in old_scenes] != [
        scene.get("scene_id") for scene in new_scenes
    ]:
        output = project.setdefault("output", {})
        if isinstance(output, dict):
            output["render_status"] = "invalidated"
            output["invalidated_at"] = utc_now()
    return sorted(changed)


@locked_project_mutation
def prepare_generation_package(
    project_root: Path,
    *,
    duration_seconds: float = 5.0,
    ratio: str = "16:9",
    short_plan_reason: Optional[str] = None,
    include_csv: bool = True,
) -> Dict[str, Any]:
    """Zapisuje JSON, Markdown, CSV i provider-free manifest manualny."""

    root = validate_project_root(project_root)
    project_path = root / "project.json"
    project = load_json(project_path)
    if not isinstance(project, dict):
        raise ScenePlanningError("project.json musi być obiektem JSON.")
    old_plan = project.get("scene_plan")
    old_scenes = old_plan.get("scenes", []) if isinstance(old_plan, dict) else []
    plan, _ordered_assets, warnings = plan_scenes(
        root,
        project,
        duration_seconds=duration_seconds,
        ratio=ratio,
        short_plan_reason=short_plan_reason,
    )
    dependency_hash = _canonical_hash(
        {
            "plan_revision": plan["revision"],
            "scenes": [
                {
                    "scene_id": scene["scene_id"],
                    "sequence_index": scene["sequence_index"],
                    "dependency_hash": scene["dependency_hash"],
                }
                for scene in plan["scenes"]
            ],
        }
    )
    changed_scene_ids = _apply_selective_invalidation(project, old_scenes, plan["scenes"])

    prompt_document = _shot_list_document(project, plan)
    prompts_dir = root / "prompts"
    package_dir = root / "generation-package"
    atomic_write_json(package_dir / "scene-plan.json", plan)
    atomic_write_json(prompts_dir / "shot-list.json", prompt_document)
    _atomic_write_text(prompts_dir / "shot-list.md", _markdown_shot_list(project, plan))
    if include_csv:
        _atomic_write_text(prompts_dir / "shot-list.csv", _csv_shot_list(plan))

    entries: List[Dict[str, Any]] = []
    for scene in plan["scenes"]:
        curated_path = _copy_curated_image(root, scene)
        entries.append(
            {
                "scene_id": scene["scene_id"],
                "sequence_index": scene["sequence_index"],
                "source_image_id": scene["source_image_id"],
                "source_sha256": scene["source_sha256"],
                "curated_image_path": curated_path,
                "prompt": scene["prompt_en"],
                "duration_seconds": scene["duration_seconds"],
                "ratio": scene["aspect_ratio"],
                "expected_filename": f"{scene['scene_id']}.mp4",
            }
        )
    manifest_core = {
        "schema_version": 1,
        "project_id": project.get("project_id"),
        "mode": "manual",
        "plan_dependency_hash": dependency_hash,
        "provider_configured": False,
        "external_generation_authorized": False,
        "entries": entries,
    }
    manifest = dict(manifest_core)
    manifest["package_fingerprint"] = _canonical_hash(manifest_core)
    manifest["created_at"] = utc_now()
    atomic_write_json(package_dir / "generation-manifest.json", manifest)

    prompt_hash = sha256_file(prompts_dir / "shot-list.json")
    manifest_hash = sha256_file(package_dir / "generation-manifest.json")
    project["scene_plan"] = {
        "revision": plan["revision"],
        "scenes": plan["scenes"],
        "tombstones": plan["tombstones"],
    }
    project["prompts"] = {
        "status": "complete",
        "json_path": "prompts/shot-list.json",
        "markdown_path": "prompts/shot-list.md",
        "csv_path": "prompts/shot-list.csv" if include_csv else None,
        "sha256": prompt_hash,
        "dependency_hash": dependency_hash,
    }
    hashes = project.setdefault("hashes", {})
    if not isinstance(hashes, dict):
        raise ScenePlanningError("Pole hashes w project.json musi być obiektem.")
    scene_plan_hash = sha256_file(package_dir / "scene-plan.json")
    hashes["generation-package/scene-plan.json"] = scene_plan_hash
    hashes["prompts/shot-list.json"] = prompt_hash
    hashes["generation-package/generation-manifest.json"] = manifest_hash
    stages = project.setdefault("stages", {})
    if not isinstance(stages, dict):
        raise ScenePlanningError("Pole stages w project.json musi być obiektem.")
    stages["scene_planning"] = "complete"
    stages["prompt_preparation"] = "complete"
    stages["generation_package"] = "complete"
    project.setdefault("warnings", []).extend(warnings)
    project["manifest_revision"] = int(project.get("manifest_revision", 0)) + 1
    timestamps = project.setdefault("timestamps", {})
    if isinstance(timestamps, dict):
        timestamps["updated_at"] = utc_now()
    atomic_write_json(project_path, project)
    return {
        "project_id": project.get("project_id"),
        "scene_count": len(plan["scenes"]),
        "scene_ids": [scene["scene_id"] for scene in plan["scenes"]],
        "changed_scene_ids": changed_scene_ids,
        "short_plan_reason": plan.get("short_plan_reason"),
        "manifest_path": str(package_dir / "generation-manifest.json"),
        "provider_calls": 0,
    }


def build_parser() -> argparse.ArgumentParser:
    """Buduje parser przygotowania pakietu generacyjnego."""

    parser = PolishArgumentParser(
        description="Tworzy plan scen, prompty I2V i pakiet do ręcznego generowania bez dostawcy."
    )
    parser.add_argument("--project", required=True, type=Path, help="Katalog projektu.")
    parser.add_argument(
        "--duration",
        type=float,
        default=5.0,
        help="Czas jednej sceny w sekundach, od 1 do 20.",
    )
    parser.add_argument(
        "--ratio",
        choices=SUPPORTED_RATIOS,
        default="16:9",
        help="Jeden format przypisany do każdej sceny.",
    )
    parser.add_argument(
        "--short-plan-reason",
        help="Jawne uzasadnienie planu krótszego niż sześć scen.",
    )
    parser.add_argument(
        "--without-csv",
        action="store_true",
        help="Nie zapisuj opcjonalnej listy CSV.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Uruchamia przygotowanie pakietu i zwraca zwięzły raport JSON."""

    args = build_parser().parse_args(argv)
    try:
        report = prepare_generation_package(
            args.project,
            duration_seconds=args.duration,
            ratio=args.ratio,
            short_plan_reason=args.short_plan_reason,
            include_csv=not args.without_csv,
        )
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ScenePlanningError, ValueError) as error:
        print(f"Błąd przygotowania pakietu generacyjnego: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
