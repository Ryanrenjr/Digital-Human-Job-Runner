#!/bin/bash
set -e

AI_WORKSPACE="${DHJR_WORKSPACE:-$HOME/AI-Workspace}"
ENGINE_WORKSPACE="${DHJR_ENGINE_WORKSPACE:-$AI_WORKSPACE}"

if [ $# -ne 1 ]; then
    echo "Usage: bash $(basename "$0") JOB_ID" >&2
    exit 1
fi

JOB_ID="$1"
JOB_DIR="$AI_WORKSPACE/jobs/$JOB_ID"
JOB_STATE_GET="$AI_WORKSPACE/app/backend/job_state_get.py"
RUN_ID="${DHJR_RUN_ID:-}"
RUN_METADATA="$JOB_DIR/run.json"
PROGRESS_HELPER="$AI_WORKSPACE/app/backend/progress_update.py"
LOG_DIR="$JOB_DIR/logs"
LOG_FILE="$LOG_DIR/run.log"
OUTPUT_DIR="${DHJR_OUTPUT_DIR:-$JOB_DIR/output}"
WORK_DIR="${DHJR_JOB_WORK_DIR:-$JOB_DIR/work}"
export DHJR_INPUT_DIR="${DHJR_INPUT_DIR:-$JOB_DIR/input}"
export DHJR_OUTPUT_DIR="$OUTPUT_DIR"
export DHJR_JOB_WORK_DIR="$WORK_DIR"

mkdir -p "$LOG_DIR"
mkdir -p "$OUTPUT_DIR" "$WORK_DIR"
WSL_PGID=$(ps -o pgid= -p $$ | tr -d ' ')
printf '{"run_id":"%s","wsl_pid":%s,"wsl_pgid":%s}\n' "$RUN_ID" "$$" "$WSL_PGID" > "$RUN_METADATA.tmp"
mv -f "$RUN_METADATA.tmp" "$RUN_METADATA"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "===================================="
echo "Run started at $(date '+%Y-%m-%dT%H:%M:%S')"
echo "JOB_ID=$JOB_ID"
echo "TYPE=voice_only"
echo "LOG=$LOG_FILE"
echo "===================================="

# --- Error handler ---
_FAILING="false"

fail_job() {
    if [ "$_FAILING" = "true" ]; then exit 1; fi
    _FAILING="true"
    trap - ERR
    local msg="${1:-Unknown error}"
    echo "[ERROR] $msg"
    echo "[ERROR] Job failed: $JOB_ID"
    python3 "$AI_WORKSPACE/app/backend/job_state_update.py" "$JOB_ID" failed "$msg" || true
    exit 1
}

trap 'fail_job "Command failed at line $LINENO"' ERR

update_progress() {
    if [ -n "${4:-}" ]; then
        python3 "$PROGRESS_HELPER" "$JOB_ID" "$1" "$2" "$3" "$4" "${5:-0}" || true
    else
        python3 "$PROGRESS_HELPER" "$JOB_ID" "$1" "$2" "$3" || true
    fi
}

if ! PYTHONPATH="$AI_WORKSPACE/app/backend" python3 "$JOB_STATE_GET" "$JOB_ID" status >/dev/null 2>&1; then
    fail_job "SQLite 中找不到任务: $JOB_ID"
fi

# ============================================================
echo ""
echo "===================================="
echo "Step 1: Prepare job"
echo "===================================="
python3 "$AI_WORKSPACE/app/backend/prepare_job.py" "$JOB_ID"
update_progress prepared 2 "任务已准备，开始生成声音"

# ============================================================
echo ""
echo "===================================="
echo "Step 2: VoxCPM2 voice generation"
echo "===================================="
update_progress voice_generation 5 "正在加载声音模型"
cd "$ENGINE_WORKSPACE/projects/VoxCPM"
CONDA_EXE="${DHJR_CONDA_EXE:-conda}"
VOXCPM_ENV="${DHJR_VOXCPM_ENV:-voxcpm}"
eval "$(\"$CONDA_EXE\" shell.bash hook)"
conda activate "$VOXCPM_ENV"
DHJR_JOB_ID="$JOB_ID" DHJR_PROGRESS_HELPER="$PROGRESS_HELPER" PYTHONPATH="$ENGINE_WORKSPACE/projects/VoxCPM:$PYTHONPATH" python "$AI_WORKSPACE/scripts/generate_voice_dynamic.py"
update_progress voice_ready 85 "声音生成完成，正在保存文件"

# ============================================================
echo ""
echo "===================================="
echo "Step 3: Voice postprocess"
echo "===================================="
echo "[INFO] Skipped legacy voice postprocess; dynamic voice generation already produced cleaned timing audio."

# ============================================================
echo ""
echo "===================================="
echo "Step 4: Check voice files"
echo "===================================="
VOICE_WAV="$OUTPUT_DIR/voice.wav"
VOICE_LS_WAV="$OUTPUT_DIR/voice_for_latentsync.wav"

if [ ! -f "$VOICE_WAV" ]; then
    fail_job "voice.wav not found: $VOICE_WAV"
fi
echo "[INFO] voice.wav            : OK"

if [ ! -f "$VOICE_LS_WAV" ]; then
    echo "[WARN] voice_for_latentsync.wav not found (non-fatal)"
fi

# ============================================================
echo ""
echo "===================================="
echo "Step 5: Collect voice output"
echo "===================================="
update_progress collecting_output 97 "正在保存声音文件"
python3 "$AI_WORKSPACE/app/backend/collect_voice_output.py" "$JOB_ID"

echo ""
echo "===================================="
echo "Voice-only job finished successfully"
echo "JOB_ID=$JOB_ID"
echo "Output: $AI_WORKSPACE/jobs/$JOB_ID/output/voice.wav"
echo "Finished at: $(date '+%Y-%m-%dT%H:%M:%S')"
echo "===================================="
