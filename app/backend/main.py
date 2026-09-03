import logging
import os
import re
import shutil
import subprocess
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from background_utils import (
    CUSTOM_DIR,
    THUMBNAILS_DIR,
    _find_ffmpeg,
    generate_thumbnail,
    get_background_by_id,
    load_backgrounds,
    make_background_id,
    save_backgrounds,
)
from job_store import create_job, list_jobs, load_job, save_job
from progress_utils import get_cleanvideo_progress
from queue_runner import queue_runner
from runner import check_no_other_running_job, is_job_process_running, kill_job_process, start_job
from schemas import (
    HealthResponse,
    JobCreateRequest,
    JobRunResponse,
    PullModelRequest,
    QueueAutoRunRequest,
    QueueShutdownRequest,
    ScriptFormatRequest,
)
import script_assistant
from settings import AI_WORKSPACE, APP_NAME, APP_VERSION, EXTRA_CORS_ORIGINS, VITE_FRONTEND_ORIGIN
from voice_store import list_voice_profiles, load_voice_profile, make_voice_id, save_voice_profile
from voice_training_runner import start_voice_training

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    queue_runner.recover_stale_jobs()
    queue_runner.start_worker()
    yield
    queue_runner.stop_worker()


app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[VITE_FRONTEND_ORIGIN, *EXTRA_CORS_ORIGINS],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _with_live_progress(job: dict) -> dict:
    if job.get("status") != "running":
        return job
    live = get_cleanvideo_progress(job["job_id"])
    if not live:
        return job
    job = dict(job)
    job["progress"] = live
    return job


def _host_path(path_value: str | None) -> Path:
    raw = str(path_value or "")
    if raw.startswith("/mnt/") and len(raw) > 7 and raw[6] == "/":
        drive = raw[5].upper()
        rest = raw[7:].replace("/", "\\")
        return Path(f"{drive}:\\{rest}")
    return Path(raw)


def _with_artifacts(job: dict) -> dict:
    job_id         = job.get("job_id", "")
    clean_video    = job.get("paths", {}).get("clean_video", "")
    # Derive subtitle_lines_txt even for jobs created before the field was added
    sl_txt_path    = job.get("paths", {}).get("subtitle_lines_txt") or \
                     str(AI_WORKSPACE / "jobs" / job_id / "output" / "subtitle_lines.txt")
    voice_wav      = job.get("paths", {}).get("voice_wav", "")
    cv_exists      = bool(clean_video and _host_path(clean_video).exists())
    sl_exists      = bool(sl_txt_path and _host_path(sl_txt_path).exists())
    vw_exists      = bool(voice_wav and _host_path(voice_wav).exists())
    job = dict(job)
    job["artifacts"] = {
        "clean_video_exists":    cv_exists,
        "voice_wav_exists":      vw_exists,
        "subtitle_lines_exists": sl_exists,
        "download_url":       f"/jobs/{job_id}/download"       if cv_exists else None,
        "preview_url":        f"/jobs/{job_id}/download"       if cv_exists else None,
        "voice_download_url": f"/jobs/{job_id}/download-voice" if vw_exists else None,
    }
    if sl_exists:
        try:
            job["subtitle_lines_text"] = _host_path(sl_txt_path).read_text(encoding="utf-8")
        except Exception:
            pass
    return job


# ============================================================ HEALTH

@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(
        status="ok",
        service=APP_NAME,
        version=APP_VERSION,
    )


# ============================================================ BACKGROUNDS


# ============================================================ VOICES

def _with_voice_progress(profile: dict) -> dict:
    result = dict(profile)
    log_path = _host_path(result.get("trainingLogPath"))
    if not log_path.exists():
        return result

    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    tail = lines[-2000:]
    progress_text = ""
    progress_percent = None

    for line in reversed(tail):
        if "[ERROR]" in line:
            progress_text = line.replace("[ERROR]", "").strip()
            break
        if "Voice training finished" in line:
            progress_text = "声音训练完成"
            progress_percent = 100
            break
        if line.startswith("Step 6:"):
            progress_text = "正在训练声音模型"
            progress_percent = 70
            break
        if line.startswith("Step 5:"):
            progress_text = "正在准备训练参数"
            progress_percent = 62
            break
        if line.startswith("Step 4:"):
            progress_text = "正在整理训练数据"
            progress_percent = 58
            break
        if line.startswith("Step 3:"):
            progress_text = "正在识别每段声音的文字"
            progress_percent = 35
            break
        if line.startswith("Step 2:"):
            progress_text = "正在切出可训练的人声片段"
            progress_percent = 20
            break
        if line.startswith("Step 1:"):
            progress_text = "正在从素材里提取声音"
            progress_percent = 8
            break

    for line in reversed(tail):
        match = re.search(r"\[train\]\s+step\s+(\d+)", line)
        if match:
            step = int(match.group(1))
            total_steps = 300
            progress_text = f"正在训练声音模型：第 {step}/{total_steps} 步"
            progress_percent = min(98, 70 + round((step / total_steps) * 28))
            break
        if line.startswith("[Audio]"):
            progress_text = "正在训练声音模型：生成试听样本"
            progress_percent = max(progress_percent or 0, 70)
            break

    if progress_percent is None or progress_percent < 58:
        for line in reversed(tail):
            match = re.search(r"\[(\d+)/(\d+)\]", line)
            if match:
                current = int(match.group(1))
                total = max(1, int(match.group(2)))
                progress_text = f"正在识别声音文字：{current}/{total} 段"
                progress_percent = min(57, 35 + round((current / total) * 22))
                break

    result["trainingProgressText"] = progress_text
    result["trainingProgressPercent"] = progress_percent
    return result


