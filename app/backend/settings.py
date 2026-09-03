import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_env_file(ENV_FILE)

APP_NAME = os.getenv("DHJR_APP_NAME", "Digital Human Job Runner")
APP_VERSION = os.getenv("DHJR_APP_VERSION", "0.2.0")

AI_WORKSPACE = Path(
    os.getenv("DHJR_WORKSPACE", str(Path.home() / "AI-Workspace"))
).expanduser()

INPUT_DIR = Path(os.getenv("DHJR_INPUT_DIR", str(AI_WORKSPACE / "DigitalHumanInput"))).expanduser()
OUTPUT_DIR = Path(os.getenv("DHJR_OUTPUT_DIR", str(AI_WORKSPACE / "DigitalHumanOutput"))).expanduser()
JOBS_DIR = Path(os.getenv("DHJR_JOBS_DIR", str(AI_WORKSPACE / "jobs"))).expanduser()
LOGS_DIR = Path(os.getenv("DHJR_LOGS_DIR", str(AI_WORKSPACE / "logs"))).expanduser()

BACKGROUNDS_JSON = Path(
    os.getenv("DHJR_BACKGROUNDS_JSON", str(AI_WORKSPACE / "app/config/backgrounds.json"))
).expanduser()
BACKGROUND_ASSETS_DIR = Path(
    os.getenv("DHJR_BACKGROUND_ASSETS_DIR", str(AI_WORKSPACE / "assets/backgrounds"))
).expanduser()
CUSTOM_BACKGROUNDS_DIR = BACKGROUND_ASSETS_DIR / "custom"
THUMBNAILS_DIR = BACKGROUND_ASSETS_DIR / "thumbnails"

DEFAULT_AVATAR_VIDEO = Path(
    os.getenv(
        "DHJR_DEFAULT_AVATAR_VIDEO",
        str(AI_WORKSPACE / "VideoRefs/boss/default/boss_default.mp4"),
    )
).expanduser()

DEFAULT_VOICE_ID = os.getenv("DHJR_DEFAULT_VOICE_ID", "default_voice")
LEGACY_VOICE_IDS = {
    v.strip()
    for v in os.getenv("DHJR_LEGACY_VOICE_IDS", "boss_voxcpm2_lora").split(",")
    if v.strip()
}
SUPPORTED_VOICE_IDS = {
    v.strip()
    for v in os.getenv("DHJR_SUPPORTED_VOICE_IDS", DEFAULT_VOICE_ID).split(",")
    if v.strip()
}
SUPPORTED_VOICE_IDS.add(DEFAULT_VOICE_ID)
SUPPORTED_VOICE_IDS.update(LEGACY_VOICE_IDS)

WINDOWS_OUTPUT_DIR = Path(
    os.getenv("DHJR_WINDOWS_OUTPUT_DIR", "/mnt/c/Users/rjxxx/Desktop/DigitalHumanOutput")
).expanduser()

RUN_SCRIPT = os.getenv("DHJR_RUN_SCRIPT", str(AI_WORKSPACE / "scripts/run_cleanvideo_job.sh"))
RUN_VOICE_SCRIPT = os.getenv("DHJR_RUN_VOICE_SCRIPT", str(AI_WORKSPACE / "scripts/run_voice_only_job.sh"))

VITE_FRONTEND_ORIGIN = os.getenv("DHJR_FRONTEND_ORIGIN", "http://127.0.0.1:5173")
EXTRA_CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("DHJR_EXTRA_CORS_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]
EXTRA_CORS_ORIGINS.extend([
    "http://127.0.0.1:5178",
    "http://localhost:5178",
])

FFMPEG_CANDIDATES = [
    c.strip()
    for c in os.getenv(
        "DHJR_FFMPEG_CANDIDATES",
        f"ffmpeg,{Path.home() / 'miniconda3/envs/latentsync/bin/ffmpeg'}",
    ).split(",")
    if c.strip()
]

FFPROBE_CANDIDATES = [
    c.strip()
    for c in os.getenv(
        "DHJR_FFPROBE_CANDIDATES",
        f"ffprobe,{Path.home() / 'miniconda3/envs/latentsync/bin/ffprobe'}",
    ).split(",")
    if c.strip()
]

LATENTSYNC_WORK_DIR = Path(
    os.getenv("DHJR_LATENTSYNC_WORK_DIR", str(AI_WORKSPACE / "projects/LatentSync/data/overlap_full_work"))
).expanduser()

SHUTDOWN_EXE = os.getenv("DHJR_SHUTDOWN_EXE", "/mnt/c/Windows/System32/shutdown.exe")
