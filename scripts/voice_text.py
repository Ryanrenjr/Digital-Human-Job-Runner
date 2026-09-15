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


def _boundary_type(text: str, paragraph_end: bool) -> str:
    if paragraph_end:
        return "paragraph"
    ending = text.rstrip()[-1:] if text.rstrip() else ""
    return {
        "，": "comma",
        ",": "comma",
        "；": "semicolon",
        ";": "semicolon",
        "：": "colon",
        ":": "colon",
        "。": "sentence_end",
        "！": "exclamation",
        "!": "exclamation",
        "？": "question",
        "?": "question",
    }.get(ending, "technical_split")


def split_semantically_with_boundaries(text: str, max_chars: int = 90) -> list[dict]:
    """Return display text plus the reason for the following boundary."""
    normalized = normalize_for_speech(text)
    segments = split_semantically(normalized, max_chars)
    paragraph_endings = []
    paragraph_starts = []
    for paragraph in (p.strip() for p in re.split(r"\n{2,}", normalized) if p.strip()):
        lines = [line.strip() for line in paragraph.split("\n") if line.strip()]
        if lines:
            paragraph_endings.append(re.sub(r"[，,\s]", "", lines[-1]))
            paragraph_starts.append(re.sub(r"[，,\s]", "", lines[0]))

    output: list[dict] = []
    for index, segment in enumerate(segments):
        if index == len(segments) - 1:
            boundary = None
        else:
            compact_segment = re.sub(r"[，,\s]", "", segment)
            next_compact = re.sub(r"[，,\s]", "", segments[index + 1])
            is_paragraph_end = any(
                ending and compact_segment.endswith(ending)
                for ending in paragraph_endings
            ) or any(
                start and next_compact.startswith(start)
                for start in paragraph_starts[1:]
            )
            boundary = _boundary_type(segment, paragraph_end=is_paragraph_end)
        output.append({"text": segment, "boundaryAfter": boundary})
    return output
