from pathlib import Path
import json
import os
import re
import subprocess

import soundfile as sf
from voxcpm import VoxCPM


ROOT = Path(os.environ.get("DHJR_ENGINE_WORKSPACE", str(Path.home() / "AI-Workspace")))
APP_WORKSPACE = Path(os.environ.get("DHJR_WORKSPACE", str(ROOT)))
INPUT_DIR = Path(os.environ.get("DHJR_INPUT_DIR", str(ROOT / "DigitalHumanInput")))
OUTPUT_DIR = Path(os.environ.get("DHJR_OUTPUT_DIR", str(ROOT / "DigitalHumanOutput")))
SEG_DIR = OUTPUT_DIR / "audio_segments"

BASE_MODEL_DIR = Path(os.environ.get(
    "DHJR_VOXCPM_PRETRAINED",
    str(ROOT / "projects/VoxCPM/pretrained_models/VoxCPM2"),
))
DEFAULT_LORA_CKPT_DIR = Path("/home/ryanrenjr/voxlora/checkpoints/boss_lora_fast/step_0000300")
DEFAULT_REF_WAV = ROOT / "VoiceRefs/boss/default/boss_default.wav"
DEFAULT_REF_TEXT = "这个人叫彼得·曼德尔森,他是英国政坛可不是小人物,而是工党中非常有分量的老牌人物。但这次的问题出在,他在正式上任前,安全审查没有顺利通过。"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
SEG_DIR.mkdir(parents=True, exist_ok=True)

JOB_ID = os.environ.get("DHJR_JOB_ID", "")
PROGRESS_HELPER = os.environ.get("DHJR_PROGRESS_HELPER", "")

PAUSE_SECONDS = 0.06
MAX_SEGMENT_CHARS = 54
MAX_SEGMENT_SECONDS = 12.0
VOICE_SAMPLE_RATE = 48000
LATENT_SAMPLE_RATE = 16000


