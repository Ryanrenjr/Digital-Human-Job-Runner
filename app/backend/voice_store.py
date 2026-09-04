import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from database import delete_voice as db_delete_voice
from database import get_voice, list_voices as db_list_voices, upsert_voice
from settings import AI_WORKSPACE


VOICES_DIR = AI_WORKSPACE / "voices"


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip()).strip("_").lower()
    return slug or "voice"


def make_voice_id(name: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return f"voice_{stamp}_{slugify(name)}"


def profile_path(voice_id: str) -> Path:
    return VOICES_DIR / voice_id / "profile.json"


def load_voice_profile(voice_id: str) -> Optional[dict]:
    profile = get_voice(voice_id)
    if profile is not None:
        return profile
    path = profile_path(voice_id)
    if not path.exists():
        return None
    profile = json.loads(path.read_text(encoding="utf-8"))
    upsert_voice(profile)
    return profile


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
    profiles = {profile.get("id"): profile for profile in db_list_voices()}
    for path in VOICES_DIR.glob("*/profile.json"):
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
            if profile.get("id") not in profiles:
                upsert_voice(profile)
                profiles[profile.get("id")] = profile
        except Exception:
            continue
    return sorted(profiles.values(), key=lambda item: item.get("createdAt", ""), reverse=True)


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
