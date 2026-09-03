import csv
import json
import os
import random
from pathlib import Path


IN_TSV = Path(os.environ["TRAIN_TRANSCRIPT_FINAL"])
TRAIN_JSONL = Path(os.environ["TRAIN_JSONL"])
VAL_JSONL = Path(os.environ["VAL_JSONL"])

rows = []
with IN_TSV.open(encoding="utf-8-sig") as f:
    reader = csv.reader(f, delimiter="\t")
    next(reader, None)
    for row in reader:
        if len(row) < 3:
            continue
        audio = row[1].strip()
        text = row[2].strip()
        if audio and text and Path(audio).exists() and len(text) >= 2:
            rows.append({"audio": audio, "text": text})

if len(rows) < 4:
    raise SystemExit(f"可训练片段太少：{len(rows)}。请上传更多干净人声。")

random.seed(42)
indices = list(range(len(rows)))
random.shuffle(indices)
val_count = min(8, max(1, len(rows) // 10))
val_idx = set(indices[:val_count])


def write_jsonl(path, items):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


write_jsonl(TRAIN_JSONL, [rows[i] for i in range(len(rows)) if i not in val_idx])
write_jsonl(VAL_JSONL, [rows[i] for i in range(len(rows)) if i in val_idx])

print(f"train.jsonl: {len(rows) - len(val_idx)}")
print(f"val.jsonl: {len(val_idx)}")
