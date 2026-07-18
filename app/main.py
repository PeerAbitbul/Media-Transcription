"""FastAPI application: lists videos, enqueues transcription jobs, reports
status, and serves the SRT/TXT results and the static frontend.
"""
import os
import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import config, db
from app.celery_app import celery

app = FastAPI(title="Video Transcriber")


@app.on_event("startup")
def _startup():
    db.init_db()


def _list_video_files() -> list[str]:
    """Return sorted relative paths of every video under VIDEOS_DIR."""
    videos: list[str] = []
    root = config.VIDEOS_DIR
    if not os.path.isdir(root):
        return videos
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if os.path.splitext(name)[1].lower() in config.MEDIA_EXTENSIONS:
                rel = os.path.relpath(os.path.join(dirpath, name), root)
                videos.append(rel)
    return sorted(videos)


def _enqueue(filename: str) -> dict:
    """Create a job row and dispatch the Celery task. Skips duplicates."""
    existing = db.active_job_for_file(filename)
    if existing:
        return existing
    job_id = db.create_job(filename)
    result = celery.send_task("app.worker.transcribe", args=[job_id, filename])
    db.set_task_id(job_id, result.id)
    return db.get_job(job_id)


@app.get("/api/videos")
def get_videos():
    """List videos and their latest job status (for the UI table)."""
    jobs = db.list_jobs()
    latest_by_file: dict[str, dict] = {}
    for job in jobs:  # jobs are ordered newest-first
        latest_by_file.setdefault(job["filename"], job)

    items = []
    for filename in _list_video_files():
        items.append({"filename": filename, "job": latest_by_file.get(filename)})
    return {"videos": items}


@app.get("/api/jobs")
def get_jobs():
    """Return every job, newest first (used by the UI polling loop)."""
    return {"jobs": db.list_jobs()}


@app.post("/api/transcribe")
def transcribe_one(payload: dict):
    filename = (payload or {}).get("filename")
    if not filename:
        raise HTTPException(status_code=400, detail="filename is required")
    if filename not in _list_video_files():
        raise HTTPException(status_code=404, detail="Unknown video file")
    return _enqueue(filename)


@app.post("/api/transcribe-all")
def transcribe_all():
    """Enqueue every video that has no completed or in-flight job."""
    jobs = db.list_jobs()
    latest_by_file: dict[str, dict] = {}
    for job in jobs:
        latest_by_file.setdefault(job["filename"], job)

    enqueued = []
    for filename in _list_video_files():
        latest = latest_by_file.get(filename)
        if latest and latest["status"] in (db.STATUS_DONE, db.STATUS_QUEUED, db.STATUS_PROCESSING):
            continue
        enqueued.append(_enqueue(filename))
    return {"enqueued": enqueued, "count": len(enqueued)}


def _result_path(job_id: int, kind: str) -> str:
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    path = job.get("srt_path") if kind == "srt" else job.get("txt_path")
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Result not ready")
    return path


@app.get("/api/jobs/{job_id}/srt")
def download_srt(job_id: int):
    path = _result_path(job_id, "srt")
    return FileResponse(path, media_type="text/plain; charset=utf-8",
                        filename=os.path.basename(path))


@app.get("/api/jobs/{job_id}/txt")
def download_txt(job_id: int):
    path = _result_path(job_id, "txt")
    return FileResponse(path, media_type="text/plain; charset=utf-8",
                        filename=os.path.basename(path))


def delete_video_and_outputs(filename: str):
    """Remove a video, its transcript files, and its job rows. Path-safe."""
    videos_root = os.path.abspath(config.VIDEOS_DIR)
    for job in db.jobs_for_file(filename):
        for key in ("srt_path", "txt_path"):
            path = job.get(key)
            if path and os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
    vpath = os.path.abspath(os.path.join(config.VIDEOS_DIR, filename))
    # Guard against path traversal — must stay inside the videos folder.
    if vpath.startswith(videos_root + os.sep) and os.path.isfile(vpath):
        try:
            os.remove(vpath)
        except OSError:
            pass
    db.delete_jobs_for_file(filename)


