#!/usr/bin/env python3
"""Importuje klipy append-only, zbiera ffprobe i zapisuje audytowalny QC."""

from __future__ import annotations

import argparse
import json
import math
import os
import secrets
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

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


QC_STATUSES = ("approved", "regenerate", "rejected", "needs-manual-review")
CRITICAL_ISSUES = {
    "bent_walls",
    "decode_error",
    "disappearing_objects",
    "distorted_windows",
    "duplicates",
    "geometry_drift",
    "impossible_reveal",
    "morphing",
    "new_geometry",
    "scene_replacement",
}
MAX_CLIP_BYTES = 2 * 1024 * 1024 * 1024


class ClipImportError(ValueError):
    """Oznacza błąd importu, integralności lub kontroli jakości klipu."""


def _float_value(value: Any) -> Optional[float]:
    """Konwertuje skończoną wartość liczbową ffprobe albo zwraca None."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _rational_value(value: Any) -> Optional[float]:
    """Odczytuje liczbę albo ułamek zapisany przez ffprobe."""

    if isinstance(value, str) and "/" in value:
        numerator, denominator = value.split("/", 1)
        top = _float_value(numerator)
        bottom = _float_value(denominator)
        if top is None or bottom in (None, 0):
            return None
        return top / bottom
    return _float_value(value)


def _scene_by_id(project: Mapping[str, Any], scene_id: str) -> Dict[str, Any]:
    """Zwraca aktywną scenę albo zatrzymuje import tombstone'a."""

    plan = project.get("scene_plan")
    if not isinstance(plan, dict):
        raise ClipImportError("Projekt nie ma planu scen.")
    tombstones = plan.get("tombstones", [])
    if any(
        isinstance(item, dict) and item.get("scene_id") == scene_id
        for item in tombstones
    ):
        raise ClipImportError("Nie można importować klipu do usuniętej sceny tombstone.")
    for scene in plan.get("scenes", []):
        if isinstance(scene, dict) and scene.get("scene_id") == scene_id:
            return scene
    raise ClipImportError(f"Nie znaleziono aktywnej sceny {scene_id}.")


def _expected_filename(project_root: Path, scene_id: str) -> str:
    """Odczytuje oczekiwaną nazwę z pakietu manualnego."""

    manifest_path = project_root / "generation-package" / "generation-manifest.json"
    if not manifest_path.exists():
        return f"{scene_id}.mp4"
    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict):
        raise ClipImportError("Manifest generacyjny ma niepoprawny format.")
    for entry in manifest.get("entries", []):
        if isinstance(entry, dict) and entry.get("scene_id") == scene_id:
            expected = entry.get("expected_filename")
            if isinstance(expected, str) and expected:
                return expected
    return f"{scene_id}.mp4"


def _probe_summary(probe: Mapping[str, Any]) -> Dict[str, Any]:
    """Redukuje wynik ffprobe do stabilnych pól technicznych."""

    streams = probe.get("streams")
    if not isinstance(streams, list):
        streams = []
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
    video = video_streams[0] if video_streams else {}
    format_data = probe.get("format") if isinstance(probe.get("format"), dict) else {}
    duration = _float_value(format_data.get("duration"))
    if duration is None:
        duration = _float_value(video.get("duration"))
    return {
        "duration_seconds": duration,
        "width": video.get("width"),
        "height": video.get("height"),
        "sample_aspect_ratio": video.get("sample_aspect_ratio"),
        "average_fps": _rational_value(video.get("avg_frame_rate")),
        "codec_name": video.get("codec_name"),
        "pixel_format": video.get("pix_fmt"),
        "video_stream_count": len(video_streams),
        "audio_stream_count": len(audio_streams),
        "format_name": format_data.get("format_name"),
    }


