#!/bin/bash
set -e

AI_WORKSPACE="${DHJR_WORKSPACE:-$HOME/AI-Workspace}"
ENGINE_WORKSPACE="${DHJR_ENGINE_WORKSPACE:-$HOME/AI-Workspace}"
PIPELINE_SCRIPTS_DIR="${DHJR_PIPELINE_SCRIPTS_DIR:-$AI_WORKSPACE/scripts}"
. "$AI_WORKSPACE/scripts/activate_conda_env.sh"

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
export DHJR_AVATAR_VIDEO="${DHJR_AVATAR_VIDEO:-$JOB_DIR/input/avatar.mp4}"

# --- Ensure log directory exists before tee ---
mkdir -p "$LOG_DIR"
mkdir -p "$OUTPUT_DIR" "$WORK_DIR"

# Register the actual WSL process group so cancellation can target the GPU work.
WSL_PGID=$(ps -o pgid= -p $$ | tr -d ' ')
printf '{"run_id":"%s","wsl_pid":%s,"wsl_pgid":%s}\n' "$RUN_ID" "$$" "$WSL_PGID" > "$RUN_METADATA.tmp"
mv -f "$RUN_METADATA.tmp" "$RUN_METADATA"

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
if [ "$CONDA_EXE" = "micromamba" ]; then
    fail_job "暂不支持 Micromamba，请使用 Conda、Miniconda 或 Miniforge。"
fi
if ! dhjr_activate_conda_env "$CONDA_EXE" "$VOXCPM_ENV"; then
    fail_job "WSL 中找不到 Conda 环境管理器或环境 '$VOXCPM_ENV'，请检查 Miniconda/Miniforge 安装。"
fi
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
OUTRO_VIDEO="$DHJR_INPUT_DIR/outro.mp4"

if [ ! -f "$CLEAN_VIDEO" ]; then
    fail_job "clean_video.mp4 not found after LatentSync: $CLEAN_VIDEO"
fi

CLEAN_VIDEO_SIZE=$(stat -c%s "$CLEAN_VIDEO" 2>/dev/null || echo 0)
MIN_VIDEO_BYTES="${DHJR_MIN_VIDEO_BYTES:-131072}"
if [ "$CLEAN_VIDEO_SIZE" -lt "$MIN_VIDEO_BYTES" ]; then
    fail_job "clean_video.mp4 is too small (${CLEAN_VIDEO_SIZE} bytes), expected >= ${MIN_VIDEO_BYTES} bytes"
fi
echo "[INFO] clean_video.mp4: OK (${CLEAN_VIDEO_SIZE} bytes)"
python3 "$AI_WORKSPACE/app/backend/validate_artifact.py" \
    "$CLEAN_VIDEO" "$VOICE_WAV" \
    --width "${DHJR_EXPECTED_VIDEO_WIDTH:-720}" \
    --height "${DHJR_EXPECTED_VIDEO_HEIGHT:-1280}" \
    --tolerance "${DHJR_AV_SYNC_TOLERANCE:-0.5}" \
    --min-bytes "$MIN_VIDEO_BYTES"