@app.post("/api/delete")
def delete_video(payload: dict):
    filename = (payload or {}).get("filename")
    if not filename:
        raise HTTPException(status_code=400, detail="filename is required")
    if db.active_job_for_file(filename):
        raise HTTPException(status_code=409, detail="Cannot delete while queued or processing")
    delete_video_and_outputs(filename)
    return {"ok": True, "filename": filename}


@app.get("/api/config")
def get_config():
    """Expose non-sensitive settings so the UI can show the active model."""
    return JSONResponse(
        {
            "model": config.WHISPER_MODEL,
            "language": config.WHISPER_LANGUAGE,
            "compute_type": config.WHISPER_COMPUTE_TYPE,
            "beam_size": config.WHISPER_BEAM_SIZE,
        }
    )


# --------------------------------------------------------------------------
# Telegram settings — configured entirely from the web UI, stored in the DB
# (persistent), applied hot by the bot service.
# --------------------------------------------------------------------------
def _mask(secret: str | None) -> str:
    """Return a masked preview of a secret, e.g. '••••8842'."""
    if not secret:
        return ""
    tail = secret[-4:] if len(secret) >= 4 else secret
    return "••••" + tail


def _write_creds_file(api_id: str | None, api_hash: str | None):
    """Write api_id/api_hash for the local Bot API server's entrypoint to read."""
    if not (api_id and api_hash):
        return
    os.makedirs(os.path.dirname(config.TELEGRAM_CREDS_FILE), exist_ok=True)
    with open(config.TELEGRAM_CREDS_FILE, "w", encoding="utf-8") as f:
        f.write(f"API_ID={api_id}\nAPI_HASH={api_hash}\n")


@app.get("/api/settings/telegram")
def get_telegram_settings():
    """Return the Telegram config with secrets masked, plus live connection status."""
    s = db.get_settings(config.TG_KEYS)
    return {
        "enabled": s.get("tg_enabled") == "1",
        "bot_token_preview": _mask(s.get("tg_bot_token")),
        "api_id": s.get("tg_api_id") or "",
        "api_hash_preview": _mask(s.get("tg_api_hash")),
        "allowed_ids": s.get("tg_allowed_ids") or "",
        "has_token": bool(s.get("tg_bot_token")),
        "has_api_hash": bool(s.get("tg_api_hash")),
        "status": s.get("tg_status") or "not_configured",
        "bot_username": s.get("tg_bot_username") or "",
        "last_error": s.get("tg_last_error") or "",
        "mode": s.get("tg_mode") or "",
    }


@app.post("/api/settings/telegram")
def save_telegram_settings(payload: dict):
    """Save Telegram config. Secret fields left blank keep their stored value."""
    payload = payload or {}

    # Secrets: only overwrite when a new non-empty value is provided.
    token = (payload.get("bot_token") or "").strip()
    if token:
        db.set_setting("tg_bot_token", token)
    api_hash = (payload.get("api_hash") or "").strip()
    if api_hash:
        db.set_setting("tg_api_hash", api_hash)

    # Non-secret fields: always set from payload.
    api_id = (payload.get("api_id") or "").strip()
    db.set_setting("tg_api_id", api_id)
    db.set_setting("tg_allowed_ids", (payload.get("allowed_ids") or "").strip())
    db.set_setting("tg_enabled", "1" if payload.get("enabled") else "0")
    db.set_setting("tg_updated_at", time.time())
    # Reset status so the UI shows we're (re)connecting until the bot reports back.
    db.set_setting("tg_status", "connecting")
    db.set_setting("tg_last_error", "")

    # Persist api creds for the local Bot API server's entrypoint.
    stored = db.get_settings(["tg_api_id", "tg_api_hash"])
    _write_creds_file(stored.get("tg_api_id"), stored.get("tg_api_hash"))

    return get_telegram_settings()


# Serve the static frontend at the root. Mounted last so /api/* wins.
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
