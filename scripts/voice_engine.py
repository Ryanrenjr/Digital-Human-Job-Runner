"""Pure configuration and scoring helpers for the VoxCPM2 voice engine.

The installed VoxCPM2 API deliberately stays in ``generate_voice_dynamic.py``.
This module only translates product settings into documented API arguments, so
it can be unit-tested without loading a GPU model.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any


STYLE_INSTRUCTIONS = {
    "professional_natural": "自然、专业、清晰、自信，像真人面对镜头解释事情",
    "professional_calm": "自然、专业、沉稳、清晰，像真人面对镜头解释事情",
    "friendly_natural": "亲切、自然、松弛，像在和一个人面对面交流",
    "clear_slow": "清楚、耐心、易于理解，重点词发音完整",
    "energetic": "有活力、明快、清晰，但不要夸张或用力过度",
    "warm_storytelling": "温和、有叙事感，像认真讲述一个故事",
    "serious_authoritative": "严肃、克制、可信，语调稳定，重点明确",
}

PACE_INSTRUCTIONS = {
    "slow": "语速稍慢，停顿自然，有轻微情绪起伏",
    "natural": "语速自然，保持自然停顿",
    "slightly_fast": "语速稍快，适合短视频口播，保持自然停顿",
    "fast": "语速较快，适合节奏明快的短视频口播，保持吐字清楚和自然停顿",
}

CONTROL_MODES = frozenset({"voice_design", "controllable_clone"})


def _canonical_pace(pace: str) -> str:
    return str(pace or "natural")


def build_voxcpm_control_instruction(
    style: str,
    pace: str,
    emotion: str | None = None,
    dialect: str | None = None,
) -> str:
    """Build the natural-language instruction supported by VoxCPM2.

    VoxCPM2 reads the parenthesized prefix as a control protocol. The caller
    adds the parentheses; keeping the returned value bare makes it easy to
    test and prevents accidental double-wrapping.
    """
    style_key = str(style or "professional_natural")
    pace_key = _canonical_pace(pace)
    style_text = STYLE_INSTRUCTIONS.get(style_key, STYLE_INSTRUCTIONS["professional_natural"])
    pace_text = PACE_INSTRUCTIONS.get(pace_key, PACE_INSTRUCTIONS["natural"])

    if style_key == "professional_natural" and pace_key == "natural":
        instruction = f"{style_text}，{pace_text}，避免传统播音腔"
    elif style_key == "professional_natural" and pace_key == "slightly_fast":
        instruction = f"{style_text}，{pace_text}，避免传统播音腔"
    elif style_key == "serious_authoritative" and pace_key == "natural":
        instruction = f"{style_text}，{pace_text}，避免夸张表达"
    elif style_key == "warm_storytelling" and pace_key == "slow":
        instruction = f"{style_text}，{pace_text}，避免表演感"
    else:
        instruction = f"{style_text}，{pace_text}"

    if emotion:
        instruction += f"，情绪{str(emotion).strip()}"
    if dialect:
        dialect_labels = {
            "mandarin": "普通话",
            "sichuanese": "四川话",
            "cantonese": "粤语",
            "wu": "吴语",
            "northeastern": "东北话",
            "henan": "河南话",
            "shaanxi": "陕西话",
            "shandong": "山东话",
            "tianjin": "天津话",
            "minnan": "闽南话",
        }
        dialect_text = dialect_labels.get(str(dialect).strip(), str(dialect).strip())
        instruction += f"，使用{dialect_text}的发音特点"
    return instruction

QUALITY_PRESETS = {
    "standard": {"cfg_value": 1.8, "inference_timesteps": 20, "best_of": 1},
    "high": {"cfg_value": 2.0, "inference_timesteps": 25, "best_of": 1},
    "maximum": {"cfg_value": 1.8, "inference_timesteps": 30, "best_of": 2},
}


@dataclass(frozen=True)
class VoiceConfig:
    mode: str
    style: str
    pace: str
    quality: str
    cfg_value: float
    inference_timesteps: int
    best_of: int
    normalize: bool
    denoise: bool
    retry_badcase: bool
    retry_badcase_max_times: int
    # None means the official VoxCPM API should materialize an automatic seed.
    requested_seed: int | None
    # Kept as a compatibility alias for callers that used config.seed.
    seed: int | None


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def parse_requested_seed(value: Any) -> int | None:
    if value in (None, "", "auto"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def requested_seed(profile: dict) -> int | None:
    value = profile.get("voice_seed")
    if value in (None, ""):
        value = profile.get("seed")
    return parse_requested_seed(value)


def _stable_seed(profile: dict, text: str, segment_index: int) -> int:
    requested = requested_seed(profile)
    if requested is not None:
        return requested + max(0, segment_index - 1)
    source = f"{profile.get('voice_id', '')}|{segment_index}|{text}"
    return int(hashlib.sha256(source.encode("utf-8")).hexdigest()[:8], 16)


def resolve_config(profile: dict) -> VoiceConfig:
    has_reference = bool(profile.get("reference_wav_path") or profile.get("referenceWavPath"))
    has_checkpoint = bool(profile.get("checkpoint_path") or profile.get("checkpointPath"))
    requested_mode = str(profile.get("mode") or profile.get("voice_mode") or "").strip()
    if requested_mode in {"", "trained_profile", "lora_finetune"}:
        mode = "controllable_clone" if (has_reference or has_checkpoint) else "basic_tts"
    else:
        mode = requested_mode

    quality = str(profile.get("quality") or profile.get("voice_quality") or "high")
    if quality not in QUALITY_PRESETS:
        quality = "high"
    preset = QUALITY_PRESETS[quality]
    try:
        cfg = float(profile.get("cfg_value", profile.get("voice_cfg", preset["cfg_value"])))
    except (TypeError, ValueError):
        cfg = preset["cfg_value"]
    try:
        steps = int(profile.get("inference_timesteps", profile.get("voice_inference_timesteps", preset["inference_timesteps"])))
    except (TypeError, ValueError):
        steps = preset["inference_timesteps"]
    try:
        best_of = int(profile.get("best_of", profile.get("voice_best_of", preset["best_of"])))
    except (TypeError, ValueError):
        best_of = preset["best_of"]

    style = str(profile.get("style") or profile.get("voice_style") or "professional_natural")
    pace = str(profile.get("pace") or profile.get("voice_pace") or "natural")
    return VoiceConfig(
        mode=mode,
        style=style if style in STYLE_INSTRUCTIONS else "professional_natural",
        pace=pace if pace in PACE_INSTRUCTIONS else "natural",
        quality=quality,
        cfg_value=max(1.0, min(3.0, cfg)),
        inference_timesteps=max(4, min(30, steps)),
        best_of=max(1, min(3, best_of)),
        normalize=_as_bool(profile.get("text_normalize", profile.get("voice_text_normalize")), True),
        denoise=_as_bool(profile.get("reference_cleanup", profile.get("voice_reference_cleanup")), False),
        retry_badcase=_as_bool(profile.get("retry_badcase", profile.get("voice_retry_badcase")), True),
        retry_badcase_max_times=max(1, min(5, int(profile.get("retry_badcase_max_times", 3)))),
        requested_seed=requested_seed(profile),
        seed=requested_seed(profile),
    )


def build_generation_text(
    speech_text: str,
    config: VoiceConfig,
    language: str = "zh",
    dialect: str | None = None,
) -> tuple[str, str]:
    """Return the model input and the applied control instruction.

    Ultimate Clone intentionally stays reference-only: VoxCPM2 documents that
    Hi-Fi cloning ignores control instructions, so adding one would only make
    the request misleading. ``speech_text`` is never modified.
    """
    if config.mode not in CONTROL_MODES:
        return speech_text, ""
    instruction = build_voxcpm_control_instruction(config.style, config.pace, dialect=dialect)
    return f"({instruction}){speech_text}", instruction


def speech_instruction(text: str, config: VoiceConfig, language: str = "zh") -> str:
    """Backward-compatible helper returning the actual VoxCPM2 text input."""
    return build_generation_text(text, config, language)[0]


def style_control_status(config: VoiceConfig) -> str:
    if config.mode in CONTROL_MODES:
        return "control_instruction"
    if config.mode == "ultimate_clone":
        return "hi_fidelity_reference_only"
    return "engine_default"


CONTROL_WARNING_TERMS = (
    "自然",
    "专业",
    "清晰",
    "自信",
    "克制",
    "可信",
    "语调稳定",
    "重点明确",
    "语速稍快",
    "语速稍慢",
    "语速自然",
    "自然停顿",
    "温和",
    "叙事感",
    "严肃",
    "避免传统播音腔",
    "避免夸张表达",
    "避免表演感",
)


def find_control_terms_in_transcript(transcript: str, terms: tuple[str, ...] = CONTROL_WARNING_TERMS) -> list[str]:
    """Find control words accidentally spoken by a post-generation ASR pass."""
    text = str(transcript or "")
    return [term for term in terms if term in text]


def seed_for_segment(profile: dict, text: str, segment_index: int, candidate_index: int = 0) -> int:
    return _stable_seed(profile, text, segment_index) + candidate_index * 7919


def expected_duration(text: str, pace: str = "natural") -> tuple[float, float]:
    """Return a broad speech-duration range; it is a gate, never a cutter."""
    chars = max(1, len(re.sub(r"\s+", "", text)))
    seconds = chars / {"slow": 3.1, "natural": 4.0, "slightly_fast": 4.8, "fast": 5.4}.get(pace, 4.0)
    return max(0.7, seconds * 0.55), max(1.5, seconds * 2.2)


def audio_quality_score(wav, sample_rate: int) -> float:
    """Small, dependency-free waveform score used to choose best-of-N."""
    try:
        import numpy as np
        data = np.asarray(wav, dtype="float32").reshape(-1)
        if data.size < max(1, int(sample_rate * 0.2)) or not np.isfinite(data).all():
            return -100.0
        peak = float(np.max(np.abs(data)))
        rms = float(np.sqrt(np.mean(np.square(data))))
        if rms < 0.003:
            return -80.0
        score = 50.0
        score -= min(30.0, max(0.0, peak - 0.95) * 200.0)
        score -= abs(rms - 0.12) * 80.0
        return score
    except Exception:
        return 0.0
