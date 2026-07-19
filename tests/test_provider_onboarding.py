"""Testy named-only onboardingu dostawcy bez sieci i generowania."""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPOSITORY_ROOT / "skills" / "create-property-walkthrough" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _common import atomic_write_json, load_json, utc_now  # noqa: E402
from configure_provider import (  # noqa: E402
    COST_CONFIRMATION_QUESTION,
    GENERATION_CONSENT_QUESTION,
    PROVIDER_QUESTION,
    UNKNOWN_COST_MESSAGE,
    build_unconfigured_profile,
    build_provider_profile,
    configure_provider,
    ProviderConfigurationError,
    main as configure_main,
    reset_provider_profile,
)
from validate_provider import (  # noqa: E402
    DEFAULT_PROFILE_MAX_AGE_DAYS,
    ProviderValidationError,
    profile_freshness,
    validate_profile_data,
    validate_profile_file,
)


EXPECTED_PROVIDER_QUESTION = (
    "Jakiego dostawcę MCP lub API chcesz skonfigurować razem z tym skillem, "
    "aby umożliwić automatyczne generowanie klipów i całego contentu "
    "walkthrough? Podaj dokładną nazwę dostawcy oraz wybierz sposób "
    "połączenia: MCP albo API."
)
EXPECTED_CONSENT_QUESTION = (
    "Czy wyrażasz zgodę na przesłanie wskazanych zdjęć do skonfigurowanego "
    "dostawcy i uruchomienie generowania zaplanowanych klipów walkthrough?"
)
EXPECTED_COST_QUESTION = "Czy potwierdzasz również wskazany koszt generowania?"
EXPECTED_UNKNOWN_COST = "Koszt generowania nie został zweryfikowany."


def validated_profile_data(name: str = "Dostawca Testowy") -> dict:
    """Zwraca syntetyczny profil zgodny z kanonicznym schema P3."""

    profile = build_provider_profile(name, "API", "env:TEST_PROVIDER_KEY")
    profile.update(
        {
            "status": "validated",
            "capabilities": {
                "image_to_video": True,
                "submission": True,
                "polling": True,
                "download": True,
                "idempotency_key": False,
                "ratios": ["16:9", "9:16"],
                "durations_seconds": [1, 5],
                "cost_status": "known",
            },
            "official_sources": [
                {
                    "url": "https://docs.example.com/video",
                    "purpose": "Syntetyczny dowód kontraktu testowego.",
                    "checked_at": utc_now(),
                }
            ],
            "verified_at": utc_now(),
            "verification_errors": [],
            "generation_authorized": False,
        }
    )
    return profile


