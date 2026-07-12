#!/usr/bin/env python3
"""Waliduje integralność projektu i wyznacza bezpieczny punkt wznowienia."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set

from _common import (
    PolishArgumentParser,
    load_json,
    resolve_project_path,
    sha256_file,
    utc_now,
    validate_project_root,
)
from _schema import DocumentValidationError, load_schema, validate_document
from render_walkthrough import RenderError, compute_render_dependency_hash


PROJECT_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "assets" / "project.schema.json"
STAGE_ORDER = (
    "curation",
    "scene_planning",
    "prompts",
    "generation_package",
    "clip_import",
    "quality_control",
    "rendering",
)


class OutputValidationError(ValueError):
    """Oznacza, że nie można bezpiecznie określić stanu wznowienia."""


def _tracked_hash_errors(project_root: Path, project: Mapping[str, Any]) -> List[str]:
    """Sprawdza wszystkie ścieżki i hashe zapisane w źródle prawdy."""

    errors: List[str] = []
    hashes = project.get("hashes")
    if not isinstance(hashes, dict):
        return ["Pole hashes nie jest obiektem."]
    for relative_path, expected_hash in sorted(hashes.items()):
        try:
            path = resolve_project_path(project_root, relative_path, must_exist=True)
            actual_hash = sha256_file(path)
        except (OSError, ValueError) as error:
            errors.append(f"Brak albo niebezpieczna ścieżka {relative_path}: {error}")
            continue
        if actual_hash != expected_hash:
            errors.append(f"Niezgodny hash pliku {relative_path}.")
    return errors


def _scene_map(project: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Indeksuje aktywne sceny z zachowaniem nieprzezroczystych ID."""

    plan = project.get("scene_plan")
    scenes = plan.get("scenes") if isinstance(plan, dict) else []
    return {
        str(scene["scene_id"]): scene
        for scene in scenes
        if isinstance(scene, dict) and isinstance(scene.get("scene_id"), str)
    }