@app.get("/voices")
def get_voices():
    return [_with_voice_progress(profile) for profile in list_voice_profiles()]


@app.get("/voices/{voice_id}")
def get_voice(voice_id: str):
    profile = load_voice_profile(voice_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Voice not found: {voice_id}")
    return _with_voice_progress(profile)


@app.get("/voices/{voice_id}/log")
def get_voice_log(voice_id: str):
    profile = load_voice_profile(voice_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Voice not found: {voice_id}")
    log_path = _host_path(profile.get("trainingLogPath"))
    if not log_path.exists():
        return {"voice_id": voice_id, "log": "", "lines": 0}
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    tail = lines[-200:]
    return {"voice_id": voice_id, "log": "\n".join(tail), "lines": len(tail)}


@app.post("/voices/{voice_id}/retry")
def retry_voice_training(voice_id: str):
    profile = load_voice_profile(voice_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Voice not found: {voice_id}")

    raw_dir = AI_WORKSPACE / "voices" / voice_id / "raw_uploads"
    if not raw_dir.exists() or not any(raw_dir.iterdir()):
        raise HTTPException(status_code=400, detail="这个声音没有可训练的原始素材，请重新上传声音素材。")

    try:
        pid = start_voice_training(voice_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"重新启动声音训练失败：{exc}")

    profile = load_voice_profile(voice_id) or profile
    profile["trainingPid"] = pid
    save_voice_profile(profile)
    return profile


@app.post("/voices/train")
async def train_voice(
    name: str = Form(...),
    language: str = Form("zh"),
    dialect: str = Form("mandarin"),
    style: str = Form("friendly_natural"),
    audio_minutes: float = Form(0),
    audio_score: int = Form(0),
    files: list[UploadFile] = File(...),
):
    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="请先填写声音名称。")
    if not files:
        raise HTTPException(status_code=400, detail="请先上传声音素材。")

    voice_id = make_voice_id(clean_name)
    voice_dir = AI_WORKSPACE / "voices" / voice_id
    raw_dir = voice_dir / "raw_uploads"
    raw_dir.mkdir(parents=True, exist_ok=True)

    saved_files = []
    for index, file in enumerate(files, 1):
        if not file.filename:
            continue
        suffix = Path(file.filename).suffix.lower()
        if suffix not in {".wav", ".mp3", ".m4a", ".mp4", ".mov", ".webm"}:
            raise HTTPException(status_code=400, detail=f"不支持的声音素材格式：{file.filename}")
        safe_name = f"{index:04d}_{Path(file.filename).name}"
        dst = raw_dir / safe_name
        content = await file.read()
        dst.write_bytes(content)
        saved_files.append({"name": file.filename, "path": str(dst), "size": len(content)})

    if not saved_files:
        raise HTTPException(status_code=400, detail="没有收到可用的声音素材文件。")

    profile = {
        "id": voice_id,
        "name": clean_name,
        "language": language,
        "dialect": dialect if language == "zh" else "",
        "style": style,
        "mode": "lora_finetune",
        "trainingStatus": "queued",
        "audioMinutes": audio_minutes,
        "audioScore": audio_score,
        "audioFiles": saved_files,
        "createdAt": datetime.now().isoformat(),
        "updatedAt": datetime.now().isoformat(),
        "trainingLogPath": str(voice_dir / "train.log"),
        "checkpointPath": None,
        "referenceWavPath": None,
        "referenceText": "",
        "trainingError": None,
    }
    save_voice_profile(profile)

    try:
        pid = start_voice_training(voice_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"启动声音训练失败：{exc}")

    profile = load_voice_profile(voice_id) or profile
    profile["trainingPid"] = pid
    save_voice_profile(profile)
    return profile

@app.get("/backgrounds")
def get_backgrounds():
    return load_backgrounds()


@app.post("/backgrounds/upload")
async def upload_background(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="请选择一个视频文件。")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".mp4", ".mov"}:
        raise HTTPException(status_code=400, detail="请上传常见视频格式。")

    bg_id    = make_background_id(file.filename)
    dst_path = CUSTOM_DIR / f"{bg_id}.mp4"
    tmp_path = CUSTOM_DIR / f"{bg_id}{suffix}"
    CUSTOM_DIR.mkdir(parents=True, exist_ok=True)

    try:
        content = await file.read()
        if suffix == ".mp4":
            dst_path.write_bytes(content)
        else:
            tmp_path.write_bytes(content)
            ffmpeg = _find_ffmpeg()
            if not ffmpeg:
                raise HTTPException(status_code=500, detail="缺少视频转换组件，暂时无法保存该视频。")
            r = subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-i",
                    str(tmp_path),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "20",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-movflags",
                    "+faststart",
                    str(dst_path),
                ],
                capture_output=True,
                timeout=600,
            )
            tmp_path.unlink(missing_ok=True)
            if r.returncode != 0 or not dst_path.exists():
                detail = r.stderr.decode("utf-8", errors="replace")[:500]
                raise HTTPException(status_code=500, detail=f"视频转换失败：{detail}")
    except HTTPException:
        tmp_path.unlink(missing_ok=True)
        raise
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"保存视频失败：{e}")

    bg = {
        "id":             bg_id,
        "name":           Path(file.filename).stem,
        "path":           str(dst_path),
        "description":    f"Custom upload {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "type":           "custom",
        "thumbnail_path": str(THUMBNAILS_DIR / f"{bg_id}.jpg"),
        "preview_url":    f"/backgrounds/{bg_id}/preview",
        "thumbnail_url":  f"/backgrounds/{bg_id}/thumbnail",
    }

    bgs = load_backgrounds()
    bgs.append(bg)
    save_backgrounds(bgs)
    generate_thumbnail(bg)

    logger.info("Uploaded background %s (%d bytes)", bg_id, len(content))
    return bg


