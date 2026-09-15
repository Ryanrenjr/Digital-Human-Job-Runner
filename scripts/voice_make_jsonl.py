import csv
import json
import os
import random
import re
from pathlib import Path


IN_TSV = Path(os.environ["TRAIN_TRANSCRIPT_FINAL"])
TRAIN_JSONL = Path(os.environ["TRAIN_JSONL"])
VAL_JSONL = Path(os.environ["VAL_JSONL"])

rows = []


def repetition_score(text: str) -> float:
    compact = re.sub(r"\s+", "", text)
    if len(compact) < 8:
        return 0.0
    repeated = 0
    for size in (2, 3, 4, 5, 6):
        seen = set()
        for i in range(0, len(compact) - size + 1):
            gram = compact[i:i + size]
            if gram in seen:
                repeated += size
            seen.add(gram)
    return repeated / max(1, len(compact))


def is_clean_training_text(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if len(compact) < 4 or len(compact) > 120:
        return False
    if repetition_score(compact) > 1.1:
        return False
    return True


with IN_TSV.open(encoding="utf-8-sig") as f:
    reader = csv.reader(f, delimiter="\t")
    next(reader, None)
    for row in reader:
        if len(row) < 3:
            continue
        audio = row[1].strip()
        text = row[2].strip()
        if audio and text and Path(audio).exists() and is_clean_training_text(text):
            rows.append({"audio": audio, "text": text})

if len(rows) < 4:
    raise SystemExit(f"可训练片段太少：{len(rows)}。请上传更多干净人声。")

validation_enabled = os.getenv("DHJR_TRAIN_VALIDATION", "0") == "1"
if validation_enabled:
    random.seed(42)
    indices = list(range(len(rows)))
    random.shuffle(indices)
    val_count = min(8, max(1, len(rows) // 10))
    val_idx = set(indices[:val_count])
else:
    # Do not throw away scarce speaker data when validation is disabled.
    # Small single-speaker LoRA runs benefit from using every clean clip.
    val_idx = set()


def choose_reference(target_index: int) -> str:
    """Pick a different clean clip from this speaker for conditioning.

    The official VoxCPM recipe recommends mixing reference-conditioned and
    ordinary samples. Keeping the reference different from the target avoids
    teaching the trainer to simply copy the same clip.
    """
    candidates = [i for i in range(len(rows)) if i != target_index]
    if not candidates:
        return rows[target_index]["audio"]
    return rows[random.choice(candidates)]["audio"]


train_rows = []
val_rows = []
ref_count = 0
for index, row in enumerate(rows):
    item = dict(row)
    if index not in val_idx:
        # Deterministic 40% mix: enough reference-conditioned examples to
        # learn speaker identity while retaining ordinary TTS behavior.
        if (index % 5) < 2:
            item["ref_audio"] = choose_reference(index)
            ref_count += 1
        train_rows.append(item)
    else:
        val_rows.append(item)


def write_jsonl(path, items):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


write_jsonl(TRAIN_JSONL, train_rows)
write_jsonl(VAL_JSONL, val_rows)

print(f"train.jsonl: {len(train_rows)} (with ref_audio: {ref_count})")
print(f"val.jsonl: {len(val_idx)}")
