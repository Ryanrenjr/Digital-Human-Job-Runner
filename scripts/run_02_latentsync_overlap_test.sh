#!/bin/bash
set -e

echo "===================================="
echo "Step 2 OVERLAP TEST"
echo "Frame-locked overlap window LatentSync test"
echo "===================================="

cd ~/AI-Workspace/projects/LatentSync

source ~/miniconda3/etc/profile.d/conda.sh
conda activate latentsync

FPS=25
CORE_SECONDS=6
PAD_SECONDS=1
TEST_DURATION="${TEST_DURATION:-36}"
AUDIO_OFFSET="${AUDIO_OFFSET:-0}"
OUTPUT_TAG="${OUTPUT_TAG:-offset_0}"

WORK_DIR="data/overlap_test_${OUTPUT_TAG}"
INPUT_AUDIO_FULL="$HOME/AI-Workspace/DigitalHumanOutput/voice_for_latentsync.wav"
INPUT_AUDIO="data/input/voice_for_overlap_test_${OUTPUT_TAG}.wav"
RAW_BOSS_VIDEO="data/input/boss_default.mp4"
FULL_LOOP_VIDEO="$WORK_DIR/boss_full_loop_fast.mp4"

OUT_DIR="$HOME/AI-Workspace/DigitalHumanOutput/overlap_tests"
mkdir -p "$OUT_DIR"
mkdir -p data/input

rm -rf "$WORK_DIR"
mkdir -p "$WORK_DIR"

cp ~/AI-Workspace/VideoRefs/boss/default/boss_default.mp4 "$RAW_BOSS_VIDEO"

echo "Preparing test audio..."
ffmpeg -y -nostdin \
  -i "$INPUT_AUDIO_FULL" \
  -t "$TEST_DURATION" \
  -ac 1 -ar 16000 \
  "$INPUT_AUDIO"

AUDIO_DUR=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$INPUT_AUDIO")
echo "Test audio duration: $AUDIO_DUR seconds"
echo "Audio offset for LatentSync: $AUDIO_OFFSET seconds"
echo "Output tag: $OUTPUT_TAG"

echo "Creating full loop boss video for test..."
ffmpeg -y -nostdin -stream_loop -1 -i "$RAW_BOSS_VIDEO" \
  -t "$AUDIO_DUR" \
  -vf "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,fps=${FPS},setsar=1" \
  -c:v libx264 -crf 23 -preset veryfast \
  -pix_fmt yuv420p \
  -an \
  "$FULL_LOOP_VIDEO"

echo "Creating overlap windows..."

python3 <<PY
import math
import subprocess
from pathlib import Path

fps = int("$FPS")
core_seconds = float("$CORE_SECONDS")
pad = float("$PAD_SECONDS")
duration = float("$AUDIO_DUR")
audio_offset = float("$AUDIO_OFFSET")

work = Path("$WORK_DIR")
full_video = Path("$FULL_LOOP_VIDEO")
full_audio = Path("$INPUT_AUDIO")

total_frames = round(duration * fps)
core_frames = round(core_seconds * fps)
pad_frames = round(pad * fps)

windows = []
start_frame = 0
index = 1

while start_frame < total_frames:
    core_start_frame = start_frame
    core_end_frame = min(total_frames, core_start_frame + core_frames)

    padded_start_frame = max(0, core_start_frame - pad_frames)
    padded_end_frame = min(total_frames, core_end_frame + pad_frames)

    core_start = core_start_frame / fps
    core_end = core_end_frame / fps
    padded_start = padded_start_frame / fps
    padded_end = padded_end_frame / fps

    core_len = core_end - core_start
    padded_len = padded_end - padded_start
    left_trim = core_start - padded_start

    windows.append((index, core_start, core_end, core_len, padded_start, padded_len, left_trim))
    start_frame += core_frames
    index += 1

meta_lines = []

