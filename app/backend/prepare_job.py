#!/usr/bin/env python3
"""
prepare_job.py — Digital Human Job Runner
Usage: python prepare_job.py JOB_ID
"""

import shutil
import json
import sys
from datetime import datetime
from pathlib import Path
from pathlib import PureWindowsPath
from job_states import ACTIVE_STATUSES
from settings import (
    BACKGROUNDS_JSON,
    JOBS_DIR,
    SUPPORTED_VOICE_IDS,
    WINDOWS_OUTPUT_DIR,
)
from job_store import load_job, save_job

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def host_path(path_value: str) -> Path:
    raw = str(path_value)
    if sys.platform.startswith("win"):
        if raw.startswith("/mnt/") and len(raw) > 7 and raw[6] == "/":
            drive = raw[5].upper()
            rest = raw[7:].replace("/", "\\")
            return Path(f"{drive}:\\{rest}")
        return Path(raw)
    if len(raw) >= 3 and raw[1] == ":" and raw[2] in {"\\", "/"}:
        win_path = PureWindowsPath(raw)
        drive = win_path.drive.rstrip(":").lower()
        parts = "/".join(win_path.parts[1:])
        return Path(f"/mnt/{drive}/{parts}")
    return Path(raw)


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
    required = ["job_id", "title", "script", "voice_id", "output_type"]
    for field in required:
        v = job.get(field)
        if v is None or v == "" or v == []:
            raise ValueError(f"Required field missing or empty: {field}")

    # background_id only required for clean_video
    if job.get("output_type") == "clean_video" and not job.get("background_id"):
        raise ValueError("Required field missing or empty: background_id")

    if job["job_id"] != job_id:
        raise ValueError(
            f"job_id mismatch: database has '{job['job_id']}', expected '{job_id}'"
        )

    status = job.get("status", "")
    if status in ((ACTIVE_STATUSES - {"starting"}) | {"finished"}):
        raise ValueError(
            f"Job status is '{status}'. Only pending/failed/cancelled/starting jobs can be prepared."
        )

    if job["output_type"] not in ("clean_video", "voice_only"):
        raise ValueError(
            f"output_type '{job['output_type']}' is not supported. "
            f"Must be 'clean_video' or 'voice_only'."
        )

    is_custom_voice = isinstance(job["voice_id"], str) and job["voice_id"].startswith("voice_")
    if job["voice_id"] not in SUPPORTED_VOICE_IDS and not is_custom_voice:
        raise ValueError(
            f"voice_id '{job['voice_id']}' is not supported in V1. "
            f"Configured voices: {sorted(SUPPORTED_VOICE_IDS)} or custom voice profiles."
        )

    if not isinstance(job.get("keywords", []), list) or not all(
        isinstance(k, str) for k in job.get("keywords", [])
    ):
        raise ValueError("keywords must be a list of strings.")

    job.setdefault("voice_language", "zh")
    job.setdefault("voice_dialect", "mandarin" if job["voice_language"] == "zh" else "")
    job.setdefault("voice_mode", "basic_tts")
    job.setdefault("voice_style", "professional_calm")


def resolve_background(background_id: str) -> Path:
    if not BACKGROUNDS_JSON.exists():
        raise FileNotFoundError(f"backgrounds.json not found: {BACKGROUNDS_JSON}")
    backgrounds = json.loads(BACKGROUNDS_JSON.read_text(encoding="utf-8"))
    for bg in backgrounds:
        if bg["id"] == background_id:
            p = host_path(bg["path"])
            if not p.exists():
                raise FileNotFoundError(
                    f"Background file not found: {p} (id={background_id})"
                )
            return p
    raise ValueError(
        f"background_id '{background_id}' not found in backgrounds.json. "
        f"Available: {[b['id'] for b in backgrounds]}"
    )


