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
JOB_JSON="$JOB_DIR/job.json"
LOG_DIR="$JOB_DIR/logs"
LOG_FILE="$LOG_DIR/run.log"

mkdir -p "$LOG_DIR"
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
    if [ -f "$JOB_JSON" ]; then
        JOB_JSON_PATH="$JOB_JSON" FAIL_MSG="$msg" python3 - <<'PYEOF' || true
import json, os, sys
from pathlib import Path
p = Path(os.environ["JOB_JSON_PATH"])
msg = os.environ.get("FAIL_MSG", "Unknown error")
try:
    j = json.loads(p.read_text(encoding="utf-8"))
    j["status"] = "failed"
    j["error_message"] = msg
    j.setdefault("progress", {})
    j["progress"]["stage"] = "failed"
    j["progress"]["message"] = msg
    p.write_text(json.dumps(j, ensure_ascii=False, indent=2), encoding="utf-8")
except Exception as e:
    print(f"[WARN] Could not update job.json: {e}", file=sys.stderr)
PYEOF
    fi
    exit 1
}

trap 'fail_job "Command failed at line $LINENO"' ERR

if [ ! -f "$JOB_JSON" ]; then
    fail_job "job.json not found: $JOB_JSON"
fi

# ============================================================
echo ""
echo "===================================="
echo "Step 1: Prepare job"
echo "===================================="
python3 "$AI_WORKSPACE/app/backend/prepare_job.py" "$JOB_ID"

# ============================================================
echo ""
echo "===================================="
echo "Step 2: VoxCPM2 voice generation"
echo "===================================="
cd "$ENGINE_WORKSPACE/projects/VoxCPM"
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate voxcpm
PYTHONPATH="$ENGINE_WORKSPACE/projects/VoxCPM:$PYTHONPATH" python "$AI_WORKSPACE/scripts/generate_voice_dynamic.py"

# ============================================================
echo ""
echo "===================================="
echo "Step 3: Voice postprocess"
echo "===================================="
python postprocess_voxcpm_segments_v12.py

# ============================================================
echo ""
echo "===================================="
echo "Step 4: Check voice files"
echo "===================================="
OUTPUT_DIR="${DHJR_OUTPUT_DIR:-$ENGINE_WORKSPACE/DigitalHumanOutput}"
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
python3 "$AI_WORKSPACE/app/backend/collect_voice_output.py" "$JOB_ID"

echo ""
echo "===================================="
echo "Voice-only job finished successfully"
echo "JOB_ID=$JOB_ID"
echo "Output: $AI_WORKSPACE/jobs/$JOB_ID/output/voice.wav"
echo "Finished at: $(date '+%Y-%m-%dT%H:%M:%S')"
echo "===================================="
