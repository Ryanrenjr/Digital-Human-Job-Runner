"""Boundary-only audio smoothing for concatenated VoxCPM2 segments.

The helpers in this module deliberately inspect only the beginning and end of
each segment. Silence inside a segment is never scanned for removal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np


BOUNDARY_PAUSE_MS = {
    "technical_split": 35,
    "comma": 105,
    "semicolon": 145,
    "colon": 150,
    "sentence_end": 210,
    "question": 230,
    "exclamation": 230,
    "paragraph": 320,
}

BOUNDARY_CROSSFADE_MS = {
    "technical_split": 15,
    "comma": 15,
    "semicolon": 0,
    "colon": 0,
    "sentence_end": 0,
    "question": 0,
    "exclamation": 0,
    "paragraph": 0,
}

DEFAULT_THRESHOLD_DBFS = -42.0
DEFAULT_LEADING_KEEP_MS = 30
DEFAULT_TRAILING_KEEP_MS = 45


@dataclass(frozen=True)
class EdgeTrimResult:
    original_samples: int
    trimmed_samples: int
    leading_trim_ms: float
    trailing_trim_ms: float
    leading_silence_ms: float
    trailing_silence_ms: float


def _as_mono(samples: np.ndarray) -> np.ndarray:
    data = np.asarray(samples, dtype="float32")
    if data.ndim == 1:
        return data
    return np.max(np.abs(data), axis=1).astype("float32")


def _active_bounds(
    samples: np.ndarray,
    sample_rate: int,
    threshold_dbfs: float = DEFAULT_THRESHOLD_DBFS,
) -> tuple[int, int] | None:
    """Return the first/last active sample using short RMS windows."""
    data = _as_mono(samples)
    if not len(data):
        return None
    frame = max(1, round(sample_rate * 0.01))
    hop = max(1, round(sample_rate * 0.005))
    starts = list(range(0, max(1, len(data) - frame + 1), hop))
    final_start = max(0, len(data) - frame)
    if starts[-1] != final_start:
        starts.append(final_start)
    threshold = 10 ** (threshold_dbfs / 20.0)
    active: list[tuple[int, float]] = []
    for start in starts:
        window = data[start:start + frame]
        rms = float(np.sqrt(np.mean(np.square(window)))) if len(window) else 0.0
        if rms >= threshold:
            active.append((start, rms))
    if not active:
        return None
    first = active[0][0]
    last = min(len(data), active[-1][0] + frame)
    return first, last


def edge_silence_ms(
    samples: np.ndarray,
    sample_rate: int,
    side: str,
    threshold_dbfs: float = DEFAULT_THRESHOLD_DBFS,
) -> float:
    """Measure only silence at one edge; internal pauses are ignored."""
    bounds = _active_bounds(samples, sample_rate, threshold_dbfs)
    if bounds is None:
        return len(_as_mono(samples)) / sample_rate * 1000.0
    edge = bounds[0] if side == "leading" else len(_as_mono(samples)) - bounds[1]
    return max(0.0, edge / sample_rate * 1000.0)


def trim_waveform_edges(
    samples: np.ndarray,
    sample_rate: int,
    leading_keep_ms: int = DEFAULT_LEADING_KEEP_MS,
    trailing_keep_ms: int = DEFAULT_TRAILING_KEEP_MS,
    threshold_dbfs: float = DEFAULT_THRESHOLD_DBFS,
) -> tuple[np.ndarray, EdgeTrimResult]:
    """Trim only model silence at the two edges with a safety margin."""
    data = np.asarray(samples, dtype="float32").reshape(-1)
    original_samples = len(data)
    bounds = _active_bounds(data, sample_rate, threshold_dbfs)
    if bounds is None:
        result = EdgeTrimResult(
            original_samples,
            original_samples,
            0.0,
            0.0,
            original_samples / sample_rate * 1000.0,
            original_samples / sample_rate * 1000.0,
        )
        return data, result

    keep_leading = round(sample_rate * leading_keep_ms / 1000.0)
    keep_trailing = round(sample_rate * trailing_keep_ms / 1000.0)
    start = max(0, bounds[0] - keep_leading)
    end = min(original_samples, bounds[1] + keep_trailing)
    trimmed = data[start:end]
    result = EdgeTrimResult(
        original_samples=original_samples,
        trimmed_samples=len(trimmed),
        leading_trim_ms=start / sample_rate * 1000.0,
        trailing_trim_ms=(original_samples - end) / sample_rate * 1000.0,
        leading_silence_ms=edge_silence_ms(trimmed, sample_rate, "leading", threshold_dbfs),
        trailing_silence_ms=edge_silence_ms(trimmed, sample_rate, "trailing", threshold_dbfs),
    )
    return trimmed, result


def pause_ms_for(boundary_type: str, legacy: bool = False) -> int:
    if legacy:
        return 30
    return BOUNDARY_PAUSE_MS.get(boundary_type, BOUNDARY_PAUSE_MS["technical_split"])


def crossfade_ms_for(boundary_type: str, legacy: bool = False) -> int:
    if legacy:
        return 0
    return BOUNDARY_CROSSFADE_MS.get(boundary_type, 0)


def _crossfade_join(left: np.ndarray, right: np.ndarray, samples: int) -> np.ndarray:
    if samples <= 0:
        return np.concatenate([left, right])
    samples = min(samples, len(left), len(right))
    if samples <= 0:
        return np.concatenate([left, right])
    fade_out = np.linspace(1.0, 0.0, samples, endpoint=False, dtype="float32")
    fade_in = 1.0 - fade_out
    overlap = left[-samples:] * fade_out + right[:samples] * fade_in
    return np.concatenate([left[:-samples], overlap, right[samples:]])


def assemble_segments(
    segments: Iterable[np.ndarray],
    sample_rate: int,
    boundary_types: list[str],
    legacy: bool = False,
) -> tuple[np.ndarray, list[dict]]:
    """Join segments with one typed pause per boundary.

    Crossfade is intentionally applied to the short silence bridge before the
    next segment. This smooths the waveform edge without overlapping speech or
    eating the first consonant of the next segment.
    """
    arrays = [np.asarray(item, dtype="float32").reshape(-1) for item in segments]
    if not arrays:
        return np.zeros(0, dtype="float32"), []
    if len(boundary_types) < len(arrays) - 1:
        boundary_types = boundary_types + ["technical_split"] * (len(arrays) - 1 - len(boundary_types))

    output = arrays[0]
    report: list[dict] = []
    for index, next_segment in enumerate(arrays[1:]):
        boundary_type = boundary_types[index]
        pause_ms = pause_ms_for(boundary_type, legacy)
        crossfade_ms = crossfade_ms_for(boundary_type, legacy)
        pause_samples = round(sample_rate * pause_ms / 1000.0)
        bridge = np.concatenate([
            np.zeros(pause_samples, dtype="float32"),
            next_segment,
        ])
        time_approx = len(output) / sample_rate
        output = _crossfade_join(
            output,
            bridge,
            round(sample_rate * crossfade_ms / 1000.0),
        )
        report.append({
            "afterSegment": index + 1,
            "type": boundary_type,
            "timeApprox": round(time_approx, 3),
            "pauseMs": pause_ms,
            "insertedPauseMs": pause_ms,
            "crossfadeMs": crossfade_ms,
            "detectedBoundaryPauseMs": pause_ms,
        })
    return output, report
