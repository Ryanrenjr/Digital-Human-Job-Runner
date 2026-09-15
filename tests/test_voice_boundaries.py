import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from voice_boundaries import (  # noqa: E402
    BOUNDARY_CROSSFADE_MS,
    BOUNDARY_PAUSE_MS,
    assemble_segments,
    pause_ms_for,
    trim_waveform_edges,
)
from voice_text import split_semantically_with_boundaries  # noqa: E402


class VoiceBoundaryTests(unittest.TestCase):
    sample_rate = 1000

    def test_technical_split_pause_is_shortest(self):
        self.assertEqual(min(BOUNDARY_PAUSE_MS.values()), BOUNDARY_PAUSE_MS["technical_split"])
        self.assertLess(pause_ms_for("technical_split"), pause_ms_for("comma"))
        self.assertEqual(BOUNDARY_CROSSFADE_MS["technical_split"], 15)

    def test_sentence_pause_is_longer_than_comma(self):
        self.assertGreater(pause_ms_for("sentence_end"), pause_ms_for("comma"))
        self.assertGreater(pause_ms_for("paragraph"), pause_ms_for("sentence_end"))

    def test_internal_natural_silence_is_preserved(self):
        tone = np.full(200, 0.2, dtype="float32")
        samples = np.concatenate([np.zeros(100), tone, np.zeros(500), tone, np.zeros(100)])
        trimmed, result = trim_waveform_edges(samples, self.sample_rate)
        self.assertGreaterEqual(len(trimmed), 750)
        self.assertGreater(result.trimmed_samples, 0)
        self.assertTrue(np.allclose(trimmed[250:650], 0.0))

    def test_leading_and_trailing_silence_are_trimmed_with_margin(self):
        samples = np.concatenate([
            np.zeros(100),
            np.full(200, 0.2, dtype="float32"),
            np.zeros(120),
        ])
        trimmed, result = trim_waveform_edges(samples, self.sample_rate)
        self.assertLess(len(trimmed), len(samples))
        self.assertGreaterEqual(result.leading_trim_ms, 50)
        self.assertGreaterEqual(result.trailing_trim_ms, 70)
        self.assertGreaterEqual(len(trimmed), 200)

    def test_speech_onset_is_not_cut(self):
        samples = np.concatenate([
            np.zeros(100),
            np.linspace(0.01, 0.2, 80, dtype="float32"),
            np.full(120, 0.2, dtype="float32"),
            np.zeros(100),
        ])
        trimmed, _ = trim_waveform_edges(samples, self.sample_rate)
        self.assertGreaterEqual(float(np.max(trimmed[:30])), 0.0)
        self.assertGreater(float(np.max(trimmed[30:100])), 0.01)

    def test_boundary_metadata_is_generated(self):
        segments = [np.full(100, 0.1, dtype="float32") for _ in range(3)]
        joined, report = assemble_segments(
            segments,
            self.sample_rate,
            ["technical_split", "sentence_end"],
        )
        self.assertGreater(len(joined), 300)
        self.assertEqual(report[0]["type"], "technical_split")
        self.assertEqual(report[0]["insertedPauseMs"], 35)
        self.assertEqual(report[1]["type"], "sentence_end")
        self.assertEqual(report[1]["insertedPauseMs"], 210)
        self.assertEqual(report[0]["crossfadeMs"], 15)

    def test_missing_boundary_metadata_uses_safe_technical_split(self):
        segments = [np.full(100, 0.1, dtype="float32") for _ in range(3)]
        _, report = assemble_segments(segments, self.sample_rate, [])
        self.assertEqual([item["type"] for item in report], ["technical_split", "technical_split"])

    def test_splitter_records_boundary_types(self):
        result = split_semantically_with_boundaries(
            "第一句内容。第二句内容？\n\n第三段内容。",
            max_chars=6,
        )
        self.assertEqual(result[0]["boundaryAfter"], "sentence_end")
        self.assertEqual(result[1]["boundaryAfter"], "paragraph")
        self.assertEqual(result[-1]["boundaryAfter"], None)

    def test_generator_does_not_use_global_silenceremove(self):
        source = (ROOT / "scripts" / "generate_voice_dynamic.py").read_text(encoding="utf-8")
        self.assertNotIn("silenceremove", source)


if __name__ == "__main__":
    unittest.main()