def normalize_script(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace('"', "“")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_script_for_voice(script: str) -> list[str]:
    text = normalize_script(script)
    chunks = []
    for para in [p.strip() for p in text.split("\n") if p.strip()]:
        chunks.extend(re.findall(r"[^。！？!?，,；;：:\n]+[。！？!?，,；;：:]?", para))

    final = []
    buf = ""
    for chunk in [x.strip() for x in chunks if x.strip()]:
        if len(chunk) > MAX_SEGMENT_CHARS:
            if buf:
                final.append(buf)
                buf = ""
            for start in range(0, len(chunk), MAX_SEGMENT_CHARS):
                final.append(chunk[start:start + MAX_SEGMENT_CHARS].strip())
            continue

        if not buf:
            buf = chunk
        elif len(buf + chunk) <= MAX_SEGMENT_CHARS:
            buf += chunk
        else:
            final.append(buf)
            buf = chunk

        if re.search(r"[。！？!?]$", chunk) and len(buf) >= 18:
            final.append(buf)
            buf = ""

    if buf:
        final.append(buf)
    return [x.strip() for x in final if x.strip()]


def estimate_max_duration(text: str) -> float:
    return min(MAX_SEGMENT_SECONDS, max(2.8, estimate_target_duration(text) * 1.35))


def estimate_target_duration(text: str) -> float:
    compact = re.sub(r"\s+", "", text)
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", compact))
    ascii_words = len(re.findall(r"[A-Za-z0-9]+", compact))
    return max(2.6, chinese_chars / 6.0 + ascii_words * 0.28 + 1.0)


def limit_wav_duration(wav, sample_rate: int, max_seconds: float):
    max_samples = int(sample_rate * max_seconds)
    if len(wav) <= max_samples:
        return wav
    trimmed = wav[:max_samples].copy()
    fade_samples = min(int(sample_rate * 0.06), len(trimmed))
    if fade_samples > 0:
        for i in range(fade_samples):
            trimmed[-fade_samples + i] *= i / fade_samples
    return trimmed


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


def clean_generated_audio(input_path: Path, output_path: Path):
    subprocess.run([
        "ffmpeg", "-y", "-i", str(input_path),
        "-af", "highpass=f=70,lowpass=f=14000,afftdn=nf=-25,loudnorm=I=-16:TP=-1.5:LRA=11",
        "-ac", "1", "-ar", str(VOICE_SAMPLE_RATE), str(output_path),
    ], check=True)


def atempo_chain(speed: float) -> str:
    parts = []
    remaining = speed
    while remaining > 2.0:
        parts.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        parts.append("atempo=0.5")
        remaining /= 0.5
    parts.append(f"atempo={remaining:.4f}")
    return ",".join(parts)


def fit_audio_duration(path: Path, target_seconds: float) -> float:
    dur = get_duration(path)
    if dur <= target_seconds * 1.12:
        return dur
    speed = min(1.55, dur / target_seconds)
    tmp = path.with_suffix(".speed.wav")
    print(f"[INFO] Segment is slower than target; speed={speed:.2f}, target={target_seconds:.2f}s")
    subprocess.run([
        "ffmpeg", "-y", "-i", str(path),
        "-af", f"{atempo_chain(speed)},loudnorm=I=-16:TP=-1.5:LRA=11",
        "-ac", "1", "-ar", str(VOICE_SAMPLE_RATE), str(tmp),
    ], check=True)
    tmp.replace(path)
    return get_duration(path)


def main():
    script = (INPUT_DIR / "script.txt").read_text(encoding="utf-8")
    title = (INPUT_DIR / "title.txt").read_text(encoding="utf-8").strip() if (INPUT_DIR / "title.txt").exists() else ""
    subtitle = (INPUT_DIR / "subtitle.txt").read_text(encoding="utf-8").strip() if (INPUT_DIR / "subtitle.txt").exists() else ""
    voice_profile = read_voice_profile()

    checkpoint_path = voice_profile.get("checkpoint_path") or ""
    reference_wav = voice_profile.get("reference_wav_path") or ""
    reference_text = voice_profile.get("reference_text") or ""

    lora_ckpt_dir = Path(checkpoint_path) if checkpoint_path else DEFAULT_LORA_CKPT_DIR
    ref_wav = Path(reference_wav) if reference_wav else DEFAULT_REF_WAV
    ref_text = reference_text or DEFAULT_REF_TEXT

    print("Voice profile:", json.dumps(voice_profile, ensure_ascii=False))
    print("LoRA checkpoint:", lora_ckpt_dir)
    print("Reference wav:", ref_wav)

    if not (lora_ckpt_dir / "lora_config.json").exists():
        raise FileNotFoundError(f"lora_config.json not found: {lora_ckpt_dir}")
    if not ref_wav.exists():
        raise FileNotFoundError(f"reference wav not found: {ref_wav}")

    segments = split_script_for_voice(script)
    keywords = read_keywords()

    print("Voice segment count:", len(segments))
    for i, seg in enumerate(segments, 1):
        print(f"{i:03d}. len={len(seg)} | {seg}")

    print("Loading VoxCPM2 + LoRA...")
    update_progress(8, "正在加载声音模型")
    from voxcpm.model.voxcpm import LoRAConfig
    lora_info = json.loads((lora_ckpt_dir / "lora_config.json").read_text(encoding="utf-8"))
    lora_cfg = LoRAConfig(**lora_info["lora_config"])
    model = VoxCPM.from_pretrained(
        hf_model_id=str(BASE_MODEL_DIR),
        load_denoiser=False,
        optimize=True,
        lora_config=lora_cfg,
        lora_weights_path=str(lora_ckpt_dir),
    )
    print("Model + LoRA loaded.")
    update_progress(12, "声音模型已加载，开始生成语音")

    for f in SEG_DIR.glob("segment_*.wav"):
        f.unlink()

    segment_paths = []
    timeline_segments = []
    captions = []
    current = 0.0

    for i, text in enumerate(segments, 1):
        out_path = SEG_DIR / f"segment_{i:03d}.wav"
        raw_path = SEG_DIR / f"segment_{i:03d}.raw.wav"
        print(f"\nGenerating segment {i}/{len(segments)}")
        print(text)
        segment_percent = 12 + round((i - 1) / max(1, len(segments)) * 20)
        update_progress(segment_percent, f"正在生成第 {i} / {len(segments)} 段声音")
        wav = model.generate(
            text=text,
            prompt_wav_path=str(ref_wav),
            prompt_text=ref_text,
            reference_wav_path=str(ref_wav),
            cfg_value=2.5,
            inference_timesteps=25,
            denoise=False,
        )
        max_duration = estimate_max_duration(text)
        limited_wav = limit_wav_duration(wav, model.tts_model.sample_rate, max_duration)
        if len(limited_wav) < len(wav):
            print(f"[WARN] Segment exceeded expected duration; trimmed to {max_duration:.2f}s")
        sf.write(raw_path, limited_wav, model.tts_model.sample_rate)
        clean_generated_audio(raw_path, out_path)
        dur = fit_audio_duration(out_path, estimate_target_duration(text))
        start = current
        end = current + dur
        segment_paths.append(out_path)
        timeline_segments.append({
            "start": round(start, 2),
            "end": round(end, 2),
            "text": text,
            "audio": str(out_path),
            "captionCount": 1,
        })
        captions.append({
            "start": round(start, 2),
            "end": round(end, 2),
            "text": text,
            "keywords": keywords_for_text(text, keywords),
        })
        current = end + PAUSE_SECONDS
        print(f"Saved: {out_path}")
        print(f"Duration: {dur:.2f}s | Start: {start:.2f}s | End: {end:.2f}s")
        update_progress(12 + round(i / max(1, len(segments)) * 20), f"已完成第 {i} / {len(segments)} 段声音")

    voice_path = OUTPUT_DIR / "voice.wav"
    concat_audio(segment_paths, voice_path, PAUSE_SECONDS)
    update_progress(34, "正在整理声音并校准时长")
    total_duration = get_duration(voice_path)

    data = {
        "title": title,
        "subtitle": subtitle,
        "mainTitle": title,
        "subTitle": subtitle,
        "voiceMode": "voxcpm2_lora_profile",
        "voiceEngine": "VoxCPM2",
        "voiceStyle": voice_profile.get("style", ""),
        "voiceSegments": timeline_segments,
        "audio": "audio/voice.wav",
        "captions": captions,
        "keywords": keywords,
        "popups": [],
        "totalDuration": total_duration,
    }
    (OUTPUT_DIR / "captions.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    voice_latent = OUTPUT_DIR / "voice_for_latentsync.wav"
    subprocess.run([
        "ffmpeg", "-y", "-i", str(voice_path),
        "-af", "highpass=f=70,lowpass=f=7600,afftdn=nf=-25,loudnorm=I=-16:TP=-1.5:LRA=11",
        "-ac", "1", "-ar", str(LATENT_SAMPLE_RATE), str(voice_latent),
    ], check=True)

    print("\nDone.")
    print("voice:", voice_path)
    print("voice_for_latentsync:", voice_latent)
    print("captions:", OUTPUT_DIR / "captions.json")
    print("total duration:", total_duration)


if __name__ == "__main__":
    main()
