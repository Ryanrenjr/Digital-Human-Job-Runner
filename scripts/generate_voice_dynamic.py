from pathlib import Path
from dataclasses import dataclass
import inspect
import json
import os
import re
import subprocess

import soundfile as sf
from voxcpm import VoxCPM

from voice_engine import (
    audio_quality_score,
    build_generation_text,
    expected_duration,
    find_control_terms_in_transcript,
    resolve_config,
    seed_for_segment,
    style_control_status,
)
from voice_text import normalize_for_speech, split_semantically


ROOT = Path(os.environ.get("DHJR_ENGINE_WORKSPACE", str(Path.home() / "AI-Workspace")))
APP_WORKSPACE = Path(os.environ.get("DHJR_WORKSPACE", str(ROOT)))
JOB_ID = os.environ.get("DHJR_JOB_ID", "standalone")
JOB_DIR = APP_WORKSPACE / "jobs" / JOB_ID
INPUT_DIR = Path(os.environ.get("DHJR_INPUT_DIR", str(JOB_DIR / "input")))
OUTPUT_DIR = Path(os.environ.get("DHJR_OUTPUT_DIR", str(JOB_DIR / "output")))
SEG_DIR = OUTPUT_DIR / "audio_segments"

BASE_MODEL_DIR = Path(os.environ.get(
    "DHJR_VOXCPM_PRETRAINED",
    str(ROOT / "projects/VoxCPM/pretrained_models/VoxCPM2"),
))
DEFAULT_LORA_CKPT_DIR = os.environ.get("DHJR_DEFAULT_LORA_CHECKPOINT", "").strip()
DEFAULT_REF_WAV = os.environ.get("DHJR_DEFAULT_REFERENCE_WAV", "").strip()
DEFAULT_REF_TEXT = os.environ.get("DHJR_DEFAULT_REFERENCE_TEXT", "").strip()

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
SEG_DIR.mkdir(parents=True, exist_ok=True)

PROGRESS_HELPER = os.environ.get("DHJR_PROGRESS_HELPER", "")

# Keep sentence-level generation stable, but avoid resetting the voice model
# for every short phrase. A later mastering pass handles the full track once.
PAUSE_SECONDS = 0.03
MAX_SEGMENT_CHARS = 90
VOICE_SAMPLE_RATE = 48000
LATENT_SAMPLE_RATE = 16000


def normalize_script(text: str) -> str:
    return normalize_for_speech(text).replace('"', "“")


def split_script_for_voice(script: str) -> list[str]:
    return split_semantically(script, max_chars=MAX_SEGMENT_CHARS)


def get_duration(path: Path) -> float:
    out = subprocess.check_output([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1",
        str(path),
    ])
    return float(out.decode().strip())


def read_keywords() -> list[str]:
    p = INPUT_DIR / "keywords.txt"
    if not p.exists():
        return []
    return [x.strip() for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def read_voice_profile() -> dict:
    p = INPUT_DIR / "voice_profile.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def update_progress(percent: int, message: str) -> None:
    if not JOB_ID or not PROGRESS_HELPER:
        return
    subprocess.run(
        ["python3", PROGRESS_HELPER, JOB_ID, "voice_generation", str(percent), message],
        check=False,
    )


def keywords_for_text(text: str, keywords: list[str]) -> list[str]:
    hits = []
    for kw in keywords:
        if kw in text and kw not in hits:
            hits.append(kw)
    return hits[:2]


def concat_audio(segment_paths: list[Path], output_path: Path, pause_seconds: float):
    concat_list = OUTPUT_DIR / "voxcpm_concat_list.txt"
    pause_path = OUTPUT_DIR / "pause.wav"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r={VOICE_SAMPLE_RATE}:cl=mono",
        "-t", str(pause_seconds), str(pause_path),
    ], check=True)
    lines = []
    for i, seg in enumerate(segment_paths):
        lines.append(f"file '{seg.resolve()}'\n")
        if i < len(segment_paths) - 1:
            lines.append(f"file '{pause_path.resolve()}'\n")
    concat_list.write_text("".join(lines), encoding="utf-8")
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-ar", str(VOICE_SAMPLE_RATE), "-ac", "1", str(output_path),
    ], check=True)


def master_generated_audio(input_path: Path, output_path: Path):
    """Apply one gentle final pass to the complete generated voice track.

    Denoising and loudness normalization per segment can make independently
    generated sentences sound metallic and can exaggerate segment boundaries.
    Keep the generated waveform intact until all segments are concatenated.
    """
    subprocess.run([
        "ffmpeg", "-y", "-i", str(input_path),
        "-af", "highpass=f=65,loudnorm=I=-16:TP=-1.5:LRA=11",
        "-ac", "1", "-ar", str(VOICE_SAMPLE_RATE), str(output_path),
    ], check=True)


