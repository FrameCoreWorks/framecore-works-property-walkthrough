#!/usr/bin/env python3
"""Konfiguruje nazwany profil dostawcy bez wykonywania połączeń sieciowych."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from _common import PolishArgumentParser, atomic_write_json, load_json


PROVIDER_QUESTION = (
    "Jakiego dostawcę MCP lub API chcesz skonfigurować razem z tym skillem, "
    "aby umożliwić automatyczne generowanie klipów i całego contentu "
    "walkthrough? Podaj dokładną nazwę dostawcy oraz wybierz sposób "
    "połączenia: MCP albo API."
)
GENERATION_CONSENT_QUESTION = (
    "Czy wyrażasz zgodę na przesłanie wskazanych zdjęć do skonfigurowanego "
    "dostawcy i uruchomienie generowania zaplanowanych klipów walkthrough?"
)
COST_CONFIRMATION_QUESTION = "Czy potwierdzasz również wskazany koszt generowania?"
UNKNOWN_COST_MESSAGE = "Koszt generowania nie został zweryfikowany."

PROFILE_SCHEMA_VERSION = 1
CONNECTION_METHODS = ("MCP", "API")
_SECRET_REFERENCE_PATTERN = re.compile(
    r"^(?:env|keychain|secret-store|mcp-oauth):[A-Za-z0-9_.@/:-]{1,240}$"
)
_FORBIDDEN_SECRET_KEYS = {
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
_SECRET_LIKE_PREFIXES = (
    "sk-",
    "ghp_",
    "github_pat_",
    "xoxb-",
    "xoxp-",
    "AIza",
)


class ProviderConfigurationError(ValueError):
    """Oznacza błąd bezpiecznej konfiguracji profilu dostawcy."""


def default_profile_path(codex_home: Optional[Path] = None) -> Path:
    """Zwraca ścieżkę profilu użytkownika poza repozytorium projektu."""

    if codex_home is None:
        configured = os.environ.get("CODEX_HOME")
        codex_home = Path(configured) if configured else Path.home() / ".codex"
    return codex_home / "state" / "create-property-walkthrough" / "provider-profile.json"


def _contains_forbidden_secret_key(value: Any) -> bool:
    """Sprawdza rekurencyjnie, czy dane zawierają pole mogące przechowywać sekret."""

    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in _FORBIDDEN_SECRET_KEYS:
                return True
            if _contains_forbidden_secret_key(child):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_secret_key(item) for item in value)
    return False


def validate_secret_reference(reference: str) -> str:
    """Waliduje wskaźnik do sekretu bez odczytywania wartości sekretu."""

    if not isinstance(reference, str) or not _SECRET_REFERENCE_PATTERN.fullmatch(reference):
        raise ProviderConfigurationError(
            "Referencja sekretu musi wskazywać env, keychain, secret-store albo mcp-oauth."
        )
    return reference


def looks_like_secret_value(value: str) -> bool:
    """Rozpoznaje typowe kształty sekretów bez zapisywania ich wartości."""

    if not isinstance(value, str):
        return False
    if value.startswith(_SECRET_LIKE_PREFIXES):
        return True
    if any(character.isspace() for character in value):
        return False
    return bool(
        len(value) >= 40
        and re.fullmatch(r"[A-Za-z0-9_+./=-]+", value)
        and len(set(value)) >= 12
    )


def build_unconfigured_profile() -> Dict[str, Any]:
    """Buduje pusty profil zgodny ze schematem, bez danych dostawcy i sekretów."""

    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "provider_name": "",
        "connection_method": "",
        "status": "not_configured",
        "capabilities": {
            "image_to_video": "unverified",
            "submission": "unverified",
            "polling": "unverified",
            "download": "unverified",
            "idempotency_key": "unverified",
            "ratios": [],
            "durations_seconds": [],
            "cost_status": "unknown",
        },
        "official_sources": [],
        "secret_reference": "",
        "verified_at": "",
        "verification_errors": [],
        "generation_authorized": False,
    }


def build_provider_profile(
    provider_name: str,
    connection_method: str,
    secret_reference: str,
    *,
    existing_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Buduje profil wyłącznie dla dokładnie wskazanego dostawcy i metody."""

    if not isinstance(provider_name, str) or not provider_name.strip():
        raise ProviderConfigurationError("Podaj dokładną nazwę dostawcy.")
    if provider_name != provider_name.strip():
        raise ProviderConfigurationError("Nazwa dostawcy nie może mieć skrajnych spacji.")
    if len(provider_name) > 160 or any(ord(character) < 32 for character in provider_name):
        raise ProviderConfigurationError("Nazwa dostawcy ma niedozwolony format.")
    if looks_like_secret_value(provider_name):
        raise ProviderConfigurationError(
            "Nazwa dostawcy przypomina wartość sekretu; podaj publiczną nazwę usługi."
        )

    method = connection_method.upper()
    if method not in CONNECTION_METHODS:
        raise ProviderConfigurationError("Sposób połączenia musi mieć wartość MCP albo API.")
    reference = validate_secret_reference(secret_reference)

    if existing_profile:
        existing_name = existing_profile.get("provider_name")
        if existing_name and existing_name != provider_name:
            raise ProviderConfigurationError(
                "Istniejący profil dotyczy innego dostawcy; jawnie utwórz osobny profil."
            )
    profile: Dict[str, Any] = {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "provider_name": provider_name,
        "connection_method": method,
        "status": "pending_validation",
        "capabilities": {
            "image_to_video": "unverified",
            "submission": "unverified",
            "polling": "unverified",
            "download": "unverified",
            "idempotency_key": "unverified",
            "ratios": [],
            "durations_seconds": [],
            "cost_status": "unknown",
        },
        "official_sources": [],
        "secret_reference": reference,
        "verified_at": "",
        "verification_errors": [],
        "generation_authorized": False,
    }
    if _contains_forbidden_secret_key(profile):
        raise ProviderConfigurationError("Profil zawiera niedozwolone pole sekretu.")
    return profile


