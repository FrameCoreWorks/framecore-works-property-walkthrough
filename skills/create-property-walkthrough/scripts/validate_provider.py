#!/usr/bin/env python3
"""Waliduje lokalny profil nazwanego dostawcy bez testów sieciowych."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from _common import PolishArgumentParser, atomic_write_json, load_json, utc_now
from _schema import DocumentValidationError, load_schema, validate_document
from configure_provider import (
    CONNECTION_METHODS,
    ProviderConfigurationError,
    looks_like_secret_value,
    validate_secret_reference,
)


REQUIRED_CAPABILITY_FIELDS = (
    "image_to_video",
    "submission",
    "polling",
    "download",
    "idempotency_key",
    "ratios",
    "durations_seconds",
    "cost_status",
)
DEFAULT_PROFILE_MAX_AGE_DAYS = 7
_FORBIDDEN_PROFILE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "credential",
    "credentials",
    "password",
    "secret",
    "token",
}


class ProviderValidationError(ValueError):
    """Oznacza, że profil nie spełnia bezpiecznego kontraktu named-only."""


PROFILE_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent / "assets" / "provider-profile.schema.json"
)


def _profile_max_age(value: int) -> int:
    """Waliduje dodatni okres ważności profilu w pełnych dniach."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProviderValidationError("Okres ważności profilu musi być dodatnią liczbą dni.")
    return value