def _clip_map(project: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Indeksuje klipy po clip_id, nie po zmiennej kolejności listy."""

    clips = project.get("clips")
    if not isinstance(clips, list):
        return {}
    return {
        str(clip["clip_id"]): clip
        for clip in clips
        if isinstance(clip, dict) and isinstance(clip.get("clip_id"), str)
    }


def _approved_integrity(
    project_root: Path,
    project: Mapping[str, Any],
) -> Dict[str, Any]:
    """Sprawdza zatwierdzone rewizje bez modyfikowania lub odrzucania historii."""

    scenes = _scene_map(project)
    clips = _clip_map(project)
    qc = project.get("qc") if isinstance(project.get("qc"), dict) else {}
    valid_scene_ids: List[str] = []
    invalidated_scene_ids: List[str] = []
    errors: List[str] = []
    preserved_hashes: Dict[str, str] = {}
    for scene_id, scene in scenes.items():
        selection = qc.get(scene_id) if isinstance(qc, dict) else None
        if not isinstance(selection, dict) or selection.get("status") != "approved":
            invalidated_scene_ids.append(scene_id)
            continue
        clip = clips.get(str(selection.get("selected_clip_id")))
        if not isinstance(clip, dict):
            invalidated_scene_ids.append(scene_id)
            errors.append(f"Scena {scene_id} wskazuje brakującą rewizję klipu.")
            continue
        relative_path = clip.get("approved_copy_path") or clip.get("path")
        try:
            path = resolve_project_path(project_root, relative_path, must_exist=True)
            actual_hash = sha256_file(path)
        except (OSError, ValueError) as error:
            invalidated_scene_ids.append(scene_id)
            errors.append(f"Nie można sprawdzić klipu sceny {scene_id}: {error}")
            continue
        if actual_hash != clip.get("sha256") or actual_hash != selection.get("selected_sha256"):
            invalidated_scene_ids.append(scene_id)
            errors.append(f"Hash zaakceptowanego klipu sceny {scene_id} jest niezgodny.")
            continue
        if clip.get("input_dependency_valid") is False:
            invalidated_scene_ids.append(scene_id)
            continue
        if clip.get("input_dependency_hash") != scene.get("dependency_hash"):
            invalidated_scene_ids.append(scene_id)
            continue
        valid_scene_ids.append(scene_id)
        preserved_hashes[scene_id] = actual_hash
    return {
        "valid_scene_ids": sorted(valid_scene_ids),
        "invalidated_scene_ids": sorted(invalidated_scene_ids),
        "errors": errors,
        "preserved_approved_hashes": preserved_hashes,
    }


def _job_reconciliation(project: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Wyznacza jawne akcje bez automatycznego submission albo resubmitu."""

    actions: List[Dict[str, Any]] = []
    jobs = project.get("jobs")
    if not isinstance(jobs, list):
        return actions
    for job in jobs:
        if not isinstance(job, dict):
            continue
        status = job.get("status")
        job_id = job.get("job_id")
        if status in {"submitted", "queued", "running"} and job_id:
            action = "poll_existing"
        elif status == "submission_pending":
            action = "reconcile_manually"
        elif status in {"failed", "rejected"}:
            action = "retry_requires_new_consent"
        elif status == "completed":
            action = "import_result_if_available"
        else:
            action = "manual_review"
        actions.append(
            {
                "scene_id": job.get("scene_id"),
                "job_id": job_id,
                "status": status,
                "action": action,
                "automatic_submission_allowed": False,
            }
        )
    return actions


def _render_integrity(
    project_root: Path,
    project: Mapping[str, Any],
) -> Dict[str, Any]:
    """Porównuje pliki renderów z hashami ich aktualnych zależności."""

    output = project.get("output")
    renders = output.get("renders") if isinstance(output, dict) else None
    if not isinstance(renders, dict):
        return {"valid_targets": [], "stale_targets": ["16x9"], "errors": []}
    valid_targets: List[str] = []
    stale_targets: List[str] = []
    errors: List[str] = []
    for target, record in sorted(renders.items()):
        if target not in {"16x9", "9x16"} or not isinstance(record, dict):
            continue
        try:
            path = resolve_project_path(project_root, record.get("path", ""), must_exist=True)
            if sha256_file(path) != record.get("sha256"):
                raise OutputValidationError("hash pliku jest niezgodny")
            expected_dependency = compute_render_dependency_hash(
                project_root, project, target
            )
            if record.get("dependency_hash") != expected_dependency:
                stale_targets.append(target)
            else:
                valid_targets.append(target)
        except (OSError, OutputValidationError, RenderError, ValueError) as error:
            stale_targets.append(target)
            errors.append(f"Render {target}: {error}")
    if "16x9" not in valid_targets and "16x9" not in stale_targets:
        stale_targets.append("16x9")
    return {
        "valid_targets": sorted(set(valid_targets)),
        "stale_targets": sorted(set(stale_targets)),
        "errors": errors,
    }


def _first_incomplete_stage(
    project_root: Path,
    project: Mapping[str, Any],
    approved: Mapping[str, Any],
    renders: Mapping[str, Any],
) -> str:
    """Znajduje pierwszy konieczny etap, zachowując poprawne wcześniejsze wyniki."""

    selected_images = project.get("selected_images")
    if not isinstance(selected_images, list) or not selected_images:
        return "curation"
    scenes = _scene_map(project)
    if not scenes:
        return "scene_planning"
    prompts = project.get("prompts")
    if not isinstance(prompts, dict) or prompts.get("status") != "complete":
        return "prompts"
    if not (project_root / "generation-package" / "generation-manifest.json").is_file():
        return "generation_package"
    clips = project.get("clips")
    imported_scene_ids = {
        clip.get("scene_id")
        for clip in clips
        if isinstance(clip, dict)
    } if isinstance(clips, list) else set()
    if not set(scenes).issubset(imported_scene_ids):
        return "clip_import"
    if set(approved.get("valid_scene_ids", [])) != set(scenes):
        return "quality_control"
    if "16x9" not in renders.get("valid_targets", []):
        return "rendering"
    return "complete"


def analyze_resume(project_root: Path) -> Dict[str, Any]:
    """Tworzy idempotentny raport resume bez provider calls i bez mutation stanu."""

    root = validate_project_root(project_root)
    project_path = root / "project.json"
    if not project_path.is_file():
        raise OutputValidationError("Brakuje project.json; plik tymczasowy nie jest źródłem prawdy.")
    project = load_json(project_path)
    if not isinstance(project, dict):
        raise OutputValidationError("project.json musi być obiektem JSON.")

    errors: List[str] = []
    try:
        validate_document(
            project,
            load_schema(PROJECT_SCHEMA_PATH),
            semantic_kind="project",
            project_root=root,
        )
    except DocumentValidationError as error:
        errors.append(str(error))
    tracked_errors = _tracked_hash_errors(root, project)
    errors.extend(error for error in tracked_errors if error not in errors)
    approved = _approved_integrity(root, project)
    errors.extend(error for error in approved["errors"] if error not in errors)
    renders = _render_integrity(root, project)
    errors.extend(error for error in renders["errors"] if error not in errors)
    first_stage = _first_incomplete_stage(root, project, approved, renders)
    first_index = STAGE_ORDER.index(first_stage) if first_stage in STAGE_ORDER else len(STAGE_ORDER)
    preserved_stages = list(STAGE_ORDER[:first_index])
    if first_stage == "quality_control":
        preserved_stages.append("quality_control_for_approved_scenes")

    report = {
        "schema_version": 1,
        "project_id": project.get("project_id"),
        "checked_at": utc_now(),
        "valid": not errors,
        "errors": errors,
        "warnings": [],
        "first_incomplete_stage": first_stage,
        "preserved_stages": preserved_stages,
        "invalidated_scene_ids": approved["invalidated_scene_ids"],
        "valid_approved_scene_ids": approved["valid_scene_ids"],
        "preserved_approved_hashes": approved["preserved_approved_hashes"],
        "render_validation": renders,
        "job_actions": _job_reconciliation(project),
        "new_submission_requires_fresh_consent": True,
        "automatic_submission_allowed": False,
        "provider_calls": 0,
    }
    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    from _common import atomic_write_json

    atomic_write_json(reports_dir / "resume-validation.json", report)
    return report


def build_parser() -> argparse.ArgumentParser:
    """Buduje parser walidacji outputu i wznowienia."""

    parser = PolishArgumentParser(
        description="Waliduje project.json, skróty plików, zaakceptowane klipy, zadania i zależności renderu."
    )
    parser.add_argument("--project", required=True, type=Path, help="Katalog projektu.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Uruchamia analizę resume i wypisuje raport JSON."""

    args = build_parser().parse_args(argv)
    try:
        report = analyze_resume(args.project)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0 if report["valid"] else 3
    except (OSError, OutputValidationError, ValueError) as error:
        print(f"Błąd walidacji projektu: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
