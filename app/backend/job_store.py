from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from database import delete_job as db_delete_job
from database import get_job, list_jobs as db_list_jobs, upsert_job
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
    migrate_legacy_jobs()
    job = get_job(job_id)
    if job is not None:
        return job
    p = _job_path(job_id)
    if not p.exists():
        return None
    job = json.loads(p.read_text(encoding="utf-8"))
    upsert_job(job)
    return job


def save_job(job: dict) -> None:
    job["updated_at"] = _now_iso()
    upsert_job(job)
    _write_json_mirror(job)


def list_jobs() -> list:
    migrate_legacy_jobs()
    return db_list_jobs()


def delete_job(job_id: str) -> None:
    db_delete_job(job_id)
    _job_path(job_id).unlink(missing_ok=True)


def get_running_job() -> Optional[dict]:
    for j in list_jobs():
        if j.get("status") == "running":
            return j
    return None


def _build_paths(job_id: str) -> dict:
    job_dir = JOBS_DIR / job_id
    return {
        "job_dir": str(job_dir),
        "input_dir": str(job_dir / "input"),
        "output_dir": str(job_dir / "output"),
        "workspace_dir": str(job_dir / "workspace"),
        "work_dir": str(job_dir / "work"),
        "avatar_video": str(job_dir / "input/avatar.mp4"),
        "log_dir": str(job_dir / "logs"),
        "title_txt": str(job_dir / "input/title.txt"),
        "subtitle_txt": str(job_dir / "input/subtitle.txt"),
        "keywords_txt": str(job_dir / "input/keywords.txt"),
        "script_txt": str(job_dir / "input/script.txt"),
        "voice_profile_json": str(job_dir / "input/voice_profile.json"),
        "voice_prompt_txt": str(job_dir / "input/voice_prompt.txt"),
        "voice_wav": str(job_dir / "output/voice.wav"),
        "voice_for_latentsync_wav": str(job_dir / "output/voice_for_latentsync.wav"),
        "clean_video": str(job_dir / "output/clean_video.mp4"),
        "final_video": None,
        "run_log": str(job_dir / "logs/run.log"),
        "windows_desktop_output": str(WINDOWS_OUTPUT_DIR / f"{job_id}_clean_video.mp4"),
        "subtitle_lines_txt": str(job_dir / "output/subtitle_lines.txt"),
        "script_meta_json": str(job_dir / "output/script_meta.json"),
    }


def _normalize_keywords(raw) -> list:
    if isinstance(raw, list):
        return [str(k).strip() for k in raw if str(k).strip()]
    return [k.strip() for k in re.split(r"[,\n、，]", str(raw)) if k.strip()]


def create_job(req: JobCreateRequest) -> dict:
    # Microseconds prevent collisions when the UI submits twice in one second.
    job_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_video_job"
    job_dir = JOBS_DIR / job_id

    for subdir in ("input", "output", "logs"):
        (job_dir / subdir).mkdir(parents=True, exist_ok=True)

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
        "voice_checkpoint_path": req.voice_checkpoint_path,
        "voice_reference_wav_path": req.voice_reference_wav_path,
        "voice_reference_text": req.voice_reference_text or "",
        "voice_training_status": req.voice_training_status,
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
        "paths": _build_paths(job_id),
    }

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
