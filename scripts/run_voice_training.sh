#!/bin/bash
set -e

AI_WORKSPACE="${DHJR_WORKSPACE:-$HOME/AI-Workspace}"
ENGINE_WORKSPACE="${DHJR_ENGINE_WORKSPACE:-/home/ryanrenjr/AI-Workspace}"
OFFICIAL_VOXCPM="${DHJR_VOXCPM_OFFICIAL:-$ENGINE_WORKSPACE/projects/VoxCPM-official}"
PRETRAINED_PATH="${DHJR_VOXCPM_PRETRAINED:-$ENGINE_WORKSPACE/projects/VoxCPM/pretrained_models/VoxCPM2}"

if [ $# -ne 1 ]; then
    echo "Usage: bash run_voice_training.sh VOICE_ID" >&2
    exit 1
fi

VOICE_ID="$1"
VOICE_DIR="$AI_WORKSPACE/voices/$VOICE_ID"
PROFILE_JSON="$VOICE_DIR/profile.json"
RAW_DIR="$VOICE_DIR/raw_uploads"
TRAIN_DIR="$VOICE_DIR/training"
RAW_WAV_DIR="$TRAIN_DIR/raw_wav"
CLIPS_DIR="$TRAIN_DIR/clips"
LOG_FILE="$VOICE_DIR/train.log"

mkdir -p "$RAW_WAV_DIR" "$CLIPS_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "===================================="
echo "Voice training started at $(date '+%Y-%m-%dT%H:%M:%S')"
echo "VOICE_ID=$VOICE_ID"
echo "VOICE_DIR=$VOICE_DIR"
echo "===================================="

fail_voice() {
    local msg="${1:-Unknown voice training error}"
    echo "[ERROR] $msg"
    PROFILE_JSON="$PROFILE_JSON" FAIL_MSG="$msg" python3 - <<'PYEOF' || true
import json, os
from datetime import datetime
from pathlib import Path
p = Path(os.environ["PROFILE_JSON"])
if p.exists():
    j = json.loads(p.read_text(encoding="utf-8"))
    j["trainingStatus"] = "failed"
    j["trainingFinishedAt"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    j["trainingError"] = os.environ.get("FAIL_MSG", "Unknown voice training error")
    p.write_text(json.dumps(j, ensure_ascii=False, indent=2), encoding="utf-8")
PYEOF
    exit 1
}

trap 'fail_voice "训练在第 $LINENO 行失败"' ERR

if [ ! -f "$PROFILE_JSON" ]; then
    fail_voice "profile.json not found: $PROFILE_JSON"
fi
if [ ! -d "$RAW_DIR" ]; then
    fail_voice "raw_uploads not found: $RAW_DIR"
fi

echo ""
echo "Step 1: Convert uploaded files to 16k wav"
find "$RAW_WAV_DIR" -type f -name "*.wav" -delete
idx=0
find "$RAW_DIR" -maxdepth 1 -type f | sort | while read -r src; do
    idx=$((idx + 1))
    out="$RAW_WAV_DIR/raw_$(printf '%04d' "$idx").wav"
    echo "Converting: $src -> $out"
    ffmpeg -y -i "$src" -vn -ac 1 -ar 16000 "$out"
done

if ! ls "$RAW_WAV_DIR"/*.wav >/dev/null 2>&1; then
    fail_voice "没有可训练的音频文件。"
fi

echo ""
echo "Step 2: Slice speech clips"
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate voxcpm
PYTHONPATH="$OFFICIAL_VOXCPM/src:$PYTHONPATH" TRAIN_RAW_WAV_DIR="$RAW_WAV_DIR" TRAIN_CLIPS_DIR="$CLIPS_DIR" python "$AI_WORKSPACE/scripts/voice_slice_audio.py"

echo ""
echo "Step 3: Transcribe clips"
TRAIN_CLIPS_DIR="$CLIPS_DIR" TRAIN_TRANSCRIPT_DRAFT="$TRAIN_DIR/transcripts_draft.tsv" python "$AI_WORKSPACE/scripts/voice_transcribe.py"
cp "$TRAIN_DIR/transcripts_draft.tsv" "$TRAIN_DIR/transcripts_final.tsv"

echo ""
echo "Step 4: Build train and validation manifests"
TRAIN_TRANSCRIPT_FINAL="$TRAIN_DIR/transcripts_final.tsv" TRAIN_JSONL="$TRAIN_DIR/train.jsonl" VAL_JSONL="$TRAIN_DIR/val.jsonl" python "$AI_WORKSPACE/scripts/voice_make_jsonl.py"

echo ""
echo "Step 5: Write LoRA config"
cat > "$TRAIN_DIR/lora.yaml" <<EOF
pretrained_path: $PRETRAINED_PATH
train_manifest: $TRAIN_DIR/train.jsonl
val_manifest: $TRAIN_DIR/val.jsonl
sample_rate: 16000
out_sample_rate: 48000
batch_size: 1
grad_accum_steps: 16
num_workers: 4
num_iters: 300
log_interval: 10
valid_interval: 50
save_interval: 50
learning_rate: 0.0001
weight_decay: 0.01
warmup_steps: 20
max_steps: 300
max_batch_tokens: 4096
max_grad_norm: 1.0
save_path: $VOICE_DIR/checkpoints/lora
tensorboard: $VOICE_DIR/logs/lora
lambdas:
  loss/diff: 1.0
  loss/stop: 1.0
lora:
  enable_lm: true
  enable_dit: true
  enable_proj: false
  r: 32
  alpha: 32
  dropout: 0.0
EOF

echo ""
echo "Step 6: Train VoxCPM LoRA"
cd "$OFFICIAL_VOXCPM"
python scripts/train_voxcpm_finetune.py --config_path "$TRAIN_DIR/lora.yaml"

CKPT="$VOICE_DIR/checkpoints/lora/latest"
if [ ! -f "$CKPT/lora_weights.safetensors" ]; then
    CKPT=$(find "$VOICE_DIR/checkpoints/lora" -maxdepth 1 -type d -name 'step_*' | sort | tail -1)
fi
if [ ! -f "$CKPT/lora_weights.safetensors" ]; then
    fail_voice "训练完成但没有找到 lora_weights.safetensors。"
fi

REF_WAV=$(find "$CLIPS_DIR" -maxdepth 1 -type f -name '*.wav' | sort | head -1)
REF_TEXT=$(tail -n +2 "$TRAIN_DIR/transcripts_final.tsv" | head -1 | cut -f3-)

PROFILE_JSON="$PROFILE_JSON" CKPT="$CKPT" REF_WAV="$REF_WAV" REF_TEXT="$REF_TEXT" python3 - <<'PYEOF'
import json, os
from datetime import datetime
from pathlib import Path
p = Path(os.environ["PROFILE_JSON"])
j = json.loads(p.read_text(encoding="utf-8"))
j["trainingStatus"] = "finished"
j["trainingFinishedAt"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
j["checkpointPath"] = os.environ["CKPT"]
j["referenceWavPath"] = os.environ["REF_WAV"]
j["referenceText"] = os.environ.get("REF_TEXT", "")
j["trainingError"] = None
p.write_text(json.dumps(j, ensure_ascii=False, indent=2), encoding="utf-8")
PYEOF

echo "===================================="
echo "Voice training finished"
echo "checkpoint: $CKPT"
echo "reference: $REF_WAV"
echo "===================================="