@app.get("/backgrounds/{background_id}/thumbnail")
def get_background_thumbnail(background_id: str):
    bg = get_background_by_id(background_id)
    if bg is None:
        raise HTTPException(status_code=404, detail=f"Background not found: {background_id}")

    thumb_path = Path(bg.get("thumbnail_path", ""))
    if not thumb_path.exists():
        generate_thumbnail(bg)

    if not thumb_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not available.")

    return FileResponse(path=str(thumb_path), media_type="image/jpeg")


@app.get("/backgrounds/{background_id}/preview")
def get_background_preview(background_id: str):
    bg = get_background_by_id(background_id)
    if bg is None:
        raise HTTPException(status_code=404, detail=f"Background not found: {background_id}")

    mp4_path = Path(bg.get("path", ""))
    if not mp4_path.exists():
        raise HTTPException(status_code=404, detail="Background video file not found.")

    return FileResponse(path=str(mp4_path), media_type="video/mp4")


@app.delete("/backgrounds/{background_id}")
def delete_background(background_id: str):
    bg = get_background_by_id(background_id)
    if bg is None:
        raise HTTPException(status_code=404, detail=f"Background not found: {background_id}")

    if bg.get("type") == "builtin":
        raise HTTPException(status_code=400, detail="Built-in backgrounds cannot be deleted.")

    for job in list_jobs():
        if job.get("status") == "running" and is_job_process_running(job["job_id"]):
            raise HTTPException(
                status_code=409,
                detail="A job is currently running. Stop it before deleting backgrounds.",
            )

    mp4_path   = Path(bg.get("path", ""))
    thumb_path = Path(bg.get("thumbnail_path", ""))
    mp4_path.unlink(missing_ok=True)
    thumb_path.unlink(missing_ok=True)

    bgs = [b for b in load_backgrounds() if b.get("id") != background_id]
    save_backgrounds(bgs)

    logger.info("Deleted background %s", background_id)
    return {"success": True, "id": background_id}


# ============================================================ QUEUE

