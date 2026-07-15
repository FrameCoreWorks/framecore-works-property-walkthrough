#!/usr/bin/env python3
"""Przygotowuje lokalne derivative'y uploadowe i fail-closed zgodę partii."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import secrets
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from _common import (
    PolishArgumentParser,
    atomic_write_json,
    ensure_managed_directory,
    load_json,
    locked_project_mutation,
    resolve_managed_output_path,
    resolve_project_path,
    sha256_file,
    utc_now,
    validate_project_root,
)
from _media import MediaError, run_ffmpeg
from _schema import DocumentValidationError, validate_scene_id
from configure_provider import (
    COST_CONFIRMATION_QUESTION,
    GENERATION_CONSENT_QUESTION,
    UNKNOWN_COST_MESSAGE,
)
from validate_provider import (
    ProviderValidationError,
    validate_profile_data,
    validate_profile_file,
)


CONSENT_QUESTION = GENERATION_CONSENT_QUESTION
COST_QUESTION = COST_CONFIRMATION_QUESTION
UNKNOWN_COST_NOTICE = UNKNOWN_COST_MESSAGE
COST_STATUSES = ("known", "unknown", "unavailable")


class GenerationSafetyError(ValueError):
    """Oznacza niespełnioną bramkę uploadu, zgody albo kosztu."""


def session_scope_sha256(session_id: str) -> str:
    """Zwiąż zgodę z bieżącym zadaniem bez utrwalania efemerycznego nonce."""

    if (
        not isinstance(session_id, str)
        or len(session_id) < 16
        or len(session_id) > 256
        or session_id != session_id.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in session_id)
    ):
        raise GenerationSafetyError(
            "Nonce bieżącej sesji musi mieć 16-256 znaków i nie zawierać znaków sterujących."
        )
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


def _safe_scene_id(value: Any) -> str:
    """Waliduje scene_id zanim identyfikator stanie się częścią ścieżki."""

    try:
        return validate_scene_id(value)
    except DocumentValidationError as exc:
        raise GenerationSafetyError(str(exc)) from exc


def canonical_hash(value: Any) -> str:
    """Oblicza SHA-256 stabilnej reprezentacji JSON."""

    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _is_nonnegative_finite_number(value: Any) -> bool:
    """Rozpoznaje bezpieczną kwotę JSON, wykluczając bool, NaN i infinity."""

    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and value >= 0
    )


def _classifications_by_id(project: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Indeksuje jawne flagi praw i PII po identyfikatorze obrazu."""

    raw = project.get("classifications")
    if not isinstance(raw, dict):
        return {}
    return {
        str(identifier): dict(record)
        for identifier, record in raw.items()
        if isinstance(identifier, str) and isinstance(record, dict)
    }


