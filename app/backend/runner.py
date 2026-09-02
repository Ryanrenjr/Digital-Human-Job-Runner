import os
import signal
import subprocess
from typing import Optional

from job_store import list_jobs, load_job
from settings import RUN_SCRIPT, RUN_VOICE_SCRIPT

_PIPELINE_MARKERS = [
    "run_02_latentsync_overlap.sh",
    "generate_voice_and_timeline_voxcpm2.py",
    "postprocess_voxcpm_segments_v12.py",
    "scripts.inference",
]


def check_no_other_running_job(job_id: str) -> Optional[str]:
    """Return the job_id of a running job that is NOT this job, or None."""
    for j in list_jobs():
        if j.get("status") == "running" and j.get("job_id") != job_id:
            return j["job_id"]
    return None


def is_job_process_running(job_id: str) -> bool:
    """
    Check whether a real pipeline process exists for job_id.

    Priority 1: run_cleanvideo_job.sh with this specific job_id in argv.
    Priority 2: any LatentSync / VoxCPM pipeline marker process — these
                don't carry the job_id but indicate a generation is active.
    Returns False on any exception so callers stay safe.
    """
    try:
        result = subprocess.run(["ps", "aux"], capture_output=True, text=True)
        lines = result.stdout.splitlines()

        for line in lines:
            if "run_cleanvideo_job.sh" in line and job_id in line:
                return True

        for line in lines:
            for marker in _PIPELINE_MARKERS:
                if marker in line:
                    return True

        return False
    except Exception:
        return False


def kill_job_process(job_id: str) -> bool:
    """
    Kill the running pipeline for job_id by sending SIGTERM to its process group.
    Tries the exact run_cleanvideo_job.sh process first, then any pipeline markers.
    Returns True if at least one process was signalled.
    """
    try:
        result = subprocess.run(["ps", "aux"], capture_output=True, text=True)
        lines = result.stdout.splitlines()

        def _kill_pgid(pid: int) -> bool:
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
                return True
            except (ProcessLookupError, OSError):
                return False

        # Priority 1: the exact run script with this job_id
        for line in lines:
            if "run_cleanvideo_job.sh" in line and job_id in line:
                pid = int(line.split()[1])
                if _kill_pgid(pid):
                    return True

        # Priority 2: any pipeline stage process (LatentSync / VoxCPM2 / etc.)
        for line in lines:
            for marker in _PIPELINE_MARKERS:
                if marker in line:
                    pid = int(line.split()[1])
                    _kill_pgid(pid)
                    return True

        return False
    except Exception:
        return False


def start_job(job_id: str) -> int:
    job = load_job(job_id)
    script = RUN_VOICE_SCRIPT if job and job.get("output_type") == "voice_only" else RUN_SCRIPT
    proc = subprocess.Popen(
        ["bash", script, job_id],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return proc.pid
