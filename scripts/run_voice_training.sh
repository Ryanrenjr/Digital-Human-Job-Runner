#!/bin/bash
set -Eeuo pipefail

AI_WORKSPACE="${DHJR_WORKSPACE:-$HOME/AI-Workspace}"
ENGINE_WORKSPACE="${DHJR_ENGINE_WORKSPACE:-$HOME/AI-Workspace}"
OFFICIAL_VOXCPM="${DHJR_VOXCPM_OFFICIAL:-$ENGINE_WORKSPACE/projects/VoxCPM-official}"
PRETRAINED_PATH="${DHJR_VOXCPM_PRETRAINED:-$ENGINE_WORKSPACE/projects/VoxCPM/pretrained_models/VoxCPM2}"
. "$AI_WORKSPACE/scripts/activate_conda_env.sh"

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
RUN_ID="${DHJR_TRAINING_RUN_ID:-}"
RUN_METADATA="${DHJR_VOICE_RUN_METADATA:-$VOICE_DIR/run.json}"

mkdir -p "$RAW_WAV_DIR" "$CLIPS_DIR"
# A retry must build a clean dataset. Otherwise stale clips from a previous
# run can remain in the manifest and make the result impossible to compare.
find "$CLIPS_DIR" -type f -name "*.wav" -delete
rm -f "$TRAIN_DIR/transcripts_draft.tsv" "$TRAIN_DIR/transcripts_final.tsv" "$TRAIN_DIR/train.jsonl" "$TRAIN_DIR/val.jsonl"
WSL_PGID=$(ps -o pgid= -p $$ | tr -d ' ')
printf '{"run_id":"%s","wsl_pid":%s,"wsl_pgid":%s}\n' "$RUN_ID" "$$" "$WSL_PGID" > "$RUN_METADATA.tmp"
mv -f "$RUN_METADATA.tmp" "$RUN_METADATA"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "===================================="
echo "Voice training started at $(date '+%Y-%m-%dT%H:%M:%S')"
echo "VOICE_ID=$VOICE_ID"
echo "VOICE_DIR=$VOICE_DIR"
echo "===================================="

