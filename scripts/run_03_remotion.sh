#!/bin/bash
set -e

WINDOWS_OUTPUT_DIR="${DHJR_WINDOWS_OUTPUT_DIR:-/mnt/c/Users/YOUR_WINDOWS_USER/Desktop/DigitalHumanOutput}"

echo "===================================="
echo "Step 3: Render packaged video and append endcard"
echo "===================================="

cd ~/AI-Workspace/projects/leovisa-video-engine

mkdir -p public/input
mkdir -p public/audio
mkdir -p public/branding
mkdir -p src/data

echo "Syncing audio assets..."
cp -r ~/AI-Workspace/AudioAssets/bgm public/audio/ || true
cp -r ~/AI-Workspace/AudioAssets/sfx public/audio/ || true

echo "Syncing branding assets..."
cp ~/AI-Workspace/BrandAssets/lower_third/lower_third.png public/branding/lower_third.png || true
cp ~/AI-Workspace/BrandAssets/endcard/endcard.mp4 public/branding/endcard.mp4 || true

echo "Preparing Remotion input files..."
cp ~/AI-Workspace/DigitalHumanOutput/clean_video.mp4 public/input/clean_video.mp4
cp ~/AI-Workspace/DigitalHumanOutput/voice.wav public/audio/voice.wav
cp ~/AI-Workspace/DigitalHumanOutput/captions.json src/data/leovisa-demo.json
cp ~/AI-Workspace/DigitalHumanOutput/video_config.json src/data/video_config.json

echo "Injecting video path and audio config..."
python3 <<'PY'
import json
from pathlib import Path

data_path = Path("src/data/leovisa-demo.json")
config_path = Path("src/data/video_config.json")

data = json.loads(data_path.read_text(encoding="utf-8"))
config = json.loads(config_path.read_text(encoding="utf-8"))

data["video"] = "input/clean_video.mp4"
data["audio"] = "audio/voice.wav"
data["popups"] = []

config["bgm"] = {
    "src": "audio/bgm/news/bgm_news_04.wav",
    "volume": 0.28
}

config["sfx"] = config.get("sfx", [])

data_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

print("Injected config.bgm volume=0.28 and video path.")
PY

echo "Rendering main video without endcard..."
npx remotion render LeovisaPolicyVideo \
~/AI-Workspace/DigitalHumanOutput/main_video_no_endcard.mp4

echo "Trimming main video exactly to voice duration..."
VOICE_DUR=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 ~/AI-Workspace/DigitalHumanOutput/voice.wav)

# 给最后一字播完留 0.8 秒余量 + BGM 淡出空间(必须与 Composition.tsx 的 +0.8s 一致)
TRIM_DUR=$(python3 -c "print($VOICE_DUR + 0.8)")
echo "Voice duration: $VOICE_DUR seconds"
echo "Trim duration:  $TRIM_DUR seconds (含 0.8s 尾巴)"

ffmpeg -y \
  -i ~/AI-Workspace/DigitalHumanOutput/main_video_no_endcard.mp4 \
  -t "$TRIM_DUR" \
  -c:v libx264 -crf 18 -preset medium \
  -c:a aac -b:a 192k \
  -pix_fmt yuv420p \
  ~/AI-Workspace/DigitalHumanOutput/main_video_trimmed.mp4

echo "Appending endcard video with its own audio..."

if [ ! -f public/branding/endcard.mp4 ]; then
  echo "ERROR: Missing public/branding/endcard.mp4"
  exit 1
fi

ffmpeg -y \
  -i ~/AI-Workspace/DigitalHumanOutput/main_video_trimmed.mp4 \
  -i public/branding/endcard.mp4 \
  -filter_complex "\
[0:v]fps=30,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[v0];\
[1:v]fps=30,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[v1];\
[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a0];\
[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a1];\
[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]" \
  -map "[v]" \
  -map "[a]" \
  -c:v libx264 -crf 18 -preset medium \
  -c:a aac -b:a 192k \
  -pix_fmt yuv420p \
  ~/AI-Workspace/DigitalHumanOutput/final_video.mp4

echo "Copying final video to Windows Desktop..."
mkdir -p "$WINDOWS_OUTPUT_DIR"

cp ~/AI-Workspace/DigitalHumanOutput/final_video.mp4 \
"$WINDOWS_OUTPUT_DIR/final_video.mp4"

cp ~/AI-Workspace/DigitalHumanOutput/main_video_no_endcard.mp4 \
"$WINDOWS_OUTPUT_DIR/main_video_no_endcard.mp4"

cp ~/AI-Workspace/DigitalHumanOutput/main_video_trimmed.mp4 \
"$WINDOWS_OUTPUT_DIR/main_video_trimmed.mp4"

cp ~/AI-Workspace/DigitalHumanOutput/captions.json \
"$WINDOWS_OUTPUT_DIR/captions.json"

cp ~/AI-Workspace/DigitalHumanOutput/voice.wav \
"$WINDOWS_OUTPUT_DIR/voice.wav"

echo "Step 3 completed."
echo "Final video:"
echo "Windows output directory: $WINDOWS_OUTPUT_DIR"
