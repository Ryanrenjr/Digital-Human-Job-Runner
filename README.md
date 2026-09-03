# Digital Human Job Runner

A local web console for creating, queuing, previewing, and downloading digital-human voice and avatar-video generation jobs.

This project was forked from a client-specific internal runner and has been generalized so it can become a reusable local product.

## What It Does

- Create video or voice-only jobs from title, subtitle, keywords, and script
- Select or upload avatar/background MP4 assets
- Queue jobs and run them one at a time
- Track generation progress and view logs
- Preview and download generated MP4/WAV outputs
- Use a local Ollama model to format scripts and generate subtitle lines

## Project Layout

```text
app/backend/     FastAPI API, job storage, queue runner, pipeline wrappers
app/frontend/    React + Vite UI
app/config/      Job schema and runtime config files
scripts/         Shell pipeline entry points
systemd/         Optional user services
```

## Quick Start

On Windows, double-click `Start-Digital-Human-Job-Runner.bat` from the project root. It installs missing local dependencies, starts the backend and frontend on free local ports, and opens the browser.

Manual startup:

1. Copy `.env.example` to `.env` and adjust paths for your machine.
2. Put this project at the workspace path configured by `DHJR_WORKSPACE`.
3. Install frontend dependencies:

```bash
cd app/frontend
npm install
```

4. Install backend dependencies:

```bash
cd app/backend
python3 -m pip install -r requirements.txt
```

5. Start backend:

```bash
cd app/backend
python3 -m uvicorn main:app --host 127.0.0.1 --port 8018
```

6. Start frontend:

```bash
cd app/frontend
npm run dev
```

Then open `http://127.0.0.1:5173`.

## Configuration

The backend reads `DHJR_*` environment variables. Important settings:

- `DHJR_WORKSPACE`: root workspace containing `app/`, `scripts/`, `jobs/`, `assets/`, and model projects
- `DHJR_DEFAULT_VOICE_ID`: default voice profile stored on each job
- `DHJR_SUPPORTED_VOICE_IDS`: comma-separated voice IDs accepted by the job preparer
- `DHJR_DEFAULT_AVATAR_VIDEO`: the avatar video path consumed by the current LatentSync pipeline
- `DHJR_WINDOWS_OUTPUT_DIR`: optional WSL-mounted Windows output folder
- `DHJR_RUN_SCRIPT` and `DHJR_RUN_VOICE_SCRIPT`: pipeline entry scripts

The frontend reads `VITE_API_BASE_URL`.

## Current Status

This is a generic local runner skeleton. The underlying VoxCPM and LatentSync scripts are still expected to exist under the configured workspace. The next product step is to make voice profiles and avatar pipeline inputs fully per-job instead of using shared runtime input/output folders.
