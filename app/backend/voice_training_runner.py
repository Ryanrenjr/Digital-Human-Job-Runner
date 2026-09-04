import os
import json
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from pathlib import PureWindowsPath

from settings import AI_WORKSPACE, CONDA_EXE, ENGINE_WORKSPACE, VOXCPM_ENV
from database import claim_gpu_lease, release_gpu_lease
from voice_store import list_voice_profiles, load_voice_profile, save_voice_profile


RUN_VOICE_TRAINING_SCRIPT = os.getenv(
    "DHJR_RUN_VOICE_TRAINING_SCRIPT",
    str(AI_WORKSPACE / "scripts/run_voice_training.sh"),
)


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _to_wsl_path(path: str | Path) -> str:
    raw = str(path)
    if len(raw) >= 3 and raw[1] == ":" and raw[2] in {"\\", "/"}:
        win_path = PureWindowsPath(raw)
        drive = win_path.drive.rstrip(":").lower()
        parts = "/".join(win_path.parts[1:])
        return f"/mnt/{drive}/{parts}"
    return raw


def _host_path(path: str | Path) -> Path:
    raw = str(path or "")
    if raw.startswith("/mnt/") and len(raw) > 7 and raw[6] == "/":
        rest = raw[7:].replace("/", "\\")
        return Path(f"{raw[5].upper()}:\\{rest}")
    return Path(raw)


