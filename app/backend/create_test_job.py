#!/usr/bin/env python3
"""
create_test_job.py — Digital Human Job Runner
Creates a test job for validating the CleanVideo pipeline.
Usage: python3 create_test_job.py
"""

import json
from datetime import datetime
from pathlib import Path
from settings import DEFAULT_VOICE_ID, JOBS_DIR, RUN_SCRIPT, WINDOWS_OUTPUT_DIR


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def build_paths(job_id: str) -> dict:
    job_dir = JOBS_DIR / job_id
    return {
        "job_dir": str(job_dir),
        "input_dir": str(job_dir / "input"),
        "output_dir": str(job_dir / "output"),
        "log_dir": str(job_dir / "logs"),
        "title_txt": str(job_dir / "input/title.txt"),
        "subtitle_txt": str(job_dir / "input/subtitle.txt"),
        "keywords_txt": str(job_dir / "input/keywords.txt"),
        "script_txt": str(job_dir / "input/script.txt"),
        "voice_wav": str(job_dir / "output/voice.wav"),
        "voice_for_latentsync_wav": str(job_dir / "output/voice_for_latentsync.wav"),
        "clean_video": str(job_dir / "output/clean_video.mp4"),
        "final_video": None,
        "run_log": str(job_dir / "logs/run.log"),
        "windows_desktop_output": str(WINDOWS_OUTPUT_DIR / f"{job_id}_clean_video.mp4"),
    }


def main() -> None:
    job_id = f"{now_stamp()}_test_video"
    job_dir = JOBS_DIR / job_id

    for subdir in ("input", "output", "logs"):
        (job_dir / subdir).mkdir(parents=True, exist_ok=True)

    job = {
        "job_id": job_id,
        "status": "pending",
        "title": "60 秒产品更新",
        "subtitle": "一段简洁的视频说明",
        "keywords": ["产品", "更新", "口播", "数字人"],
        "script": "这是一个 Digital Human Job Runner 测试任务。你可以输入任意口播文案，选择一个 Avatar 视频，然后生成一段数字人口播视频。",
        "background_id": "boss_03",
        "voice_id": DEFAULT_VOICE_ID,
        "output_type": "clean_video",
        "shutdown_after_done": False,
        "created_at": now_iso(),
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
        "paths": build_paths(job_id),
    }

    job_json_path = job_dir / "job.json"
    job_json_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")

    run_cmd = f"bash {RUN_SCRIPT} {job_id}"
    log_cmd = f"tail -f {JOBS_DIR / job_id / 'logs/run.log'}"

    print(f"Created test job: {job_id}")
    print(f"Job path: {job_dir}")
    print(f"Run command:")
    print(f"  {run_cmd}")
    print(f"Log command:")
    print(f"  {log_cmd}")


if __name__ == "__main__":
    main()
