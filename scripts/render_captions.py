#!/usr/bin/env python3
"""Build a readable ASS subtitle track from the generated voice timeline."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


COMMON_WORD_PAIRS = frozenset({
    "自动", "字幕", "口播", "视频", "工具", "生成", "速度", "声音", "画面",
    "彼此", "配合", "复杂", "处理", "后台", "简单", "明确", "选择", "用户",
    "无论", "介绍", "产品", "分享", "知识", "记录", "想法", "轻松", "完成",
    "观察", "连贯", "停顿", "自然", "以及", "阅读", "习惯", "效果", "实际",
})


def ass_time(seconds: float) -> str:
    total_cs = max(0, round(float(seconds) * 100))
    hours, remainder = divmod(total_cs, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"


def _escape_ass_text(text: str) -> str:
    # Keep ASS's intentional line-break token while protecting override tags.
    line_break = "\u0000"
    return (
        text.replace(r"\N", line_break)
        .replace("\\", "\\\\")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace(line_break, r"\N")
    )


def _pick_caption_break(text: str, target: int, max_chars: int) -> int:
    """Pick a natural single-line chunk, preferring punctuation near its end."""
    punctuation = set("，。！？；：,.!?;:")
    # A small soft overflow keeps short Chinese phrases intact while keeping
    # the normal line length close to the 10-13 character target.
    upper_bound = min(len(text) - 1, max_chars + 2)
    candidates = [
        index + 1
        for index, char in enumerate(text[:upper_bound])
        if char in punctuation and index + 1 >= 4
    ]
    if candidates:
        target = max(candidates)
    else:
        target = max(1, min(len(text) - 1, target, max_chars))
    # Move a forced break by one character when it would split a common word.
    for candidate in (target, target - 1, target + 1, target - 2, target + 2):
        if 4 <= candidate < len(text) and text[candidate - 1:candidate + 1] not in COMMON_WORD_PAIRS:
            return candidate
    return target


def split_caption_text(text: str, max_chars: int = 13) -> list[str]:
    """Split a long caption into readable single-line chunks."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    chunks: list[str] = []
    while text:
        if len(text) <= max_chars + 2:
            chunks.append(text)
            break
        break_at = _pick_caption_break(text, round(len(text) / 2), max_chars)
        chunks.append(text[:break_at].strip())
        text = text[break_at:].strip()
        # Punctuation belongs to the preceding chunk, never the next one.
        while text and text[0] in set("，。！？；：、,.!?;:") and chunks:
            chunks[-1] += text[0]
            text = text[1:].lstrip()
    return [chunk for chunk in chunks if chunk]


def wrap_caption(text: str, max_chars: int = 13) -> str:
    """Compatibility helper: captions are now always emitted as one line."""
    return str(text or "").strip()


def _caption_events(start: float, end: float, text: str, max_chars: int) -> list[tuple[float, float, str]]:
    chunks = split_caption_text(text, max_chars)
    if not chunks:
        return []
    total_chars = sum(len(chunk) for chunk in chunks)
    duration = max(0.01, end - start)
    events: list[tuple[float, float, str]] = []
    cursor = start
    for index, chunk in enumerate(chunks):
        if index == len(chunks) - 1:
            chunk_end = end
        else:
            chunk_end = cursor + duration * len(chunk) / total_chars
        events.append((cursor, chunk_end, chunk))
        cursor = chunk_end
    return events


def build_ass(captions: list[dict], *, font_name: str, width: int, height: int) -> str:
    font_size = max(36, round(height * 0.04))
    margin_v = max(82, round(height * 0.105))
    # Short-video captions are always single-line; longer voice segments are
    # divided into timed caption events below.
    max_chars = 13 if width <= 900 else 20
    events: list[str] = []
    for item in captions:
        try:
            start = float(item.get("start", 0))
            end = float(item.get("end", 0))
        except (TypeError, ValueError):
            continue
        text = str(item.get("text") or item.get("speechText") or "").strip()
        if not text or end <= start:
            continue
        for event_start, event_end, chunk in _caption_events(start, end, text, max_chars):
            events.append(
                f"Dialogue: 0,{ass_time(event_start)},{ass_time(event_end)},Default,,0,0,0,,{{\\fad(80,80)}}{_escape_ass_text(chunk)}"
            )

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes
WrapStyle: 2
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},&H00FFFFFF,&H00FFFFFF,&H00101010,&HFF080808,1,0,0,0,100,100,0,0,1,4,2,2,44,44,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    return header + "\n".join(events) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("captions_json", type=Path)
    parser.add_argument("output_ass", type=Path)
    parser.add_argument("--font-name", default="Noto Sans CJK SC")
    parser.add_argument("--width", type=int, default=720)
    parser.add_argument("--height", type=int, default=1280)
    args = parser.parse_args()

    data = json.loads(args.captions_json.read_text(encoding="utf-8"))
    captions = data.get("captions") or []
    if not captions:
        raise ValueError(f"captions.json contains no captions: {args.captions_json}")
    ass = build_ass(captions, font_name=args.font_name, width=args.width, height=args.height)
    args.output_ass.parent.mkdir(parents=True, exist_ok=True)
    args.output_ass.write_text(ass, encoding="utf-8")
    print(f"[INFO] wrote {len(captions)} caption events to {args.output_ass}")
    print(f"[INFO] caption font: {args.font_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
