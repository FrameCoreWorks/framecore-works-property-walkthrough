"""Testy jawnego podzbioru JSON Schema i walidacji semantycznej."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "create-property-walkthrough"
SCRIPTS = SKILL / "scripts"
ASSETS = SKILL / "assets"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _common import load_json, utc_now  # noqa: E402
from _schema import (  # noqa: E402
    DocumentValidationError,
    SchemaDefinitionError,
    load_schema,
    validate_document,
    validate_instance,
    validate_schema,
)


HASH_A = "a" * 64
HASH_B = "b" * 64


class SchemaSubsetTests(unittest.TestCase):
    """Sprawdza ograniczony walidator i jawne odrzucanie rozszerzeń."""

    def test_wszystkie_schematy_assetow_sa_obslugiwane(self) -> None:
        schema_paths = sorted(ASSETS.glob("*.schema.json"))
        self.assertEqual(len(schema_paths), 4)
        for path in schema_paths:
            with self.subTest(path=path.name):
                self.assertIsInstance(load_schema(path), dict)

    def test_nieobslugiwane_slowo_jest_bledem_na_kazdym_poziomie(self) -> None:
        with self.assertRaisesRegex(SchemaDefinitionError, "nieobsługiwane.*oneOf"):
            validate_schema({"oneOf": [{"type": "string"}]})
        with self.assertRaisesRegex(SchemaDefinitionError, "nieobsługiwane.*format"):
            validate_schema(
                {
                    "type": "object",
                    "properties": {"czas": {"type": "string", "format": "date-time"}},
                }
            )

    def test_required_additional_properties_i_bool_jako_integer(self) -> None:
        schema = {
            "type": "object",
            "properties": {"liczba": {"type": "integer", "minimum": 1}},
            "required": ["liczba"],
            "additionalProperties": False,
        }
        validate_instance({"liczba": 2}, schema)
        with self.assertRaisesRegex(DocumentValidationError, "brakuje wymaganej"):
            validate_instance({}, schema)
        with self.assertRaisesRegex(DocumentValidationError, "dodatkowa właściwość"):
            validate_instance({"liczba": 2, "inna": 3}, schema)
        with self.assertRaisesRegex(DocumentValidationError, "liczba całkowita"):
            validate_instance({"liczba": True}, schema)

    def test_type_union_enum_pattern_i_granice(self) -> None:
        schema = {
            "type": ["string", "null"],
            "enum": ["gotowe", None],
            "minLength": 3,
            "maxLength": 8,
            "pattern": "^[a-z]+$",
        }
        validate_instance(None, schema)
        validate_instance("gotowe", schema)
        with self.assertRaises(DocumentValidationError):
            validate_instance("ZA-DŁUGIE", schema)


class SemanticValidationTests(unittest.TestCase):
    """Sprawdza reguły domenowe oddzielone od struktury JSON."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.image_schema = load_schema(ASSETS / "image-analysis.schema.json")
        cls.scene_schema = load_schema(ASSETS / "scene-plan.schema.json")
        cls.provider_schema = load_schema(ASSETS / "provider-profile.schema.json")

    def test_analiza_zdjec_rozdziela_taksonomie(self) -> None:
        document = {
            "schema_version": "1.0",
            "project_id": "mieszkanie-testowe",
            "generated_at": utc_now(),
            "images": [
                {
                    "image_id": HASH_A,
                    "sha256": HASH_A,
                    "relative_path": "source-images/łazienka_żółta.jpg",
                    "asset_kind": "photo",
                    "room_type": "łazienka",
                    "room_instance_id": "lazienka-1",
                    "curation_status": "selected",
                    "technical_quality": "high",
                    "animation_utility": "high",
                    "deformation_risk": "low",
                    "visible_spaces": ["łazienka"],
                    "reasons_pl": ["Czytelna geometria."],
                }
            ],
            "warnings": [],
        }
        validate_document(document, self.image_schema, "image-analysis")
        invalid = copy.deepcopy(document)
        invalid["images"][0]["asset_kind"] = "floor_plan"
        with self.assertRaisesRegex(DocumentValidationError, "musi być fotografią"):
            validate_document(invalid, self.image_schema, "image-analysis")
        invalid = copy.deepcopy(document)
        invalid["images"][0]["sha256"] = HASH_B
        with self.assertRaisesRegex(DocumentValidationError, "dokładnie odpowiadać"):
            validate_document(invalid, self.image_schema, "image-analysis")

    def _scene_plan(self) -> dict:
        return {
            "schema_version": "1.0",
            "project_id": "mieszkanie-testowe",
            "revision": 1,
            "generated_at": utc_now(),
            "scenes": [
                {
                    "scene_id": "scn_123456789abc",
                    "sequence_index": 0,
                    "source_image_id": HASH_A,
                    "source_sha256": HASH_A,
                    "source_path": "source-images/salon.jpg",
                    "room_instance_id": "salon-1",
                    "room_type": "salon",
                    "aspect_ratio": "16:9",
                    "duration_seconds": 5,
                    "camera_motion": "slow_push_in",
                    "deformation_risk": "low",
                    "vertical_strategy": "not_applicable",
                    "prompt_en": (
                        "Create a restrained cinematic push-in from this exact source frame. "
                        "Preserve every wall, opening, object, reflection and all visible geometry."
                    ),
                    "metadata_pl": {
                        "title": "Salon",
                        "status_note": "Scena gotowa do pakietu manualnego.",
                    },
                    "status": "ready",
                    "dependency_hash": HASH_B,
                }
            ],
            "tombstones": [],
            "short_plan_reason": "Dostępne jest tylko jedno bezpieczne zdjęcie syntetyczne.",
            "warnings": [],
        }

    def test_plan_scen_sprawdza_jeden_ruch_i_krotszy_plan(self) -> None:
        document = self._scene_plan()
        validate_document(document, self.scene_schema, "scene-plan")
        invalid = copy.deepcopy(document)
        invalid["scenes"][0]["camera_motion"] = "push_in+pan_left"
        with self.assertRaises(DocumentValidationError):
            validate_document(invalid, self.scene_schema, "scene-plan")
        invalid = copy.deepcopy(document)
        invalid["short_plan_reason"] = None
        with self.assertRaisesRegex(DocumentValidationError, "krótszy niż 6"):
            validate_document(invalid, self.scene_schema, "scene-plan")
        invalid = copy.deepcopy(document)
        invalid["scenes"][0]["source_sha256"] = HASH_B
        with self.assertRaisesRegex(DocumentValidationError, "source_sha256"):
            validate_document(invalid, self.scene_schema, "scene-plan")

    def test_scene_id_z_tombstone_nie_moze_wrocic(self) -> None:
        document = self._scene_plan()
        document["tombstones"] = [
            {
                "scene_id": "scn_123456789abc",
                "removed_at": utc_now(),
                "reason": "Usunięto po selekcji.",
                "last_sequence_index": 0,
                "source_image_id": HASH_A,
            }
        ]
        with self.assertRaisesRegex(DocumentValidationError, "nie może zostać użyte ponownie"):
            validate_document(document, self.scene_schema, "scene-plan")

    def test_kanoniczny_profil_providera_nie_autoryzuje_generowania(self) -> None:
        unconfigured = load_json(
            ASSETS / "project-templates" / "provider-profile.snapshot.json"
        )
        validate_document(unconfigured, self.provider_schema, "provider-profile")

        configured = {
            "schema_version": 1,
            "provider_name": "Dostawca wskazany przez użytkownika",
            "connection_method": "MCP",
            "status": "validated",
            "capabilities": {
                "image_to_video": True,
                "ratios": ["16:9"],
                "durations_seconds": [5],
                "submission": True,
                "polling": True,
                "download": True,
                "idempotency_key": False,
                "cost_status": "known",
            },
            "official_sources": [
                {
                    "url": "https://docs.example.invalid/image-to-video",
                    "purpose": "Kontrakt I2V",
                    "checked_at": utc_now(),
                }
            ],
            "secret_reference": "mcp-oauth:provider-server",
            "verified_at": utc_now(),
            "verification_errors": [],
            "generation_authorized": False,
        }
        validate_document(configured, self.provider_schema, "provider-profile")
        stale = copy.deepcopy(configured)
        stale["status"] = "stale"
        stale["verification_errors"] = ["Profil wymaga ponownej walidacji."]
        validate_document(stale, self.provider_schema, "provider-profile")
        invalid = copy.deepcopy(configured)
        invalid["generation_authorized"] = True
        with self.assertRaises(DocumentValidationError):
            validate_document(invalid, self.provider_schema, "provider-profile")
        invalid = copy.deepcopy(configured)
        invalid["secret_reference"] = "surowy-sekret"
        with self.assertRaisesRegex(DocumentValidationError, "referencja"):
            validate_document(invalid, self.provider_schema, "provider-profile")
        invalid = copy.deepcopy(configured)
        invalid["secret_reference"] = "mcp_oauth:provider-server"
        with self.assertRaisesRegex(DocumentValidationError, "referencja"):
            validate_document(invalid, self.provider_schema, "provider-profile")


if __name__ == "__main__":
    unittest.main()
