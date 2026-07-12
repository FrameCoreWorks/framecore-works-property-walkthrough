#!/usr/bin/env python3
"""Renderuje lokalny walkthrough H.264 z hard cuts i bez automatycznych dodatków."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from _common import (
    PolishArgumentParser,
    atomic_write_json,
    load_json,
    locked_project_mutation,
    resolve_project_path,
    sha256_file,
    utc_now,
    validate_project_root,
)
from _media import MediaError, ffprobe_json, run_ffmpeg


TARGETS = {
    "16x9": {"width": 1920, "height": 1080, "filename": "walkthrough-16x9.mp4"},
    "9x16": {"width": 1080, "height": 1920, "filename": "walkthrough-9x16.mp4"},
}
VERTICAL_STRATEGIES = ("anchored_crop", "contain", "padded_background")
DEFAULT_FPS = 30


class RenderError(ValueError):
    """Oznacza niespełniony kontrakt wejść albo parametrów finalnego renderu."""


def _canonical_hash(value: Any) -> str:
    """Oblicza stabilny hash zależności renderu."""

    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _approved_clip(
    project_root: Path,
    project: Mapping[str, Any],
    scene: Mapping[str, Any],
) -> Dict[str, Any]:
    """Zwraca dokładnie rewizję zatwierdzoną w QC i sprawdza jej hash."""

    scene_id = scene.get("scene_id")
    qc = project.get("qc")
    if not isinstance(qc, dict):
        raise RenderError("Projekt nie ma raportu QC.")
    selection = qc.get(scene_id)
    if not isinstance(selection, dict) or selection.get("status") != "approved":
        raise RenderError(f"Scena {scene_id} nie ma zatwierdzonego klipu.")
    clip_id = selection.get("selected_clip_id")
    clips = project.get("clips")
    if not isinstance(clips, list):
        raise RenderError("Pole clips musi być listą rewizji.")
    selected: Optional[Dict[str, Any]] = None
    for record in clips:
        if isinstance(record, dict) and record.get("clip_id") == clip_id:
            selected = record
            break
    if selected is None:
        raise RenderError(f"Brakuje wybranej rewizji klipu sceny {scene_id}.")
    if selected.get("scene_id") != scene_id or selected.get("qc_status") != "approved":
        raise RenderError(f"Niespójny wybór QC sceny {scene_id}.")
    if selected.get("input_dependency_valid") is False:
        raise RenderError(f"Klip sceny {scene_id} został unieważniony przez zmianę źródła.")
    if selected.get("input_dependency_hash") != scene.get("dependency_hash"):
        raise RenderError(f"Klip sceny {scene_id} nie odpowiada aktualnemu promptowi i źródłu.")
    relative = selected.get("approved_copy_path") or selected.get("path")
    if not isinstance(relative, str):
        raise RenderError(f"Klip sceny {scene_id} nie ma bezpiecznej ścieżki.")
    clip_path = resolve_project_path(project_root, relative, must_exist=True)
    expected_hash = selected.get("sha256")
    if sha256_file(clip_path) != expected_hash:
        raise RenderError(f"Hash zatwierdzonego klipu sceny {scene_id} jest niezgodny.")
    result = dict(selected)
    result["resolved_path"] = clip_path
    return result


def _ordered_inputs(
    project_root: Path, project: Mapping[str, Any]
) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Buduje kompletną sekwencję aktywnych scen bez pomijania braków."""

    plan = project.get("scene_plan")
    scenes = plan.get("scenes") if isinstance(plan, dict) else None
    if not isinstance(scenes, list) or not scenes:
        raise RenderError("Projekt nie ma aktywnego planu scen.")
    ordered = sorted(scenes, key=lambda scene: scene.get("sequence_index", -1))
    expected_indexes = list(range(len(ordered)))
    actual_indexes = [scene.get("sequence_index") for scene in ordered]
    if actual_indexes != expected_indexes:
        raise RenderError("sequence_index musi tworzyć ciąg 0..n-1.")
    result: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for scene in ordered:
        if not isinstance(scene, dict):
            raise RenderError("Plan zawiera niepoprawny rekord sceny.")
        result.append((scene, _approved_clip(project_root, project, scene)))
    return result


def compute_render_dependency_hash(
    project_root: Path,
    project: Mapping[str, Any],
    target: str,
    *,
    fps: int = DEFAULT_FPS,
) -> str:
    """Wiąże render z kolejnością, klipami, strategiami i parametrami kodowania."""

    if target not in TARGETS:
        raise RenderError("Nieznany target renderu.")
    inputs = _ordered_inputs(project_root, project)
    return _canonical_hash(
        {
            "target": target,
            "width": TARGETS[target]["width"],
            "height": TARGETS[target]["height"],
            "fps": fps,
            "codec": "h264",
            "pixel_format": "yuv420p",
            "sample_aspect_ratio": "1:1",
            "transition": "hard_cut",
            "audio": "none",
            "overlays": "none",
            "inputs": [
                {
                    "scene_id": scene["scene_id"],
                    "sequence_index": scene["sequence_index"],
                    "clip_sha256": clip["sha256"],
                    "vertical_strategy": (
                        scene.get("vertical_strategy") if target == "9x16" else "contain"
                    ),
                }
                for scene, clip in inputs
            ],
        }
    )


