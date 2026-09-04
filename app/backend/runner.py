import os
import signal
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from pathlib import PureWindowsPath
from typing import Optional

from job_store import list_jobs, load_job, save_job
from settings import AI_WORKSPACE, RUN_SCRIPT, RUN_VOICE_SCRIPT

_PIPELINE_MARKERS = [
    "run_02_latentsync_overlap.sh",
    "generate_voice_and_timeline_voxcpm2.py",
    "postprocess_voxcpm_segments_v12.py",
    "scripts.inference",
]


def check_no_other_running_job(job_id: str) -> Optional[str]:
    """Return the job_id of a running job that is NOT this job, or None."""
    for j in list_jobs():
        if j.get("status") in {"starting", "running", "collecting"} and j.get("job_id") != job_id:
            return j["job_id"]
    return None


def _ps_lines() -> list[str]:
    command = ["wsl", "ps", "aux"] if sys.platform.startswith("win") else ["ps", "aux"]
    result = subprocess.run(command, capture_output=True, text=True)
    return result.stdout.splitlines()


def is_job_process_running(job_id: str) -> bool:
    """
    Check whether a real pipeline process exists for job_id.

    Priority 1: run_cleanvideo_job.sh with this specific job_id in argv.
    Priority 2: any LatentSync / VoxCPM pipeline marker process — these
                don't carry the job_id but indicate a generation is active.
    Returns False on any exception so callers stay safe.
    """
    try:
        job = load_job(job_id)
        recorded_pid = job.get("launcher_pid") if job else None
        if recorded_pid:
            if sys.platform.startswith("win"):
                probe = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {int(recorded_pid)}", "/NH"],
                    capture_output=True, text=True, timeout=5,
                )
                if str(recorded_pid) in probe.stdout:
                    return True
            else:
                os.kill(int(recorded_pid), 0)
                return True
        lines = _ps_lines()

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
        job = load_job(job_id)
        recorded_pid = job.get("launcher_pid") if job else None
        if recorded_pid and sys.platform.startswith("win"):
            probe = subprocess.run(
                ["tasklist", "/FI", f"PID eq {int(recorded_pid)}", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            if str(recorded_pid) in probe.stdout:
                subprocess.run(
                    ["taskkill", "/PID", str(int(recorded_pid)), "/T", "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
                )
                return True
        lines = _ps_lines()

        def _kill_pgid(pid: int) -> bool:
            try:
                if sys.platform.startswith("win"):
                    subprocess.run(
                        [
                            "wsl",
                            "sh",
                            "-lc",
                            f"pgid=$(ps -o pgid= -p {pid} | awk '{{print $1}}'); "
                            f"[ -n \"$pgid\" ] && kill -TERM -\"$pgid\" 2>/dev/null || true; "
                            f"kill -TERM {pid} 2>/dev/null || true",
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=10,
                    )
                    return True
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


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _append_launcher_log(job: dict, message: str) -> None:
    log_path = Path(job.get("paths", {}).get("run_log", ""))
    if not log_path:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", errors="replace") as f:
        f.write(message.rstrip() + "\n")


def _mark_failed(job: dict, message: str) -> None:
    job["status"] = "failed"
    job["finished_at"] = _now_iso()
    job["error_message"] = message
    job.setdefault("progress", {})
    job["progress"]["stage"] = "failed"
    job["progress"]["percent"] = 0
    job["progress"]["message"] = message
    save_job(job)
    _append_launcher_log(job, f"[启动失败] {message}")


def _to_wsl_path(path: str | Path) -> str:
    raw = str(path)
    if len(raw) >= 3 and raw[1] == ":" and raw[2] in {"\\", "/"}:
        win_path = PureWindowsPath(raw)
        drive = win_path.drive.rstrip(":").lower()
        parts = "/".join(win_path.parts[1:])
        return f"/mnt/{drive}/{parts}"
    if raw.startswith("/"):
        return raw
    result = subprocess.run(
        ["wsl", "wslpath", "-a", raw],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Windows 路径转换到 WSL 路径失败。")
    return result.stdout.strip()


def _build_wsl_command(script: str, job_id: str) -> list[str]:
    app_workspace = _to_wsl_path(AI_WORKSPACE)
    script_path = _to_wsl_path(script)
    engine_workspace = os.getenv("DHJR_ENGINE_WORKSPACE", "")
    windows_output_dir = os.getenv("DHJR_WINDOWS_OUTPUT_DIR", f"{app_workspace}/exports")
    job_workspace = f"{app_workspace}/jobs/{job_id}"
    engine_expr = shlex.quote(engine_workspace) if engine_workspace else "$HOME/AI-Workspace"

    env = {
        "DHJR_WORKSPACE": app_workspace,
        "DHJR_JOBS_DIR": f"{app_workspace}/jobs",
        "DHJR_BACKGROUNDS_JSON": f"{app_workspace}/app/config/backgrounds.json",
        "DHJR_BACKGROUND_ASSETS_DIR": f"{app_workspace}/assets/backgrounds",
        "DHJR_INPUT_DIR": f"{job_workspace}/input",
        "DHJR_OUTPUT_DIR": f"{job_workspace}/output",
        "DHJR_JOB_WORKSPACE": f"{job_workspace}/workspace",
        "DHJR_JOB_WORK_DIR": f"{job_workspace}/work",
        "DHJR_AVATAR_VIDEO": f"{job_workspace}/input/avatar.mp4",
        "DHJR_WINDOWS_OUTPUT_DIR": windows_output_dir,
    }
    exports = " ".join(f"{key}={shlex.quote(value)}" for key, value in env.items())
    exports += f" DHJR_ENGINE_WORKSPACE={engine_expr}"
    clean_script = f"/tmp/dhjr_{shlex.quote(job_id)}_{Path(script).name}"
    command = (
        f"cd {shlex.quote(app_workspace)} && "
        f"tr -d '\\r' < {shlex.quote(script_path)} > {clean_script} && "
        f"chmod +x {clean_script} && "
        f"{exports} bash {clean_script} {shlex.quote(job_id)}"
    )
    return ["wsl", "bash", "-lc", command]


def _build_local_command(script: str, job_id: str) -> list[str]:
    return ["bash", script, job_id]


def _trained_voice_ready(job: dict) -> bool:
    voice_id = str(job.get("voice_id", ""))
    if not voice_id.startswith("voice_"):
        return True
    return (
        job.get("voice_training_status") == "finished"
        and bool(job.get("voice_checkpoint_path"))
    )


def start_job(job_id: str) -> int:
    job = load_job(job_id)
    if not job:
        raise RuntimeError(f"任务不存在：{job_id}")

    run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    job["status"] = "starting"
    job["run_id"] = run_id
    job["started_at"] = job.get("started_at") or _now_iso()
    job.setdefault("progress", {}).update({
        "stage": "starting",
        "percent": 0,
        "message": "正在启动任务",
    })
    save_job(job)

    if not _trained_voice_ready(job):
        message = "这个声音还没有完成后台训练，请先在“素材与训练”里完成声音训练；现在可以先选择“系统默认声音”测试视频生成。"
        _mark_failed(job, message)
        raise RuntimeError(message)

    script = RUN_VOICE_SCRIPT if job and job.get("output_type") == "voice_only" else RUN_SCRIPT
    if not Path(script).exists():
        message = f"运行脚本不存在：{script}"
        _mark_failed(job, message)
        raise RuntimeError(message)

    try:
        command = _build_wsl_command(script, job_id) if sys.platform.startswith("win") else _build_local_command(script, job_id)
    except Exception as exc:
        message = str(exc)
        _mark_failed(job, message)
        raise RuntimeError(message)
    _append_launcher_log(job, f"[启动] {' '.join(command)}")

    proc = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    job = load_job(job_id) or job
    job["launcher_pid"] = proc.pid
    job["process_group_id"] = proc.pid
    save_job(job)
    time.sleep(1.5)
    if proc.poll() is not None:
        log_path = Path(job.get("paths", {}).get("run_log", ""))
        detail = ""
        if log_path.exists():
            detail = "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-40:])
        message = detail[-1200:] if detail else f"运行脚本启动后立即退出，退出码：{proc.returncode}"
        latest = load_job(job_id) or job
        if latest.get("status") not in {"failed", "running", "finished"}:
            _mark_failed(latest, message)
        else:
            _append_launcher_log(latest, f"[启动进程退出] {message}")
        raise RuntimeError(message)
    return proc.pid
