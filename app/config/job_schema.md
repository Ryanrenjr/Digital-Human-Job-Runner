# Job Schema V1 - Digital Human Job Runner

## Overview

Each generation request is stored as a **job**. Each job has a unique `job_id` and a matching directory under `DHJR_JOBS_DIR`.

The current local runner supports:

- `clean_video`: avatar video with generated voice
- `voice_only`: generated voice WAV only

## Directory Structure

```text
jobs/<job_id>/
├── job.json
├── input/
│   ├── title.txt
│   ├── subtitle.txt
│   ├── keywords.txt
│   └── script.txt
├── output/
│   ├── voice.wav
│   ├── voice_for_latentsync.wav
│   └── clean_video.mp4
└── logs/
    └── run.log
```

## Fields

### job_id

- Type: `string`
- Format: `YYYYMMDD_HHMMSS_<slug>`
- Description: unique job identifier and directory name.

### status

- Type: `string`
- Values: `pending`, `running`, `finished`, `failed`, `cancelled`

### title

- Type: `string`
- Description: main title, also written to `input/title.txt`.

### subtitle

- Type: `string`
- Description: subtitle, also written to `input/subtitle.txt`.

### keywords

- Type: `array<string>`
- Description: metadata keywords, written one per line to `input/keywords.txt`.

### script

- Type: `string`
- Description: full voiceover script, also written to `input/script.txt`.

### background_id

- Type: `string`
- Description: selected avatar/background video id from `app/config/backgrounds.json`.

The current LatentSync wrapper still copies the selected video to `DHJR_DEFAULT_AVATAR_VIDEO` for compatibility with the legacy pipeline. A later version should pass per-job avatar paths directly to the model runner.

### voice_id

- Type: `string`
- Default: `DHJR_DEFAULT_VOICE_ID`
- Description: voice profile identifier. Accepted values are configured by `DHJR_SUPPORTED_VOICE_IDS` and `DHJR_LEGACY_VOICE_IDS`.

### output_type

- Type: `string`
- Values:
  - `clean_video`
  - `voice_only`

### shutdown_after_done

- Type: `boolean`
- Default: `false`
- Description: whether the local machine should shut down after this job finishes.

### created_at, started_at, finished_at

- Type: ISO-like timestamp string or `null`
- Description: lifecycle timestamps.

### error_message

- Type: `string | null`
- Description: failure reason when status is `failed`.

### progress

```json
{
  "stage": "pending",
  "current_window": 0,
  "total_windows": 0,
  "percent": 0,
  "message": "Waiting to start"
}
```

Known stages: `pending`, `prepared`, `voice_generation`, `voice_postprocess`, `latentsync`, `collecting_output`, `finished`, `failed`, `cancelled`.

### paths

Absolute paths for job input, output, logs, downloads, and optional Windows-mounted output.

```json
{
  "job_dir": "/home/YOUR_USER/AI-Workspace/jobs/<job_id>",
  "input_dir": "/home/YOUR_USER/AI-Workspace/jobs/<job_id>/input",
  "output_dir": "/home/YOUR_USER/AI-Workspace/jobs/<job_id>/output",
  "log_dir": "/home/YOUR_USER/AI-Workspace/jobs/<job_id>/logs",
  "title_txt": "/home/YOUR_USER/AI-Workspace/jobs/<job_id>/input/title.txt",
  "subtitle_txt": "/home/YOUR_USER/AI-Workspace/jobs/<job_id>/input/subtitle.txt",
  "keywords_txt": "/home/YOUR_USER/AI-Workspace/jobs/<job_id>/input/keywords.txt",
  "script_txt": "/home/YOUR_USER/AI-Workspace/jobs/<job_id>/input/script.txt",
  "voice_wav": "/home/YOUR_USER/AI-Workspace/jobs/<job_id>/output/voice.wav",
  "voice_for_latentsync_wav": "/home/YOUR_USER/AI-Workspace/jobs/<job_id>/output/voice_for_latentsync.wav",
  "clean_video": "/home/YOUR_USER/AI-Workspace/jobs/<job_id>/output/clean_video.mp4",
  "final_video": null,
  "run_log": "/home/YOUR_USER/AI-Workspace/jobs/<job_id>/logs/run.log",
  "windows_desktop_output": "/mnt/c/Users/YOUR_WINDOWS_USER/Desktop/DigitalHumanOutput/<job_id>_clean_video.mp4"
}
```
