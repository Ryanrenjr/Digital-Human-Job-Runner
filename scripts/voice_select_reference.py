import csv
import json
import math
import os
import re
import uuid
from pathlib import Path

import soundfile as sf

from voice_store import save_voice_profile


PROFILE_JSON = Path(os.environ["PROFILE_JSON"])
TRANSCRIPT_TSV = Path(os.environ["TRAIN_TRANSCRIPT_FINAL"])
CHECKPOINT = os.environ["CKPT"]

REFERENCE_AVOID_TERMS = (
    "噪音", "噪声", "电流", "回声", "键盘", "风声", "混响", "背景音乐",
    "录音", "音频质量", "测试", "训练素材",
)


def repetition_score(text: str) -> float:
    compact = re.sub(r"\s+", "", text)
    repeated = 0
    for size in (2, 3, 4, 5, 6):
        seen = set()
        for i in range(0, len(compact) - size + 1):
            gram = compact[i:i + size]
            if gram in seen:
                repeated += size
            seen.add(gram)
    return repeated / max(1, len(compact))


def score_row(text: str) -> float:
    compact = re.sub(r"\s+", "", text)
    length = len(compact)
    if length < 12 or length > 55:
        return -100.0
    score = 50.0
    score -= abs(length - 28) * 0.7
    score -= repetition_score(text) * 30
    if re.search(r"[。！？!?]$", text):
        score += 8
    if re.search(r"[A-Za-z0-9]", text):
        score -= 6
    if any(term in text for term in REFERENCE_AVOID_TERMS):
        score -= 35
    return score


def score_audio(path: str) -> float:
    """Prefer a clean 5-30 second reference, not just a good transcript."""
    try:
        info = sf.info(path)
        duration = float(info.duration)
        if duration < 5.0 or duration > 30.0:
            return -100.0
        audio, _ = sf.read(path, dtype="float32", always_2d=False)
        if getattr(audio, "size", 0) == 0:
            return -100.0
        peak = float(abs(audio).max())
        rms = float(math.sqrt(float((audio * audio).mean())))
    except Exception:
        return -100.0

    score = 30.0
    score -= abs(duration - 12.0) * 0.8
    if 0.15 <= rms <= 0.35:
        score += 12.0
    elif 0.08 <= rms <= 0.45:
        score += 5.0
    else:
        score -= 8.0
    if peak >= 0.995:
        score -= 20.0
    elif peak >= 0.98:
        score -= 8.0
    return score


rows = []
with TRANSCRIPT_TSV.open(encoding="utf-8-sig") as f:
    reader = csv.reader(f, delimiter="\t")
    next(reader, None)
    for row in reader:
        if len(row) < 3:
            continue
        audio = row[1].strip()
        text = row[2].strip()
        if audio and text and Path(audio).exists():
            audio_score = score_audio(audio)
            if audio_score <= -99.0:
                continue
            rows.append((score_row(text) + audio_score, audio, text))

if not rows:
    raise SystemExit("没有找到可用的参考音频。")

_, ref_wav, ref_text = sorted(rows, key=lambda item: item[0], reverse=True)[0]

profile = json.loads(PROFILE_JSON.read_text(encoding="utf-8"))
profile["trainingStatus"] = "finished"
profile["checkpointPath"] = CHECKPOINT
profile["referenceWavPath"] = ref_wav
profile["referenceText"] = ref_text
profile["references"] = [{
    "path": ref_wav,
    "text": ref_text,
    "qualityScore": round(sorted(rows, key=lambda item: item[0], reverse=True)[0][0], 3),
    "role": "primary",
}]
profile["trainingError"] = None
profile["revision"] = uuid.uuid4().hex
save_voice_profile(profile)

print("Selected reference wav:", ref_wav)
print("Selected reference text:", ref_text)
