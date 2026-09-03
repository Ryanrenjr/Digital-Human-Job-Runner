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

PAUSE_SECONDS = 0.06


def normalize_script(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace('"', "“")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_script_for_voice(script: str) -> list[str]:
    text = normalize_script(script)
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    sentences = []
    for para in paragraphs:
        parts = re.split(r"(?<=[。！？!?])", para)
        for part in [x.strip() for x in parts if x.strip()]:
            if len(part) <= 120:
                sentences.append(part)
            else:
                sentences.extend([x.strip() for x in re.split(r"(?<=[，；：、,;:])", part) if x.strip()])

    merged = []
    buf = ""
    for sent in sentences:
        if not buf:
            buf = sent
        elif len(buf + sent) <= 210 or (len(buf) < 120 and len(buf + sent) <= 250):
            buf += sent
        else:
            merged.append(buf)
            buf = sent
    if buf:
        merged.append(buf)

    final = []
    for item in merged:
        if len(item) <= 260:
            final.append(item)
            continue
        buf = ""
        for part in [x.strip() for x in re.split(r"(?<=[，；：、,;:])", item) if x.strip()]:
            if not buf or len(buf + part) <= 210:
                buf += part
            else:
                final.append(buf)
                buf = part
        if buf:
            final.append(buf)
    return [x.strip() for x in final if x.strip()]


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
        "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
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
        "-ar", "48000", "-ac", "1", str(output_path),
    ], check=True)


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

    for f in SEG_DIR.glob("segment_*.wav"):
        f.unlink()

    segment_paths = []
    timeline_segments = []
    captions = []
    current = 0.0

    for i, text in enumerate(segments, 1):
        out_path = SEG_DIR / f"segment_{i:03d}.wav"
        print(f"\nGenerating segment {i}/{len(segments)}")
        print(text)
        wav = model.generate(
            text=text,
            prompt_wav_path=str(ref_wav),
            prompt_text=ref_text,
            cfg_value=2.5,
            inference_timesteps=25,
            denoise=False,
        )
        sf.write(out_path, wav, model.tts_model.sample_rate)
        dur = get_duration(out_path)
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

    voice_path = OUTPUT_DIR / "voice.wav"
    concat_audio(segment_paths, voice_path, PAUSE_SECONDS)
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
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-ac", "1", "-ar", "16000", str(voice_latent),
    ], check=True)

    print("\nDone.")
    print("voice:", voice_path)
    print("voice_for_latentsync:", voice_latent)
    print("captions:", OUTPUT_DIR / "captions.json")
    print("total duration:", total_duration)


if __name__ == "__main__":
    main()