def _technical_issues(scene: Mapping[str, Any], summary: Mapping[str, Any]) -> List[str]:
    """Wykrywa techniczne rozbieżności bez udawania wizualnego CV."""

    issues: List[str] = []
    if summary.get("video_stream_count") != 1:
        issues.append("video_stream_count")
    duration = summary.get("duration_seconds")
    expected_duration = _float_value(scene.get("duration_seconds"))
    if duration is None or duration <= 0:
        issues.append("duration_missing")
    elif expected_duration is not None:
        tolerance = max(0.6, expected_duration * 0.15)
        if abs(duration - expected_duration) > tolerance:
            issues.append("duration_mismatch")
    width = summary.get("width")
    height = summary.get("height")
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        issues.append("resolution_missing")
    else:
        expected_ratio = scene.get("aspect_ratio")
        target = 16 / 9 if expected_ratio == "16:9" else 9 / 16
        if abs((width / height) - target) > 0.04:
            issues.append("aspect_ratio_mismatch")
    sar = summary.get("sample_aspect_ratio")
    if sar not in (None, "1:1", "N/A"):
        issues.append("non_square_pixels")
    return issues


def _sample_timestamps(duration: float) -> List[float]:
    """Wyznacza próbki 0/25/50/75/100% bez żądania klatki poza końcem."""

    end = max(0.0, duration - min(0.04, duration / 10))
    return [0.0, duration * 0.25, duration * 0.5, duration * 0.75, end]


def _extract_sample_frames(
    clip_path: Path,
    destination_dir: Path,
    duration: float,
) -> List[str]:
    """Tworzy pięć lokalnych próbek bez metadanych i bez sieci."""

    destination_dir.mkdir(parents=True, exist_ok=True)
    generated: List[str] = []
    for label, timestamp in zip((0, 25, 50, 75, 100), _sample_timestamps(duration)):
        destination = destination_dir / f"sample-{label:03d}.jpg"
        temporary = destination.with_name(
            f".{destination.stem}.{secrets.token_hex(5)}.tmp.jpg"
        )
        try:
            run_ffmpeg(
                [
                    "-y",
                    "-v",
                    "error",
                    "-ss",
                    f"{timestamp:.6f}",
                    "-i",
                    str(clip_path),
                    "-map",
                    "0:v:0",
                    "-frames:v",
                    "1",
                    "-map_metadata",
                    "-1",
                    "-q:v",
                    "2",
                    str(temporary),
                ],
                timeout=60,
            )
            if not temporary.is_file() or temporary.stat().st_size == 0:
                raise ClipImportError("Nie udało się utworzyć klatki próbnej.")
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()
        generated.append(destination.as_posix())
    return generated


