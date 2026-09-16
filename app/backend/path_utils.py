"""Cross-platform filesystem path conversion for host and WSL backends."""

import os
import re
from pathlib import Path


def windows_path_to_wsl(raw: str) -> str:
    drive = raw[0].lower()
    rest = raw[3:].replace("\\", "/")
    return f"/mnt/{drive}/{rest}"


def local_path(value: str | Path) -> Path:
    """Return a path usable by the process that is currently running."""
    raw = str(value or "")
    if os.name == "nt" and raw.startswith("/mnt/") and len(raw) > 7 and raw[6] == "/":
        drive = raw[5].upper()
        rest = raw[7:].replace("/", "\\")
        return Path(f"{drive}:\\{rest}")
    if os.name != "nt" and re.match(r"^[A-Za-z]:[\\/]", raw):
        return Path(windows_path_to_wsl(raw))
    return Path(raw)
