#!/usr/bin/env python3
"""
collect_voice_output.py — Voice-only job output collector
Usage: python collect_voice_output.py JOB_ID
"""

import shutil
import os
import sys
from datetime import datetime
from pathlib import Path
from settings import JOBS_DIR, WINDOWS_OUTPUT_DIR
from job_store import load_job, patch_job, save_job
from job_states import ACTIVE_STATUSES


def now_iso():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def fail_job(job, msg):
    print(f"[ERROR] {msg}", file=sys.stderr)
    if job:
        try:
            run_id = os.getenv("DHJR_RUN_ID", "").strip()
            if run_id:
                patch_job(job["job_id"], run_id, {"status": "failed", "error_message": msg, "progress": {"stage": "failed", "message": msg}}, ACTIVE_STATUSES - {"cancelling"})
            else:
                job["status"] = "failed"
                job["error_message"] = msg
                job.setdefault("progress", {})
                job["progress"].update({"stage": "failed", "message": msg})
                save_job(job)
        except Exception as e:
            print(f"[WARN] Could not update SQLite job state: {e}", file=sys.stderr)
    sys.exit(1)


def main():
    if len(sys.argv) != 2:
        print("Usage: python collect_voice_output.py JOB_ID", file=sys.stderr)
        sys.exit(1)

    job_id   = sys.argv[1]
    job_path = JOBS_DIR / job_id

    print(f"[INFO] collect_voice_output.py — job={job_id}")

    job = load_job(job_id)
    if job is None:
        fail_job(None, f"SQLite 中找不到任务：{job_id}")

    job_output_dir = JOBS_DIR / job_id / "output"
    voice_src = job_output_dir / "voice.wav"
    if not voice_src.exists():
        fail_job(job, f"voice.wav not found: {voice_src}")

    job_output_dir.mkdir(parents=True, exist_ok=True)

    # Copy voice files to job output
    for name in ("voice.wav", "voice_for_latentsync.wav"):
        src = job_output_dir / name
        if src.exists():
            print(f"[INFO] Job output contains {name}")
        else:
            print(f"[WARN] {name} not found, skipping")

    # Copy voice.wav to Windows Desktop
    win_dst = None
    try:
        WINDOWS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        win_dst = WINDOWS_OUTPUT_DIR / f"{job_id}_voice.wav"
        shutil.copy2(voice_src, win_dst)
        print(f"[INFO] Copied to Windows Desktop: {win_dst}")
    except Exception as e:
        print(f"[WARN] Could not copy to Windows Desktop: {e}")
        win_dst = None

    # Update job.json
    try:
        progress = {**job.get("progress", {})}
        progress["stage"]   = "finished"
        progress["percent"] = 100
        progress["message"] = "Voice generated successfully"

        paths = {**job.get("paths", {})}
        paths["voice_wav"] = str(job_output_dir / "voice.wav")
        paths["voice_for_latentsync_wav"] = str(job_output_dir / "voice_for_latentsync.wav")
        paths["clean_video"] = None
        if win_dst:
            paths["windows_desktop_output"] = str(win_dst)

        run_id = os.getenv("DHJR_RUN_ID", "").strip()
        finished_at = now_iso()
        saved = patch_job(
            job_id,
            run_id,
            {"status": "finished", "finished_at": finished_at, "error_message": None, "progress": progress, "paths": paths},
            ACTIVE_STATUSES - {"cancelling"},
        ) if run_id else save_job({**job, "status": "finished", "finished_at": finished_at, "error_message": None, "progress": progress, "paths": paths})
        if not saved:
            fail_job(None, "任务已被取消，拒绝写入完成状态。")
        job.update({"status": "finished", "finished_at": finished_at, "error_message": None, "progress": progress, "paths": paths})
        print(f"[INFO] job.json updated: status=finished")
    except Exception as e:
        fail_job(job, f"Failed to update SQLite job state: {e}")

    print(f"[INFO] Voice-only collection done: {job_id}")


if __name__ == "__main__":
    main()
