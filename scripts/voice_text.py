"""Text preparation shared by voice generation and its tests."""

from __future__ import annotations

import re


def normalize_for_speech(text: str) -> str:
    """Apply only safe substitutions; VoxCPM2 performs the full normalization."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(\d+(?:\.\d+)?)%", r"百分之\1", text)
    text = text.replace("&", "和")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_semantically(text: str, max_chars: int = 90) -> list[str]:
    """Prefer sentence/phrase boundaries, then split only long clauses."""
    text = normalize_for_speech(text)
    chunks: list[str] = []
    for paragraph in (p.strip() for p in text.split("\n") if p.strip()):
        chunks.extend(re.findall(r"[^。！？!?，,；;：:\n]+[。！？!?，,；;：:]?", paragraph))

    result: list[str] = []
    buffer = ""

    def join(left: str, right: str) -> str:
        if not left or not right:
            return left + right
        if re.search(r"[。！？!?，,；;：:]$", left) or re.match(r"^[。！？!?，,；;：:]", right):
            return left + right
        return left + "，" + right

    for raw in chunks:
        chunk = raw.strip()
        if not chunk:
            continue
        if len(chunk) > max_chars:
            if buffer:
                result.append(buffer)
                buffer = ""
            result.extend(chunk[i:i + max_chars].strip() for i in range(0, len(chunk), max_chars))
            continue
        candidate = join(buffer, chunk) if buffer else chunk
        if buffer and len(candidate) > max_chars:
            result.append(buffer)
            buffer = chunk
        else:
            buffer = candidate
        if re.search(r"[。！？!?]$", chunk) and len(buffer) >= 18:
            result.append(buffer)
            buffer = ""
    if buffer:
        result.append(buffer)
    return [item for item in result if item]
