"""Testy stabilnego planowania scen na syntetycznych materiałach."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPOSITORY_ROOT / "skills" / "create-property-walkthrough" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _common import atomic_write_json, load_json, sha256_file  # noqa: E402
from ingest_images import ingest_images  # noqa: E402
from init_project import create_project  # noqa: E402
from prepare_generation_package import (  # noqa: E402
    ScenePlanningError,
    prepare_generation_package,
)


ROOM_TYPES = (
    "exterior",
    "entrance",
    "hallway",
    "living_room",
    "dining_room",
    "kitchen",
    "bedroom",
    "office",
    "bathroom",
    "balcony",
)


def require_ffmpeg(testcase: unittest.TestCase) -> None:
    """Pomija test multimedialny, gdy środowisko nie ma FFmpeg/ffprobe."""

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        testcase.skipTest("Test wymaga lokalnych programów ffmpeg i ffprobe.")


def run_ffmpeg(arguments: List[str]) -> None:
    """Uruchamia FFmpeg dla syntetycznego fixture'u bez sieci."""

    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin"] + arguments,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def make_synthetic_image(path: Path, index: int, size: str = "320x180") -> None:
    """Tworzy unikalny jednobarwny obraz PNG bez danych rzeczywistych."""

    path.parent.mkdir(parents=True, exist_ok=True)
    color = f"0x{(0x234567 + index * 0x152637) % 0xFFFFFF:06x}"
    run_ffmpeg(
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s={size}:d=0.1",
            "-frames:v",
            "1",
            str(path),
        ]
    )


def make_synthetic_clip(
    path: Path,
    *,
    duration: float = 1.0,
    index: int = 0,
    size: str = "320x180",
    with_audio: bool = False,
) -> None:
    """Tworzy lokalny klip H.264, opcjonalnie z syntetycznym tonem audio."""

    path.parent.mkdir(parents=True, exist_ok=True)
    color = f"0x{(0x654321 + index * 0x12345) % 0xFFFFFF:06x}"
    arguments = [
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s={size}:r=30:d={duration}",
    ]
    if with_audio:
        arguments.extend(
            [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={440 + index * 20}:duration={duration}",
                "-shortest",
            ]
        )
    arguments.extend(
        [
            "-t",
            str(duration),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
        ]
    )
    if with_audio:
        arguments.extend(["-c:a", "aac"])
    else:
        arguments.append("-an")
    arguments.extend(["-movflags", "+faststart", str(path)])
    run_ffmpeg(arguments)


def create_synthetic_project(base: Path, count: int = 6) -> Path:
    """Inicjalizuje kanoniczny projekt i dodaje wyłącznie syntetyczną selekcję."""

    projects_root = base / "projekty"
    project_root = create_project(
        projects_root,
        "Projekt testowy",
        project_id="projekt-testowy",
        source_mode="synthetic",
    )
    source_directory = base / "synthetic-input"
    for index in range(count):
        make_synthetic_image(source_directory / f"syntetyczny-{index:02d}.png", index)
    ingestion = ingest_images(
        source_directory,
        project_root / "source-images",
        provenance_kind="synthetic_fixture",
    )

    project = load_json(project_root / "project.json")
    classifications: Dict[str, Dict[str, Any]] = {}
    selected: List[str] = []
    for index, asset in enumerate(ingestion["assets"]):
        image_path = Path(asset["original_path"])
        digest = asset["sha256"]
        if sha256_file(image_path) != digest:
            raise AssertionError("Syntetyczny asset ingestion ma niespójny SHA-256.")
        room_type = ROOM_TYPES[index % len(ROOM_TYPES)]
        classifications[digest] = {
            "image_id": digest,
            "sha256": digest,
            "relative_path": image_path.relative_to(project_root).as_posix(),
            "asset_kind": "photo",
            "room_type": room_type,
            "room_instance_id": f"{room_type}-{index:02d}",
            "curation_status": "selected",
            "technical_quality": "high",
            "animation_utility": "high",
            "deformation_risk": "low" if index % 2 == 0 else "medium",
            "visible_spaces": [room_type],
            "reasons_pl": ["Syntetyczne zdjęcie testowe."],
            "rights_confirmed": True,
            "pii_reviewed": True,
            "contains_pii": False,
        }
        selected.append(digest)
    project["classifications"] = classifications
    project["selected_images"] = selected
    project["stages"]["ingestion"] = "complete"
    project["stages"]["image_analysis"] = "complete"
    project["manifest_revision"] += 1
    atomic_write_json(project_root / "project.json", project)
    return project_root


