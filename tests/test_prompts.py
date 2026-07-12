"""Testy samodzielnych angielskich promptów I2V i polskich metadanych."""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPOSITORY_ROOT / "skills" / "create-property-walkthrough" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _common import atomic_write_json, load_json  # noqa: E402
from prepare_generation_package import (  # noqa: E402
    ScenePlanningError,
    prepare_generation_package,
)
from tests.test_scene_planning import (  # noqa: E402
    create_synthetic_project,
    prepare_synthetic_project,
    require_ffmpeg,
)


class PromptContractTests(unittest.TestCase):
    """Sprawdza komplet blokad źródła, geometrii i jeden ruch."""

    def setUp(self) -> None:
        require_ffmpeg(self)
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_each_prompt_is_standalone_and_contains_all_locks(self) -> None:
        project_root = prepare_synthetic_project(self.base, 6)
        plan = load_json(project_root / "generation-package" / "scene-plan.json")
        required_phrases = (
            "only visual source of truth",
            "architecture",
            "spatial geometry",
            "walls",
            "doors",
            "windows",
            "floors",
            "ceilings",
            "furniture",
            "decorations",
            "materials",
            "lighting",
            "one camera movement only",
            "realistic, physically plausible parallax",
            "Do not create unseen rooms",
            "new doors",
            "new windows",
            "disappearance",
            "duplication",
            "morphing",
            "melting",
            "bending",
            "geometry drift",
            "scene replacement",
            "impossible reveals",
        )
        for scene in plan["scenes"]:
            prompt = scene["prompt_en"]
            for phrase in required_phrases:
                self.assertIn(phrase, prompt)
            self.assertIn("for exactly 1 seconds", prompt)
            self.assertIn("16:9", prompt)
            self.assertNotIn("negative_prompt", scene)
            self.assertNotIn("Negative Prompt", prompt)
            metadata = scene["metadata_pl"]
            for key in (
                "id_sceny",
                "typ_pomieszczenia",
                "ruch_kamery",
                "czas_trwania_sekundy",
                "format",
                "status_generowania",
                "status_kontroli_jakosci",
                "title",
                "status_note",
            ):
                self.assertIn(key, metadata)

    def test_compound_or_unknown_camera_motion_is_rejected(self) -> None:
        project_root = create_synthetic_project(self.base, 1)
        project = load_json(project_root / "project.json")
        image_id = project["selected_images"][0]
        project["classifications"][image_id]["camera_move"] = "pan_then_push"
        atomic_write_json(project_root / "project.json", project)
        with self.assertRaises(ScenePlanningError):
            prepare_generation_package(project_root, duration_seconds=1.0)

    def test_json_markdown_and_csv_have_the_same_scene_ids(self) -> None:
        project_root = prepare_synthetic_project(self.base, 4)
        shot_list = load_json(project_root / "prompts" / "shot-list.json")
        json_ids = [scene["scene_id"] for scene in shot_list["scenes"]]
        markdown = (project_root / "prompts" / "shot-list.md").read_text(encoding="utf-8")
        with (project_root / "prompts" / "shot-list.csv").open(
            "r", encoding="utf-8", newline=""
        ) as handle:
            csv_ids = [row["scene_id"] for row in csv.DictReader(handle)]
        self.assertEqual(json_ids, csv_ids)
        for scene_id in json_ids:
            self.assertIn(scene_id, markdown)
        json.loads((project_root / "prompts" / "shot-list.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
