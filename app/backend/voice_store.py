import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from settings import AI_WORKSPACE


VOICES_DIR = AI_WORKSPACE / "voices"


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip()).strip("_").lower()
    return slug or "voice"


def make_voice_id(name: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"voice_{stamp}_{slugify(name)}"


def profile_path(voice_id: str) -> Path:
    return VOICES_DIR / voice_id / "profile.json"


def load_voice_profile(voice_id: str) -> Optional[dict]:
    path = profile_path(voice_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_voice_profile(profile: dict) -> dict:
    voice_id = profile["id"]
    path = profile_path(voice_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return profile


def list_voice_profiles() -> list[dict]:
    profiles = []
    for path in VOICES_DIR.glob("*/profile.json"):
        try:
            profiles.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    profiles.sort(key=lambda item: item.get("createdAt", ""), reverse=True)
    return profiles