def configure_provider(
    provider_name: str,
    connection_method: str,
    secret_reference: str,
    *,
    output_path: Optional[Path] = None,
) -> Path:
    """Zapisuje profil atomowo, bez skanowania integracji i bez testu połączenia."""

    destination = output_path or default_profile_path()
    existing: Optional[Dict[str, Any]] = None
    if destination.exists():
        loaded = load_json(destination)
        if not isinstance(loaded, dict):
            raise ProviderConfigurationError("Istniejący profil ma niepoprawny format.")
        existing = loaded
    profile = build_provider_profile(
        provider_name,
        connection_method,
        secret_reference,
        existing_profile=existing,
    )
    atomic_write_json(destination, profile)
    return destination


def reset_provider_profile(*, output_path: Optional[Path] = None) -> Path:
    """Resetuje profil atomowo do stanu not_configured bez usuwania katalogu stanu."""

    destination = output_path or default_profile_path()
    atomic_write_json(destination, build_unconfigured_profile())
    return destination


def build_parser() -> argparse.ArgumentParser:
    """Buduje parser poleceń neutralnego onboardingu."""

    parser = PolishArgumentParser(
        description="Konfiguruje wyłącznie wskazanego dostawcę, bez sieci i generowania."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "question",
        help="Wyświetl dokładne pytanie o nazwę dostawcy i metodę połączenia.",
    )
    configure = subparsers.add_parser(
        "configure",
        help="Zapisz profil wskazanego dostawcy bez sekretów.",
    )
    configure.add_argument("--name", required=True, help="Dokładna nazwa dostawcy.")
    configure.add_argument(
        "--connection-method",
        required=True,
        choices=CONNECTION_METHODS,
        help="Sposób połączenia: MCP albo API.",
    )
    configure.add_argument(
        "--secret-reference",
        required=True,
        help="Bezpieczna referencja, np. env:NAZWA_ZMIENNEJ, bez wartości sekretu.",
    )
    configure.add_argument(
        "--output",
        type=Path,
        help="Opcjonalna ścieżka profilu; domyślnie profil w CODEX_HOME/state.",
    )
    reset = subparsers.add_parser(
        "reset",
        help="Wyzeruj profil do stanu not_configured bez usuwania pliku.",
    )
    reset.add_argument(
        "--output",
        type=Path,
        help="Opcjonalna ścieżka profilu; domyślnie profil w CODEX_HOME/state.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Uruchamia lokalne polecenie konfiguracji i zwraca kod zakończenia."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "question":
            print(PROVIDER_QUESTION)
            return 0
        if args.command == "reset":
            destination = reset_provider_profile(output_path=args.output)
            print(
                json.dumps(
                    {"status": "not_configured", "profile_path": str(destination)},
                    ensure_ascii=False,
                )
            )
            return 0
        destination = configure_provider(
            args.name,
            args.connection_method,
            args.secret_reference,
            output_path=args.output,
        )
        print(
            json.dumps(
                {"status": "pending_validation", "profile_path": str(destination)},
                ensure_ascii=False,
            )
        )
        return 0
    except (OSError, ProviderConfigurationError, ValueError) as error:
        print(f"Błąd konfiguracji dostawcy: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
