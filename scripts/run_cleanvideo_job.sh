#!/bin/bash
set -e

AI_WORKSPACE="${DHJR_WORKSPACE:-$HOME/AI-Workspace}"
ENGINE_WORKSPACE="${DHJR_ENGINE_WORKSPACE:-$AI_WORKSPACE}"
PIPELINE_SCRIPTS_DIR="${DHJR_PIPELINE_SCRIPTS_DIR:-$AI_WORKSPACE/scripts}"

if [ $# -ne 1 ]; then
    echo "Usage: bash $(basename "$0") JOB_ID" >&2
    exit 1
fi

JOB_ID="$1"
JOB_DIR="$AI_WORKSPACE/jobs/$JOB_ID"
JOB_STATE_GET="$AI_WORKSPACE/app/backend/job_state_get.py"
PROGRESS_HELPER="$AI_WORKSPACE/app/backend/progress_update.py"
LOG_DIR="$JOB_DIR/logs"
LOG_FILE="$LOG_DIR/run.log"
OUTPUT_DIR="${DHJR_OUTPUT_DIR:-$JOB_DIR/output}"
WORK_DIR="${DHJR_JOB_WORK_DIR:-$JOB_DIR/work}"
export DHJR_INPUT_DIR="${DHJR_INPUT_DIR:-$JOB_DIR/input}"
export DHJR_OUTPUT_DIR="$OUTPUT_DIR"
export DHJR_JOB_WORK_DIR="$WORK_DIR"
export DHJR_AVATAR_VIDEO="${DHJR_AVATAR_VIDEO:-$JOB_DIR/input/avatar.mp4}"

# --- Ensure log directory exists before tee ---
mkdir -p "$LOG_DIR"
mkdir -p "$OUTPUT_DIR" "$WORK_DIR"

# --- Redirect all output to log + terminal ---
exec > >(tee -a "$LOG_FILE") 2>&1

echo "===================================="
echo "Run started at $(date '+%Y-%m-%dT%H:%M:%S')"
echo "JOB_ID=$JOB_ID"
echo "LOG=$LOG_FILE"
echo "===================================="

# --- Error handler ---
_FAILING="false"

fail_job() {
    if [ "$_FAILING" = "true" ]; then
        exit 1
    fi
    _FAILING="true"
    trap - ERR

    local msg="${1:-Unknown error}"
    echo ""
    echo "[ERROR] =============================="
    echo "[ERROR] $msg"
    echo "[ERROR] Job failed: $JOB_ID"
    echo "[ERROR] =============================="

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

# --- Shutdown handler (post-success, non-fatal) ---
maybe_shutdown_after_done() {
    local SHUTDOWN_EXE="${DHJR_SHUTDOWN_EXE:-/mnt/c/Windows/System32/shutdown.exe}"

    local status
    local should_shutdown
    status=$(PYTHONPATH="$AI_WORKSPACE/app/backend" python3 "$JOB_STATE_GET" "$JOB_ID" status 2>/dev/null || echo "")
    should_shutdown=$(PYTHONPATH="$AI_WORKSPACE/app/backend" python3 "$JOB_STATE_GET" "$JOB_ID" shutdown_after_done 2>/dev/null || echo "no")

    if [ "$status" = "finished" ] && [ "$should_shutdown" = "yes" ]; then
        echo ""
        echo "===================================="
        echo "Shutdown requested"
        echo "System will shut down in 60 seconds."
        echo "Cancel command:"
        echo "  /mnt/c/Windows/System32/shutdown.exe /a"
        echo "===================================="
        if [ -f "$SHUTDOWN_EXE" ]; then
            "$SHUTDOWN_EXE" /s /t 60 || echo "[WARN] shutdown.exe returned a non-zero exit code."
        else
            echo "[WARN] shutdown.exe not found, skipping shutdown."
        fi
    else
        echo "[INFO] Shutdown after done: false, skipping shutdown."
    fi
    return 0
}

# --- Check the authoritative SQLite job exists before anything ---
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
update_progress voice_ready 35 "声音生成完成，开始准备视频"

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
    fail_job "voice.wav not found after VoxCPM2 generation: $VOICE_WAV"
fi
if [ ! -f "$VOICE_LS_WAV" ]; then
    fail_job "voice_for_latentsync.wav not found after VoxCPM2 generation: $VOICE_LS_WAV"
fi
echo "[INFO] voice.wav            : OK"
echo "[INFO] voice_for_latentsync : OK"

# ============================================================
echo ""
echo "===================================="
echo "Step 5: LatentSync — generate CleanVideo"
echo "===================================="
update_progress latentsync 40 "正在准备视频处理"
cd "$PIPELINE_SCRIPTS_DIR"
DHJR_JOB_ID="$JOB_ID" DHJR_PROGRESS_HELPER="$PROGRESS_HELPER" \
DHJR_INPUT_AUDIO_FULL="$OUTPUT_DIR/voice_for_latentsync.wav" \
DHJR_MUX_AUDIO_FULL="$OUTPUT_DIR/voice.wav" \
DHJR_AVATAR_VIDEO="$DHJR_AVATAR_VIDEO" \
DHJR_OUTPUT_DIR="$OUTPUT_DIR" \
DHJR_JOB_WORK_DIR="$WORK_DIR" \
AUDIO_OFFSET=0 bash "$PIPELINE_SCRIPTS_DIR/run_02_latentsync_overlap.sh"

# ============================================================
echo ""
echo "===================================="
echo "Step 6: Check CleanVideo"
echo "===================================="
CLEAN_VIDEO="$OUTPUT_DIR/clean_video.mp4"

if [ ! -f "$CLEAN_VIDEO" ]; then
    fail_job "clean_video.mp4 not found after LatentSync: $CLEAN_VIDEO"
fi

CLEAN_VIDEO_SIZE=$(stat -c%s "$CLEAN_VIDEO" 2>/dev/null || echo 0)
if [ "$CLEAN_VIDEO_SIZE" -lt 1048576 ]; then
    fail_job "clean_video.mp4 is too small (${CLEAN_VIDEO_SIZE} bytes), expected > 1MB"
fi
echo "[INFO] clean_video.mp4: OK (${CLEAN_VIDEO_SIZE} bytes)"

# ============================================================
echo ""
echo "===================================="
echo "Step 7: Collect output"
echo "===================================="
update_progress collecting_output 97 "视频处理完成，正在整理输出文件"
python3 "$AI_WORKSPACE/app/backend/collect_output.py" "$JOB_ID"

# ============================================================
# Read the output path from authoritative SQLite for summary
WINDOWS_OUTPUT=$(PYTHONPATH="$AI_WORKSPACE/app/backend" python3 "$JOB_STATE_GET" "$JOB_ID" paths.windows_desktop_output 2>/dev/null || echo "N/A")

echo ""
echo "===================================="
echo "CleanVideo job finished successfully"
echo "JOB_ID=$JOB_ID"
echo "Output:"
echo "  $AI_WORKSPACE/jobs/$JOB_ID/output/clean_video.mp4"
echo "Windows:"
echo "  $WINDOWS_OUTPUT"
echo "Finished at: $(date '+%Y-%m-%dT%H:%M:%S')"
echo "===================================="

# ============================================================
# Step 8: Maybe shutdown (non-fatal — never changes job status)
maybe_shutdown_after_done || true
