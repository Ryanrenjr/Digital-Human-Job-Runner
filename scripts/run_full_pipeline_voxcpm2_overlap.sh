#!/bin/bash
set -e

echo "===================================="
echo "Digital Human Job Runner Full Pipeline V1.2"
echo "VoxCPM2 + segment slow/normalize + WhisperX ASR captions + LatentSync Overlap + Remotion"
echo "===================================="

echo ""
echo "Step 0: Check input files"
echo "===================================="
for f in title.txt subtitle.txt script.txt keywords.txt; do
  if [ ! -f "$HOME/AI-Workspace/DigitalHumanInput/$f" ]; then
    echo "Missing input file: $HOME/AI-Workspace/DigitalHumanInput/$f"
    exit 1
  fi
done

echo "Title:"
cat ~/AI-Workspace/DigitalHumanInput/title.txt
echo ""
echo "Subtitle:"
cat ~/AI-Workspace/DigitalHumanInput/subtitle.txt

echo ""
echo "Step 1: Generate voice with VoxCPM2"
echo "===================================="
cd ~/AI-Workspace/projects/VoxCPM
source ~/miniconda3/etc/profile.d/conda.sh
conda activate voxcpm
python generate_voice_and_timeline_voxcpm2.py

echo ""
echo "Step 1.5: Post-process voice segments V1.2"
echo "===================================="
python postprocess_voxcpm_segments_v12.py

echo ""
echo "Step 2: Generate captions with WhisperX ASR"
echo "===================================="
cd ~/AI-Workspace/projects/leovisa-alignment
conda activate leovisa-align
python align_captions_with_whisperx_asr.py

echo ""
echo "Step 3: Post-process captions and sync Remotion data"
echo "===================================="
python3 <<'PY'
import json
from pathlib import Path

base = Path.home() / "AI-Workspace"

captions_path = base / "DigitalHumanOutput/captions.json"
demo_path = base / "projects/leovisa-video-engine/src/data/leovisa-demo.json"
output_config_path = base / "DigitalHumanOutput/video_config.json"
engine_config_path = base / "projects/leovisa-video-engine/src/data/video_config.json"

data = json.loads(captions_path.read_text(encoding="utf-8"))
caps = data.get("captions", [])

merged = []
for c in caps:
    start = float(c.get("start", 0))
    end = float(c.get("end", 0))
    text = c.get("text", "")

    if merged and (end - start) < 0.35:
        merged[-1]["end"] = end
        merged[-1]["text"] = (merged[-1].get("text", "") + text).strip()
    else:
        merged.append(c)

data["captions"] = merged
data["captionStats"] = data.get("captionStats", {})
data["captionStats"]["postProcessed"] = True
data["captionStats"]["captionCountAfterPostProcess"] = len(merged)

captions_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
demo_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

title = data.get("mainTitle") or data.get("title") or ""
subtitle = data.get("subTitle") or data.get("subtitle") or ""
keywords = data.get("keywords", [])

for path in [output_config_path, engine_config_path]:
    if not path.exists():
        continue

    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["title"] = title
    cfg["subtitle"] = subtitle
    cfg["mainTitle"] = title
    cfg["subTitle"] = subtitle
    cfg["keywords"] = keywords

    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

print("Synced captions.json -> leovisa-demo.json")
print("Updated video_config top-level title/subtitle only")
print("title:", title)
print("subtitle:", subtitle)
print("caption count:", len(merged))
PY

echo ""
echo "Step 4: Generate lip-sync video with LatentSync overlap"
echo "===================================="
cd ~/AI-Workspace/scripts
AUDIO_OFFSET=0 bash run_02_latentsync_overlap.sh

echo ""
echo "Step 5: Render final video with Remotion"
echo "===================================="
bash run_03_remotion.sh

echo ""
echo "Step 6: Duration check"
echo "===================================="
echo "voice.wav:"
ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 ~/AI-Workspace/DigitalHumanOutput/voice.wav

echo "clean_video.mp4:"
ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 ~/AI-Workspace/DigitalHumanOutput/clean_video.mp4

echo "final_video.mp4:"
ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 ~/AI-Workspace/DigitalHumanOutput/final_video.mp4

echo ""
echo "Done."
echo "Final video:"
echo "Windows output directory: ${DHJR_WINDOWS_OUTPUT_DIR:-/mnt/c/Users/YOUR_WINDOWS_USER/Desktop/DigitalHumanOutput}"

echo ""
echo "Step 7: Copy final video to Windows"
echo "===================================="
DATESTAMP=$(date +%Y%m%d)
DEST="${DHJR_WINDOWS_OUTPUT_DIR:-/mnt/c/Users/YOUR_WINDOWS_USER/Desktop/DigitalHumanOutput}/final_video_${DATESTAMP}.mp4"
cp ~/AI-Workspace/DigitalHumanOutput/final_video.mp4 "$DEST"
echo "Copied to: $DEST"
