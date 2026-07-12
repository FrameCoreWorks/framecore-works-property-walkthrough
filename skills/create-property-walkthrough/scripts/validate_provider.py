#!/usr/bin/env python3
"""Waliduje lokalny profil nazwanego dostawcy bez testów sieciowych."""

from __future__ import annotations

import argparse
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
) -> Dict[str, Any]:
    """Waliduje profil i zwraca bezpieczny raport bez sekretów."""

    if not isinstance(profile, dict):
        raise ProviderValidationError("Profil musi być obiektem JSON.")
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
        if profile.get("status") != "validated":
            raise ProviderValidationError("Profil nie ma statusu validated.")
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
) -> Dict[str, Any]:
    """Waliduje plik oraz opcjonalnie zapisuje jawny snapshot bez sekretów."""

    profile = load_json(profile_path)
    if not isinstance(profile, dict):
        raise ProviderValidationError("Profil musi być obiektem JSON.")
    if evidence_path is not None:
        evidence = load_json(evidence_path)
        profile = apply_local_evidence(profile, evidence)
        atomic_write_json(profile_path, profile)
    report = validate_profile_data(
        profile,
        expected_provider_name=expected_provider_name,
        require_verified=evidence_path is not None or profile.get("status") == "validated",
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
