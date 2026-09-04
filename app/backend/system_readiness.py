"""Lightweight checks for whether this machine can run the local pipeline."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path, PurePosixPath

from settings import (
    AI_WORKSPACE,
    CONDA_EXE,
    ENGINE_WORKSPACE,
    FFMPEG_CANDIDATES,
    FFPROBE_CANDIDATES,
    LATENTSYNC_ENV,
    MIN_FREE_DISK_BYTES,
    VOXCPM_ENV,
)

_CACHE_TTL_SECONDS = 45
_CACHE_LOCK = threading.Lock()
_CACHE: tuple[float, dict] | None = None


def _command_exists(command: str) -> bool:
    if Path(command).is_file():
        return True
    return shutil.which(command) is not None


def _runs(command: list[str], timeout: int = 8) -> bool:
    try:
        return subprocess.run(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=timeout, check=False,
        ).returncode == 0
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False


def _wsl_engine_root() -> PurePosixPath | None:
    configured = os.getenv("DHJR_ENGINE_WORKSPACE", "").strip()
    if not configured:
        return None
    if len(configured) >= 3 and configured[1] == ":":
        return PurePosixPath(f"/mnt/{configured[0].lower()}/{configured[3:].replace(chr(92), '/')}")
    return PurePosixPath(configured)


def _runtime_path_exists(path: Path, kind: str = "e") -> bool:
    if os.name != "nt":
        return path.exists()
    relative = PurePosixPath(path.relative_to(ENGINE_WORKSPACE).as_posix())
    root = _wsl_engine_root()
    # The wildcard is intentionally left unquoted so WSL expands the distro user.
    target = str(root / relative) if root else f"/home/*/AI-Workspace/{relative}"
    target_arg = target if target.startswith("/home/*/") else shlex.quote(target)
    return _runs(["wsl", "bash", "-lc", f"test -{kind} {target_arg}"])


def _wsl_command_exists(command: str) -> bool:
    return _runs(["wsl", "bash", "-lc", f"command -v {shlex.quote(command)} >/dev/null"])


def _wsl_conda_command_exists(environment: str, command: str) -> bool:
    if CONDA_EXE == "micromamba":
        call = [CONDA_EXE, "run", "-n", environment, command, "-version"]
        script = " ".join(shlex.quote(item) for item in call)
    else:
        call = [CONDA_EXE, "run", "--no-capture-output", "-n", environment, command, "-version"]
        script = (
            "source /home/*/miniconda3/etc/profile.d/conda.sh 2>/dev/null "
            "|| source /home/*/miniforge3/etc/profile.d/conda.sh 2>/dev/null "
            "|| source /home/*/mambaforge/etc/profile.d/conda.sh 2>/dev/null; "
            + " ".join(shlex.quote(item) for item in call)
        )
    return _runs(["wsl", "bash", "-lc", script], timeout=20)


def _conda_env_exists(name: str, conda_ok: bool) -> bool:
    if not conda_ok:
        return False
    command = [CONDA_EXE, "run", "--no-capture-output", "-n", name, "python", "--version"]
    if os.name == "nt" and not _command_exists(CONDA_EXE):
        script = (
            "source /home/*/miniconda3/etc/profile.d/conda.sh 2>/dev/null "
            "|| source /home/*/miniforge3/etc/profile.d/conda.sh 2>/dev/null "
            "|| source /home/*/mambaforge/etc/profile.d/conda.sh 2>/dev/null; "
            + " ".join(shlex.quote(item) for item in command)
        )
        return _runs(["wsl", "bash", "-lc", script], timeout=30)
    return _runs(command, timeout=20)


def _check(key: str, label: str, ok: bool, message: str, fix: str, required: bool = True) -> dict:
    return {
        "key": key,
        "label": label,
        "status": "ready" if ok else "missing",
        "message": message if ok else "缺少或无法使用",
        "fix": "" if ok else fix,
        "required": required,
    }


def get_readiness(force: bool = False) -> dict:
    return _get_readiness(force=force)


def _get_readiness(force: bool = False) -> dict:
    global _CACHE
    now = time.monotonic()
    with _CACHE_LOCK:
        if not force and _CACHE and now - _CACHE[0] < _CACHE_TTL_SECONDS:
            import copy
            return copy.deepcopy(_CACHE[1])

    checks = []
    checks.append(_check(
        "gpu", "GPU / CUDA",
        _command_exists("nvidia-smi") or _runs(["wsl", "nvidia-smi"]),
        "GPU 可用", "安装 NVIDIA 驱动并确认 WSL 可以访问 GPU。",
    ))
    checks.append(_check(
        "wsl", "WSL",
        not os.name == "nt" or _runs(["wsl", "--status"]),
        "WSL 可用", "安装并启动 WSL；Windows 用户需要用 WSL 运行模型脚本。",
    ))
    checks.append(_check(
        "ffmpeg", "FFmpeg",
        any(_command_exists(item) for item in FFMPEG_CANDIDATES)
        or (os.name == "nt" and (_wsl_conda_command_exists(LATENTSYNC_ENV, "ffmpeg") or _wsl_command_exists("ffmpeg"))),
        "媒体处理工具可用", "安装 FFmpeg，并将 ffmpeg 加入 PATH 或配置 DHJR_FFMPEG_CANDIDATES。",
    ))
    checks.append(_check(
        "ffprobe", "FFprobe",
        any(_command_exists(item) for item in FFPROBE_CANDIDATES)
        or (os.name == "nt" and (_wsl_conda_command_exists(LATENTSYNC_ENV, "ffprobe") or _wsl_command_exists("ffprobe"))),
        "媒体检测工具可用", "安装 FFmpeg（其中包含 ffprobe），或配置 DHJR_FFPROBE_CANDIDATES。",
    ))
    conda_ok = CONDA_EXE != "micromamba" and (
        (_command_exists(CONDA_EXE) and _runs([CONDA_EXE, "--version"]))
        or (os.name == "nt" and _runs(["wsl", "bash", "-lc", (
            "source /home/*/miniconda3/etc/profile.d/conda.sh 2>/dev/null "
            "|| source /home/*/miniforge3/etc/profile.d/conda.sh 2>/dev/null "
            "|| source /home/*/mambaforge/etc/profile.d/conda.sh 2>/dev/null; "
            "conda --version >/dev/null"
        )]))
    )
    checks.append(_check(
        "conda", "Conda / Miniconda / Miniforge",
        conda_ok,
        f"环境管理器可用（{CONDA_EXE}）",
        "请安装 Conda、Miniconda 或 Miniforge，并配置 DHJR_CONDA_EXE；当前暂不支持 Micromamba。",
    ))
    vox_dir = ENGINE_WORKSPACE / "projects" / "VoxCPM"
    checks.append(_check(
        "voxcpm", "VoxCPM",
        _runtime_path_exists(vox_dir, "d") and _conda_env_exists(VOXCPM_ENV, conda_ok),
        f"项目目录和环境 {VOXCPM_ENV} 已配置",
        f"确认 {vox_dir} 存在，并创建环境 {VOXCPM_ENV}。",
    ))
    latent_dir = ENGINE_WORKSPACE / "projects" / "LatentSync"
    latent_ckpt = latent_dir / "checkpoints" / "latentsync_unet.pt"
    checks.append(_check(
        "latentsync", "LatentSync",
        _runtime_path_exists(latent_dir, "d")
        and _runtime_path_exists(latent_ckpt)
        and _conda_env_exists(LATENTSYNC_ENV, conda_ok),
        f"项目、模型和环境 {LATENTSYNC_ENV} 已配置",
        f"确认 {latent_ckpt} 存在，并创建环境 {LATENTSYNC_ENV}。",
    ))
    checks.append(_check(
        "ollama", "本地模型服务",
        _command_exists("ollama"),
        "Ollama 可用", "安装 Ollama；不使用智能文案助手时可以暂时忽略。", required=False,
    ))
    try:
        free_bytes = shutil.disk_usage(AI_WORKSPACE).free
        disk_ok = free_bytes >= MIN_FREE_DISK_BYTES
        disk_message = f"剩余 {free_bytes / 1024 ** 3:.1f} GB"
    except OSError:
        free_bytes = 0
        disk_ok = False
        disk_message = "无法读取磁盘空间"
    checks.append(_check(
        "disk", "磁盘空间", disk_ok, disk_message,
        f"至少预留 {MIN_FREE_DISK_BYTES / 1024 ** 3:.0f} GB 可用空间。",
    ))

    required_ok = all(item["status"] == "ready" for item in checks if item["required"])
    result = {
        "ready": required_ok,
        "status": "ready" if required_ok else "missing",
        "checks": checks,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    with _CACHE_LOCK:
        _CACHE = (time.monotonic(), result)
    return result