for index, core_start, core_end, core_len, padded_start, padded_len, left_trim in windows:
    idx = f"{index:03d}"

    video_chunk = work / f"video_{idx}.mp4"
    audio_chunk = work / f"audio_{idx}.wav"

    model_audio_start = padded_start + audio_offset

    print(
        f"Window {idx}: core={core_start:.3f}-{core_end:.3f} "
        f"core_len={core_len:.3f} padded={padded_start:.3f}-{padded_start+padded_len:.3f} "
        f"model_audio_start={model_audio_start:.3f} left_trim={left_trim:.3f}"
    )

    meta_lines.append(
        f"{idx},{core_start:.6f},{core_end:.6f},{core_len:.6f},{padded_start:.6f},{padded_len:.6f},{left_trim:.6f}\\n"
    )

    subprocess.run([
        "ffmpeg", "-y", "-nostdin",
        "-ss", f"{padded_start:.6f}",
        "-t", f"{padded_len:.6f}",
        "-i", str(full_video),
        "-vf", f"fps={fps},setsar=1",
        "-c:v", "libx264",
        "-crf", "23",
        "-preset", "veryfast",
        "-pix_fmt", "yuv420p",
        "-an",
        str(video_chunk)
    ], check=True)

    # Build model audio chunk with optional offset.
    # If offset makes start negative, prepend silence.
    if model_audio_start < 0:
        silence_dur = -model_audio_start
        real_dur = max(0.001, padded_len - silence_dur)
        silence = work / f"silence_{idx}.wav"
        real = work / f"real_audio_{idx}.wav"
        concat = work / f"audio_concat_{idx}.txt"

        subprocess.run([
            "ffmpeg", "-y", "-nostdin",
            "-f", "lavfi",
            "-i", "anullsrc=r=16000:cl=mono",
            "-t", f"{silence_dur:.6f}",
            str(silence)
        ], check=True)

        subprocess.run([
            "ffmpeg", "-y", "-nostdin",
            "-ss", "0",
            "-t", f"{real_dur:.6f}",
            "-i", str(full_audio),
            "-ac", "1",
            "-ar", "16000",
            str(real)
        ], check=True)

        concat.write_text(f"file '{silence.resolve()}'\\nfile '{real.resolve()}'\\n", encoding="utf-8")

        subprocess.run([
            "ffmpeg", "-y", "-nostdin",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat),
            "-t", f"{padded_len:.6f}",
            "-ac", "1",
            "-ar", "16000",
            str(audio_chunk)
        ], check=True)

    else:
        subprocess.run([
            "ffmpeg", "-y", "-nostdin",
            "-ss", f"{model_audio_start:.6f}",
            "-t", f"{padded_len:.6f}",
            "-i", str(full_audio),
            "-af", f"apad,atrim=0:{padded_len:.6f}",
            "-ac", "1",
            "-ar", "16000",
            str(audio_chunk)
        ], check=True)

(work / "windows_meta.csv").write_text("".join(meta_lines), encoding="utf-8")
print(f"Created {len(windows)} windows.")
PY

echo "Running LatentSync overlap windows..."

exec 3< "$WORK_DIR/windows_meta.csv"

while IFS=',' read -r index core_start core_end core_len padded_start padded_len left_trim <&3; do
  video_chunk="$WORK_DIR/video_${index}.mp4"
  audio_chunk="$WORK_DIR/audio_${index}.wav"
  out_chunk="$WORK_DIR/out_${index}.mp4"
  core_chunk="$WORK_DIR/core_${index}.mp4"

  echo "===================================="
  echo "Processing window $index"
  echo "core=$core_start-$core_end len=$core_len padded_len=$padded_len left_trim=$left_trim"
  echo "===================================="

  python -m scripts.inference \
    --unet_config_path "configs/unet/stage2_512.yaml" \
    --inference_ckpt_path "checkpoints/latentsync_unet.pt" \
    --inference_steps 15 \
    --guidance_scale 1.5 \
    --enable_deepcache \
    --video_path "$video_chunk" \
    --audio_path "$audio_chunk" \
    --video_out_path "$out_chunk" \
    < /dev/null

  echo "Keeping core part for window $index..."

  ffmpeg -y -nostdin \
    -ss "$left_trim" \
    -i "$out_chunk" \
    -t "$core_len" \
    -vf "fps=${FPS},scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,tpad=stop_mode=clone:stop_duration=1,trim=duration=${core_len},setpts=PTS-STARTPTS" \
    -an \
    -c:v libx264 -crf 23 -preset veryfast \
    -pix_fmt yuv420p \
    "$core_chunk"

done

exec 3<&-

echo "Concatenating core windows..."

CONCAT_FILE="$WORK_DIR/concat_core.txt"
rm -f "$CONCAT_FILE"

for f in "$WORK_DIR"/core_*.mp4; do
  echo "file '$(realpath "$f")'" >> "$CONCAT_FILE"
done

ffmpeg -y -nostdin -f concat -safe 0 -i "$CONCAT_FILE" \
  -c:v libx264 -crf 23 -preset veryfast \
  -pix_fmt yuv420p \
  "$WORK_DIR/video_only.mp4"

echo "Attaching original test audio..."

FINAL_OUT="$OUT_DIR/clean_overlap_${OUTPUT_TAG}.mp4"

ffmpeg -y -nostdin \
  -i "$WORK_DIR/video_only.mp4" \
  -i "$INPUT_AUDIO" \
  -t "$AUDIO_DUR" \
  -map 0:v:0 \
  -map 1:a:0 \
  -c:v libx264 -crf 23 -preset veryfast \
  -c:a aac -b:a 160k \
  -pix_fmt yuv420p \
  "$FINAL_OUT"

echo "Copying to Windows Desktop..."

WIN_OUT_DIR="${DHJR_WINDOWS_OUTPUT_DIR:-/mnt/c/Users/YOUR_WINDOWS_USER/Desktop/DigitalHumanOutput}/overlap_tests"
mkdir -p "$WIN_OUT_DIR"
cp "$FINAL_OUT" "$WIN_OUT_DIR/"

echo "===================================="
echo "Overlap test completed:"
echo "$FINAL_OUT"
echo "Windows:"
echo "Windows output directory: $WIN_OUT_DIR"
echo "===================================="
