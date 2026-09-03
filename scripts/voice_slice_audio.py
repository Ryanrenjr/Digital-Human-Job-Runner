import glob
import os
from pathlib import Path

import soundfile as sf
from silero_vad import get_speech_timestamps, load_silero_vad, read_audio


RAW_DIR = Path(os.environ["TRAIN_RAW_WAV_DIR"])
OUT_DIR = Path(os.environ["TRAIN_CLIPS_DIR"])
OUT_DIR.mkdir(parents=True, exist_ok=True)

SR = 16000
MIN_DUR = 3.0
MAX_DUR = 15.0
model = load_silero_vad()
clip_idx = 0


def flush(wav, start, end):
    global clip_idx
    if start is None:
        return
    if (end - start) / SR < MIN_DUR:
        return
    out = OUT_DIR / f"clip_{clip_idx:04d}.wav"
    sf.write(out, wav[start:end].numpy(), SR)
    print(f"{out} {(end - start) / SR:.2f}s")
    clip_idx += 1


for wav_path in sorted(glob.glob(str(RAW_DIR / "*.wav"))):
    wav = read_audio(wav_path, sampling_rate=SR)
    timestamps = get_speech_timestamps(
        wav,
        model,
        sampling_rate=SR,
        min_speech_duration_ms=500,
        min_silence_duration_ms=300,
    )
    buf_s = buf_e = None
    for seg in timestamps:
        s, e = seg["start"], seg["end"]
        if buf_s is None:
            buf_s, buf_e = s, e
        elif (e - buf_s) / SR <= MAX_DUR:
            buf_e = e
        else:
            flush(wav, buf_s, buf_e)
            buf_s, buf_e = s, e
    flush(wav, buf_s, buf_e)

print(f"Total clips: {clip_idx}")
if clip_idx == 0:
    raise SystemExit("没有切出可训练的人声片段。")
