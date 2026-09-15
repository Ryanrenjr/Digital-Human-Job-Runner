#!/bin/bash
set -e

ROOT="$HOME/AI-Workspace"
INPUT="$ROOT/DigitalHumanInput"
OUTPUT="$ROOT/DigitalHumanOutput"
VOX="$ROOT/projects/VoxCPM"
SCRIPTS="$ROOT/scripts"
DESKTOP="${DHJR_WINDOWS_OUTPUT_DIR:-/mnt/c/Users/YOUR_WINDOWS_USER/Desktop/DigitalHumanOutput}"

TS=$(date +%Y%m%d_%H%M%S)
WORK="$OUTPUT/patch_intro_video_$TS"
BACKUP_INPUT="$WORK/input_backup"
BACKUP_OUTPUT="$WORK/output_backup"

mkdir -p "$WORK" "$BACKUP_INPUT" "$BACKUP_OUTPUT" "$DESKTOP"

echo "===================================="
echo "Generate intro patch VIDEO with current VoxCPM2 LoRA + LatentSync"
echo "===================================="

echo ""
echo "Step 1: Backup current input files"
echo "===================================="
for f in title.txt subtitle.txt keywords.txt script.txt; do
  if [ -f "$INPUT/$f" ]; then
    cp "$INPUT/$f" "$BACKUP_INPUT/$f"
  fi
done

echo ""
echo "Step 2: Backup current output files"
echo "===================================="
for f in voice.wav voice_for_latentsync.wav captions.json video_config.json clean_video.mp4 final_video.mp4 main_video_no_endcard.mp4 main_video_trimmed.mp4; do
  if [ -f "$OUTPUT/$f" ]; then
    cp "$OUTPUT/$f" "$BACKUP_OUTPUT/$f"
  fi
done

if [ -d "$OUTPUT/audio_segments" ]; then
  cp -r "$OUTPUT/audio_segments" "$BACKUP_OUTPUT/audio_segments"
fi

if [ -d "$OUTPUT/audio_segments_original_speed" ]; then
  cp -r "$OUTPUT/audio_segments_original_speed" "$BACKUP_OUTPUT/audio_segments_original_speed"
fi

echo ""
echo "Step 3: Write patch sentence"
echo "===================================="

cat > "$INPUT/title.txt" <<'EOF'
补录开头
EOF

cat > "$INPUT/subtitle.txt" <<'EOF'
一句话补录
EOF

cat > "$INPUT/keywords.txt" <<'EOF'
印度裔
华裔
英国
EOF

cat > "$INPUT/script.txt" <<'EOF'
如果一百五十万印度裔和五十万华裔都离开英国，会发生什么？
EOF

echo ""
echo "Step 4: Clear temporary output for patch"
echo "===================================="
rm -rf "$OUTPUT/audio_segments"
rm -rf "$OUTPUT/audio_segments_original_speed"
rm -f "$OUTPUT/voice.wav"
rm -f "$OUTPUT/voice_for_latentsync.wav"
rm -f "$OUTPUT/captions.json"
rm -f "$OUTPUT/clean_video.mp4"

echo ""
echo "Step 5: Generate patch voice using current VoxCPM2 script"
echo "===================================="
cd "$VOX"
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate voxcpm

python generate_voice_and_timeline_voxcpm2.py

echo ""
echo "Step 6: Apply current postprocess"
echo "===================================="
python postprocess_voxcpm_segments_v12.py

echo ""
echo "Step 7: Generate patch lip-sync video"
echo "===================================="
cd "$SCRIPTS"

# 只生成口型视频，不跑 Remotion，不加字幕，不加BGM
AUDIO_OFFSET=0 bash run_02_latentsync_overlap.sh

echo ""
echo "Step 8: Copy patch video/audio to Desktop"
echo "===================================="

cp "$OUTPUT/clean_video.mp4" "$DESKTOP/intro_patch_150w_indian_50w_chinese_video_$TS.mp4"
cp "$OUTPUT/voice.wav" "$DESKTOP/intro_patch_150w_indian_50w_chinese_voice_$TS.wav"
cp "$OUTPUT/voice_for_latentsync.wav" "$DESKTOP/intro_patch_150w_indian_50w_chinese_latentsync_$TS.wav"
cp "$OUTPUT/captions.json" "$DESKTOP/intro_patch_150w_indian_50w_chinese_captions_$TS.json"

echo ""
echo "Step 9: Restore original input files"
echo "===================================="
for f in title.txt subtitle.txt keywords.txt script.txt; do
  if [ -f "$BACKUP_INPUT/$f" ]; then
    cp "$BACKUP_INPUT/$f" "$INPUT/$f"
  fi
done

echo ""
echo "Step 10: Restore original output files"
echo "===================================="
for f in voice.wav voice_for_latentsync.wav captions.json video_config.json clean_video.mp4 final_video.mp4 main_video_no_endcard.mp4 main_video_trimmed.mp4; do
  if [ -f "$BACKUP_OUTPUT/$f" ]; then
    cp "$BACKUP_OUTPUT/$f" "$OUTPUT/$f"
  else
    rm -f "$OUTPUT/$f"
  fi
done

rm -rf "$OUTPUT/audio_segments"
if [ -d "$BACKUP_OUTPUT/audio_segments" ]; then
  cp -r "$BACKUP_OUTPUT/audio_segments" "$OUTPUT/audio_segments"
fi

rm -rf "$OUTPUT/audio_segments_original_speed"
if [ -d "$BACKUP_OUTPUT/audio_segments_original_speed" ]; then
  cp -r "$BACKUP_OUTPUT/audio_segments_original_speed" "$OUTPUT/audio_segments_original_speed"
fi

echo ""
echo "===================================="
echo "Done."
echo "补录视频已生成："
echo "Windows output directory: $DESKTOP"
echo "===================================="

explorer.exe "$(wslpath -w "$DESKTOP")" || true
