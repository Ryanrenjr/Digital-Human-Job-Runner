import csv
import json
import os
import re
from pathlib import Path

from voice_store import save_voice_profile


PROFILE_JSON = Path(os.environ["PROFILE_JSON"])
TRANSCRIPT_TSV = Path(os.environ["TRAIN_TRANSCRIPT_FINAL"])
CHECKPOINT = os.environ["CKPT"]


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
            rows.append((score_row(text), audio, text))

if not rows:
    raise SystemExit("没有找到可用的参考音频。")

_, ref_wav, ref_text = sorted(rows, key=lambda item: item[0], reverse=True)[0]

profile = json.loads(PROFILE_JSON.read_text(encoding="utf-8"))
profile["trainingStatus"] = "finished"
profile["checkpointPath"] = CHECKPOINT
profile["referenceWavPath"] = ref_wav
profile["referenceText"] = ref_text
profile["trainingError"] = None
save_voice_profile(profile)

print("Selected reference wav:", ref_wav)
print("Selected reference text:", ref_text)