class ProviderOnboardingTests(unittest.TestCase):
    """Sprawdza exact strings, jeden schema i brak sekretów/provider calls."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_all_required_questions_are_exact_literals(self) -> None:
        self.assertEqual(EXPECTED_PROVIDER_QUESTION, PROVIDER_QUESTION)
        self.assertEqual(EXPECTED_CONSENT_QUESTION, GENERATION_CONSENT_QUESTION)
        self.assertEqual(EXPECTED_COST_QUESTION, COST_CONFIRMATION_QUESTION)
        self.assertEqual(EXPECTED_UNKNOWN_COST, UNKNOWN_COST_MESSAGE)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = configure_main(["question"])
        self.assertEqual(0, result)
        self.assertEqual(EXPECTED_PROVIDER_QUESTION + "\n", output.getvalue())

    def test_pending_profile_uses_only_canonical_fields_and_no_secret(self) -> None:
        profile = build_provider_profile(
            "Dostawca Użytkownika",
            "MCP",
            "mcp-oauth:dostawca-uzytkownika",
        )
        self.assertEqual(
            {
                "schema_version",
                "provider_name",
                "connection_method",
                "status",
                "capabilities",
                "official_sources",
                "secret_reference",
                "verified_at",
                "verification_errors",
                "generation_authorized",
            },
            set(profile),
        )
        self.assertEqual("pending_validation", profile["status"])
        self.assertFalse(profile["generation_authorized"])
        self.assertNotIn("api_key", json.dumps(profile).lower())
        validate_profile_data(profile)

    def test_configuration_and_validation_never_open_a_socket(self) -> None:
        profile_path = self.base / "stan" / "provider-profile.json"
        evidence_path = self.base / "evidence.json"
        snapshot_path = self.base / "projekt" / "provider-profile.snapshot.json"
        evidence = {
            "provider_name": "Wyłącznie Nazwany Dostawca",
            "connection_method": "API",
            "capabilities": validated_profile_data()["capabilities"],
            "official_sources": validated_profile_data()["official_sources"],
        }
        atomic_write_json(evidence_path, evidence)
        with mock.patch("socket.socket", side_effect=AssertionError("wywołanie sieci")):
            configure_provider(
                "Wyłącznie Nazwany Dostawca",
                "API",
                "env:TEST_PROVIDER_KEY",
                output_path=profile_path,
            )
            report = validate_profile_file(
                profile_path,
                evidence_path=evidence_path,
                expected_provider_name="Wyłącznie Nazwany Dostawca",
                snapshot_path=snapshot_path,
            )
        self.assertTrue(report["valid"])
        self.assertFalse(report["generation_performed"])
        self.assertFalse(report["network_access_performed"])
        self.assertEqual("validated", load_json(snapshot_path)["status"])

    def test_validated_profile_is_reused_without_authorizing_submission(self) -> None:
        profile_path = self.base / "provider-profile.json"
        atomic_write_json(profile_path, validated_profile_data("Stały Dostawca"))

        report = validate_profile_file(profile_path)

        self.assertTrue(report["provider_reuse_allowed"])
        self.assertEqual(
            "reuse_validated_profile_after_batch_consent",
            report["next_run_provider_action"],
        )
        self.assertFalse(report["automatic_submission_allowed"])
        self.assertFalse(load_json(profile_path)["generation_authorized"])

    def test_pending_profile_still_requires_provider_validation(self) -> None:
        profile_path = self.base / "provider-profile.json"
        configure_provider(
            "Stały Dostawca",
            "API",
            "env:TEST_PROVIDER_KEY",
            output_path=profile_path,
        )

        report = validate_profile_file(profile_path)

        self.assertFalse(report["provider_reuse_allowed"])
        self.assertEqual(
            "ask_user_for_provider_or_validation",
            report["next_run_provider_action"],
        )
        self.assertFalse(report["automatic_submission_allowed"])

    def test_profile_rejects_secret_field_and_wrong_named_provider(self) -> None:
        profile = validated_profile_data()
        profile["api_key"] = "sekret-testowy-canary"
        with self.assertRaises(ProviderValidationError):
            validate_profile_data(profile, require_verified=True)
        clean = validated_profile_data()
        with self.assertRaises(ProviderValidationError):
            validate_profile_data(
                clean,
                expected_provider_name="Inny Dostawca",
                require_verified=True,
            )

    def test_nazwa_dostawcy_nie_moze_przypominac_sekretu(self) -> None:
        secret_like_name = "sk-" + "AbCdEf0123456789" * 3
        with self.assertRaisesRegex(ProviderConfigurationError, "przypomina wartość sekretu"):
            build_provider_profile(secret_like_name, "API", "env:TEST_PROVIDER_KEY")

        profile = validated_profile_data()
        profile["provider_name"] = secret_like_name
        with self.assertRaisesRegex(ProviderValidationError, "przypomina wartość sekretu"):
            validate_profile_data(profile, require_verified=True)

    def test_przeterminowany_profil_jest_zapisywany_jako_stale(self) -> None:
        now = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
        profile = validated_profile_data()
        profile["verified_at"] = (
            now - timedelta(days=DEFAULT_PROFILE_MAX_AGE_DAYS, seconds=1)
        ).isoformat().replace("+00:00", "Z")
        profile_path = self.base / "provider-profile.json"
        atomic_write_json(profile_path, profile)

        self.assertEqual("stale", profile_freshness(profile, now=now))
        with self.assertRaisesRegex(ProviderValidationError, "nieaktualny"):
            validate_profile_file(profile_path, now=now)

        persisted = load_json(profile_path)
        self.assertEqual("stale", persisted["status"])
        self.assertFalse(persisted["generation_authorized"])
        self.assertTrue(persisted["verification_errors"])

    def test_reset_profila_zapisuje_kanoniczny_stan_not_configured(self) -> None:
        profile_path = self.base / "provider-profile.json"
        atomic_write_json(profile_path, validated_profile_data())

        destination = reset_provider_profile(output_path=profile_path)

        self.assertEqual(profile_path, destination)
        self.assertEqual(build_unconfigured_profile(), load_json(profile_path))
        self.assertEqual("not_configured", load_json(profile_path)["status"])

        configure_provider(
            "Nowy Dostawca",
            "MCP",
            "mcp-oauth:nowy-dostawca",
            output_path=profile_path,
        )
        self.assertEqual("Nowy Dostawca", load_json(profile_path)["provider_name"])

    def test_okres_waznosci_musi_byc_dodatni(self) -> None:
        with self.assertRaisesRegex(ProviderValidationError, "dodatnią liczbą dni"):
            validate_profile_data(
                validated_profile_data(),
                require_verified=True,
                max_age_days=0,
            )


if __name__ == "__main__":
    unittest.main()