@app.get("/queue/status")
def get_queue_status():
    try:
        return queue_runner.get_status()
    except Exception as exc:
        logger.error("[QueueStatus] Unexpected error: %s", exc)
        return {
            "auto_run": False,
            "paused": False,
            "status": "idle",
            "current_job_id": None,
            "current_job_title": None,
            "pending_count": 0,
            "running_count": 0,
            "finished_count": 0,
            "failed_count": 0,
            "cancelled_count": 0,
            "shutdown_after_complete": False,
            "worker_alive": False,
            "error": str(exc),
        }


@app.post("/queue/auto-run")
def set_queue_auto_run(req: QueueAutoRunRequest):
    queue_runner.set_auto_run(req.enabled)
    return queue_runner.get_status()


@app.post("/queue/pause")
def pause_queue():
    queue_runner.set_paused(True)
    return queue_runner.get_status()


@app.post("/queue/resume")
def resume_queue():
    queue_runner.set_paused(False)
    return queue_runner.get_status()


@app.post("/queue/run-next")
def run_next_job():
    job_id = queue_runner.run_next_pending()
    if job_id is None:
        raise HTTPException(
            status_code=409,
            detail="No pending jobs or a job is already running.",
        )
    return {"started": job_id, **queue_runner.get_status()}


@app.post("/queue/shutdown-after-complete")
def set_shutdown_after_complete(req: QueueShutdownRequest):
    queue_runner.set_shutdown_after_complete(req.enabled)
    return queue_runner.get_status()


# ============================================================ JOBS

@app.post("/jobs")
def create_job_endpoint(req: JobCreateRequest):
    if req.output_type not in ("clean_video", "voice_only"):
        raise HTTPException(
            status_code=400,
            detail=f"output_type '{req.output_type}' is not supported. Use 'clean_video' or 'voice_only'.",
        )
    try:
        voice_profile = load_voice_profile(req.voice_id) if req.voice_id else None
        if voice_profile:
            req.voice_checkpoint_path = voice_profile.get("checkpointPath")
            req.voice_reference_wav_path = voice_profile.get("referenceWavPath")
            req.voice_reference_text = voice_profile.get("referenceText", "")
            req.voice_training_status = voice_profile.get("trainingStatus")
        job = create_job(req)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create job: {e}")
    return job


@app.get("/jobs")
def get_jobs():
    return [_with_artifacts(_with_live_progress(j)) for j in list_jobs()]


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = load_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return _with_artifacts(_with_live_progress(job))


