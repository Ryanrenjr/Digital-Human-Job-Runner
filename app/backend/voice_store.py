import json
import re
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from database import delete_voice as db_delete_voice
from database import get_voice, list_voices as db_list_voices, upsert_voice
from settings import AI_WORKSPACE


VOICES_DIR = AI_WORKSPACE / "voices"
logger = logging.getLogger(__name__)


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip()).strip("_").lower()
    return slug or "voice"


def make_voice_id(name: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return f"voice_{stamp}_{slugify(name)}"


def migrate_legacy_voice_profiles() -> None:
    """Import legacy profile mirrors during application startup only."""
    VOICES_DIR.mkdir(parents=True, exist_ok=True)
    known = {profile.get("id") for profile in db_list_voices()}
    for path in VOICES_DIR.glob("*/profile.json"):
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
            voice_id = profile.get("id")
            if voice_id and voice_id not in known:
                upsert_voice(profile)
                known.add(voice_id)
        except Exception as exc:
            logger.warning("Skipping legacy voice profile %s: %s", path, exc)


def profile_path(voice_id: str) -> Path:
    return VOICES_DIR / voice_id / "profile.json"


def load_voice_profile(voice_id: str) -> Optional[dict]:
    return get_voice(voice_id)


def save_voice_profile(profile: dict) -> dict:
    voice_id = profile["id"]
    path = profile_path(voice_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    upsert_voice(profile)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
    return profile


def list_voice_profiles() -> list[dict]:
    return sorted(db_list_voices(), key=lambda item: item.get("createdAt", ""), reverse=True)


def delete_voice_profile(voice_id: str) -> None:
    """Remove the profile index and its raw/checkpoint files."""
    path = profile_path(voice_id)
    voice_dir = VOICES_DIR / voice_id
    if path.exists():
        path.unlink()
    db_delete_voice(voice_id)
    if voice_dir.exists():
        import shutil
        shutil.rmtree(voice_dir)
