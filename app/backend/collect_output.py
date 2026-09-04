#!/usr/bin/env python3
"""
collect_output.py — Digital Human Job Runner
Usage: python collect_output.py JOB_ID
"""

import shutil
import sys
from datetime import datetime
from pathlib import Path
from settings import JOBS_DIR, WINDOWS_OUTPUT_DIR
from job_store import load_job, save_job


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def fail_job(job: dict | None, msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)
    if job:
        try:
            job["status"] = "failed"
            job["error_message"] = msg
            job.setdefault("progress", {})
            job["progress"]["stage"] = "failed"
            job["progress"]["message"] = msg
            save_job(job)
            print("[INFO] SQLite job state updated: status=failed")
        except Exception as e:
            print(f"[WARN] Could not update SQLite job state after failure: {e}", file=sys.stderr)
    sys.exit(1)


def validate_job(job: dict, job_id: str) -> None:
    if job.get("job_id") != job_id:
        raise ValueError(
            f"job_id mismatch: database has '{job.get('job_id')}', expected '{job_id}'"
        )
    if job.get("output_type") != "clean_video":
        raise ValueError(
            f"output_type '{job.get('output_type')}' is not supported. "
            f"final_video is not implemented in V1."
        )


def copy_audio_files(job_id: str) -> None:
    job_output_dir = JOBS_DIR / job_id / "output"
    audio_files = [
        ("voice.wav", "voice.wav"),
        ("voice_for_latentsync.wav", "voice_for_latentsync.wav"),
    ]
    for src_name, dst_name in audio_files:
        src = job_output_dir / src_name
        dst = job_output_dir / dst_name
        if src.exists() and src.resolve() != dst.resolve():
            shutil.copy2(src, dst)
            print(f"[INFO] Copied audio: {src_name} -> job output/")
        else:
            print(f"[WARN] Audio file not found, skipping: {src_name}")


def copy_to_windows_desktop(job_id: str, src: Path) -> Path:
    WINDOWS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    dst = WINDOWS_OUTPUT_DIR / f"{job_id}_clean_video.mp4"
    shutil.copy2(src, dst)
    print(f"[INFO] Copied to Windows Desktop: {dst}")
    return dst


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python collect_output.py JOB_ID", file=sys.stderr)
        sys.exit(1)

    job_id = sys.argv[1]
    job_path = JOBS_DIR / job_id

    print(f"[INFO] ========================================")
    print(f"[INFO] collect_output.py — Digital Human Job Runner")
    print(f"[INFO] Job ID : {job_id}")
    print(f"[INFO] Job    : {job_path}")
    print(f"[INFO] ========================================")

    job = load_job(job_id)
    if job is None:
        fail_job(None, f"SQLite 中找不到任务：{job_id}")

    try:
        validate_job(job, job_id)
    except ValueError as e:
        fail_job(job, str(e))

    # --- Check clean_video.mp4 exists ---
    job_output_dir = JOBS_DIR / job_id / "output"
    clean_video_src = job_output_dir / "clean_video.mp4"
    if not clean_video_src.exists():
        fail_job(job, f"clean_video.mp4 not found: {clean_video_src}")

    print(f"[INFO] clean_video.mp4 found: {clean_video_src}")

    # --- Ensure job output and logs dirs exist ---
    job_logs_dir = JOBS_DIR / job_id / "logs"
    job_output_dir.mkdir(parents=True, exist_ok=True)
    job_logs_dir.mkdir(parents=True, exist_ok=True)
    print(f"[INFO] Job output/logs dirs ensured.")

    # --- Copy clean_video to job output ---
    print(f"[INFO] Collecting output files...")
    job_clean_video = job_output_dir / "clean_video.mp4"
    print(f"[INFO] Job output already contains clean_video.mp4; no shared output copy needed.")

    # --- Copy audio files (non-fatal if missing) ---
    try:
        copy_audio_files(job_id)
    except Exception as e:
        fail_job(job, f"Failed to copy audio files: {e}")

    # --- Copy to Windows Desktop ---
    print(f"[INFO] Copying to Windows Desktop...")
    try:
        windows_dst = copy_to_windows_desktop(job_id, job_clean_video)
    except Exception as e:
        fail_job(job, f"Failed to copy to Windows Desktop: {e}")

    # --- Update job.json ---
    print(f"[INFO] Updating job.json...")
    try:
        job["status"] = "finished"
        job["finished_at"] = now_iso()
        job["error_message"] = None

        progress = job.setdefault("progress", {})
        total = progress.get("total_windows", 0)
        progress["stage"] = "finished"
        progress["current_window"] = total if total > 0 else 0
        progress["percent"] = 100
        progress["message"] = "CleanVideo generated successfully"

        paths = job.setdefault("paths", {})
        paths["clean_video"] = str(job_clean_video)
        paths["voice_wav"] = str(job_output_dir / "voice.wav")
        paths["voice_for_latentsync_wav"] = str(job_output_dir / "voice_for_latentsync.wav")
        paths["windows_desktop_output"] = str(windows_dst)

        save_job(job)
    except Exception as e:
        fail_job(job, f"Failed to update SQLite job state: {e}")

    print(f"[INFO] ========================================")
    print(f"[INFO] collect_output.py DONE")
    print(f"[INFO] status     : {job['status']}")
    print(f"[INFO] stage      : {job['progress']['stage']}")
    print(f"[INFO] finished_at: {job['finished_at']}")
    print(f"[INFO] clean_video: {paths['clean_video']}")
    print(f"[INFO] windows    : {paths['windows_desktop_output']}")
    print(f"[INFO] ========================================")


if __name__ == "__main__":
    main()
