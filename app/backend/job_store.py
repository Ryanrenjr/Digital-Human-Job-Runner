from __future__ import annotations

import json
import logging
import os
import re
import shutil
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from database import delete_job as db_delete_job
from database import (
    get_job,
    list_jobs as db_list_jobs,
    patch_job_if_run_matches as db_patch_job_if_run_matches,
    update_job_if_run_matches,
    upsert_job,
)
from job_states import ACTIVE_STATUSES
from settings import DEFAULT_VOICE_ID, JOBS_DIR, WINDOWS_OUTPUT_DIR

if TYPE_CHECKING:
    from schemas import JobCreateRequest

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _job_path(job_id: str) -> Path:
    return JOBS_DIR / job_id / "job.json"


def _write_json_mirror(job: dict) -> None:
    p = _job_path(job["job_id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    temp = p.with_suffix(".json.tmp")
    temp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(p)


def migrate_legacy_jobs() -> None:
    """Import old job.json files once, without replacing newer SQLite rows."""
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    known = {job.get("job_id") for job in db_list_jobs()}
    for job_json in JOBS_DIR.glob("*/job.json"):
        try:
            job = json.loads(job_json.read_text(encoding="utf-8"))
            if job.get("job_id") and job["job_id"] not in known:
                upsert_job(job)
                known.add(job["job_id"])
        except Exception as exc:
            logger.warning("Skipping legacy job.json: %s — %s", job_json, exc)


def load_job(job_id: str) -> Optional[dict]:
    return get_job(job_id)


def save_job(
    job: dict,
    expected_run_id: str | None = None,
    allowed_statuses: set[str] | frozenset[str] | None = None,
) -> bool:
    job["updated_at"] = _now_iso()
    if expected_run_id is not None:
        updated = update_job_if_run_matches(job, expected_run_id, allowed_statuses)
        if not updated:
            return False
        _write_json_mirror(job)
        return True
    upsert_job(job)
    _write_json_mirror(job)
    return True


def patch_job(
    job_id: str,
    expected_run_id: str,
    patch: dict,
    allowed_statuses: set[str] | frozenset[str] | None = None,
) -> bool:
    updated = db_patch_job_if_run_matches(job_id, expected_run_id, patch, allowed_statuses)
    if updated:
        job = get_job(job_id)
        if job is not None:
            _write_json_mirror(job)
    return updated


def list_jobs() -> list:
    return db_list_jobs()


def delete_job(job_id: str) -> None:
    db_delete_job(job_id)
    _job_path(job_id).unlink(missing_ok=True)


def get_running_job() -> Optional[dict]:
    for j in list_jobs():
        if j.get("status") in ACTIVE_STATUSES:
            return j
    return None


def build_paths(job_id: str, output_type: str = "clean_video") -> dict:
    job_dir = JOBS_DIR / job_id
    is_voice = output_type == "voice_only"
    return {
        "job_dir": str(job_dir),
        "input_dir": str(job_dir / "input"),
        "output_dir": str(job_dir / "output"),
        "workspace_dir": str(job_dir / "workspace"),
        "work_dir": str(job_dir / "work"),
        "run_metadata": str(job_dir / "run.json"),
        "avatar_video": str(job_dir / "input/avatar.mp4"),
        "background_snapshot": str(job_dir / "input/avatar.mp4"),
        "log_dir": str(job_dir / "logs"),
        "title_txt": str(job_dir / "input/title.txt"),
        "subtitle_txt": str(job_dir / "input/subtitle.txt"),
        "keywords_txt": str(job_dir / "input/keywords.txt"),
        "script_txt": str(job_dir / "input/script.txt"),
        "voice_profile_json": str(job_dir / "input/voice_profile.json"),
        "voice_reference_snapshot": str(job_dir / "input/voice_reference.wav"),
        "voice_prompt_txt": str(job_dir / "input/voice_prompt.txt"),
        "voice_wav": str(job_dir / "output/voice.wav"),
        "voice_for_latentsync_wav": str(job_dir / "output/voice_for_latentsync.wav"),
        "clean_video": None if is_voice else str(job_dir / "output/clean_video.mp4"),
        "final_video": None,
        "run_log": str(job_dir / "logs/run.log"),
        "windows_desktop_output": str(
            WINDOWS_OUTPUT_DIR / f"{job_id}_voice.wav"
            if is_voice else WINDOWS_OUTPUT_DIR / f"{job_id}_clean_video.mp4"
        ),
        "subtitle_lines_txt": str(job_dir / "output/subtitle_lines.txt"),
        "script_meta_json": str(job_dir / "output/script_meta.json"),
    }


def _normalize_keywords(raw) -> list:
    if isinstance(raw, list):
        return [str(k).strip() for k in raw if str(k).strip()]
    return [k.strip() for k in re.split(r"[,\n、，]", str(raw)) if k.strip()]


def _host_path(value: str | Path) -> Path:
    raw = str(value or "")
    if raw.startswith("/mnt/") and len(raw) > 7 and raw[6] == "/":
        drive = raw[5].upper()
        rest = raw[7:].replace("/", "\\")
        return Path(f"{drive}:\\{rest}")
    return Path(raw)


def _wsl_path(value: str | Path) -> str:
    raw = str(value or "")
    if os.name == "nt" and len(raw) >= 3 and raw[1] == ":":
        drive = raw[0].lower()
        return f"/mnt/{drive}/{raw[3:].replace(chr(92), '/') }"
    return raw


def _snapshot_file(source: str | Path, destination: Path) -> None:
    src = _host_path(source)
    if not src.exists() or not src.is_file():
        raise FileNotFoundError(f"依赖文件不存在：{src}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, destination)
    except (AttributeError, FileExistsError, OSError):
        shutil.copy2(src, destination)


def create_job(req: JobCreateRequest, voice_data: dict | None = None) -> dict:
    # Microseconds prevent collisions when the UI submits twice in one second.
    job_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_video_job"
    job_dir = JOBS_DIR / job_id

    for subdir in ("input", "output", "logs"):
        (job_dir / subdir).mkdir(parents=True, exist_ok=True)

    voice_data = voice_data or {}
    job = {
        "job_id": job_id,
        "status": "pending",
        "title": req.title,
        "subtitle": req.subtitle,
        "keywords": _normalize_keywords(req.keywords),
        "script": req.script,
        "background_id": req.background_id,
        "voice_id": req.voice_id or DEFAULT_VOICE_ID,
        "voice_language": req.voice_language or "zh",
        "voice_dialect": req.voice_dialect if req.voice_language == "zh" else "",
        "voice_mode": req.voice_mode or "basic_tts",
        "voice_style": req.voice_style or "professional_calm",
        "voice_checkpoint_path": voice_data.get("checkpoint_path"),
        "voice_reference_wav_path": voice_data.get("reference_wav_path"),
        "voice_reference_text": voice_data.get("reference_text", ""),
        "voice_revision": voice_data.get("revision"),
        "voice_training_status": voice_data.get("training_status"),
        "output_type": req.output_type,
        "shutdown_after_done": req.shutdown_after_done,
        "created_at": _now_iso(),
        "started_at": None,
        "finished_at": None,
        "error_message": None,
        "progress": {
            "stage": "pending",
            "current_window": 0,
            "total_windows": 0,
            "percent": 0,
            "message": "Waiting to start",
        },
        "paths": build_paths(job_id, req.output_type),
    }

    # Snapshot dependencies before the job becomes visible to the queue.
    if job["output_type"] == "clean_video":
        from background_utils import get_background_by_id
        background = get_background_by_id(job["background_id"])
        if not background:
            raise FileNotFoundError(f"背景素材不存在：{job['background_id']}")
        _snapshot_file(background.get("path", ""), Path(job["paths"]["background_snapshot"]))

    reference = job.get("voice_reference_wav_path")
    if reference:
        snapshot = Path(job["paths"]["voice_reference_snapshot"])
        _snapshot_file(reference, snapshot)
        job["voice_reference_wav_path"] = _wsl_path(snapshot)

    save_job(job)

    # Optional: save AI-generated subtitle lines
    if req.subtitle_lines:
        p = Path(job["paths"]["subtitle_lines_txt"])
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(req.subtitle_lines), encoding="utf-8")

    # Optional: save AI script metadata
    if req.script_source == "ollama":
        meta = {
            "title":        req.title,
            "subtitle":     req.subtitle,
            "keywords":     _normalize_keywords(req.keywords),
            "opening_hook": req.opening_hook or "",
            "source":       req.script_source or "manual",
            "model":        req.script_model  or "",
            "voice_language": job["voice_language"],
            "voice_dialect": job["voice_dialect"],
            "voice_mode": job["voice_mode"],
            "voice_style": job["voice_style"],
        }
        p = Path(job["paths"]["script_meta_json"])
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return job


def duplicate_job(source: dict) -> dict:
    """Create an immutable-input copy of an existing job with a fresh ID."""
    job_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_video_job"
    job_dir = JOBS_DIR / job_id
    for subdir in ("input", "output", "logs"):
        (job_dir / subdir).mkdir(parents=True, exist_ok=True)

    job = {
        key: deepcopy(source.get(key))
        for key in (
            "title", "subtitle", "keywords", "script", "background_id", "voice_id",
            "voice_language", "voice_dialect", "voice_mode", "voice_style",
            "voice_checkpoint_path", "voice_reference_wav_path", "voice_reference_text",
            "voice_revision", "voice_training_status", "output_type", "shutdown_after_done",
        )
    }
    job.update({
        "job_id": job_id,
        "status": "pending",
        "created_at": _now_iso(),
        "started_at": None,
        "finished_at": None,
        "error_message": None,
        "progress": {"stage": "pending", "current_window": 0, "total_windows": 0, "percent": 0, "message": "Waiting to start"},
        "paths": build_paths(job_id, job.get("output_type", "clean_video")),
    })

    source_paths = source.get("paths", {})
    for source_key, target_key in (
        ("background_snapshot", "background_snapshot"),
        ("voice_reference_snapshot", "voice_reference_snapshot"),
    ):
        source_path = source_paths.get(source_key)
        target_path = job["paths"].get(target_key)
        if source_path and target_path and Path(_host_path(source_path)).exists():
            _snapshot_file(source_path, Path(target_path))
            if target_key == "voice_reference_snapshot":
                job["voice_reference_wav_path"] = _wsl_path(target_path)

    for filename in ("subtitle_lines.txt", "script_meta.json"):
        source_file = _host_path(source_paths.get("output_dir", "")) / filename
        target_file = Path(job["paths"]["output_dir"]) / filename
        if source_file.exists():
            shutil.copy2(source_file, target_file)

    save_job(job)
    return job
