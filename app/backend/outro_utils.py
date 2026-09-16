"""Configured end cards that can be snapshotted into a video job."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from path_utils import local_path
from settings import AI_WORKSPACE, OUTRO_ASSETS_DIR, OUTROS_JSON


def load_outros() -> list[dict]:
    if not OUTROS_JSON.exists():
        return []
    try:
        data = json.loads(OUTROS_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in data if isinstance(item, dict) and item.get("id") and item.get("path")]


def save_outros(outros: list[dict]) -> None:
    OUTROS_JSON.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = OUTROS_JSON.with_suffix(f"{OUTROS_JSON.suffix}.tmp")
    tmp_path.write_text(json.dumps(outros, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(OUTROS_JSON)


def make_outro_id(filename: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9_\u4e00-\u9fff]+", "_", Path(filename).stem).strip("_")[:36]
    stem = stem or "outro"
    return f"custom_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}_{stem}"


def get_outro_by_id(outro_id: str) -> Optional[dict]:
    return next((item for item in load_outros() if item.get("id") == outro_id), None)


def resolve_outro_path(outro: dict) -> Path:
    raw = str(outro.get("path", ""))
    path = Path(raw)
    if not path.is_absolute():
        path = AI_WORKSPACE / path
    return local_path(path)


def is_managed_outro_path(path: Path) -> bool:
    """Only delete files stored inside the configured outro asset directory."""
    try:
        path.resolve().relative_to(OUTRO_ASSETS_DIR.resolve())
        return True
    except ValueError:
        return False