def _copy_clip_append_only(source: Path, destination: Path, expected_hash: str) -> None:
    """Publikuje nową rewizję bez nadpisywania istniejącego pliku."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha256_file(destination) != expected_hash:
            raise ClipImportError("Kolizja ścieżki rewizji z inną zawartością.")
        return
    temporary = destination.with_name(f".{destination.name}.{secrets.token_hex(6)}.tmp")
    try:
        with source.open("rb") as source_handle, temporary.open("xb") as target_handle:
            shutil.copyfileobj(source_handle, target_handle)
            target_handle.flush()
            os.fsync(target_handle.fileno())
        if sha256_file(temporary) != expected_hash:
            raise ClipImportError("Hash skopiowanego klipu nie zgadza się ze źródłem.")
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if sha256_file(destination) != expected_hash:
                raise ClipImportError("Inny proces opublikował sprzeczną rewizję.")
        temporary.unlink()
    finally:
        if temporary.exists():
            temporary.unlink()


@locked_project_mutation
def import_clip(
    project_root: Path,
    scene_id: str,
    clip_path: Path,
    *,
    provider_name: Optional[str] = None,
    model_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Importuje jedną rewizję i zachowuje wszystkie poprzednie rewizje."""

    root = validate_project_root(project_root)
    source = clip_path.expanduser().resolve(strict=True)
    if source.is_symlink() or not source.is_file():
        raise ClipImportError("Klip wejściowy musi być zwykłym plikiem.")
    if source.stat().st_size <= 0 or source.stat().st_size > MAX_CLIP_BYTES:
        raise ClipImportError("Rozmiar klipu jest pusty albo przekracza limit 2 GiB.")
    expected_filename = _expected_filename(root, scene_id)
    if source.name != expected_filename:
        raise ClipImportError(
            f"Oczekiwano pliku {expected_filename}, otrzymano {source.name}."
        )

    project = load_json(root / "project.json")
    if not isinstance(project, dict):
        raise ClipImportError("project.json musi być obiektem JSON.")
    scene = _scene_by_id(project, scene_id)
    clip_hash = sha256_file(source)
    clips = project.get("clips")
    if not isinstance(clips, list):
        raise ClipImportError("Pole clips musi być listą rewizji.")
    for existing in clips:
        if (
            isinstance(existing, dict)
            and existing.get("scene_id") == scene_id
            and existing.get("sha256") == clip_hash
        ):
            return dict(existing)

    revisions = [
        int(item.get("revision", 0))
        for item in clips
        if isinstance(item, dict)
        and item.get("scene_id") == scene_id
        and isinstance(item.get("revision"), int)
    ]
    revision = max(revisions, default=0) + 1
    suffix = source.suffix.lower()
    if suffix not in {".mp4", ".mov", ".mkv", ".webm"}:
        raise ClipImportError("Nieobsługiwane rozszerzenie klipu.")
    destination = root / "scenes" / "imported" / scene_id / (
        f"rev-{revision:03d}-{clip_hash[:12]}{suffix}"
    )
    _copy_clip_append_only(source, destination, clip_hash)

    probe = ffprobe_json(destination)
    summary = _probe_summary(probe)
    issues = _technical_issues(scene, summary)
    duration = summary.get("duration_seconds")
    sample_paths: List[str] = []
    if isinstance(duration, (int, float)) and duration > 0 and summary.get("video_stream_count"):
        samples_dir = root / "reports" / "qc" / scene_id / f"rev-{revision:03d}" / "frames"
        absolute_samples = _extract_sample_frames(destination, samples_dir, float(duration))
        sample_paths = [
            Path(path).relative_to(root).as_posix() for path in absolute_samples
        ]
    else:
        issues.append("sample_frames_unavailable")

    fatal = any(
        issue in {"video_stream_count", "duration_missing", "resolution_missing", "sample_frames_unavailable"}
        for issue in issues
    )
    record: Dict[str, Any] = {
        "clip_id": f"clp_{secrets.token_hex(10)}",
        "scene_id": scene_id,
        "revision": revision,
        "path": destination.relative_to(root).as_posix(),
        "sha256": clip_hash,
        "size_bytes": destination.stat().st_size,
        "expected_filename": expected_filename,
        "provider_name": provider_name,
        "model_id": model_id,
        "input_dependency_hash": scene.get("dependency_hash"),
        "input_dependency_valid": True,
        "technical_status": "failed" if fatal else "passed" if not issues else "needs-manual-review",
        "technical_issues": sorted(set(issues)),
        "probe_summary": summary,
        "sample_frames": sample_paths,
        "qc_status": "rejected" if fatal else "needs-manual-review",
        "qc_issues": [],
        "imported_at": utc_now(),
        "approved_at": None,
    }
    clips.append(record)
    hashes = project.setdefault("hashes", {})
    if not isinstance(hashes, dict):
        raise ClipImportError("Pole hashes musi być obiektem.")
    hashes[record["path"]] = clip_hash
    stages = project.setdefault("stages", {})
    if not isinstance(stages, dict):
        raise ClipImportError("Pole stages musi być obiektem.")
    stages["clip_import"] = "complete"
    stages["quality_control"] = "pending"
    project["manifest_revision"] = int(project.get("manifest_revision", 0)) + 1
    timestamps = project.setdefault("timestamps", {})
    if isinstance(timestamps, dict):
        timestamps["updated_at"] = utc_now()

    technical_report = {
        "schema_version": 1,
        "scene_id": scene_id,
        "clip_id": record["clip_id"],
        "revision": revision,
        "source_image_id": scene.get("source_image_id"),
        "source_path": scene.get("source_path"),
        "clip_path": record["path"],
        "clip_sha256": clip_hash,
        "technical_status": record["technical_status"],
        "technical_issues": record["technical_issues"],
        "probe_summary": summary,
        "sample_frames": sample_paths,
        "visual_comparison_required": True,
        "created_at": utc_now(),
    }
    report_path = root / "reports" / "qc" / scene_id / f"rev-{revision:03d}" / "technical.json"
    atomic_write_json(report_path, technical_report)
    atomic_write_json(root / "project.json", project)
    return record


