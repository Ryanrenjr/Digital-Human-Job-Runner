# Digital Human Job Runner

A local web console for creating, queuing, previewing, and downloading digital-human voice and avatar-video generation jobs.

This project was forked from a client-specific internal runner and has been generalized so it can become a reusable local product.

## What It Does

- Create video or voice-only jobs from title, subtitle, keywords, and script
- Select or upload avatar/background MP4 assets
- Queue jobs and run them one at a time
- Keep each job's inputs, temporary work files, outputs, and logs isolated
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
- `DHJR_ENGINE_WORKSPACE`: read-only engine/model workspace used by the pipeline
- `DHJR_DATABASE_PATH`: SQLite database for job, voice, and queue metadata
- `DHJR_CONDA_EXE`: Conda, Miniforge, or Micromamba executable available to WSL
- `DHJR_VOXCPM_ENV` and `DHJR_LATENTSYNC_ENV`: model environment names
- `DHJR_WINDOWS_OUTPUT_DIR`: optional WSL-mounted Windows output folder
- `DHJR_RUN_SCRIPT` and `DHJR_RUN_VOICE_SCRIPT`: pipeline entry scripts

The frontend reads `VITE_API_BASE_URL`.

## Runtime isolation

The engine workspace contains models and code only. A job runs from its own
`jobs/<job_id>/input`, `jobs/<job_id>/work`, and `jobs/<job_id>/output`
directories, so one job no longer clears or overwrites another job's media.
The SQLite database is the metadata source; `job.json` and voice `profile.json`
files remain as readable compatibility mirrors for existing tools.

When a job is created, its avatar video and voice reference audio are snapshotted
inside the job input directory. Removing a later global asset therefore cannot
break a queued job. Legacy JSON mirrors are migrated once during backend startup;
normal reads are SQLite-only. The environment status is available at
`GET /system/readiness` and is also shown in the task page.