# Render captions from the exact generated voice timeline. This keeps captions
# aligned with the audio without starting a second ASR process.
SUBTITLE_ENABLED=$(PYTHONPATH="$AI_WORKSPACE/app/backend" python3 "$JOB_STATE_GET" "$JOB_ID" subtitle_enabled 2>/dev/null | tail -n 1 || echo "yes")
if [ "$SUBTITLE_ENABLED" = "yes" ]; then
    echo ""
    echo "===================================="
    echo "Step 6a: Render automatic captions"
    echo "===================================="
    update_progress captions 93 "正在添加自动字幕"
    CAPTIONS_JSON="$OUTPUT_DIR/captions.json"
    CAPTIONS_ASS="$OUTPUT_DIR/captions.ass"
    CAPTIONED_TMP="$OUTPUT_DIR/clean_video.captioned.tmp.mp4"
    CAPTION_FONT_NAME="${DHJR_CAPTION_FONT_NAME:-Noto Sans CJK SC}"
    CAPTION_GEOMETRY=$(ffprobe -v error -select_streams v:0 \
        -show_entries stream=width,height -of csv=s=x:p=0 "$CLEAN_VIDEO" 2>/dev/null || true)
    IFS='x' read -r CAPTION_WIDTH CAPTION_HEIGHT <<< "$CAPTION_GEOMETRY"
    if [[ ! "$CAPTION_WIDTH" =~ ^[0-9]+$ || ! "$CAPTION_HEIGHT" =~ ^[0-9]+$ ]]; then
        fail_job "could not read video dimensions for captions: $CAPTION_GEOMETRY"
    fi
    if [ ! -f "$CAPTIONS_JSON" ]; then
        fail_job "captions.json not found after voice generation: $CAPTIONS_JSON"
    fi
    if ! fc-match "$CAPTION_FONT_NAME" >/dev/null 2>&1; then
        fail_job "caption font not found in WSL: $CAPTION_FONT_NAME"
    fi
    python3 "$AI_WORKSPACE/scripts/render_captions.py" \
        "$CAPTIONS_JSON" "$CAPTIONS_ASS" \
        --font-name "$CAPTION_FONT_NAME" \
        --width "$CAPTION_WIDTH" --height "$CAPTION_HEIGHT"
    if ! ffmpeg -filters 2>/dev/null | grep -qE '(^| )ass[[:space:]]|(^| )subtitles[[:space:]]'; then
        fail_job "当前 FFmpeg 未启用 libass 字幕滤镜，无法渲染自动字幕。"
    fi
    rm -f "$CAPTIONED_TMP"
    ffmpeg -y -nostdin -i "$CLEAN_VIDEO" -vf "ass=$CAPTIONS_ASS" \
        -map 0:v:0 -map 0:a? -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p \
        -c:a copy -movflags +faststart "$CAPTIONED_TMP"
    mv -f "$CAPTIONED_TMP" "$CLEAN_VIDEO"
    python3 "$AI_WORKSPACE/app/backend/validate_artifact.py" \
        "$CLEAN_VIDEO" "$VOICE_WAV" \
        --width "$CAPTION_WIDTH" --height "$CAPTION_HEIGHT" \
        --tolerance "${DHJR_AV_SYNC_TOLERANCE:-0.5}" \
        --min-bytes "$MIN_VIDEO_BYTES"
    echo "[INFO] automatic captions rendered with $CAPTION_FONT_NAME"
fi

# Optional account-specific end card. The main CleanVideo remains available
# as the intermediate artifact; the selected end card becomes final_video.mp4.
if [ -f "$OUTRO_VIDEO" ]; then
    echo ""
    echo "===================================="
    echo "Step 6b: Append selected outro"
    echo "===================================="
    update_progress outro 96 "正在添加片尾"
    FINAL_VIDEO="$OUTPUT_DIR/final_video.mp4"
    FINAL_TMP="$OUTPUT_DIR/final_video.mp4.tmp"
    VIDEO_GEOMETRY=$(ffprobe -v error -select_streams v:0 \
        -show_entries stream=width,height,r_frame_rate -of csv=s=x:p=0 "$CLEAN_VIDEO" 2>/dev/null || true)
    IFS='x' read -r BASE_WIDTH BASE_HEIGHT BASE_FPS <<< "$VIDEO_GEOMETRY"
    if [[ ! "$BASE_WIDTH" =~ ^[0-9]+$ || ! "$BASE_HEIGHT" =~ ^[0-9]+$ || -z "$BASE_FPS" ]]; then
        fail_job "could not read output video geometry: $VIDEO_GEOMETRY"
    fi
    rm -f "$FINAL_TMP" "$FINAL_VIDEO"
    ffmpeg -y -nostdin \
        -i "$CLEAN_VIDEO" \
        -i "$OUTRO_VIDEO" \
        -filter_complex \
        "[0:v]setpts=PTS-STARTPTS,format=yuv420p[v0];[1:v]scale=${BASE_WIDTH}:${BASE_HEIGHT}:force_original_aspect_ratio=decrease,pad=${BASE_WIDTH}:${BASE_HEIGHT}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=${BASE_FPS},format=yuv420p,setpts=PTS-STARTPTS[v1];[0:a]aresample=async=1:first_pts=0[a0];[1:a]aresample=async=1:first_pts=0[a1];[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]" \
        -map "[v]" -map "[a]" \
        -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p \
        -c:a aac -b:a 192k -movflags +faststart \
        "$FINAL_TMP"
    mv -f "$FINAL_TMP" "$FINAL_VIDEO"
    FINAL_SIZE=$(stat -c%s "$FINAL_VIDEO" 2>/dev/null || echo 0)
    if [ "$FINAL_SIZE" -lt "$MIN_VIDEO_BYTES" ]; then
        fail_job "final_video.mp4 is too small (${FINAL_SIZE} bytes), expected >= ${MIN_VIDEO_BYTES} bytes"
    fi
    ffprobe -v error -select_streams v:0 -show_entries stream=width,height \
        -of csv=p=0 "$FINAL_VIDEO" >/dev/null
    ffprobe -v error -select_streams a:0 -show_entries stream=codec_name \
        -of csv=p=0 "$FINAL_VIDEO" >/dev/null
    echo "[INFO] final_video.mp4: OK (${FINAL_SIZE} bytes)"
fi

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