def _find_clip_record(
    clips: Iterable[Any], scene_id: str, revision: int
) -> Dict[str, Any]:
    """Znajduje dokładną rewizję bez domyślnego wyboru najnowszej."""

    for record in clips:
        if (
            isinstance(record, dict)
            and record.get("scene_id") == scene_id
            and record.get("revision") == revision
        ):
            return record
    raise ClipImportError("Nie znaleziono wskazanej rewizji klipu.")


def _publish_approved_copy(project_root: Path, record: Mapping[str, Any]) -> str:
    """Publikuje kopię zatwierdzonej rewizji bez nadpisywania starszych plików."""

    source = resolve_project_path(project_root, record["path"], must_exist=True)
    suffix = source.suffix.lower()
    destination = project_root / "scenes" / "approved" / str(record["scene_id"]) / (
        f"rev-{int(record['revision']):03d}-{str(record['sha256'])[:12]}{suffix}"
    )
    _copy_clip_append_only(source, destination, str(record["sha256"]))
    return destination.relative_to(project_root).as_posix()


@locked_project_mutation
def record_quality_control(
    project_root: Path,
    scene_id: str,
    revision: int,
    status: str,
    *,
    issues: Optional[Sequence[str]] = None,
    notes_pl: str = "",
    source_comparison_performed: bool = False,
    comparison_evidence_pl: str = "",
) -> Dict[str, Any]:
    """Zapisuje ręczny QC i blokuje akceptację krytycznych błędów geometrii."""

    if status not in QC_STATUSES:
        raise ClipImportError("Niepoprawny status kontroli jakości.")
    if not isinstance(source_comparison_performed, bool):
        raise ClipImportError("Informacja o porównaniu ze źródłem musi być wartością logiczną.")
    if source_comparison_performed and not comparison_evidence_pl.strip():
        raise ClipImportError(
            "Wykonane porównanie ze źródłem wymaga krótkiego opisu dowodu."
        )
    normalized_issues = sorted(
        {str(issue).strip() for issue in (issues or []) if str(issue).strip()}
    )
    critical = sorted(set(normalized_issues).intersection(CRITICAL_ISSUES))
    root = validate_project_root(project_root)
    project = load_json(root / "project.json")
    if not isinstance(project, dict) or not isinstance(project.get("clips"), list):
        raise ClipImportError("Projekt nie ma listy klipów.")
    record = _find_clip_record(project["clips"], scene_id, revision)
    qc = project.setdefault("qc", {})
    if not isinstance(qc, dict):
        raise ClipImportError("Pole qc musi być obiektem.")
    previous_selection = qc.get(scene_id)
    previous_approved_clip_id = (
        previous_selection.get("selected_clip_id")
        if isinstance(previous_selection, dict)
        and previous_selection.get("status") == "approved"
        else None
    )
    selection_changed = False
    selection_revoked = False
    if status == "approved":
        if record.get("technical_status") == "failed":
            raise ClipImportError("Nie można zaakceptować klipu z krytycznym błędem technicznym.")
        if critical:
            raise ClipImportError(
                "Krytyczne błędy geometrii blokują approved: " + ", ".join(critical)
            )
        clip_path = resolve_project_path(root, record["path"], must_exist=True)
        if sha256_file(clip_path) != record.get("sha256"):
            raise ClipImportError("Klip zmienił się od importu i nie może zostać zaakceptowany.")
        approved_path = _publish_approved_copy(root, record)
        record["approved_copy_path"] = approved_path
        record["approved_at"] = utc_now()
        hashes = project.setdefault("hashes", {})
        if isinstance(hashes, dict):
            hashes[approved_path] = record["sha256"]
        selection_changed = previous_approved_clip_id != record["clip_id"]
    elif previous_approved_clip_id == record["clip_id"]:
        # Jawna zmiana statusu aktywnej rewizji unieważnia jej wybór. Status
        # kandydata innej rewizji nie może natomiast odebrać poprzedniej,
        # nadal zaakceptowanej selekcji.
        selection_revoked = True

    record["qc_status"] = status
    record["qc_issues"] = normalized_issues
    record["qc_notes_pl"] = notes_pl
    record["source_comparison_performed"] = source_comparison_performed
    record["comparison_evidence_pl"] = comparison_evidence_pl.strip()
    record["qc_reviewed_at"] = utc_now()
    if status == "approved":
        qc[scene_id] = {
            "status": "approved",
            "selected_clip_id": record["clip_id"],
            "selected_revision": revision,
            "selected_sha256": record["sha256"],
            "input_dependency_hash": record.get("input_dependency_hash"),
            "source_comparison_performed": source_comparison_performed,
            "comparison_evidence_pl": comparison_evidence_pl.strip(),
            "reviewed_at": utc_now(),
        }
    elif (
        isinstance(previous_selection, dict)
        and previous_selection.get("status") == "approved"
        and previous_approved_clip_id != record["clip_id"]
    ):
        preserved_selection = dict(previous_selection)
        preserved_selection.update(
            {
                "candidate_status": status,
                "candidate_clip_id": record["clip_id"],
                "candidate_revision": revision,
                "candidate_sha256": record["sha256"],
                "candidate_issues": normalized_issues,
                "candidate_reviewed_at": record["qc_reviewed_at"],
            }
        )
        qc[scene_id] = preserved_selection
    else:
        qc[scene_id] = {
            "status": status,
            "candidate_clip_id": record["clip_id"],
            "candidate_revision": revision,
            "reviewed_at": utc_now(),
        }

    if selection_changed or selection_revoked:
        output = project.setdefault("output", {})
        if isinstance(output, dict):
            output["render_status"] = "invalidated"
            invalidated = output.setdefault("invalidated_scene_ids", [])
            if isinstance(invalidated, list) and scene_id not in invalidated:
                invalidated.append(scene_id)

    active_scene_ids = {
        scene.get("scene_id")
        for scene in project.get("scene_plan", {}).get("scenes", [])
        if isinstance(scene, dict)
    }
    approved_scene_ids = {
        scene_key
        for scene_key, value in qc.items()
        if isinstance(value, dict)
        and value.get("status") == "approved"
        and value.get("source_comparison_performed") is True
    }
    stages = project.setdefault("stages", {})
    if isinstance(stages, dict):
        stages["quality_control"] = (
            "complete" if active_scene_ids and active_scene_ids <= approved_scene_ids else "pending"
        )
        if selection_changed or selection_revoked:
            stages["rendering"] = "invalidated"
    project["manifest_revision"] = int(project.get("manifest_revision", 0)) + 1
    timestamps = project.setdefault("timestamps", {})
    if isinstance(timestamps, dict):
        timestamps["updated_at"] = utc_now()

    report = {
        "schema_version": 1,
        "scene_id": scene_id,
        "clip_id": record["clip_id"],
        "revision": revision,
        "status": status,
        "issues": normalized_issues,
        "critical_issues": critical,
        "notes_pl": notes_pl,
        "source_comparison_performed": source_comparison_performed,
        "comparison_evidence_pl": comparison_evidence_pl.strip(),
        "reviewed_at": record["qc_reviewed_at"],
    }
    report_path = root / "reports" / "qc" / scene_id / f"rev-{revision:03d}" / "review.json"
    atomic_write_json(report_path, report)
    atomic_write_json(root / "project.json", project)
    return report


