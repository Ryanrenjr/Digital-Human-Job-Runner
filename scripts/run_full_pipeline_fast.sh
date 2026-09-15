#!/bin/bash
set -e

echo "===================================="
echo "Digital Human Job Runner FAST Pipeline"
echo "===================================="

echo "Checking input files..."

if [ ! -f ~/AI-Workspace/DigitalHumanInput/title.txt ]; then
  echo "ERROR: Missing title.txt"
  exit 1
fi

if [ ! -f ~/AI-Workspace/DigitalHumanInput/subtitle.txt ]; then
  echo "ERROR: Missing subtitle.txt"
  exit 1
fi

if [ ! -f ~/AI-Workspace/DigitalHumanInput/script.txt ]; then
  echo "ERROR: Missing script.txt"
  exit 1
fi

if [ ! -f ~/AI-Workspace/DigitalHumanInput/keywords.txt ]; then
  echo "ERROR: Missing keywords.txt"
  exit 1
fi

bash ~/AI-Workspace/scripts/run_01_voice.sh
bash ~/AI-Workspace/scripts/run_02_latentsync_fast.sh
bash ~/AI-Workspace/scripts/run_03_remotion.sh

echo ""
echo "===================================="
echo "FAST pipeline completed."
echo "Final output:"
echo "Windows output directory: ${DHJR_WINDOWS_OUTPUT_DIR:-/mnt/c/Users/YOUR_WINDOWS_USER/Desktop/DigitalHumanOutput}"
echo "===================================="