def _rights_and_pii(
    classification: Mapping[str, Any],
    override: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Normalizuje bramki praw i danych osobowych bez zakładania zgody."""

    combined = dict(classification)
    if override:
        combined.update(override)
    rights_confirmed = combined.get("rights_confirmed") is True
    pii_reviewed = combined.get("pii_reviewed") is True
    contains_pii = combined.get("contains_pii") is True
    return {
        "rights_confirmed": rights_confirmed,
        "rights_status": "confirmed" if rights_confirmed else "unconfirmed",
        "pii_reviewed": pii_reviewed,
        "contains_pii": contains_pii,
        "pii_status": (
            "contains_pii"
            if contains_pii
            else "clear"
            if pii_reviewed
            else "unreviewed"
        ),
    }


def _prepare_single_derivative(
    project_root: Path,
    scene: Mapping[str, Any],
    destination_dir: Path,
) -> Dict[str, Any]:
    """Transkoduje jedno źródło przez FFmpeg, usuwając metadane."""

    scene_id = _safe_scene_id(scene.get("scene_id"))
    source_relative = scene.get("source_path")
    if not isinstance(source_relative, str):
        raise GenerationSafetyError(f"Scena {scene_id} nie ma source_path.")
    source = resolve_project_path(project_root, source_relative, must_exist=True)
    source_hash = sha256_file(source)
    if scene.get("source_sha256") != source_hash:
        raise GenerationSafetyError(f"Hash źródła sceny {scene_id} jest nieaktualny.")

    destination = resolve_managed_output_path(
        project_root,
        destination_dir / f"{scene_id}-upload.jpg",
        create_parent=True,
    )
    if destination.resolve(strict=False) == source.resolve(strict=False):
        raise GenerationSafetyError("Derivative nie może zastępować oryginału.")
    temporary = destination.with_name(
        f".{destination.stem}.{secrets.token_hex(6)}.tmp.jpg"
    )
    try:
        run_ffmpeg(
            [
                "-y",
                "-i",
                str(source),
                "-map_metadata",
                "-1",
                "-map_chapters",
                "-1",
                "-frames:v",
                "1",
                "-vf",
                "scale=w='min(iw,2048)':h=-2:flags=lanczos",
                "-c:v",
                "mjpeg",
                "-q:v",
                "2",
                "-metadata",
                "comment=",
                str(temporary),
            ],
            timeout=120,
        )
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise GenerationSafetyError("FFmpeg nie utworzył derivative'u uploadowego.")
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()

    derivative_hash = sha256_file(destination)
    return {
        "scene_id": scene_id,
        "source_image_id": scene.get("source_image_id"),
        "original_path": source.relative_to(project_root).as_posix(),
        "original_sha256": source_hash,
        "upload_derivative_path": destination.relative_to(project_root).as_posix(),
        "upload_derivative_sha256": derivative_hash,
        "metadata_stripped": True,
        "original_substitution_forbidden": True,
        "duration_seconds": scene.get("duration_seconds"),
        "aspect_ratio": scene.get("aspect_ratio"),
    }


def build_batch_fingerprint_payload(
    *,
    profile: Mapping[str, Any],
    profile_sha256: str,
    model_id: str,
    entries: Sequence[Mapping[str, Any]],
    cost: Mapping[str, Any],
    output_path: str,
    session_scope: str,
    retry_number: int = 0,
) -> Dict[str, Any]:
    """Buduje immutable zakres zgody związany ze wszystkimi istotnymi danymi."""

    return {
        "provider_name": profile.get("provider_name"),
        "connection_method": profile.get("connection_method"),
        "provider_profile_sha256": profile_sha256,
        "model_id": model_id,
        "scene_ids": [entry.get("scene_id") for entry in entries],
        "assets": [
            {
                "scene_id": entry.get("scene_id"),
                "original_sha256": entry.get("original_sha256"),
                "upload_derivative_sha256": entry.get("upload_derivative_sha256"),
                "duration_seconds": entry.get("duration_seconds"),
                "aspect_ratio": entry.get("aspect_ratio"),
            }
            for entry in entries
        ],
        "job_count": len(entries),
        "cost": dict(cost),
        "output_path": output_path,
        "session_scope_sha256": session_scope,
        "retry_number": retry_number,
    }


@locked_project_mutation
def prepare_upload_derivatives(
    project_root: Path,
    profile_path: Path,
    *,
    model_id: str,
    cost_status: str,
    cost_amount: Optional[float] = None,
    currency: Optional[str] = None,
    budget: Optional[float] = None,
    output_path: str = "scenes/imported",
    session_id: str,
    rights_overrides: Optional[Mapping[str, Mapping[str, Any]]] = None,
    retry_number: int = 0,
) -> Dict[str, Any]:
    """Tworzy tylko lokalny pakiet derivative'ów; niczego nie wysyła."""

    root = validate_project_root(project_root)
    project = load_json(root / "project.json")
    if not isinstance(project, dict):
        raise GenerationSafetyError("project.json musi być obiektem JSON.")
    validate_profile_file(profile_path)
    profile = load_json(profile_path)
    if not isinstance(profile, dict):
        raise GenerationSafetyError("Profil dostawcy musi być obiektem JSON.")
    validate_profile_data(profile, require_verified=True)
    session_scope = session_scope_sha256(session_id)
    if not isinstance(model_id, str) or not model_id.strip():
        raise GenerationSafetyError("Pakiet wymaga jawnego model_id.")
    if cost_status not in COST_STATUSES:
        raise GenerationSafetyError("cost_status musi mieć wartość known, unknown albo unavailable.")
    if cost_amount is not None and not _is_nonnegative_finite_number(cost_amount):
        raise GenerationSafetyError("Kwota kosztu musi być nieujemną liczbą.")
    if budget is not None and not _is_nonnegative_finite_number(budget):
        raise GenerationSafetyError("Budżet musi być nieujemną liczbą.")
    if cost_status == "known" and cost_amount is None:
        raise GenerationSafetyError("Znany koszt wymaga pola cost_amount.")
    if cost_status != "known" and cost_amount is not None:
        raise GenerationSafetyError("Kwota nie może być podana dla nieznanego kosztu.")
    if (
        cost_status == "known"
        and budget is not None
        and cost_amount is not None
        and cost_amount > budget
    ):
        raise GenerationSafetyError("Znany koszt przekracza wskazany budżet.")

    plan = project.get("scene_plan")
    scenes = plan.get("scenes") if isinstance(plan, dict) else None
    if not isinstance(scenes, list) or not scenes:
        raise GenerationSafetyError("Projekt nie ma aktywnego planu scen.")
    classifications = _classifications_by_id(project)
    derivative_dir = ensure_managed_directory(
        root, Path("generation-package") / "upload-derivatives"
    )
    snapshot_path = resolve_managed_output_path(
        root,
        Path("provider") / "provider-profile.snapshot.json",
        create_parent=True,
    )
    manifest_path = resolve_managed_output_path(
        root,
        Path("generation-package") / "provider-batch-manifest.json",
        create_parent=True,
    )
    entries: List[Dict[str, Any]] = []
    for scene in sorted(scenes, key=lambda item: item.get("sequence_index", 0)):
        if not isinstance(scene, dict):
            raise GenerationSafetyError("Plan scen zawiera niepoprawny rekord.")
        entry = _prepare_single_derivative(root, scene, derivative_dir)
        image_id = str(scene.get("source_image_id"))
        override = rights_overrides.get(image_id) if rights_overrides else None
        entry.update(_rights_and_pii(classifications.get(image_id, {}), override))
        entries.append(entry)

    atomic_write_json(snapshot_path, profile)
    profile_hash = sha256_file(snapshot_path)
    cost = {
        "status": cost_status,
        "amount": float(cost_amount) if cost_amount is not None else None,
        "currency": currency,
        "budget": float(budget) if budget is not None else None,
    }
    fingerprint_payload = build_batch_fingerprint_payload(
        profile=profile,
        profile_sha256=profile_hash,
        model_id=model_id,
        entries=entries,
        cost=cost,
        output_path=output_path,
        session_scope=session_scope,
        retry_number=retry_number,
    )
    fingerprint = canonical_hash(fingerprint_payload)
    manifest = {
        "schema_version": 1,
        "created_at": utc_now(),
        "batch_fingerprint": fingerprint,
        "fingerprint_payload": fingerprint_payload,
        "provider_profile_snapshot_path": "provider/provider-profile.snapshot.json",
        "provider_profile_sha256": profile_hash,
        "session_scope_sha256": session_scope,
        "model_id": model_id,
        "entries": entries,
        "cost": cost,
        "consent_question": CONSENT_QUESTION,
        "cost_confirmation_question": COST_QUESTION,
        "unknown_cost_message": UNKNOWN_COST_NOTICE,
        "execution_status": "blocked_pending_explicit_consent",
        "submission_allowed": False,
        "provider_calls": 0,
    }
    atomic_write_json(manifest_path, manifest)

    project["provider_profile"] = {
        "status": profile["status"],
        "snapshot_path": "provider/provider-profile.snapshot.json",
        "snapshot_sha256": profile_hash,
    }
    hashes = project.setdefault("hashes", {})
    if not isinstance(hashes, dict):
        raise GenerationSafetyError("Pole hashes musi być obiektem.")
    hashes["provider/provider-profile.snapshot.json"] = profile_hash
    for entry in entries:
        hashes[entry["upload_derivative_path"]] = entry["upload_derivative_sha256"]
    hashes["generation-package/provider-batch-manifest.json"] = sha256_file(manifest_path)
    stages = project.setdefault("stages", {})
    if not isinstance(stages, dict):
        raise GenerationSafetyError("Pole stages musi być obiektem.")
    stages["upload_derivatives"] = "complete"
    stages["generation"] = "pending"
    project["manifest_revision"] = int(project.get("manifest_revision", 0)) + 1
    timestamps = project.setdefault("timestamps", {})
    if isinstance(timestamps, dict):
        timestamps["updated_at"] = utc_now()
    atomic_write_json(root / "project.json", project)
    return manifest


def _fingerprint_binding_reasons(manifest: Mapping[str, Any]) -> List[str]:
    """Sprawdza, czy bieżący manifest nadal odpowiada podpisanemu zakresowi."""

    payload = manifest.get("fingerprint_payload")
    fingerprint = manifest.get("batch_fingerprint")
    if not isinstance(payload, dict):
        return ["Manifest nie zawiera zakresu związanego z fingerprintem partii."]
    try:
        calculated = canonical_hash(payload)
    except (TypeError, ValueError):
        return ["Zakres fingerprintu partii nie jest prawidłowym dokumentem JSON."]
    reasons: List[str] = []
    if fingerprint != calculated:
        reasons.append("Niezgodny fingerprint zakresu partii.")

    entries = manifest.get("entries")
    if isinstance(entries, list) and all(isinstance(entry, dict) for entry in entries):
        current_assets = [
            {
                "scene_id": entry.get("scene_id"),
                "original_sha256": entry.get("original_sha256"),
                "upload_derivative_sha256": entry.get("upload_derivative_sha256"),
                "duration_seconds": entry.get("duration_seconds"),
                "aspect_ratio": entry.get("aspect_ratio"),
            }
            for entry in entries
        ]
        if payload.get("assets") != current_assets:
            reasons.append("Zawartość partii nie odpowiada fingerprintowi zgody.")
        if payload.get("scene_ids") != [entry.get("scene_id") for entry in entries]:
            reasons.append("Lista scen nie odpowiada fingerprintowi zgody.")
        if payload.get("job_count") != len(entries):
            reasons.append("Liczba zadań nie odpowiada fingerprintowi zgody.")
    if payload.get("provider_profile_sha256") != manifest.get("provider_profile_sha256"):
        reasons.append("Profil dostawcy nie odpowiada fingerprintowi zgody.")
    if payload.get("model_id") != manifest.get("model_id"):
        reasons.append("Model nie odpowiada fingerprintowi zgody.")
    if payload.get("cost") != manifest.get("cost"):
        reasons.append("Koszt nie odpowiada fingerprintowi zgody.")
    if payload.get("session_scope_sha256") != manifest.get("session_scope_sha256"):
        reasons.append("Zakres sesji nie odpowiada fingerprintowi zgody.")
    return reasons


def _live_derivative_reasons(
    project_root: Path,
    manifest: Mapping[str, Any],
) -> List[str]:
    """Ponownie sprawdza pliki derivative dokładnie w chwili autoryzacji."""

    try:
        root = validate_project_root(project_root)
    except ValueError as exc:
        return [f"Nie można zweryfikować katalogu projektu: {exc}"]
    profile_relative = manifest.get("provider_profile_snapshot_path")
    if not isinstance(profile_relative, str):
        return ["Manifest nie zawiera ścieżki snapshotu profilu dostawcy."]
    try:
        profile_path = resolve_managed_output_path(
            root, profile_relative, must_exist=True
        )
        if not profile_path.is_file():
            raise GenerationSafetyError("Snapshot profilu musi być zwykłym plikiem.")
        if sha256_file(profile_path) != manifest.get("provider_profile_sha256"):
            raise GenerationSafetyError("Hash snapshotu profilu dostawcy jest nieaktualny.")
        profile = load_json(profile_path)
        if not isinstance(profile, dict):
            raise GenerationSafetyError("Snapshot profilu dostawcy musi być obiektem JSON.")
        validate_profile_data(profile, require_verified=True)
    except (OSError, ProviderValidationError, ValueError) as exc:
        return [f"Nie można potwierdzić aktualnego profilu dostawcy: {exc}"]

    entries = manifest.get("entries")
    if not isinstance(entries, list):
        return ["Manifest nie zawiera listy derivative'ów do weryfikacji na żywo."]

    reasons: List[str] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        scene_label = entry.get("scene_id")
        try:
            scene_id = _safe_scene_id(scene_label)
            derivative_relative = entry.get("upload_derivative_path")
            original_relative = entry.get("original_path")
            if not isinstance(derivative_relative, str) or not isinstance(
                original_relative, str
            ):
                raise GenerationSafetyError("Brakuje ścieżki derivative'u albo oryginału.")
            derivative = resolve_managed_output_path(
                root, derivative_relative, must_exist=True
            )
            original = resolve_managed_output_path(
                root, original_relative, must_exist=True
            )
            if not derivative.is_file() or not original.is_file():
                raise GenerationSafetyError("Derivative i oryginał muszą być zwykłymi plikami.")
            if derivative.resolve(strict=True) == original.resolve(strict=True):
                raise GenerationSafetyError("Derivative wskazuje ten sam plik co oryginał.")
            if sha256_file(derivative) != entry.get("upload_derivative_sha256"):
                raise GenerationSafetyError("Hash derivative'u zmienił się po przygotowaniu zgody.")
            if sha256_file(original) != entry.get("original_sha256"):
                raise GenerationSafetyError("Hash oryginału zmienił się po przygotowaniu zgody.")
        except (OSError, ValueError) as exc:
            reasons.append(f"Scena {scene_label}: {exc}")
            continue
        if scene_id != scene_label:
            reasons.append(f"Scena {scene_label}: identyfikator sceny jest niekanoniczny.")
    return reasons


def evaluate_generation_gate(
    manifest: Mapping[str, Any],
    consent: Mapping[str, Any],
    *,
    project_root: Optional[Path] = None,
    current_session_id: Optional[str] = None,
    paid_retry: bool = False,
) -> Dict[str, Any]:
    """Ocenia zgodę fail-closed bez uruchamiania submission."""

    reasons: List[str] = []
    fingerprint = manifest.get("batch_fingerprint")
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        reasons.append("Manifest nie ma prawidłowego fingerprintu partii.")
    if consent.get("batch_fingerprint") != fingerprint:
        reasons.append("Zgoda dotyczy innego albo zmienionego fingerprintu partii.")
    if consent.get("consent_question") != CONSENT_QUESTION:
        reasons.append("Zgoda nie jest związana z dokładnym pytaniem o upload i generowanie.")
    if consent.get("upload_and_generation_approved") is not True:
        reasons.append("Brak jednoznacznej zgody na upload i generowanie.")
    if current_session_id is None:
        reasons.append("Brak identyfikatora bieżącej sesji zadania.")
    else:
        try:
            current_session_scope = session_scope_sha256(current_session_id)
        except GenerationSafetyError as exc:
            reasons.append(str(exc))
        else:
            if manifest.get("session_scope_sha256") != current_session_scope:
                reasons.append("Manifest został przygotowany w innej sesji zadania.")
            if consent.get("session_scope_sha256") != current_session_scope:
                reasons.append("Zgoda nie dotyczy bieżącej sesji zadania.")
    reasons.extend(_fingerprint_binding_reasons(manifest))
    if project_root is None:
        reasons.append("Brak katalogu projektu do końcowej weryfikacji derivative'ów.")
    else:
        reasons.extend(_live_derivative_reasons(project_root, manifest))

    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        reasons.append("Manifest nie zawiera derivative'ów do uploadu.")
    else:
        for entry in entries:
            if not isinstance(entry, dict):
                reasons.append("Manifest zawiera niepoprawny wpis derivative'u.")
                continue
            if entry.get("original_substitution_forbidden") is not True:
                reasons.append("Manifest nie blokuje podstawienia oryginału.")
            if entry.get("rights_confirmed") is not True:
                reasons.append(f"Brak potwierdzenia praw dla sceny {entry.get('scene_id')}.")
            if entry.get("pii_reviewed") is not True or entry.get("contains_pii") is True:
                reasons.append(f"Niezamknięta kontrola PII dla sceny {entry.get('scene_id')}.")
            if entry.get("upload_derivative_path") == entry.get("original_path"):
                reasons.append("Ścieżka uploadu wskazuje oryginał zamiast derivative'u.")

    cost = manifest.get("cost")
    if not isinstance(cost, dict):
        reasons.append("Manifest nie ma profilu kosztu.")
        cost = {}
    cost_status = cost.get("status")
    amount = cost.get("amount")
    budget = cost.get("budget")
    valid_amount = _is_nonnegative_finite_number(amount)
    valid_budget = budget is None or _is_nonnegative_finite_number(budget)
    if cost_status not in COST_STATUSES:
        reasons.append("Manifest ma nieprawidłowy status kosztu.")
    if cost_status == "known" and not valid_amount:
        reasons.append("Manifest nie zawiera prawidłowej znanej kwoty kosztu.")
    if not valid_budget:
        reasons.append("Manifest nie zawiera prawidłowego budżetu.")
    if (
        cost_status == "known"
        and valid_amount
        and valid_budget
        and budget is not None
        and amount > budget
    ):
        reasons.append("Znany koszt przekracza wskazany budżet.")
    may_be_paid = cost_status != "known" or not valid_amount or amount > 0
    if may_be_paid:
        if consent.get("cost_confirmation_question") != COST_QUESTION:
            reasons.append("Brak dokładnego pytania o potwierdzenie kosztu.")
        if consent.get("cost_confirmed") is not True:
            reasons.append("Brak jawnego potwierdzenia kosztu.")
    if cost_status in {"unknown", "unavailable"}:
        if consent.get("unknown_cost_message") != UNKNOWN_COST_NOTICE:
            reasons.append("Nie pokazano dokładnego komunikatu o niezweryfikowanym koszcie.")
        if consent.get("unknown_cost_risk_confirmed") is not True:
            reasons.append("Nieznany koszt wymaga jawnego potwierdzenia ryzyka.")
    if paid_retry and may_be_paid and consent.get("paid_retry_confirmed") is not True:
        reasons.append("Płatny retry wymaga nowego jawnego potwierdzenia.")

    return {
        "allowed": not reasons,
        "batch_fingerprint": fingerprint,
        "reasons": reasons,
        "provider_calls": 0,
    }


def assert_generation_authorized(
    manifest: Mapping[str, Any],
    consent: Mapping[str, Any],
    *,
    project_root: Path,
    current_session_id: str,
    paid_retry: bool = False,
) -> Dict[str, Any]:
    """Zwraca autoryzację albo zatrzymuje wykonanie z polskim komunikatem."""

    result = evaluate_generation_gate(
        manifest,
        consent,
        project_root=project_root,
        current_session_id=current_session_id,
        paid_retry=paid_retry,
    )
    if not result["allowed"]:
        raise GenerationSafetyError("; ".join(result["reasons"]))
    return result


def can_create_submission_intent(
    jobs: Sequence[Mapping[str, Any]], scene_id: str, batch_fingerprint: str
) -> bool:
    """Blokuje duplikat oraz automatyczny resubmit po crash window."""

    blocking_statuses = {
        "submission_pending",
        "submitted",
        "queued",
        "running",
        "completed",
    }
    return not any(
        job.get("scene_id") == scene_id
        and job.get("batch_fingerprint") == batch_fingerprint
        and job.get("status") in blocking_statuses
        for job in jobs
        if isinstance(job, Mapping)
    )


def build_parser() -> argparse.ArgumentParser:
    """Buduje parser lokalnego przygotowania i oceny zgody."""

    parser = PolishArgumentParser(
        description="Przygotowuje pliki pochodne i zgodę partii bez przesyłania danych ani wywoływania dostawcy."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare", help="Utwórz lokalne pliki pochodne do przesłania.")
    prepare.add_argument("--project", required=True, type=Path, help="Katalog projektu.")
    prepare.add_argument("--profile", required=True, type=Path, help="Zwalidowany profil.")
    prepare.add_argument("--model", required=True, help="Jawny identyfikator modelu.")
    prepare.add_argument("--cost-status", required=True, choices=COST_STATUSES)
    prepare.add_argument("--cost-amount", type=float)
    prepare.add_argument("--currency")
    prepare.add_argument("--budget", type=float)
    prepare.add_argument("--output-path", default="scenes/imported")
    prepare.add_argument(
        "--session-nonce",
        dest="session_id",
        required=True,
        help="Losowy efemeryczny nonce bieżącego zadania; w manifeście zapisywany jest tylko jego hash.",
    )
    prepare.add_argument("--rights-json", type=Path)
    prepare.add_argument("--retry-number", type=int, default=0)

    authorize = subparsers.add_parser(
        "authorize",
        help="Sprawdź zapis zgody; każdy brak lub błąd blokuje generowanie.",
    )
    authorize.add_argument("--manifest", required=True, type=Path)
    authorize.add_argument("--consent", required=True, type=Path)
    authorize.add_argument(
        "--project",
        required=True,
        type=Path,
        help="Katalog projektu do ponownej walidacji plików derivative.",
    )
    authorize.add_argument(
        "--session-nonce",
        dest="session_id",
        required=True,
        help="Ten sam losowy efemeryczny nonce bieżącego zadania.",
    )
    authorize.add_argument("--paid-retry", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Uruchamia wyłącznie lokalne operacje przygotowawcze i walidacyjne."""

    args = build_parser().parse_args(argv)
    try:
        if args.command == "prepare":
            overrides = load_json(args.rights_json) if args.rights_json else None
            manifest = prepare_upload_derivatives(
                args.project,
                args.profile,
                model_id=args.model,
                cost_status=args.cost_status,
                cost_amount=args.cost_amount,
                currency=args.currency,
                budget=args.budget,
                output_path=args.output_path,
                session_id=args.session_id,
                rights_overrides=overrides,
                retry_number=args.retry_number,
            )
            print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
            return 0
        manifest = load_json(args.manifest)
        consent = load_json(args.consent)
        if not isinstance(manifest, dict) or not isinstance(consent, dict):
            raise GenerationSafetyError("Manifest i zgoda muszą być obiektami JSON.")
        result = evaluate_generation_gate(
            manifest,
            consent,
            project_root=args.project,
            current_session_id=args.session_id,
            paid_retry=args.paid_retry,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["allowed"] else 3
    except (
        GenerationSafetyError,
        MediaError,
        OSError,
        ProviderValidationError,
        ValueError,
    ) as error:
        print(f"Błąd bezpieczeństwa generowania: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
