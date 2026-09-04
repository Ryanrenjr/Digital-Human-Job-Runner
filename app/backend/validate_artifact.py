#!/usr/bin/env python3
"""Validate final audio/video artifacts before a job can be marked finished."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def probe(path: Path) -> dict:
    ffprobe = shutil.which("ffprobe") or "ffprobe"
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise ValueError(f"ffprobe failed for {path.name}: {result.stderr.strip()[-300:]}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid ffprobe output for {path.name}") from exc


def duration(stream: dict, metadata: dict) -> float:
    value = stream.get("duration") or metadata.get("duration") or 0
    return float(value)


def validate_audio(path: Path) -> float:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"audio artifact is missing or empty: {path}")
    data = probe(path)
    audio = next((item for item in data.get("streams", []) if item.get("codec_type") == "audio"), None)
    if not audio or duration(audio, data.get("format", {})) <= 0:
        raise ValueError(f"audio stream is missing or invalid: {path}")
    return duration(audio, data.get("format", {}))


def validate_video(path: Path, audio_path: Path, expected_width: int, expected_height: int, tolerance: float) -> None:
    if not path.is_file() or path.stat().st_size <= 1024 * 1024:
        raise ValueError(f"video artifact is missing or too small: {path}")
    data = probe(path)
    video = next((item for item in data.get("streams", []) if item.get("codec_type") == "video"), None)
    audio = next((item for item in data.get("streams", []) if item.get("codec_type") == "audio"), None)
    if not video:
        raise ValueError("final video has no video stream")
    if not audio:
        raise ValueError("final video has no audio stream")
    if int(video.get("width") or 0) != expected_width or int(video.get("height") or 0) != expected_height:
        raise ValueError(
            f"unexpected video resolution: {video.get('width')}x{video.get('height')}, "
            f"expected {expected_width}x{expected_height}"
        )
    video_duration = duration(video, data.get("format", {}))
    audio_duration = duration(audio, data.get("format", {}))
    reference_duration = validate_audio(audio_path)
    if video_duration <= 0 or audio_duration <= 0 or reference_duration <= 0:
        raise ValueError("video/audio duration is invalid")
    if abs(video_duration - reference_duration) > tolerance:
        raise ValueError(
            f"video/audio duration mismatch: video={video_duration:.3f}s audio={reference_duration:.3f}s "
            f"tolerance={tolerance:.3f}s"
        )
    if abs(audio_duration - reference_duration) > tolerance:
        raise ValueError(
            f"embedded audio duration mismatch: video_audio={audio_duration:.3f}s reference={reference_duration:.3f}s"
        )
    print(
        f"artifact ok: video={video_duration:.3f}s audio={reference_duration:.3f}s "
        f"resolution={expected_width}x{expected_height}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", dest="audio_only")
    parser.add_argument("video", nargs="?")
    parser.add_argument("reference_audio", nargs="?")
    parser.add_argument("--width", type=int, default=720)
    parser.add_argument("--height", type=int, default=1280)
    parser.add_argument("--tolerance", type=float, default=0.5)
    args = parser.parse_args()
    try:
        if args.audio_only:
            seconds = validate_audio(Path(args.audio_only))
            print(f"audio artifact ok: duration={seconds:.3f}s")
        elif args.video and args.reference_audio:
            validate_video(Path(args.video), Path(args.reference_audio), args.width, args.height, args.tolerance)
        else:
            parser.error("provide --audio FILE or VIDEO REFERENCE_AUDIO")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"artifact validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