def _run_metadata(profile: dict | None) -> dict:
    if not profile:
        return {}
    path = _host_path(profile.get("trainingRunMetadata", ""))
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def is_voice_training_process_running(voice_id: str) -> bool:
    profile = load_voice_profile(voice_id)
    if not profile:
        return False
    metadata = _run_metadata(profile)
    pgid = metadata.get("wsl_pgid")
    try:
        if sys.platform.startswith("win") and pgid:
            return subprocess.run(
                ["wsl", "bash", "-lc", f"kill -0 -- -{int(pgid)} 2>/dev/null"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
            ).returncode == 0
        pid = profile.get("trainingPid")
        if pid:
            os.kill(int(pid), 0)
            return True
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False
    return False


def _set_failed(voice_id: str, message: str, run_id: str | None = None) -> bool:
    profile = load_voice_profile(voice_id)
    if not profile:
        return False
    if run_id is not None and profile.get("trainingRunId") != run_id:
        return False
    profile["trainingStatus"] = "failed"
    profile["trainingFinishedAt"] = _now_iso()
    profile["trainingError"] = message
    profile["trainingPid"] = None
    profile["trainingProcessGroupId"] = None
    save_voice_profile(profile)
    release_gpu_lease("voice_training", voice_id, run_id)
    return True


class GpuBusyError(RuntimeError):
    pass


def recover_stale_voice_training() -> None:
    """Mark training records failed when their exact process is gone at startup."""
    for profile in list_voice_profiles():
        if profile.get("trainingStatus") != "training":
            continue
        voice_id = profile.get("id")
        if voice_id and not is_voice_training_process_running(voice_id):
            _set_failed(voice_id, "声音训练进程未找到，已恢复为失败状态。", profile.get("trainingRunId"))


def start_voice_training(voice_id: str) -> int:
    profile = load_voice_profile(voice_id)
    if not profile:
        raise RuntimeError(f"声音不存在：{voice_id}")

    if profile.get("trainingStatus") in {"queued", "training", "training_requested"}:
        if profile.get("trainingStatus") == "training" and is_voice_training_process_running(voice_id):
            raise GpuBusyError("这个声音正在训练中，请等待当前训练结束。")
        if profile.get("trainingStatus") == "training":
            _set_failed(voice_id, "检测到上一次训练进程已退出，请重新启动训练。", profile.get("trainingRunId"))

    script = Path(RUN_VOICE_TRAINING_SCRIPT)
    if not script.exists():
        message = f"训练脚本不存在：{script}"
        _set_failed(voice_id, message)
        raise RuntimeError(message)

    run_id = f"voice_run_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    lease = claim_gpu_lease("voice_training", voice_id, run_id, _now_iso())
    if not lease.get("claimed"):
        raise GpuBusyError(f"GPU 正在执行另一个任务：{lease.get('owner_id', '未知任务')}。")

    profile["trainingStatus"] = "training"
    profile["trainingRunId"] = run_id
    profile["trainingRunMetadata"] = str(AI_WORKSPACE / "voices" / voice_id / "run.json")
    profile["trainingStartedAt"] = _now_iso()
    profile["trainingFinishedAt"] = None
    profile["trainingError"] = None
    profile["checkpointPath"] = None
    profile["referenceWavPath"] = None
    profile["referenceText"] = ""
    profile["trainingPid"] = None
    profile["trainingProcessGroupId"] = None
    save_voice_profile(profile)

    if sys.platform.startswith("win"):
        app_workspace = _to_wsl_path(AI_WORKSPACE)
        script_path = _to_wsl_path(script)
        engine_workspace = os.getenv("DHJR_ENGINE_WORKSPACE", "").strip()
        engine_expr = shlex.quote(_to_wsl_path(engine_workspace)) if engine_workspace else "$HOME/AI-Workspace"
        clean_script = f"/tmp/dhjr_train_{shlex.quote(voice_id)}_{script.name}"
        database_expr = (
            f"DHJR_DATABASE_PATH={shlex.quote(_to_wsl_path(os.environ['DHJR_DATABASE_PATH']))} "
            if os.environ.get("DHJR_DATABASE_PATH") else ""
        )
        command = (
            f"cd {shlex.quote(app_workspace)} && "
            f"tr -d '\\r' < {shlex.quote(script_path)} > {clean_script} && "
            f"chmod +x {clean_script} && "
            f"DHJR_WORKSPACE={shlex.quote(app_workspace)} "
            f"DHJR_ENGINE_WORKSPACE={engine_expr} "
            f"DHJR_CONDA_EXE={shlex.quote(CONDA_EXE)} "
            f"DHJR_VOXCPM_ENV={shlex.quote(VOXCPM_ENV)} "
            f"DHJR_TRAINING_RUN_ID={shlex.quote(run_id)} "
            f"DHJR_VOICE_RUN_METADATA={shlex.quote(_to_wsl_path(profile['trainingRunMetadata']))} "
            f"{database_expr}"
            f"bash {clean_script} {shlex.quote(voice_id)}"
        )
        args = ["wsl", "bash", "-lc", command]
    else:
        args = [
            "env",
            f"DHJR_TRAINING_RUN_ID={run_id}",
            f"DHJR_VOICE_RUN_METADATA={profile['trainingRunMetadata']}",
            f"DHJR_WORKSPACE={AI_WORKSPACE}",
            f"DHJR_ENGINE_WORKSPACE={ENGINE_WORKSPACE}",
            f"DHJR_CONDA_EXE={CONDA_EXE}",
            f"DHJR_VOXCPM_ENV={VOXCPM_ENV}",
            "bash", str(script), voice_id,
        ]

    try:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:
        _set_failed(voice_id, f"无法启动声音训练进程：{exc}", run_id)
        raise RuntimeError(f"无法启动声音训练进程：{exc}") from exc

    current = load_voice_profile(voice_id) or profile
    if current.get("trainingStatus") != "training" or current.get("trainingRunId") != run_id:
        try:
            proc.kill()
        except OSError:
            pass
        release_gpu_lease("voice_training", voice_id, run_id)
        raise RuntimeError("声音训练状态在启动期间发生变化。")
    current["trainingPid"] = proc.pid
    current["trainingProcessGroupId"] = proc.pid
    save_voice_profile(current)
    time.sleep(1.5)
    if proc.poll() is not None:
        message = f"训练脚本启动后立即退出，退出码：{proc.returncode}"
        _set_failed(voice_id, message, run_id)
        raise RuntimeError(message)
    return proc.pid
