import os
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from pathlib import PureWindowsPath

from settings import AI_WORKSPACE
from voice_store import load_voice_profile, save_voice_profile


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


def _set_failed(voice_id: str, message: str) -> None:
    profile = load_voice_profile(voice_id)
    if not profile:
        return
    profile["trainingStatus"] = "failed"
    profile["trainingFinishedAt"] = _now_iso()
    profile["trainingError"] = message
    save_voice_profile(profile)


def start_voice_training(voice_id: str) -> int:
    profile = load_voice_profile(voice_id)
    if not profile:
        raise RuntimeError(f"声音不存在：{voice_id}")

    script = Path(RUN_VOICE_TRAINING_SCRIPT)
    if not script.exists():
        message = f"训练脚本不存在：{script}"
        _set_failed(voice_id, message)
        raise RuntimeError(message)

    profile["trainingStatus"] = "training"
    profile["trainingStartedAt"] = _now_iso()
    profile["trainingError"] = None
    save_voice_profile(profile)

    if sys.platform.startswith("win"):
        app_workspace = _to_wsl_path(AI_WORKSPACE)
        script_path = _to_wsl_path(script)
        engine_workspace = os.getenv("DHJR_ENGINE_WORKSPACE", "/home/ryanrenjr/AI-Workspace")
        clean_script = f"/tmp/dhjr_train_{shlex.quote(voice_id)}_{script.name}"
        command = (
            f"cd {shlex.quote(app_workspace)} && "
            f"tr -d '\\r' < {shlex.quote(script_path)} > {clean_script} && "
            f"chmod +x {clean_script} && "
            f"DHJR_WORKSPACE={shlex.quote(app_workspace)} "
            f"DHJR_ENGINE_WORKSPACE={shlex.quote(engine_workspace)} "
            f"bash {clean_script} {shlex.quote(voice_id)}"
        )
        args = ["wsl", "bash", "-lc", command]
    else:
        args = ["bash", str(script), voice_id]

    proc = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    time.sleep(1.5)
    if proc.poll() is not None:
        message = f"训练脚本启动后立即退出，退出码：{proc.returncode}"
        _set_failed(voice_id, message)
        raise RuntimeError(message)
    return proc.pid
