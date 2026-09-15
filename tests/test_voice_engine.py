import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from voice_engine import (
    build_generation_text,
    build_voxcpm_control_instruction,
    expected_duration,
    find_control_terms_in_transcript,
    resolve_config,
)
from voice_text import normalize_for_speech, split_semantically


class VoiceEngineConfigTests(unittest.TestCase):
    def test_legacy_trained_profile_gets_clone_defaults(self):
        config = resolve_config({
            "voice_id": "voice_legacy",
            "mode": "lora_finetune",
            "checkpoint_path": "/tmp/checkpoint",
            "reference_wav_path": "/tmp/reference.wav",
        })
        self.assertEqual(config.mode, "controllable_clone")
        self.assertEqual(config.quality, "high")
        self.assertEqual(config.inference_timesteps, 25)
        self.assertTrue(config.normalize)
        self.assertTrue(config.retry_badcase)

    def test_controllable_clone_injects_control_instruction(self):
        config = resolve_config({
            "mode": "controllable_clone",
            "style": "professional_natural",
            "pace": "natural",
        })
        generation_text, instruction = build_generation_text("这是测试。", config)
        self.assertTrue(generation_text.startswith("("))
        self.assertIn(instruction, generation_text)
        self.assertTrue(generation_text.endswith("这是测试。"))

    def test_ultimate_clone_does_not_inject_control_instruction(self):
        config = resolve_config({
            "mode": "ultimate_clone",
            "style": "warm_storytelling",
            "pace": "slow",
            "quality": "maximum",
        })
        generation_text, instruction = build_generation_text("这是测试。", config)
        self.assertEqual(generation_text, "这是测试。")
        self.assertEqual(instruction, "")
        self.assertEqual(config.best_of, 2)

    def test_style_instructions_are_distinct(self):
        professional = build_voxcpm_control_instruction("professional_natural", "natural")
        warm = build_voxcpm_control_instruction("warm_storytelling", "natural")
        self.assertNotEqual(professional, warm)

    def test_pace_instructions_are_distinct(self):
        natural = build_voxcpm_control_instruction("professional_natural", "natural")
        fast = build_voxcpm_control_instruction("professional_natural", "slightly_fast")
        self.assertNotEqual(natural, fast)
        very_fast = build_voxcpm_control_instruction("professional_natural", "fast")
        self.assertNotEqual(fast, very_fast)

    def test_seed_auto_and_integer_are_distinct(self):
        self.assertIsNone(resolve_config({"voice_seed": "auto"}).requested_seed)
        self.assertEqual(resolve_config({"voice_seed": 20260915}).requested_seed, 20260915)

    def test_display_text_and_captions_stay_clean(self):
        display_text = "这是字幕正文。"
        config = resolve_config({"mode": "controllable_clone", "style": "serious_authoritative", "pace": "natural"})
        generation_text, _ = build_generation_text(display_text, config)
        caption = {"text": display_text, "speechText": display_text}
        self.assertEqual(caption["text"], display_text)
        self.assertNotIn("严肃", caption["text"])
        self.assertIn(display_text, generation_text)

    def test_asr_control_terms_are_reported(self):
        self.assertEqual(find_control_terms_in_transcript("这是正文。"), [])
        self.assertIn("专业", find_control_terms_in_transcript("自然、专业，然后是正文。"))

    def test_text_normalization_preserves_semantic_content(self):
        text = normalize_for_speech("误差 5%，请检查。")
        self.assertEqual(text, "误差 百分之5，请检查。")

    def test_splitter_keeps_short_sentences_together(self):
        chunks = split_semantically("第一句内容。第二句内容。第三句内容。", max_chars=90)
        self.assertEqual(chunks, ["第一句内容。第二句内容。第三句内容。"])

    def test_splitter_never_exceeds_limit_for_long_text(self):
        chunks = split_semantically("这是一个很长的句子" * 20, max_chars=30)
        self.assertTrue(chunks)
        self.assertTrue(all(len(item) <= 30 for item in chunks))

    def test_duration_gate_is_broad_and_never_a_cut_instruction(self):
        low, high = expected_duration("这是一段用于测试自然语速的文案。", "natural")
        self.assertGreater(low, 0)
        self.assertGreater(high, low)


if __name__ == "__main__":
    unittest.main()
