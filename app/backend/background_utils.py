import json
import logging
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional
from settings import BACKGROUND_ASSETS_DIR, BACKGROUNDS_JSON, CUSTOM_BACKGROUNDS_DIR, FFMPEG_CANDIDATES, THUMBNAILS_DIR

logger = logging.getLogger(__name__)

BUILTIN_DIR = BACKGROUND_ASSETS_DIR
CUSTOM_DIR = CUSTOM_BACKGROUNDS_DIR


def _find_ffmpeg() -> str:
    for candidate in FFMPEG_CANDIDATES:
        try:
            r = subprocess.run([candidate, "-version"], capture_output=True, timeout=5)
            if r.returncode == 0:
                return candidate
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    return ""


def _ensure_dirs():
    CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
    THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)


def generate_thumbnail(bg: dict) -> bool:
    """Generate thumbnail jpg for a background. Non-fatal on failure."""
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        logger.warning("ffmpeg not found — skipping thumbnail for %s", bg.get("id"))
        return False

    src = Path(bg.get("path", ""))
    dst = Path(bg.get("thumbnail_path", ""))
    if not src or not dst:
        return False
    if not src.exists():
        logger.warning("Source video not found: %s", src)
        return False

    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(
            [ffmpeg, "-y", "-ss", "00:00:01", "-i", str(src),
             "-frames:v", "1", "-q:v", "2", str(dst)],
            capture_output=True, timeout=30,
        )
        if r.returncode == 0 and dst.exists():
            logger.info("Thumbnail generated: %s", dst)
            return True
        logger.warning(
            "ffmpeg thumbnail failed for %s: %s",
            bg.get("id"),
            r.stderr.decode("utf-8", errors="replace")[:300],
        )
        return False
    except Exception as e:
        logger.warning("Thumbnail error for %s: %s", bg.get("id"), e)
        return False


def load_backgrounds() -> list:
    """Load backgrounds.json, auto-upgrading legacy entries to V1.3 structure."""
    _ensure_dirs()
    if not BACKGROUNDS_JSON.exists():
        return []
    try:
        bgs = json.loads(BACKGROUNDS_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error("Failed to read backgrounds.json: %s", e)
        return []

    changed = False
    for bg in bgs:
        bid = bg.get("id", "")
        if "type" not in bg:
            bg["type"] = "builtin"; changed = True
        if "thumbnail_path" not in bg:
            bg["thumbnail_path"] = str(THUMBNAILS_DIR / f"{bid}.jpg"); changed = True
        if "preview_url" not in bg:
            bg["preview_url"] = f"/backgrounds/{bid}/preview"; changed = True
        if "thumbnail_url" not in bg:
            bg["thumbnail_url"] = f"/backgrounds/{bid}/thumbnail"; changed = True

    if changed:
        save_backgrounds(bgs)
    return bgs


def save_backgrounds(bgs: list) -> None:
    BACKGROUNDS_JSON.write_text(
        json.dumps(bgs, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def get_background_by_id(bg_id: str) -> Optional[dict]:
    for bg in load_backgrounds():
        if bg.get("id") == bg_id:
            return bg
    return None


def make_background_id(filename: str) -> str:
    stem = Path(filename).stem
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", stem)[:30].strip("_") or "video"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"custom_{ts}_{safe}"