def _parse_verified_at(value: str) -> datetime:
    """Odczytuje znacznik UTC profilu do świadomego obiektu datetime."""

    if not isinstance(value, str) or not value:
        raise ProviderValidationError("Profil nie zawiera czasu ostatniej weryfikacji.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ProviderValidationError("Czas ostatniej weryfikacji ma niepoprawny format.") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProviderValidationError("Czas ostatniej weryfikacji musi zawierać strefę UTC.")
    return parsed.astimezone(timezone.utc)


def profile_freshness(
    profile: Dict[str, Any],
    *,
    max_age_days: int = DEFAULT_PROFILE_MAX_AGE_DAYS,
    now: Optional[datetime] = None,
) -> str:
    """Zwraca fresh, stale albo unverified dla lokalnego profilu dostawcy."""

    days = _profile_max_age(max_age_days)
    verified_at = profile.get("verified_at")
    if not verified_at:
        return "unverified"
    checked = _parse_verified_at(verified_at)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ProviderValidationError("Czas odniesienia musi zawierać strefę czasową.")
    current = current.astimezone(timezone.utc)
    if checked > current + timedelta(minutes=5):
        raise ProviderValidationError("Czas weryfikacji profilu znajduje się w przyszłości.")
    if current - checked > timedelta(days=days):
        return "stale"
    return "fresh"


def mark_profile_stale(
    profile: Dict[str, Any],
    *,
    max_age_days: int = DEFAULT_PROFILE_MAX_AGE_DAYS,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Oznacza przeterminowany validated profile jako stale i zamyka wykonanie."""

    if profile.get("status") != "validated":
        return dict(profile)
    if profile_freshness(profile, max_age_days=max_age_days, now=now) != "stale":
        return dict(profile)
    updated = dict(profile)
    updated["status"] = "stale"
    updated["verification_errors"] = [
        "Profil dostawcy wymaga ponownej walidacji po przekroczeniu {} dni.".format(
            max_age_days
        )
    ]
    updated["generation_authorized"] = False
    return updated


def _forbidden_paths(value: Any, prefix: str = "$") -> List[str]:
    """Zwraca ścieżki niedozwolonych pól mogących zawierać sekret."""

    paths: List[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            child_path = f"{prefix}.{key}"
            if normalized in _FORBIDDEN_PROFILE_KEYS:
                paths.append(child_path)
            paths.extend(_forbidden_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_forbidden_paths(child, f"{prefix}[{index}]"))
    return paths


def validate_profile_data(
    profile: Dict[str, Any],
    *,
    expected_provider_name: Optional[str] = None,
    require_verified: bool = False,
    max_age_days: int = DEFAULT_PROFILE_MAX_AGE_DAYS,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Waliduje profil i zwraca bezpieczny raport bez sekretów."""

    if not isinstance(profile, dict):
        raise ProviderValidationError("Profil musi być obiektem JSON.")
    _profile_max_age(max_age_days)
    forbidden = _forbidden_paths(profile)
    if forbidden:
        raise ProviderValidationError(
            "Profil zawiera niedozwolone pola sekretów: " + ", ".join(forbidden)
        )
    name = profile.get("provider_name")
    if not isinstance(name, str) or not name or name != name.strip():
        raise ProviderValidationError("Profil nie zawiera dokładnej nazwy dostawcy.")
    if looks_like_secret_value(name):
        raise ProviderValidationError(
            "Nazwa dostawcy przypomina wartość sekretu i nie może zostać zapisana w profilu."
        )
    if expected_provider_name is not None and name != expected_provider_name:
        raise ProviderValidationError("Profil dotyczy innego dostawcy niż wskazany.")
    if profile.get("connection_method") not in CONNECTION_METHODS:
        raise ProviderValidationError("Metoda połączenia musi mieć wartość MCP albo API.")
    if profile.get("generation_authorized") is not False:
        raise ProviderValidationError("Profil dostawcy nigdy nie autoryzuje generowania.")
    validate_secret_reference(profile.get("secret_reference", ""))
    capabilities = profile.get("capabilities")
    if not isinstance(capabilities, dict):
        raise ProviderValidationError("Profil nie zawiera obiektu capabilities.")
    missing = [key for key in REQUIRED_CAPABILITY_FIELDS if key not in capabilities]
    if missing:
        raise ProviderValidationError("Brakuje pól capabilities: " + ", ".join(missing))
    if require_verified:
        if profile.get("status") == "stale":
            raise ProviderValidationError(
                "Profil dostawcy jest nieaktualny i wymaga ponownej walidacji."
            )
        if profile.get("status") != "validated":
            raise ProviderValidationError("Profil nie ma statusu validated.")
        if profile_freshness(profile, max_age_days=max_age_days, now=now) != "fresh":
            raise ProviderValidationError(
                "Profil dostawcy jest nieaktualny i wymaga ponownej walidacji."
            )
        required_states = ("image_to_video", "submission", "polling", "download")
        unverified = [key for key in required_states if capabilities.get(key) is not True]
        if unverified:
            raise ProviderValidationError(
                "Niezweryfikowane capabilities: " + ", ".join(unverified)
            )
        if not capabilities.get("ratios") or not capabilities.get("durations_seconds"):
            raise ProviderValidationError("Brakuje zweryfikowanych formatów lub czasów trwania.")
        documentation = profile.get("official_sources")
        if not isinstance(documentation, list) or not documentation:
            raise ProviderValidationError("Brakuje dowodów z oficjalnej dokumentacji.")
    try:
        validate_document(
            profile,
            load_schema(PROFILE_SCHEMA_PATH),
            semantic_kind="provider-profile",
        )
    except (DocumentValidationError, ValueError) as error:
        raise ProviderValidationError(str(error)) from error
    return {
        "valid": True,
        "provider_name": name,
        "connection_method": profile["connection_method"],
        "status": profile.get("status"),
        "provider_reuse_allowed": bool(
            require_verified and profile.get("status") == "validated"
        ),
        "next_run_provider_action": (
            "reuse_validated_profile_after_batch_consent"
            if require_verified and profile.get("status") == "validated"
            else "ask_user_for_provider_or_validation"
        ),
        "automatic_submission_allowed": False,
        "generation_performed": False,
        "network_access_performed": False,
    }


def apply_local_evidence(
    profile: Dict[str, Any],
    evidence: Dict[str, Any],
) -> Dict[str, Any]:
    """Łączy dostarczony lokalny dowód tylko z profilem tego samego dostawcy."""

    if not isinstance(evidence, dict):
        raise ProviderValidationError("Dowód walidacyjny musi być obiektem JSON.")
    if evidence.get("provider_name") != profile.get("provider_name"):
        raise ProviderValidationError("Dowód dotyczy innego dostawcy.")
    if evidence.get("connection_method") != profile.get("connection_method"):
        raise ProviderValidationError("Dowód dotyczy innej metody połączenia.")
    if _forbidden_paths(evidence):
        raise ProviderValidationError("Dowód zawiera niedozwolone pole sekretu.")
    capabilities = evidence.get("capabilities")
    documentation = evidence.get("official_sources")
    if not isinstance(capabilities, dict) or not isinstance(documentation, list):
        raise ProviderValidationError("Dowód musi zawierać capabilities i dokumentację.")
    updated = dict(profile)
    updated["capabilities"] = dict(capabilities)
    updated["official_sources"] = list(documentation)
    updated["status"] = "validated"
    updated["verified_at"] = utc_now()
    updated["verification_errors"] = []
    updated["generation_authorized"] = False
    validate_profile_data(updated, require_verified=True)
    return updated


def validate_profile_file(
    profile_path: Path,
    *,
    evidence_path: Optional[Path] = None,
    expected_provider_name: Optional[str] = None,
    snapshot_path: Optional[Path] = None,
    max_age_days: int = DEFAULT_PROFILE_MAX_AGE_DAYS,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Waliduje plik oraz opcjonalnie zapisuje jawny snapshot bez sekretów."""

    profile = load_json(profile_path)
    if not isinstance(profile, dict):
        raise ProviderValidationError("Profil musi być obiektem JSON.")
    if evidence_path is not None:
        evidence = load_json(evidence_path)
        profile = apply_local_evidence(profile, evidence)
        atomic_write_json(profile_path, profile)
    elif profile.get("status") == "validated":
        refreshed = mark_profile_stale(
            profile,
            max_age_days=max_age_days,
            now=now,
        )
        if refreshed.get("status") == "stale":
            profile = refreshed
            atomic_write_json(profile_path, profile)
    report = validate_profile_data(
        profile,
        expected_provider_name=expected_provider_name,
        require_verified=(
            evidence_path is not None
            or profile.get("status") in {"validated", "stale"}
        ),
        max_age_days=max_age_days,
        now=now,
    )
    if snapshot_path is not None:
        atomic_write_json(snapshot_path, profile)
        report["snapshot_path"] = str(snapshot_path)
    return report


def build_parser() -> argparse.ArgumentParser:
    """Buduje parser walidacji profilu bez połączeń z dostawcą."""

    parser = PolishArgumentParser(
        description="Waliduje lokalny profil wskazanego dostawcy; nie używa sieci ani generowania."
    )
    parser.add_argument("--profile", required=True, type=Path, help="Plik profilu JSON.")
    parser.add_argument(
        "--evidence",
        type=Path,
        help="Opcjonalny lokalny zapis dowodów z oficjalnej dokumentacji.",
    )
    parser.add_argument(
        "--expected-name",
        help="Dokładna nazwa dostawcy oczekiwana przez bieżący projekt.",
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        help="Opcjonalna ścieżka kopii profilu w projekcie.",
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=DEFAULT_PROFILE_MAX_AGE_DAYS,
        help="Maksymalny wiek zwalidowanego profilu przed ponowną walidacją.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Uruchamia lokalną walidację i wypisuje zredagowany raport."""

    args = build_parser().parse_args(argv)
    try:
        report = validate_profile_file(
            args.profile,
            evidence_path=args.evidence,
            expected_provider_name=args.expected_name,
            snapshot_path=args.snapshot,
            max_age_days=args.max_age_days,
        )
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    except (
        OSError,
        ProviderConfigurationError,
        ProviderValidationError,
        ValueError,
    ) as error:
        print(f"Błąd walidacji dostawcy: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
