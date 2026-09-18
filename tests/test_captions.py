import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from render_captions import (  # noqa: E402
    ass_time,
    build_ass,
    normalize_caption_items,
    split_caption_text,
)


class CaptionRenderingTests(unittest.TestCase):
    def test_ass_time_uses_centiseconds(self):
        self.assertEqual(ass_time(0), "0:00:00.00")
        self.assertEqual(ass_time(61.239), "0:01:01.24")

    def test_long_chinese_text_wraps_without_changing_content(self):
        text = "这是一个比较长的字幕句子，用来检查换行不会丢失正文。"
        chunks = split_caption_text(text, 10)
        self.assertGreater(len(chunks), 1)
        self.assertEqual("".join(chunks), text)

    def test_caption_prefers_one_line_and_never_exceeds_two_lines(self):
        self.assertEqual(split_caption_text("这是一句短字幕。"), ["这是一句短字幕。"])
        chunks = split_caption_text("这是一段适合短视频的较长字幕，需要清楚易读。", 13)
        self.assertTrue(all(r"\N" not in chunk for chunk in chunks))
        self.assertTrue(all(len(chunk) <= 15 for chunk in chunks))
        self.assertEqual("".join(chunks), "这是一段适合短视频的较长字幕，需要清楚易读。")

    def test_caption_does_not_split_common_two_character_words(self):
        chunks = split_caption_text("测试数字人口播和自动字幕的实际效果。", 13)
        self.assertEqual("".join(chunks), "测试数字人口播和自动字幕的实际效果。")
        self.assertNotIn("自", [chunk[-1] for chunk in chunks[:-1]])

    def test_caption_does_not_split_latin_words(self):
        chunks = split_caption_text(
            "父母其中一方已经是British citizen，孩子通常会自动成为英国公民。",
            13,
        )
        self.assertEqual(
            "".join(chunks).replace(" ", ""),
            "父母其中一方已经是British citizen，孩子通常会自动成为英国公民。".replace(" ", ""),
        )
        latin_words = [word for chunk in chunks for word in re.findall(r"[A-Za-z0-9]+", chunk)]
        self.assertIn("British", latin_words)
        self.assertIn("citizen", latin_words)
        self.assertNotIn("Briti", latin_words)
        self.assertNotIn("citiz", latin_words)

    def test_caption_keeps_common_two_word_terms_together(self):
        chunks = split_caption_text(
            "目前这种British citizenship registration申请需要准备材料。",
            13,
        )
        self.assertIn("British citizenship", chunks)

    def test_caption_moves_leading_punctuation_to_previous_event(self):
        normalized = normalize_caption_items([
            {"start": 0, "end": 1, "text": "第一句"},
            {"start": 1, "end": 2, "text": "”，第二句"},
        ])
        self.assertEqual(normalized[0]["text"], "第一句”，")
        self.assertEqual(normalized[1]["text"], "第二句")

    def test_ass_uses_configured_font_and_clean_caption_text(self):
        text = "这是字幕正文，不是控制指令。"
        ass = build_ass(
            [{"start": 0, "end": 2.5, "text": text}],
            font_name="Noto Sans CJK SC",
            width=720,
            height=1280,
        )
        self.assertIn("Style: Default,Noto Sans CJK SC", ass)
        self.assertIn(text, ass.replace(r"\N", ""))
        self.assertNotIn("(专业", ass)

    def test_ass_line_break_is_not_rendered_as_visible_text(self):
        ass = build_ass(
            [{"start": 0, "end": 2.5, "text": "第一句内容很长，需要换行显示，确保字幕不会挤成一整行。"}],
            font_name="Noto Sans CJK SC",
            width=720,
            height=1280,
        )
        self.assertNotIn(r"\N", ass)
        self.assertNotIn(r"\\N", ass)

    def test_ass_does_not_start_dialogue_with_closing_punctuation(self):
        ass = build_ass(
            [
                {"start": 0, "end": 1, "text": "第一句"},
                {"start": 1, "end": 2, "text": "，第二句"},
            ],
            font_name="Noto Sans CJK SC",
            width=720,
            height=1280,
        )
        self.assertNotIn("}，", ass)

    def test_invalid_caption_window_is_skipped(self):
        ass = build_ass(
            [{"start": 2, "end": 1, "text": "不会显示"}],
            font_name="Noto Sans CJK SC",
            width=720,
            height=1280,
        )
        self.assertNotIn("不会显示", ass)


if __name__ == "__main__":
    unittest.main()