def import_expected_clips(
    project_root: Path,
    clips_directory: Path,
) -> List[Dict[str, Any]]:
    """Importuje wszystkie oczekiwane pliki z katalogu bez zgadywania nazw."""

    root = validate_project_root(project_root)
    project = load_json(root / "project.json")
    if not isinstance(project, dict):
        raise ClipImportError("project.json musi być obiektem JSON.")
    directory = clips_directory.expanduser().resolve(strict=True)
    if not directory.is_dir() or directory.is_symlink():
        raise ClipImportError("Katalog klipów musi być zwykłym katalogiem.")
    results: List[Dict[str, Any]] = []
    scenes = project.get("scene_plan", {}).get("scenes", [])
    for scene in sorted(scenes, key=lambda item: item.get("sequence_index", 0)):
        if not isinstance(scene, dict):
            continue
        scene_id = str(scene.get("scene_id"))
        expected = directory / _expected_filename(root, scene_id)
        if not expected.is_file():
            raise ClipImportError(f"Brakuje oczekiwanego klipu {expected.name}.")
        results.append(import_clip(root, scene_id, expected))
    return results


def build_parser() -> argparse.ArgumentParser:
    """Buduje parser importu i ręcznego QC."""

    parser = PolishArgumentParser(
        description="Importuje klipy bez nadpisywania wcześniejszych rewizji, uruchamia ffprobe i zapisuje kontrolę jakości."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    import_command = subparsers.add_parser("import", help="Importuj jedną rewizję klipu.")
    import_command.add_argument("--project", required=True, type=Path)
    import_command.add_argument("--scene-id", required=True)
    import_command.add_argument("--clip", required=True, type=Path)
    import_command.add_argument("--provider-name")
    import_command.add_argument("--model-id")

    import_all = subparsers.add_parser("import-all", help="Importuj komplet oczekiwanych nazw.")
    import_all.add_argument("--project", required=True, type=Path)
    import_all.add_argument("--clips-directory", required=True, type=Path)

    qc_command = subparsers.add_parser("qc", help="Zapisz ręczny status kontroli jakości.")
    qc_command.add_argument("--project", required=True, type=Path)
    qc_command.add_argument("--scene-id", required=True)
    qc_command.add_argument("--revision", required=True, type=int)
    qc_command.add_argument("--status", required=True, choices=QC_STATUSES)
    qc_command.add_argument("--issue", action="append", default=[])
    qc_command.add_argument("--notes", default="")
    qc_command.add_argument(
        "--source-comparison-performed",
        action="store_true",
        help="Potwierdź wykonanie porównania klipu ze zdjęciem źródłowym.",
    )
    qc_command.add_argument(
        "--comparison-evidence",
        default="",
        help="Krótki opis dowodu porównania ze źródłem.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Uruchamia import albo QC i zwraca raport JSON."""

    args = build_parser().parse_args(argv)
    try:
        if args.command == "import":
            result: Any = import_clip(
                args.project,
                args.scene_id,
                args.clip,
                provider_name=args.provider_name,
                model_id=args.model_id,
            )
        elif args.command == "import-all":
            result = import_expected_clips(args.project, args.clips_directory)
        else:
            result = record_quality_control(
                args.project,
                args.scene_id,
                args.revision,
                args.status,
                issues=args.issue,
                notes_pl=args.notes,
                source_comparison_performed=args.source_comparison_performed,
                comparison_evidence_pl=args.comparison_evidence,
            )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (ClipImportError, MediaError, OSError, ValueError) as error:
        print(f"Błąd importu lub kontroli jakości: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
