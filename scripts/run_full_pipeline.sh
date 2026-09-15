#!/bin/bash
set -e

echo "===================================="
echo "Digital Human Job Runner Pipeline"
echo "Default Mode: FAST"
echo "720x1280 / 25fps / 15 steps"
echo "===================================="

bash ~/AI-Workspace/scripts/run_01_voice.sh
bash ~/AI-Workspace/scripts/run_02_latentsync_fast.sh
bash ~/AI-Workspace/scripts/run_03_remotion.sh

echo ""
echo "===================================="
echo "Pipeline completed."
echo "Final output:"
echo "Windows output directory: ${DHJR_WINDOWS_OUTPUT_DIR:-/mnt/c/Users/YOUR_WINDOWS_USER/Desktop/DigitalHumanOutput}"
echo "===================================="