fail_voice() {
    local msg="${1:-Unknown voice training error}"
    echo "[ERROR] $msg"
PROFILE_JSON="$PROFILE_JSON" FAIL_MSG="$msg" VOICE_ID="$VOICE_ID" TRAINING_RUN_ID="$RUN_ID" PYTHONPATH="$AI_WORKSPACE/app/backend:${PYTHONPATH:-}" python3 - <<'PYEOF' || true
import json, os
from datetime import datetime
from pathlib import Path
from voice_store import save_voice_profile
p = Path(os.environ["PROFILE_JSON"])
if p.exists():
    j = json.loads(p.read_text(encoding="utf-8"))
    j["trainingStatus"] = "failed"
    j["trainingFinishedAt"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    j["trainingError"] = os.environ.get("FAIL_MSG", "Unknown voice training error")
    j["trainingPid"] = None
    j["trainingProcessGroupId"] = None
    save_voice_profile(j)
from database import release_gpu_lease
release_gpu_lease("voice_training", os.environ["VOICE_ID"], os.environ.get("TRAINING_RUN_ID"))
PYEOF
    exit 1
}

handle_training_error() {
    local exit_code=$?
    local line_number="${1:-unknown}"
    local recent_log=""
    if [ -f "$LOG_FILE" ]; then
        recent_log=$(tail -n 24 "$LOG_FILE" 2>/dev/null | tail -c 2000 || true)
    fi
    fail_voice "训练脚本在第 ${line_number} 行退出，退出码：${exit_code}。最近日志：${recent_log}"
}

trap 'handle_training_error "$LINENO"' ERR

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
while IFS= read -r src; do
    idx=$((idx + 1))
    out="$RAW_WAV_DIR/raw_$(printf '%04d' "$idx").wav"
    echo "Converting: $src -> $out"
    ffmpeg -nostdin -y -i "$src" -vn -ac 1 -ar 16000 "$out"
done < <(find "$RAW_DIR" -maxdepth 1 -type f | sort)

if ! ls "$RAW_WAV_DIR"/*.wav >/dev/null 2>&1; then
    fail_voice "没有可训练的音频文件。"
fi

echo ""
echo "Step 2: Slice speech clips"
CONDA_EXE="${DHJR_CONDA_EXE:-conda}"
VOXCPM_ENV="${DHJR_VOXCPM_ENV:-voxcpm}"
if [ "$CONDA_EXE" = "micromamba" ]; then
    fail_voice "暂不支持 Micromamba，请使用 Conda、Miniconda 或 Miniforge。"
fi
if ! dhjr_activate_conda_env "$CONDA_EXE" "$VOXCPM_ENV"; then
    fail_voice "WSL 中找不到 Conda 环境管理器或环境 '$VOXCPM_ENV'，请检查 Miniconda/Miniforge 安装。"
fi
PYTHONPATH="$AI_WORKSPACE/app/backend:$OFFICIAL_VOXCPM/src:${PYTHONPATH:-}" TRAIN_RAW_WAV_DIR="$RAW_WAV_DIR" TRAIN_CLIPS_DIR="$CLIPS_DIR" python "$AI_WORKSPACE/scripts/voice_slice_audio.py"

echo ""
echo "Step 3: Transcribe clips"
TRAIN_CLIPS_DIR="$CLIPS_DIR" TRAIN_TRANSCRIPT_DRAFT="$TRAIN_DIR/transcripts_draft.tsv" DHJR_TRAIN_LANGUAGE="${DHJR_TRAIN_LANGUAGE:-zh}" python "$AI_WORKSPACE/scripts/voice_transcribe.py"
# Keep a manually reviewed transcript when one exists. A new run still works
# out of the box by falling back to Whisper's draft.
if [ -f "$TRAIN_DIR/transcripts_reviewed.tsv" ]; then
    cp "$TRAIN_DIR/transcripts_reviewed.tsv" "$TRAIN_DIR/transcripts_final.tsv"
else
    cp "$TRAIN_DIR/transcripts_draft.tsv" "$TRAIN_DIR/transcripts_final.tsv"
fi

echo ""
echo "Step 4: Build train and validation manifests"
DHJR_TRAIN_VALIDATION="${DHJR_TRAIN_VALIDATION:-0}" TRAIN_TRANSCRIPT_FINAL="$TRAIN_DIR/transcripts_final.tsv" TRAIN_JSONL="$TRAIN_DIR/train.jsonl" VAL_JSONL="$TRAIN_DIR/val.jsonl" python "$AI_WORKSPACE/scripts/voice_make_jsonl.py"

echo ""
echo "Step 5: Validate training manifest"
PYTHONPATH="$OFFICIAL_VOXCPM/src:${PYTHONPATH:-}" python -m voxcpm.cli validate \
    --manifest "$TRAIN_DIR/train.jsonl" \
    --sample-rate 16000

echo ""
echo "Step 6: Write LoRA config"
if [ "${DHJR_TRAIN_VALIDATION:-0}" = "1" ]; then
    VAL_MANIFEST="$TRAIN_DIR/val.jsonl"
    echo "训练验证：已启用"
else
    # Validation sample generation does not update weights. It is expensive and
    # can duplicate model/audio-VAE memory on small or unstable WSL setups.
    VAL_MANIFEST=""
    echo "训练验证：已关闭（可设置 DHJR_TRAIN_VALIDATION=1 开启）"
fi

TRAIN_SAMPLES=$(wc -l < "$TRAIN_DIR/train.jsonl" | tr -d ' ')
TRAIN_EPOCHS="${DHJR_TRAIN_EPOCHS:-3}"
BATCH_SIZE=1
GRAD_ACCUM_STEPS="${DHJR_TRAIN_GRAD_ACCUM_STEPS:-1}"
EFFECTIVE_BATCH=$((BATCH_SIZE * GRAD_ACCUM_STEPS))
STEPS_PER_EPOCH=$(( (TRAIN_SAMPLES + EFFECTIVE_BATCH - 1) / EFFECTIVE_BATCH ))
NUM_ITERS=$((STEPS_PER_EPOCH * TRAIN_EPOCHS))
WARMUP_STEPS=$((NUM_ITERS / 10))
SAVE_INTERVAL=$((NUM_ITERS / 3))
[ "$WARMUP_STEPS" -lt 5 ] && WARMUP_STEPS=5
[ "$SAVE_INTERVAL" -lt 10 ] && SAVE_INTERVAL=10
echo "训练样本：$TRAIN_SAMPLES；目标轮数：$TRAIN_EPOCHS；训练步数：$NUM_ITERS"
cat > "$TRAIN_DIR/lora.yaml" <<EOF
pretrained_path: $PRETRAINED_PATH
train_manifest: $TRAIN_DIR/train.jsonl
val_manifest: "$VAL_MANIFEST"
sample_rate: 16000
out_sample_rate: 48000
batch_size: $BATCH_SIZE
grad_accum_steps: $GRAD_ACCUM_STEPS
num_workers: 2
num_iters: $NUM_ITERS
log_interval: 10
valid_interval: $SAVE_INTERVAL
save_interval: $SAVE_INTERVAL
learning_rate: 0.0001
weight_decay: 0.01
warmup_steps: $WARMUP_STEPS
max_steps: $NUM_ITERS
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
# Never silently resume an old retry. Preserve it for comparison, then start
# this run from step 0 with the newly built manifests and reference mix.
if [ -d "$VOICE_DIR/checkpoints/lora" ]; then
    ARCHIVE_DIR="$VOICE_DIR/checkpoints/archive/${RUN_ID:-$(date '+%Y%m%d_%H%M%S')}"
    mkdir -p "$(dirname "$ARCHIVE_DIR")"
    mv "$VOICE_DIR/checkpoints/lora" "$ARCHIVE_DIR"
fi
mkdir -p "$VOICE_DIR/checkpoints/lora"
cd "$OFFICIAL_VOXCPM"
set +e
python scripts/train_voxcpm_finetune.py --config_path "$TRAIN_DIR/lora.yaml"
TRAIN_EXIT=$?
set -e
if [ "$TRAIN_EXIT" -ne 0 ]; then
    fail_voice "VoxCPM 训练脚本退出，退出码：$TRAIN_EXIT。"
fi

CKPT="$VOICE_DIR/checkpoints/lora/latest"
if [ ! -f "$CKPT/lora_weights.safetensors" ]; then
    CKPT=$(find "$VOICE_DIR/checkpoints/lora" -maxdepth 1 -type d -name 'step_*' | sort | tail -1)
fi
if [ ! -f "$CKPT/lora_weights.safetensors" ]; then
    fail_voice "训练完成但没有找到 lora_weights.safetensors。"
fi

PROFILE_JSON="$PROFILE_JSON" TRAIN_TRANSCRIPT_FINAL="$TRAIN_DIR/transcripts_final.tsv" CKPT="$CKPT" PYTHONPATH="$AI_WORKSPACE/app/backend:${PYTHONPATH:-}" python "$AI_WORKSPACE/scripts/voice_select_reference.py"

PROFILE_JSON="$PROFILE_JSON" PYTHONPATH="$AI_WORKSPACE/app/backend:${PYTHONPATH:-}" python3 - <<'PYEOF'
import json, os
from datetime import datetime
from pathlib import Path
from voice_store import save_voice_profile
p = Path(os.environ["PROFILE_JSON"])
j = json.loads(p.read_text(encoding="utf-8"))
j["trainingFinishedAt"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
j["trainingPid"] = None
j["trainingProcessGroupId"] = None
save_voice_profile(j)
from database import release_gpu_lease
release_gpu_lease("voice_training", j["id"], j.get("trainingRunId"))
PYEOF

echo "===================================="
echo "Voice training finished"
echo "checkpoint: $CKPT"
echo "===================================="