def write_input_files(job: dict, job_input_dir: Path) -> None:
    keywords_text = "\n".join(job["keywords"])

    pairs = [
        ("title.txt", job["title"]),
        ("subtitle.txt", job["subtitle"]),
        ("keywords.txt", keywords_text),
        ("script.txt", job["script"]),
    ]

    for name, content in pairs:
        path = job_input_dir / name
        path.write_text(content, encoding="utf-8")
        print(f"[INFO] Written: job input/{name}")

    voice_profile = {
        "voice_id": job.get("voice_id", ""),
        "language": job.get("voice_language", "zh"),
        "dialect": job.get("voice_dialect", ""),
        "mode": job.get("voice_mode", "basic_tts"),
        "style": job.get("voice_style", "professional_calm"),
        "checkpoint_path": job.get("voice_checkpoint_path") or "",
        "reference_wav_path": job.get("voice_reference_wav_path") or "",
        "reference_text": job.get("voice_reference_text") or "",
    }
    voice_prompt = build_voice_prompt(voice_profile)

    (job_input_dir / "voice_profile.json").write_text(
        json.dumps(voice_profile, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (job_input_dir / "voice_prompt.txt").write_text(voice_prompt, encoding="utf-8")
    print(f"[INFO] Written: voice_profile.json and voice_prompt.txt")


def build_voice_prompt(profile: dict) -> str:
    parts = [
        f"language={profile.get('language', 'zh')}",
        f"mode={profile.get('mode', 'basic_tts')}",
        f"style={profile.get('style', 'professional_calm')}",
    ]
    dialect = profile.get("dialect")
    if dialect:
        parts.insert(1, f"dialect={dialect}")
    return "\n".join(parts) + "\n"


def clean_job_outputs(job_output_dir: Path) -> None:
    files_to_remove = [
        "clean_video.mp4",
        "final_video.mp4",
        "main_video_no_endcard.mp4",
        "main_video_trimmed.mp4",
        "voice.wav",
        "voice_for_latentsync.wav",
        "captions.json",
        "video_config.json",
    ]
    dirs_to_remove = [
        "audio_segments",
        "audio_segments_original_speed",
    ]

    for name in files_to_remove:
        p = job_output_dir / name
        if p.exists():
            p.unlink()
            print(f"[INFO] Removed old output file: {name}")

    for name in dirs_to_remove:
        p = job_output_dir / name
        if p.exists():
            shutil.rmtree(p)
            print(f"[INFO] Removed old output dir: {name}")


def build_paths(job_id: str, output_type: str = "clean_video") -> dict:
    job_dir = JOBS_DIR / job_id
    is_voice = output_type == "voice_only"
    return {
        "job_dir": str(job_dir),
        "input_dir": str(job_dir / "input"),
        "output_dir": str(job_dir / "output"),
        "workspace_dir": str(job_dir / "workspace"),
        "work_dir": str(job_dir / "work"),
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
        "subtitle_lines_txt": str(job_dir / "output/subtitle_lines.txt"),
        "script_meta_json": str(job_dir / "output/script_meta.json"),
        "windows_desktop_output": (
            str(WINDOWS_OUTPUT_DIR / f"{job_id}_voice.wav")
            if is_voice else
            str(WINDOWS_OUTPUT_DIR / f"{job_id}_clean_video.mp4")
        ),
    }


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python prepare_job.py JOB_ID", file=sys.stderr)
        sys.exit(1)

    job_id = sys.argv[1]
    job_path = JOBS_DIR / job_id

    print(f"[INFO] ========================================")
    print(f"[INFO] prepare_job.py — Digital Human Job Runner")
    print(f"[INFO] Job ID : {job_id}")
    print(f"[INFO] Job    : {job_path}")
    print(f"[INFO] ========================================")

    job = load_job(job_id)
    if job is None:
        fail_job(None, f"SQLite 中找不到任务：{job_id}")

    # --- Validate ---
    print(f"[INFO] Validating job fields...")
    try:
        validate_job(job, job_id)
    except ValueError as e:
        fail_job(job, str(e))

    print(f"[INFO] Validation passed.")
    print(f"[INFO]   title        : {job['title']}")
    print(f"[INFO]   subtitle     : {job['subtitle']}")
    print(f"[INFO]   background_id: {job['background_id']}")
    print(f"[INFO]   voice_id     : {job['voice_id']}")
    print(f"[INFO]   language     : {job.get('voice_language', 'zh')}")
    print(f"[INFO]   dialect      : {job.get('voice_dialect', '')}")
    print(f"[INFO]   voice_mode   : {job.get('voice_mode', 'basic_tts')}")
    print(f"[INFO]   voice_style  : {job.get('voice_style', 'professional_calm')}")
    print(f"[INFO]   output_type  : {job['output_type']}")
    print(f"[INFO]   keywords     : {job['keywords']}")

    output_type = job["output_type"]
    stamp = now_stamp()

    # --- Resolve background without touching any shared engine asset ---
    if output_type == "clean_video":
        snapshot = Path(job.get("paths", {}).get("background_snapshot", ""))
        if snapshot.exists():
            bg_src = snapshot
            print(f"[INFO] Background snapshot found: {bg_src}")
        else:
            try:
                bg_src = resolve_background(job["background_id"])
            except (FileNotFoundError, ValueError) as e:
                fail_job(job, str(e))
            print(f"[INFO] Legacy background resolved: {bg_src}")
    else:
        bg_src = None
        print(f"[INFO] voice_only — skipping background switch")

    # --- Create job directory structure ---
    job_dir = JOBS_DIR / job_id
    for subdir in ("input", "output", "logs"):
        (job_dir / subdir).mkdir(parents=True, exist_ok=True)
    print(f"[INFO] Job directories ensured: {job_dir}/{{input,output,logs}}")

    # --- Write input files ---
    print(f"[INFO] Writing input files...")
    try:
        write_input_files(job, job_dir / "input")
    except Exception as e:
        fail_job(job, f"Failed to write input files: {e}")

    if output_type == "clean_video":
        avatar_path = job_dir / "input/avatar.mp4"
        if not avatar_path.exists():
            print(f"[INFO] Copying legacy background into this job workspace: {job['background_id']}")
            try:
                shutil.copy2(bg_src, avatar_path)
            except Exception as e:
                fail_job(job, f"Failed to prepare avatar video: {e}")
        print(f"[INFO] Avatar video: {avatar_path}")

    # --- Clean only this job's previous outputs ---
    print(f"[INFO] Cleaning this job's previous output files...")
    try:
        clean_job_outputs(job_dir / "output")
    except Exception as e:
        fail_job(job, f"Failed to clean old outputs: {e}")

    # --- Update job.json ---
    print(f"[INFO] Updating job.json...")
    try:
        job["status"] = "running"
        if not job.get("started_at"):
            job["started_at"] = now_iso()
        job["error_message"] = None
        job.setdefault("progress", {})
        job["progress"]["stage"] = "prepared"
        job["progress"]["current_window"] = 0
        job["progress"]["total_windows"] = 0
        job["progress"]["percent"] = 0
        job["progress"]["message"] = "Job prepared successfully"
        job["paths"] = build_paths(job_id, output_type)
        save_job(job)
    except Exception as e:
        fail_job(job, f"Failed to update SQLite job state: {e}")

    print(f"[INFO] ========================================")
    print(f"[INFO] prepare_job.py DONE")
    print(f"[INFO] status    : {job['status']}")
    print(f"[INFO] stage     : {job['progress']['stage']}")
    print(f"[INFO] started_at: {job['started_at']}")
    print(f"[INFO] ========================================")


if __name__ == "__main__":
    main()