def prepare_synthetic_project(
    base: Path,
    count: int = 6,
    *,
    duration: float = 1.0,
    ratio: str = "16:9",
) -> Path:
    """Tworzy projekt oraz provider-free pakiet generacyjny."""

    project_root = create_synthetic_project(base, count)
    prepare_generation_package(
        project_root,
        duration_seconds=duration,
        ratio=ratio,
    )
    return project_root


class ScenePlanningTests(unittest.TestCase):
    """Sprawdza ID, reorder, tombstone'y i krótszy uzasadniony plan."""

    def setUp(self) -> None:
        require_ffmpeg(self)
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_six_scenes_keep_opaque_ids_after_reorder(self) -> None:
        project_root = prepare_synthetic_project(self.base, 6)
        first = load_json(project_root / "project.json")
        first_ids = {
            scene["source_image_id"]: scene["scene_id"]
            for scene in first["scene_plan"]["scenes"]
        }
        self.assertEqual(list(range(6)), [
            scene["sequence_index"] for scene in first["scene_plan"]["scenes"]
        ])
        for scene_id in first_ids.values():
            self.assertRegex(scene_id, r"^scn_[a-z0-9]{12,32}$")

        project = load_json(project_root / "project.json")
        for index, image_id in enumerate(reversed(project["selected_images"])):
            project["classifications"][image_id]["sequence_index"] = index
        atomic_write_json(project_root / "project.json", project)
        prepare_generation_package(project_root, duration_seconds=1.0)
        second = load_json(project_root / "project.json")
        second_ids = {
            scene["source_image_id"]: scene["scene_id"]
            for scene in second["scene_plan"]["scenes"]
        }
        self.assertEqual(first_ids, second_ids)
        self.assertNotEqual(
            [scene["source_image_id"] for scene in first["scene_plan"]["scenes"]],
            [scene["source_image_id"] for scene in second["scene_plan"]["scenes"]],
        )

    def test_sparse_plan_has_nonempty_reason_without_fillers(self) -> None:
        project_root = prepare_synthetic_project(self.base, 3)
        plan = load_json(project_root / "generation-package" / "scene-plan.json")
        self.assertEqual(3, len(plan["scenes"]))
        self.assertTrue(plan["short_plan_reason"])
        self.assertIn("3", plan["short_plan_reason"])
        self.assertEqual(3, len({scene["source_image_id"] for scene in plan["scenes"]}))

    def test_removed_scene_leaves_tombstone_and_id_is_never_reused(self) -> None:
        project_root = prepare_synthetic_project(self.base, 2)
        first = load_json(project_root / "project.json")
        removed_image = first["selected_images"][0]
        removed_id = next(
            scene["scene_id"]
            for scene in first["scene_plan"]["scenes"]
            if scene["source_image_id"] == removed_image
        )
        first["selected_images"] = [first["selected_images"][1]]
        atomic_write_json(project_root / "project.json", first)
        prepare_generation_package(project_root, duration_seconds=1.0)
        removed = load_json(project_root / "project.json")
        self.assertIn(removed_id, {
            item["scene_id"] for item in removed["scene_plan"]["tombstones"]
        })

        removed["selected_images"].append(removed_image)
        atomic_write_json(project_root / "project.json", removed)
        prepare_generation_package(project_root, duration_seconds=1.0)
        restored = load_json(project_root / "project.json")
        restored_id = next(
            scene["scene_id"]
            for scene in restored["scene_plan"]["scenes"]
            if scene["source_image_id"] == removed_image
        )
        self.assertNotEqual(removed_id, restored_id)

    def test_non_photo_cannot_become_i2v_scene(self) -> None:
        project_root = create_synthetic_project(self.base, 1)
        project = load_json(project_root / "project.json")
        image_id = project["selected_images"][0]
        project["classifications"][image_id]["asset_kind"] = "floor_plan"
        atomic_write_json(project_root / "project.json", project)
        with self.assertRaises(ScenePlanningError):
            prepare_generation_package(project_root, duration_seconds=1.0)


if __name__ == "__main__":
    unittest.main()