def _simple_filter(width: int, height: int, strategy: str, fps: int) -> str:
    """Buduje filtr zachowujący proporcje dla contain albo centralnego cropu."""

    if strategy == "contain":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"setsar=1,fps={fps},format=yuv420p"
        )
    if strategy == "anchored_crop":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={width}:{height}:(iw-ow)/2:(ih-oh)/2,"
            f"setsar=1,fps={fps},format=yuv420p"
        )
    raise RenderError("Niepoprawna prosta strategia kadrowania.")


def _normalize_clip(
    source: Path,
    destination: Path,
    *,
    width: int,
    height: int,
    strategy: str,
    fps: int,
) -> None:
    """Normalizuje jeden klip bez rozciągania i bez mapowania audio."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    if strategy in {"contain", "anchored_crop"}:
        run_ffmpeg(
            [
                "-y",
                "-v",
                "error",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-vf",
                _simple_filter(width, height, strategy, fps),
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(fps),
                "-video_track_timescale",
                "90000",
                str(destination),
            ],
            timeout=300,
        )
        return
    if strategy != "padded_background":
        raise RenderError("Nieobsługiwana strategia pionowa.")
    filter_complex = (
        "[0:v]split=2[background][foreground];"
        f"[background]scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={width}:{height},boxblur=20:10[blurred];"
        f"[foreground]scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos[front];"
        f"[blurred][front]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={fps},format=yuv420p[out]"
    )
    run_ffmpeg(
        [
            "-y",
            "-v",
            "error",
            "-i",
            str(source),
            "-filter_complex",
            filter_complex,
            "-map",
            "[out]",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(fps),
            "-video_track_timescale",
            "90000",
            str(destination),
        ],
        timeout=300,
    )


def _ffconcat_escape(path: Path) -> str:
    """Escapuje pojedynczy lokalny path dla demuxera concat."""

    return path.as_posix().replace("'", "'\\''")


def _probe_output(path: Path, width: int, height: int, fps: int) -> Dict[str, Any]:
    """Sprawdza końcowy profil techniczny i brak strumienia audio."""

    probe = ffprobe_json(path)
    streams = probe.get("streams")
    if not isinstance(streams, list):
        raise RenderError("ffprobe nie zwrócił listy strumieni.")
    video_streams = [
        stream
        for stream in streams
        if isinstance(stream, dict) and stream.get("codec_type") == "video"
    ]
    audio_streams = [
        stream
        for stream in streams
        if isinstance(stream, dict) and stream.get("codec_type") == "audio"
    ]
    if len(video_streams) != 1:
        raise RenderError("Render musi zawierać dokładnie jeden strumień obrazu.")
    video = video_streams[0]
    if video.get("codec_name") != "h264":
        raise RenderError("Render nie używa kodeka H.264.")
    if video.get("pix_fmt") != "yuv420p":
        raise RenderError("Render nie używa formatu pikseli yuv420p.")
    if video.get("width") != width or video.get("height") != height:
        raise RenderError("Render ma niepoprawną rozdzielczość.")
    if video.get("sample_aspect_ratio") not in ("1:1", None):
        raise RenderError("Render nie ma SAR 1:1.")
    if audio_streams:
        raise RenderError("Render zawiera automatycznie dodany strumień audio.")
    return {
        "codec_name": video.get("codec_name"),
        "pixel_format": video.get("pix_fmt"),
        "width": video.get("width"),
        "height": video.get("height"),
        "sample_aspect_ratio": video.get("sample_aspect_ratio"),
        "fps": video.get("avg_frame_rate"),
        "audio_stream_count": len(audio_streams),
        "duration_seconds": probe.get("format", {}).get("duration"),
    }


def _render_target(
    project_root: Path,
    project: Mapping[str, Any],
    target: str,
    *,
    fps: int,
) -> Dict[str, Any]:
    """Tworzy jeden target przez normalizację i concat z hard cuts."""

    config = TARGETS[target]
    width = int(config["width"])
    height = int(config["height"])
    inputs = _ordered_inputs(project_root, project)
    final_dir = project_root / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    destination = final_dir / str(config["filename"])
    dependency_hash = compute_render_dependency_hash(
        project_root, project, target, fps=fps
    )

    existing_renders = project.get("output", {}).get("renders", {})
    existing = existing_renders.get(target) if isinstance(existing_renders, dict) else None
    if isinstance(existing, dict) and existing.get("dependency_hash") == dependency_hash:
        existing_path = resolve_project_path(
            project_root, existing.get("path", ""), must_exist=True
        )
        if sha256_file(existing_path) == existing.get("sha256"):
            skipped = dict(existing)
            skipped["skipped_as_current"] = True
            return skipped

    temporary_output = final_dir / (
        f".{destination.stem}.{secrets.token_hex(6)}.tmp.mp4"
    )
    try:
        with tempfile.TemporaryDirectory(prefix="render-", dir=str(final_dir)) as work:
            work_dir = Path(work)
            normalized: List[Path] = []
            for index, (scene, clip) in enumerate(inputs):
                strategy = "contain"
                if target == "9x16":
                    strategy = str(scene.get("vertical_strategy"))
                    if strategy not in VERTICAL_STRATEGIES:
                        raise RenderError(
                            f"Scena {scene.get('scene_id')} wymaga jawnej strategii 9:16."
                        )
                intermediate = work_dir / f"scene-{index:03d}.mp4"
                _normalize_clip(
                    Path(clip["resolved_path"]),
                    intermediate,
                    width=width,
                    height=height,
                    strategy=strategy,
                    fps=fps,
                )
                normalized.append(intermediate)
            concat_path = work_dir / "concat.txt"
            with concat_path.open("w", encoding="utf-8", newline="\n") as handle:
                for path in normalized:
                    handle.write(f"file '{_ffconcat_escape(path)}'\n")
                handle.flush()
                os.fsync(handle.fileno())
            run_ffmpeg(
                [
                    "-y",
                    "-v",
                    "error",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(concat_path),
                    "-map",
                    "0:v:0",
                    "-an",
                    "-c",
                    "copy",
                    "-movflags",
                    "+faststart",
                    str(temporary_output),
                ],
                timeout=300,
            )
        probe_summary = _probe_output(temporary_output, width, height, fps)
        os.replace(temporary_output, destination)
    finally:
        if temporary_output.exists():
            temporary_output.unlink()
    return {
        "path": destination.relative_to(project_root).as_posix(),
        "sha256": sha256_file(destination),
        "dependency_hash": dependency_hash,
        "target": target,
        "transition": "hard_cut",
        "audio_added": False,
        "pii_overlays_added": False,
        "probe": probe_summary,
        "rendered_at": utc_now(),
        "skipped_as_current": False,
    }


@locked_project_mutation
def render_walkthrough(
    project_root: Path,
    *,
    include_vertical: bool = False,
    fps: int = DEFAULT_FPS,
) -> Dict[str, Any]:
    """Renderuje obowiązkowe 16:9 i opcjonalne 9:16 bez stretchu."""

    if isinstance(fps, bool) or not isinstance(fps, int) or not 1 <= fps <= 60:
        raise RenderError("FPS musi być liczbą całkowitą od 1 do 60.")
    root = validate_project_root(project_root)
    project = load_json(root / "project.json")
    if not isinstance(project, dict):
        raise RenderError("project.json musi być obiektem JSON.")
    targets = ["16x9", "9x16"] if include_vertical else ["16x9"]
    results: Dict[str, Dict[str, Any]] = {}
    for target in targets:
        results[target] = _render_target(root, project, target, fps=fps)

    output = project.setdefault("output", {})
    if not isinstance(output, dict):
        raise RenderError("Pole output musi być obiektem.")
    renders = output.setdefault("renders", {})
    if not isinstance(renders, dict):
        raise RenderError("Pole output.renders musi być obiektem.")
    renders.update(results)
    output["render_status"] = "complete"
    output["invalidated_scene_ids"] = []
    output["audio_added"] = False
    output["pii_overlays_added"] = False
    hashes = project.setdefault("hashes", {})
    if not isinstance(hashes, dict):
        raise RenderError("Pole hashes musi być obiektem.")
    for result in results.values():
        hashes[result["path"]] = result["sha256"]
    stages = project.setdefault("stages", {})
    if not isinstance(stages, dict):
        raise RenderError("Pole stages musi być obiektem.")
    stages["rendering"] = "complete"
    project["manifest_revision"] = int(project.get("manifest_revision", 0)) + 1
    timestamps = project.setdefault("timestamps", {})
    if isinstance(timestamps, dict):
        timestamps["updated_at"] = utc_now()
    atomic_write_json(root / "project.json", project)
    return {
        "targets": results,
        "hard_cuts": True,
        "audio_added": False,
        "pii_overlays_added": False,
        "provider_calls": 0,
    }


def build_parser() -> argparse.ArgumentParser:
    """Buduje parser deterministycznego renderu lokalnego."""

    parser = PolishArgumentParser(
        description="Renderuje filmową prezentację H.264/yuv420p/SAR 1:1 z cięciami bez przejść."
    )
    parser.add_argument("--project", required=True, type=Path, help="Katalog projektu.")
    parser.add_argument(
        "--vertical",
        action="store_true",
        help="Utwórz dodatkowo wariant 1080x1920 według strategii scen.",
    )
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS, help="Stały FPS 1-60.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Uruchamia lokalny render i wypisuje raport JSON."""

    args = build_parser().parse_args(argv)
    try:
        report = render_walkthrough(
            args.project,
            include_vertical=args.vertical,
            fps=args.fps,
        )
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    except (MediaError, OSError, RenderError, ValueError) as error:
        print(f"Błąd renderowania walkthrough: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
