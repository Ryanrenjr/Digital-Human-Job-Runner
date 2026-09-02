import json
import math
import subprocess
from pathlib import Path
from settings import FFPROBE_CANDIDATES, JOBS_DIR, LATENTSYNC_WORK_DIR, OUTPUT_DIR

LATENTSYNC_WORK = LATENTSYNC_WORK_DIR

VOICE_LS_WAV   = OUTPUT_DIR / "voice_for_latentsync.wav"
CLEAN_VIDEO    = OUTPUT_DIR / "clean_video.mp4"


def _audio_duration(path: Path) -> float:
    """Return WAV duration in seconds via ffprobe, or 0.0 on any failure."""
    for candidate in FFPROBE_CANDIDATES:
        try:
            result = subprocess.run(
                [
                    candidate, "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=nw=1:nk=1",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            val = result.stdout.strip()
            if val:
                return float(val)
        except Exception:
            continue
    return 0.0


def get_cleanvideo_progress(job_id: str) -> dict:
    """
    Return a live progress dict for the given job.

    - Non-running jobs: returns existing progress from job.json unchanged.
    - Running jobs: inspects filesystem to compute real-time stage/percent.
    - Never raises; returns {} on read failure so callers stay safe.
    """
    job_path = JOBS_DIR / job_id / "job.json"
    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    existing = dict(job.get("progress", {}))
    status   = job.get("status")

    if status == "finished":
        return {
            "stage":          "finished",
            "current_window": existing.get("current_window", 0),
            "total_windows":  existing.get("total_windows", 0),
            "percent":        100,
            "message":        "CleanVideo generated successfully",
        }

    if status in ("failed", "cancelled", "pending"):
        return existing

    if status != "running":
        return existing

    # --- Dynamic detection for running jobs ---
    try:
        # A: voice not yet generated — still in VoxCPM2 / postprocess
        if not VOICE_LS_WAV.exists():
            return {
                "stage":          "voice_generation",
                "current_window": 0,
                "total_windows":  0,
                "percent":        5,
                "message":        "Generating voice audio",
            }

        # C: clean_video exists but job not marked finished — collecting output
        if CLEAN_VIDEO.exists():
            return {
                "stage":          "collecting_output",
                "current_window": existing.get("current_window", 0),
                "total_windows":  existing.get("total_windows", 0),
                "percent":        95,
                "message":        "Collecting output files",
            }

        # B: LatentSync in progress
        duration = _audio_duration(VOICE_LS_WAV)
        total_windows = math.ceil(duration / 6) if duration > 0 else 0

        core_files    = list(LATENTSYNC_WORK.glob("core_*.mp4"))
        current_window = len(core_files)

        if total_windows > 0:
            percent = int(10 + min(85, current_window / total_windows * 85))
        else:
            percent = 10

        return {
            "stage":          "latentsync",
            "current_window": current_window,
            "total_windows":  total_windows,
            "percent":        percent,
            "message":        f"Processing window {current_window} / {total_windows}",
        }

    except Exception:
        return existing
