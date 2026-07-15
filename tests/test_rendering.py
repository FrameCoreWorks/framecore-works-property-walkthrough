"""Testy lokalnego renderu H.264 z zachowaniem proporcji i hard cuts."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict, Tuple


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPOSITORY_ROOT / "skills" / "create-property-walkthrough" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _common import load_json, sha256_file  # noqa: E402
from import_clips import import_clip, record_quality_control  # noqa: E402
from render_walkthrough import (  # noqa: E402
    RenderError,
    _ffconcat_escape,
    _simple_filter,
    render_walkthrough,
)
from tests.test_scene_planning import (  # noqa: E402
    make_synthetic_clip,
    prepare_synthetic_project,
    require_ffmpeg,
)


def prepare_approved_project(
    base: Path,
    *,
    scene_count: int = 2,
    duration: float = 1.0,
    clips_with_audio: bool = True,
) -> Path:
    """Tworzy projekt z lokalnymi syntetycznymi klipami zatwierdzonymi w QC."""

    project_root = prepare_synthetic_project(
        base,
        scene_count,
        duration=duration,
    )
    project = load_json(project_root / "project.json")
    for index, scene in enumerate(project["scene_plan"]["scenes"]):
        source = project_root / "manual-clips" / f"{scene['scene_id']}.mp4"
        make_synthetic_clip(
            source,
            duration=duration,
            index=index,
            size="640x360",
            with_audio=clips_with_audio,
        )
        record = import_clip(project_root, scene["scene_id"], source)
        record_quality_control(
            project_root,
            scene["scene_id"],
            int(record["revision"]),
            "approved",
            notes_pl="Syntetyczny klip testowy zgodny ze źródłem.",
            source_comparison_performed=True,
            comparison_evidence_pl="Porównano syntetyczne próbki ze źródłem.",
        )
    return project_root


def sample_rgb(path: Path, seconds: float, x: int, y: int) -> Tuple[int, int, int]:
    """Odczytuje średni kolor małego obszaru jednej klatki przez lokalny FFmpeg."""

    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-ss",
            f"{seconds:.3f}",
            "-i",
            str(path),
            "-vf",
            f"crop=2:2:{x}:{y},scale=1:1:flags=neighbor,format=rgb24",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "pipe:1",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if len(result.stdout) < 3:
        raise AssertionError("FFmpeg nie zwrócił próbki RGB.")
    return tuple(result.stdout[:3])  # type: ignore[return-value]


class RenderingTests(unittest.TestCase):
    """Sprawdza profil techniczny, hard cuts, brak audio i brak stretchu."""

    def setUp(self) -> None:
        require_ffmpeg(self)
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @unittest.skipIf(sys.platform.startswith("win"), "Symlinki wymagają uprawnień Windows.")
    def test_symlink_final_blokuje_render_poza_projektem(self) -> None:
        project_root = prepare_approved_project(self.base, scene_count=1)
        final_dir = project_root / "final"
        outside = self.base / "outside-final"
        final_dir.rmdir()
        outside.mkdir()
        final_dir.symlink_to(outside, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, "dowiązaniem symbolicznym"):
            render_walkthrough(project_root)
        self.assertEqual(list(outside.iterdir()), [])

    def test_horizontal_and_vertical_outputs_have_required_profile(self) -> None:
        project_root = prepare_approved_project(self.base)

        report = render_walkthrough(project_root, include_vertical=True)

        self.assertEqual(0, report["provider_calls"])
        self.assertTrue(report["hard_cuts"])
        self.assertFalse(report["audio_added"])
        self.assertFalse(report["pii_overlays_added"])
        expected_dimensions: Dict[str, Tuple[int, int]] = {
            "16x9": (1920, 1080),
            "9x16": (1080, 1920),
        }
        for target, (width, height) in expected_dimensions.items():
            result = report["targets"][target]
            probe = result["probe"]
            self.assertEqual("h264", probe["codec_name"])
            self.assertEqual("yuv420p", probe["pixel_format"])
            self.assertEqual(width, probe["width"])
            self.assertEqual(height, probe["height"])
            self.assertIn(probe["sample_aspect_ratio"], ("1:1", None))
            self.assertEqual(0, probe["audio_stream_count"])
            self.assertEqual("hard_cut", result["transition"])
            self.assertFalse(result["audio_added"])
            self.assertFalse(result["pii_overlays_added"])
            output_path = project_root / result["path"]
            self.assertEqual(result["sha256"], sha256_file(output_path))

        duration = float(report["targets"]["16x9"]["probe"]["duration_seconds"])
        self.assertGreater(duration, 1.7)
        self.assertLess(duration, 2.3)

    def test_vertical_contain_preserves_ratio_and_sequence_uses_hard_cut(self) -> None:
        project_root = prepare_approved_project(self.base)
        report = render_walkthrough(project_root, include_vertical=True)
        vertical = project_root / report["targets"]["9x16"]["path"]
        horizontal = project_root / report["targets"]["16x9"]["path"]

        top_letterbox = sample_rgb(vertical, 0.5, 540, 100)
        center = sample_rgb(vertical, 0.5, 540, 960)
        self.assertLess(max(top_letterbox), 20)
        self.assertGreater(max(center), 30)

        first_scene = sample_rgb(horizontal, 0.5, 960, 540)
        second_scene = sample_rgb(horizontal, 1.5, 960, 540)
        self.assertGreater(
            sum(abs(first - second) for first, second in zip(first_scene, second_scene)),
            25,
        )
        self.assertIn("force_original_aspect_ratio=decrease", _simple_filter(1080, 1920, "contain", 30))
        self.assertIn("force_original_aspect_ratio=increase", _simple_filter(1080, 1920, "anchored_crop", 30))
        self.assertIn("crop=1080:1920:0:(ih-oh)/2", _simple_filter(1080, 1920, "anchored_crop", 30, "left"))
        self.assertIn("crop=1080:1920:iw-ow:(ih-oh)/2", _simple_filter(1080, 1920, "anchored_crop", 30, "right"))

    def test_current_render_is_skipped_without_changing_file(self) -> None:
        project_root = prepare_approved_project(self.base, scene_count=1)
        first = render_walkthrough(project_root, include_vertical=True)
        hashes = {
            target: sha256_file(project_root / result["path"])
            for target, result in first["targets"].items()
        }

        second = render_walkthrough(project_root, include_vertical=True)

        for target, result in second["targets"].items():
            self.assertTrue(result["skipped_as_current"])
            self.assertEqual(hashes[target], sha256_file(project_root / result["path"]))

    def test_lista_concat_uzywa_wylacznie_wzglednych_nazw(self) -> None:
        self.assertEqual("scene-001.mp4", _ffconcat_escape("scene-001.mp4"))
        with self.assertRaises(RenderError):
            _ffconcat_escape("C:/projekt/scene-001.mp4")
        with self.assertRaises(RenderError):
            _ffconcat_escape("../scene-001.mp4")


if __name__ == "__main__":
    unittest.main()