def trim_segment_edges(path: Path) -> None:
    """Remove only leading model silence; never cut a natural mid-sentence pause."""
    tmp = path.with_suffix(".trimmed.wav")
    subprocess.run([
        "ffmpeg", "-y", "-i", str(path),
        "-af",
        "silenceremove=start_periods=1:start_duration=0.08:start_threshold=-45dB:stop_periods=0",
        "-ac", "1", "-ar", str(VOICE_SAMPLE_RATE), str(tmp),
    ], check=True)
    tmp.replace(path)


def optional_asr_control_check(audio_path: Path, language: str) -> dict:
    """Optionally ASR the final track and warn if control text was spoken.

    ASR is deliberately opt-in because loading a Whisper model after every
    job is expensive. CI and audio QA can enable it with
    ``DHJR_GENERATION_ASR_CHECK=1``; generation itself never fails on a leak.
    """
    enabled = os.environ.get("DHJR_GENERATION_ASR_CHECK", "").strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return {"status": "not_requested", "leakedTerms": []}
    try:
        import stable_whisper
        model = stable_whisper.load_model(os.environ.get("DHJR_ASR_MODEL", "base"))
        result = model.transcribe(str(audio_path), language=language or None, verbose=False)
        transcript = getattr(result, "text", "")
        leaked_terms = find_control_terms_in_transcript(transcript)
        if leaked_terms:
            print(f"[WARN] ASR detected control words in generated audio: {leaked_terms}")
        return {"status": "checked", "leakedTerms": leaked_terms, "transcript": transcript}
    except Exception as exc:
        print(f"[WARN] ASR control-word check unavailable: {exc}")
        return {"status": "unavailable", "leakedTerms": [], "error": str(exc)}


def _set_seed(seed: int) -> None:
    """Fallback for older VoxCPM packages without the official seed keyword."""
    try:
        import numpy as np
        np.random.seed(seed % (2**32 - 1))
    except Exception:
        pass
    try:
        import torch
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
    except Exception:
        pass


def supports_official_seed(model) -> bool:
    try:
        return "seed" in inspect.signature(model._generate).parameters
    except (AttributeError, TypeError, ValueError):
        return False


def successful_seed(model, fallback: int | None) -> int | None:
    value = getattr(getattr(model, "tts_model", None), "last_successful_seed", None)
    try:
        return int(value) if value is not None else fallback
    except (TypeError, ValueError):
        return fallback


@dataclass
class CandidateResult:
    wav: object
    candidate_index: int
    score: float
    duration: float
    requested_seed: int | None
    successful_seed: int | None


def generate_candidate(model, speech_text: str, profile: dict, config, ref_wav: Path | None,
                       ref_text: str, segment_index: int, candidate_index: int,
                       generation_text: str | None = None):
    candidate_seed = seed_for_segment(profile, speech_text, segment_index, candidate_index)
    official_seed = supports_official_seed(model)
    requested_seed = (
        config.requested_seed
        if config.requested_seed is not None and config.best_of == 1
        else candidate_seed
        if config.requested_seed is not None
        else None
    )
    kwargs = {
        "text": generation_text if generation_text is not None else speech_text,
        "cfg_value": config.cfg_value,
        "inference_timesteps": config.inference_timesteps,
        "normalize": config.normalize,
        "denoise": config.denoise,
        "retry_badcase": config.retry_badcase,
        "retry_badcase_max_times": config.retry_badcase_max_times,
        # This is part of the installed VoxCPM2 API, but was previously left
        # at its implicit default, making buzzier retries harder to control.
        "retry_badcase_ratio_threshold": 6.0,
    }
    if official_seed:
        # None intentionally delegates seed materialization to VoxCPM2. A
        # fixed request is passed through its official API, which also records
        # the seed actually used after bad-case retries.
        kwargs["seed"] = requested_seed
    else:
        _set_seed(candidate_seed)
    if ref_wav and config.mode in {"controllable_clone", "ultimate_clone", "trained_profile", "lora_finetune"}:
        kwargs["reference_wav_path"] = str(ref_wav)
        if config.mode == "ultimate_clone" and segment_index == 1 and ref_text:
            kwargs.update({"prompt_wav_path": str(ref_wav), "prompt_text": ref_text})
    wav = model.generate(**kwargs)
    fallback_seed = requested_seed if official_seed else candidate_seed
    return wav, requested_seed, successful_seed(model, fallback_seed), official_seed


