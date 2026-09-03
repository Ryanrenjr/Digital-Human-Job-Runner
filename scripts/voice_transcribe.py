import csv
import glob
import os
from pathlib import Path

import stable_whisper


CLIPS_DIR = Path(os.environ["TRAIN_CLIPS_DIR"])
OUT_TSV = Path(os.environ["TRAIN_TRANSCRIPT_DRAFT"])

print("Loading Whisper model: large-v3")
model = stable_whisper.load_model("large-v3")

rows = []
clips = sorted(glob.glob(str(CLIPS_DIR / "*.wav")))
for i, clip in enumerate(clips, 1):
    result = model.transcribe(clip, language="zh", verbose=False)
    text = result.text.strip()
    print(f"[{i}/{len(clips)}] {Path(clip).name}: {text}")
    rows.append((Path(clip).name, clip, text))

OUT_TSV.parent.mkdir(parents=True, exist_ok=True)
with OUT_TSV.open("w", encoding="utf-8", newline="") as f:
    writer = csv.writer(f, delimiter="\t")
    writer.writerow(["clip", "abspath", "text"])
    writer.writerows(rows)

print(f"Transcript draft: {OUT_TSV}")