@app.post("/jobs/{job_id}/run", response_model=JobRunResponse)
def run_job(job_id: str):
    job = load_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    status = job.get("status")
    if status == "running":
        raise HTTPException(status_code=400, detail=f"Job {job_id} is already running.")
    if status == "finished":
        raise HTTPException(
            status_code=400,
            detail=f"Job {job_id} is already finished. Reset the job to run again.",
        )

    running_other = check_no_other_running_job(job_id)
    if running_other:
        raise HTTPException(
            status_code=409,
            detail=f"Another job is already running: {running_other}.",
        )

    try:
        pid = start_job(job_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start job: {e}")

    logger.info("Started job %s with PID %d", job_id, pid)
    return JobRunResponse(message="Job started", job_id=job_id, pid=pid)


@app.get("/jobs/{job_id}/log")
def get_job_log(job_id: str):
    job = load_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    run_log  = job.get("paths", {}).get("run_log", "")
    log_path = _host_path(run_log) if run_log else None

    if not log_path or not log_path.exists():
        return {"job_id": job_id, "log": "", "lines": 0}

    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    tail  = lines[-200:]
    return {"job_id": job_id, "log": "\n".join(tail), "lines": len(tail)}


@app.delete("/jobs/{job_id}")
def delete_job_endpoint(job_id: str):
    job = load_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    if job.get("status") == "running" and is_job_process_running(job_id):
        raise HTTPException(status_code=409, detail="Cannot delete a running job. Cancel it first.")

    job_dir = AI_WORKSPACE / "jobs" / job_id
    shutil.rmtree(job_dir, ignore_errors=True)
    logger.info("Deleted job %s", job_id)
    return {"success": True, "job_id": job_id}


@app.get("/jobs/{job_id}/download")
def download_job(job_id: str):
    job = load_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    clean_video = job.get("paths", {}).get("clean_video", "")
    clean_video_path = _host_path(clean_video)
    if not clean_video or not clean_video_path.exists():
        raise HTTPException(status_code=404, detail="clean_video.mp4 not found for this job.")

    return FileResponse(path=str(clean_video_path), media_type="video/mp4")


@app.get("/jobs/{job_id}/download-voice")
def download_job_voice(job_id: str):
    job = load_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    voice_wav = job.get("paths", {}).get("voice_wav", "")
    voice_wav_path = _host_path(voice_wav)
    if not voice_wav or not voice_wav_path.exists():
        raise HTTPException(status_code=404, detail="voice.wav not found for this job.")

    return FileResponse(
        path=str(voice_wav_path),
        media_type="audio/wav",
        filename=f"{job_id}_voice.wav",
    )


@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    job = load_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    status = job.get("status")
    if status == "finished":
        raise HTTPException(status_code=400, detail="Cannot cancel a finished job.")

    if status == "running":
        kill_job_process(job_id)

    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    job["status"]        = "cancelled"
    job["finished_at"]   = now
    job["error_message"] = "Cancelled by user."
    job.setdefault("progress", {})
    job["progress"]["stage"]   = "cancelled"
    job["progress"]["message"] = "Cancelled by user."
    save_job(job)
    logger.info("Cancelled job %s (was: %s)", job_id, status)
    return job


@app.post("/jobs/{job_id}/reset")
def reset_job(job_id: str):
    job = load_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    status = job.get("status")
    if status == "finished":
        raise HTTPException(status_code=400, detail="Cannot reset a finished job.")
    if status == "running" and is_job_process_running(job_id):
        raise HTTPException(status_code=409, detail="Job appears to be actively running. Cannot reset.")
    if status == "pending":
        return job

    job["status"]        = "pending"
    job["started_at"]    = None
    job["finished_at"]   = None
    job["error_message"] = None
    job.setdefault("progress", {})
    job["progress"]["stage"]          = "pending"
    job["progress"]["current_window"] = 0
    job["progress"]["total_windows"]  = 0
    job["progress"]["percent"]        = 0
    job["progress"]["message"]        = "Reset to pending"
    save_job(job)
    logger.info("Reset job %s to pending (was: %s)", job_id, status)
    return job


# ============================================================ SCRIPT ASSISTANT

@app.post("/script/install-ollama")
async def install_ollama_endpoint():
    return await script_assistant.install_ollama()


@app.get("/script/install-status")
async def install_status_endpoint():
    return await script_assistant.install_status()


@app.post("/script/repair-runners")
async def repair_runners_endpoint():
    return await script_assistant.repair_runners()


@app.get("/script/repair-status")
async def repair_status_endpoint():
    return await script_assistant.repair_status()


@app.post("/script/start-ollama")
async def start_ollama_endpoint():
    return await script_assistant.start_ollama()


@app.post("/script/pull-model")
async def pull_model_endpoint(req: PullModelRequest):
    return await script_assistant.pull_model(req.model)


@app.get("/script/pull-status")
async def pull_status_endpoint(model: str = "qwen2.5:7b"):
    return await script_assistant.pull_status(model)


@app.get("/script/health")
async def script_health(model: str = "qwen2.5:7b"):
    result = await script_assistant.check_health(model)
    msg_raw = result.get("message", "")

    if msg_raw == "ollama_not_running":
        result["user_message"] = "Ollama is not running. Please start Ollama first."
        result["user_message_zh"] = "Ollama 未启动，请先启动 Ollama。"
    elif msg_raw == "runner_missing":
        result["user_message"] = "CPU runner missing. Please repair Ollama installation."
        result["user_message_zh"] = "CPU 运行库缺失，请修复 Ollama 安装。"
    elif msg_raw.startswith("model_not_found:"):
        m = msg_raw.split(":", 1)[1]
        result["user_message"] = f"Model not found. Run: ollama pull {m}"
        result["user_message_zh"] = f"模型未找到，请先运行：ollama pull {m}"
    elif msg_raw == "ready":
        result["user_message"] = "AI is ready"
        result["user_message_zh"] = "AI 可以使用"

    return result


@app.post("/script/format")
async def format_script(req: ScriptFormatRequest):
    try:
        result = await script_assistant.format_script(
            raw_text=req.raw_text,
            model=req.model,
        )
        return result
    except ValueError as exc:
        code = str(exc)
        if code == "ollama_not_running":
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "OLLAMA_NOT_RUNNING",
                    "message": "Ollama is not running. Please start Ollama first.",
                },
            )
        if code == "runner_missing":
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "RUNNER_MISSING",
                    "message": "CPU runner missing. Click '② 修复运行库' to fix.",
                },
            )
        if code.startswith("model_not_found:"):
            m = code.split(":", 1)[1]
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "MODEL_NOT_FOUND",
                    "message": f"Model not found. Run: ollama pull {m}",
                    "model": m,
                },
            )
        raise HTTPException(
            status_code=500,
            detail={"code": "AI_ERROR", "message": f"AI formatting failed: {code}"},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "AI_ERROR", "message": f"Unexpected error: {exc}"},
        )
