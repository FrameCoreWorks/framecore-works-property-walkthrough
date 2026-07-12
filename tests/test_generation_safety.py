"""Testy bramek zgody, kosztu i lokalnych plików do wysłania."""

from __future__ import annotations

import copy
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPOSITORY_ROOT / "skills" / "create-property-walkthrough" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _common import atomic_write_json, load_json, sha256_file  # noqa: E402
from prepare_upload_derivatives import (  # noqa: E402
    CONSENT_QUESTION,
    COST_QUESTION,
    UNKNOWN_COST_NOTICE,
    GenerationSafetyError,
    build_batch_fingerprint_payload,
    canonical_hash,
    evaluate_generation_gate,
    prepare_upload_derivatives,
)
from tests.test_provider_onboarding import validated_profile_data  # noqa: E402
from tests.test_scene_planning import (  # noqa: E402
    prepare_synthetic_project,
    require_ffmpeg,
)


class GenerationSafetyTests(unittest.TestCase):
    """Sprawdza, że lokalne przygotowanie nie omija bramek wykonania."""

    def setUp(self) -> None:
        require_ffmpeg(self)
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _profile_path(self) -> Path:
        path = self.base / "profil-dostawcy.json"
        atomic_write_json(path, validated_profile_data())
        return path

    def _manifest(self, *, cost_status: str = "known", amount: object = 5.0,
                  budget: object = 10.0, retry_number: int = 0) -> dict:
        entry = {
            "scene_id": "scn_test00000001",
            "source_image_id": "1" * 64,
            "original_path": "source-images/syntetyczny.png",
            "original_sha256": "1" * 64,
            "upload_derivative_path": "generation-package/upload-derivatives/scn_test00000001-upload.jpg",
            "upload_derivative_sha256": "2" * 64,
            "metadata_stripped": True,
            "original_substitution_forbidden": True,
            "duration_seconds": 5,
            "aspect_ratio": "16:9",
            "rights_confirmed": True,
            "pii_reviewed": True,
            "contains_pii": False,
        }
        cost = {
            "status": cost_status,
            "amount": amount if cost_status == "known" else None,
            "currency": "PLN" if cost_status == "known" else None,
            "budget": budget,
        }
        profile = validated_profile_data()
        profile_sha256 = "3" * 64
        payload = build_batch_fingerprint_payload(
            profile=profile,
            profile_sha256=profile_sha256,
            model_id="synthetic-model",
            entries=[entry],
            cost=cost,
            output_path="scenes/imported",
            retry_number=retry_number,
        )
        return {
            "batch_fingerprint": canonical_hash(payload),
            "fingerprint_payload": payload,
            "provider_profile_sha256": profile_sha256,
            "model_id": "synthetic-model",
            "entries": [entry],
            "cost": cost,
            "provider_calls": 0,
        }

    @staticmethod
    def _consent(manifest: dict) -> dict:
        return {
            "batch_fingerprint": manifest["batch_fingerprint"],
            "consent_question": CONSENT_QUESTION,
            "upload_and_generation_approved": True,
            "cost_confirmation_question": COST_QUESTION,
            "cost_confirmed": True,
        }

    def test_lokalne_przygotowanie_nie_wykonuje_polaczenia_ani_wysylki(self) -> None:
        project_root = prepare_synthetic_project(self.base, 1)
        project = load_json(project_root / "project.json")
        source = project_root / project["scene_plan"]["scenes"][0]["source_path"]
        source_hash_before = sha256_file(source)
        with mock.patch.object(
            socket,
            "socket",
            side_effect=AssertionError("niedozwolone połączenie sieciowe"),
        ):
            manifest = prepare_upload_derivatives(
                project_root,
                self._profile_path(),
                model_id="synthetic-model",
                cost_status="known",
                cost_amount=0,
                budget=0,
            )

        self.assertEqual(0, manifest["provider_calls"])
        self.assertFalse(manifest["submission_allowed"])
        self.assertEqual("blocked_pending_explicit_consent", manifest["execution_status"])
        self.assertEqual(source_hash_before, sha256_file(source))
        entry = manifest["entries"][0]
        self.assertTrue(entry["metadata_stripped"])
        self.assertTrue(entry["original_substitution_forbidden"])
        self.assertNotEqual(entry["original_path"], entry["upload_derivative_path"])
        self.assertNotEqual(entry["original_sha256"], entry["upload_derivative_sha256"])
        derivative = project_root / entry["upload_derivative_path"]
        self.assertEqual(entry["upload_derivative_sha256"], sha256_file(derivative))

    def test_zmiana_zawartosci_partii_uniewaznia_stara_zgode(self) -> None:
        manifest = self._manifest()
        consent = self._consent(manifest)
        self.assertTrue(evaluate_generation_gate(manifest, consent)["allowed"])

        changed = copy.deepcopy(manifest)
        changed["entries"][0]["upload_derivative_sha256"] = "f" * 64
        result = evaluate_generation_gate(changed, consent)

        self.assertFalse(result["allowed"])
        self.assertTrue(any("fingerprint" in reason for reason in result["reasons"]))
        self.assertEqual(0, result["provider_calls"])

    def test_zgoda_na_poprzedni_retry_jest_nieaktualna(self) -> None:
        first = self._manifest(retry_number=0)
        second = self._manifest(retry_number=1)
        self.assertNotEqual(first["batch_fingerprint"], second["batch_fingerprint"])

        result = evaluate_generation_gate(second, self._consent(first))

        self.assertFalse(result["allowed"])
        self.assertIn(
            "Zgoda dotyczy innego albo zmienionego fingerprintu partii.",
            result["reasons"],
        )

    def test_nieznany_koszt_wymaga_dokladnego_komunikatu_i_zgody_na_ryzyko(self) -> None:
        manifest = self._manifest(cost_status="unknown", amount=None, budget=10.0)
        consent = self._consent(manifest)

        blocked = evaluate_generation_gate(manifest, consent)
        self.assertFalse(blocked["allowed"])
        self.assertTrue(any("Nieznany koszt" in reason for reason in blocked["reasons"]))

        consent["unknown_cost_message"] = UNKNOWN_COST_NOTICE
        consent["unknown_cost_risk_confirmed"] = True
        allowed = evaluate_generation_gate(manifest, consent)
        self.assertTrue(allowed["allowed"], allowed["reasons"])

    def test_platny_retry_wymaga_nowego_jawnego_potwierdzenia(self) -> None:
        manifest = self._manifest(amount=5.0, budget=10.0)
        consent = self._consent(manifest)
        self.assertTrue(evaluate_generation_gate(manifest, consent)["allowed"])

        blocked = evaluate_generation_gate(manifest, consent, paid_retry=True)
        self.assertFalse(blocked["allowed"])
        self.assertTrue(any("Płatny retry" in reason for reason in blocked["reasons"]))

        consent["paid_retry_confirmed"] = True
        self.assertTrue(
            evaluate_generation_gate(manifest, consent, paid_retry=True)["allowed"]
        )

    def test_znany_koszt_przekraczajacy_budzet_jest_blokowany_przed_plikami(self) -> None:
        project_root = prepare_synthetic_project(self.base, 1)
        with mock.patch(
            "prepare_upload_derivatives._prepare_single_derivative",
            side_effect=AssertionError("nie przygotowuj plików po przekroczeniu budżetu"),
        ) as derivative:
            with self.assertRaisesRegex(GenerationSafetyError, "przekracza.*budżet"):
                prepare_upload_derivatives(
                    project_root,
                    self._profile_path(),
                    model_id="synthetic-model",
                    cost_status="known",
                    cost_amount=11,
                    currency="PLN",
                    budget=10,
                )
        derivative.assert_not_called()
        self.assertFalse(
            (project_root / "generation-package" / "provider-batch-manifest.json").exists()
        )

    def test_sfabrykowany_manifest_z_kosztem_ponad_budzet_nie_przechodzi_bramki(self) -> None:
        manifest = self._manifest(amount=11.0, budget=10.0)
        result = evaluate_generation_gate(manifest, self._consent(manifest))
        self.assertFalse(result["allowed"])
        self.assertTrue(any("przekracza" in reason for reason in result["reasons"]))
        self.assertEqual(0, result["provider_calls"])


if __name__ == "__main__":
    unittest.main()