def main():
    script = (INPUT_DIR / "script.txt").read_text(encoding="utf-8")
    title = (INPUT_DIR / "title.txt").read_text(encoding="utf-8").strip() if (INPUT_DIR / "title.txt").exists() else ""
    subtitle = (INPUT_DIR / "subtitle.txt").read_text(encoding="utf-8").strip() if (INPUT_DIR / "subtitle.txt").exists() else ""
    voice_profile = read_voice_profile()
    config = resolve_config(voice_profile)

    checkpoint_path = voice_profile.get("checkpoint_path") or ""
    reference_wav = voice_profile.get("reference_wav_path") or ""
    reference_text = voice_profile.get("reference_text") or ""

    lora_ckpt_dir = Path(checkpoint_path or DEFAULT_LORA_CKPT_DIR) if (checkpoint_path or DEFAULT_LORA_CKPT_DIR) else None
    ref_wav = Path(reference_wav or DEFAULT_REF_WAV) if (reference_wav or DEFAULT_REF_WAV) else None
    ref_text = reference_text or DEFAULT_REF_TEXT

    print("Voice profile:", json.dumps(voice_profile, ensure_ascii=False))
    print("Voice engine config:", json.dumps(config.__dict__, ensure_ascii=False))
    print("LoRA checkpoint:", lora_ckpt_dir or "base model")
    print("Reference wav:", ref_wav or "none")

    use_clone = config.mode in {"controllable_clone", "ultimate_clone", "trained_profile", "lora_finetune"}
    if not use_clone:
        lora_ckpt_dir = None
        ref_wav = None
        ref_text = ""

    if lora_ckpt_dir and not (lora_ckpt_dir / "lora_config.json").exists():
        raise FileNotFoundError(f"lora_config.json not found: {lora_ckpt_dir}")
    if ref_wav and not ref_wav.exists():
        raise FileNotFoundError(f"reference wav not found: {ref_wav}")

    display_segments = split_script_for_voice(script)
    keywords = read_keywords()

    print("Voice segment count:", len(display_segments))
    for i, seg in enumerate(display_segments, 1):
        print(f"{i:03d}. len={len(seg)} | {seg}")

    print("Loading VoxCPM2%s..." % (" + saved voice profile" if lora_ckpt_dir else " base model"))
    update_progress(8, "正在加载声音模型")
    model_kwargs = {
        "hf_model_id": str(BASE_MODEL_DIR),
        "load_denoiser": False,
        "optimize": True,
    }
    if lora_ckpt_dir:
        from voxcpm.model.voxcpm import LoRAConfig
        lora_info = json.loads((lora_ckpt_dir / "lora_config.json").read_text(encoding="utf-8"))
        model_kwargs["lora_config"] = LoRAConfig(**lora_info["lora_config"])
        model_kwargs["lora_weights_path"] = str(lora_ckpt_dir)
    model = VoxCPM.from_pretrained(**model_kwargs)
    print("Model + LoRA loaded.")
    official_seed = supports_official_seed(model)
    print(f"Official VoxCPM seed API: {'supported' if official_seed else 'not supported; using compatibility fallback'}")
    update_progress(12, "声音模型已加载，开始生成语音")

    for f in SEG_DIR.glob("segment_*.wav"):
        f.unlink()

    segment_paths = []
    timeline_segments = []
    captions = []
    current = 0.0

    segment_metadata = []
    for i, display_text in enumerate(display_segments, 1):
        out_path = SEG_DIR / f"segment_{i:03d}.wav"
        # Keep the spoken text stable for captions/debugging while using the
        # VoxCPM2 control protocol only in the modes that support it.
        speech_text = display_text
        generation_text, control_instruction = build_generation_text(
            speech_text,
            config,
            voice_profile.get("language", "zh"),
            voice_profile.get("dialect") or voice_profile.get("voice_dialect"),
        )
        print(f"\nGenerating segment {i}/{len(display_segments)}")
        print(display_text)
        segment_percent = 12 + round((i - 1) / max(1, len(display_segments)) * 20)
        update_progress(segment_percent, f"正在生成第 {i} / {len(display_segments)} 段声音")
        candidates = []
        low, high = expected_duration(display_text, config.pace)
        for candidate_index in range(config.best_of):
            candidate, candidate_requested_seed, candidate_successful_seed, _ = generate_candidate(
                model, speech_text, voice_profile, config, ref_wav, ref_text,
                i, candidate_index, generation_text,
            )
            duration = len(candidate) / float(model.tts_model.sample_rate)
            score = audio_quality_score(candidate, model.tts_model.sample_rate)
            if low <= duration <= high:
                score += 8.0
            candidates.append({
                "candidate": candidate_index + 1,
                "wav": candidate,
                "duration": duration,
                "score": score,
                "requested_seed": "auto" if candidate_requested_seed is None else candidate_requested_seed,
                "successful_seed": candidate_successful_seed,
            })
        selected = max(candidates, key=lambda item: item["score"])
        score = selected["score"]
        wav = selected["wav"]
        candidate_index = selected["candidate"] - 1
        # Do not force timing with atempo or cut the end of a sentence. VoxCPM
        # already has bad-case retry logic, and timing surgery is a common
        # source of clipped words and unnatural pauses.
        sf.write(out_path, wav, model.tts_model.sample_rate)
        trim_segment_edges(out_path)
        dur = get_duration(out_path)
        start = current
        end = current + dur
        segment_paths.append(out_path)
        timeline_segments.append({
            "start": round(start, 2),
            "end": round(end, 2),
            "text": display_text,
            "speechText": speech_text,
            "audio": str(out_path),
            "captionCount": 1,
        })
        captions.append({
            "start": round(start, 2),
            "end": round(end, 2),
            "text": display_text,
            "speechText": speech_text,
            "keywords": keywords_for_text(display_text, keywords),
        })
        segment_metadata.append({
            "index": i,
            "displayText": display_text,
            "speechText": speech_text,
            "generationText": generation_text,
            "controlInstruction": control_instruction or None,
            "requestedSeed": selected["requested_seed"],
            "successfulSeed": selected["successful_seed"],
            "candidateCount": len(candidates),
            "selectedCandidate": candidate_index,
            "score": round(score, 3),
            "candidates": [
                {
                    "candidate": item["candidate"],
                    "requestedSeed": item["requested_seed"],
                    "successfulSeed": item["successful_seed"],
                    "score": round(item["score"], 3),
                }
                for item in candidates
            ],
            "expectedDuration": [round(low, 2), round(high, 2)],
            "actualDuration": round(dur, 3),
        })
        current = end + PAUSE_SECONDS
        print(f"Saved: {out_path}")
        print(f"Duration: {dur:.2f}s | Start: {start:.2f}s | End: {end:.2f}s")
        update_progress(12 + round(i / max(1, len(display_segments)) * 20), f"已完成第 {i} / {len(display_segments)} 段声音")

    concatenated_path = OUTPUT_DIR / "voice_concatenated.wav"
    concat_audio(segment_paths, concatenated_path, PAUSE_SECONDS)
    voice_path = OUTPUT_DIR / "voice.wav"
    master_generated_audio(concatenated_path, voice_path)
    update_progress(34, "正在整理声音并校准时长")
    total_duration = get_duration(voice_path)
    asr_check = optional_asr_control_check(
        voice_path,
        voice_profile.get("language", "zh"),
    )

    data = {
        "title": title,
        "subtitle": subtitle,
        "mainTitle": title,
        "subTitle": subtitle,
        "voiceMode": config.mode,
        "voiceEngine": "VoxCPM2",
        "voiceStyle": voice_profile.get("style", ""),
        "voicePace": config.pace,
        "voiceQuality": config.quality,
        "voiceSegments": timeline_segments,
        "audio": "audio/voice.wav",
        "captions": captions,
        "keywords": keywords,
        "popups": [],
        "totalDuration": total_duration,
    }
    (OUTPUT_DIR / "captions.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "voice_generation.json").write_text(json.dumps({
        "engine": "VoxCPM2",
        "api": "generate(text, reference_wav_path, prompt_wav_path, prompt_text, cfg_value, inference_timesteps, normalize, denoise, retry_badcase, seed)",
        "mode": config.mode,
        "style": config.style,
        "styleControl": style_control_status(config),
        "controlInstructionApplied": config.mode in {"voice_design", "controllable_clone"},
        "pace": config.pace,
        "quality": config.quality,
        "cfgValue": config.cfg_value,
        "inferenceTimesteps": config.inference_timesteps,
        "normalize": config.normalize,
        "denoise": config.denoise,
        "retryBadcase": config.retry_badcase,
        "seedSupport": "official" if official_seed else "compatibility_fallback",
        "requestedSeed": "auto" if config.requested_seed is None else config.requested_seed,
        "successfulSeeds": [item.get("successfulSeed") for item in segment_metadata],
        "asrControlCheck": asr_check,
        "segments": segment_metadata,
        "totalDuration": total_duration,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    voice_latent = OUTPUT_DIR / "voice_for_latentsync.wav"
    subprocess.run([
        "ffmpeg", "-y", "-i", str(voice_path),
        "-ac", "1", "-ar", str(LATENT_SAMPLE_RATE), str(voice_latent),
    ], check=True)

    print("\nDone.")
    print("voice:", voice_path)
    print("voice_for_latentsync:", voice_latent)
    print("captions:", OUTPUT_DIR / "captions.json")
    print("total duration:", total_duration)


if __name__ == "__main__":
    main()
