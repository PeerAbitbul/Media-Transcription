"""Celery task that transcribes a single video with faster-whisper.

The model is loaded lazily and cached per worker process. Each job is fully
isolated: a failure on one file marks that job failed and never blocks the
rest of the queue.
"""
import os
import time

from celery.signals import worker_ready

from app import config, db
from app.celery_app import celery

# Ensure the jobs table exists on the worker side too, so the system is
# robust to start order and to the DB file being (re)created.
db.init_db()


@worker_ready.connect
def _resume_pending(**_kwargs):
    """On startup, re-queue every job that was pending when we last stopped.

    Makes the system survive a shutdown/reboot: the DB is the source of truth,
    so we purge whatever the broker may still hold (avoiding duplicates) and
    re-enqueue all queued/processing jobs. An interrupted job restarts from the
    beginning (Whisper has no mid-file checkpoint) — but it restarts on its own.
    """
    try:
        purged = celery.control.purge()
    except Exception as e:  # noqa: BLE001
        purged = None
        print(f"[worker] startup purge failed: {e}", flush=True)

    pending = db.jobs_to_resume()
    for job in pending:
        db.reset_to_queued(job["id"])
        result = celery.send_task("app.worker.transcribe", args=[job["id"], job["filename"]])
        db.set_task_id(job["id"], result.id)
    print(f"[worker] startup: purged={purged}, re-queued {len(pending)} pending job(s)",
          flush=True)

# Loaded once per worker process (see _get_model). faster-whisper is imported
# lazily so the API container never needs to pull it into memory.
_model = None


def _get_model():
    """Load (and cache) the Whisper model. Downloaded once into whisper-cache."""
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        print(
            f"[worker] loading model={config.WHISPER_MODEL} "
            f"device={config.WHISPER_DEVICE} compute_type={config.WHISPER_COMPUTE_TYPE}",
            flush=True,
        )
        _model = WhisperModel(
            config.WHISPER_MODEL,
            device=config.WHISPER_DEVICE,
            compute_type=config.WHISPER_COMPUTE_TYPE,
        )
    return _model


def _format_timestamp(seconds: float) -> str:
    """Format seconds as an SRT timestamp: HH:MM:SS,mmm."""
    if seconds < 0:
        seconds = 0.0
    millis = int(round(seconds * 1000.0))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


@celery.task(name="app.worker.transcribe", bind=True)
def transcribe(self, job_id: int, filename: str):
    """Transcribe one video file into SRT + TXT next to /app/transcripts."""
    db.mark_processing(job_id)
    started = time.time()

    video_path = os.path.join(config.VIDEOS_DIR, filename)
    if not os.path.isfile(video_path):
        db.mark_failed(job_id, f"Video file not found: {video_path}")
        return {"job_id": job_id, "status": "failed"}

    base = os.path.splitext(os.path.basename(filename))[0]
    os.makedirs(config.TRANSCRIPTS_DIR, exist_ok=True)
    srt_path = os.path.join(config.TRANSCRIPTS_DIR, f"{base}.srt")
    txt_path = os.path.join(config.TRANSCRIPTS_DIR, f"{base}.txt")

    try:
        model = _get_model()
        # Language is chosen in the UI and stored in the DB (falls back to the
        # env default). "auto"/empty → let Whisper detect the language.
        lang = db.get_setting("whisper_language", config.WHISPER_LANGUAGE)
        lang = None if not lang or lang == "auto" else lang
        segments, info = model.transcribe(
            video_path,
            language=lang,
            beam_size=config.WHISPER_BEAM_SIZE,
            vad_filter=True,
            # Anti-loop settings (see config.py) — restore the temperature
            # fallback and stop the model from feeding a loop back to itself.
            temperature=config.WHISPER_TEMPERATURE,
            condition_on_previous_text=config.WHISPER_CONDITION_PREVIOUS,
            repetition_penalty=config.WHISPER_REPETITION_PENALTY,
            no_repeat_ngram_size=config.WHISPER_NO_REPEAT_NGRAM,
        )

        # Total audio length in seconds — used to turn each segment's end
        # timestamp into a 0–100% progress figure.
        total = getattr(info, "duration", 0.0) or 0.0
        last_pct = -1

        # segments is a generator — consume it while streaming to both files so
        # a very long video never has to fit fully in memory.
        with open(srt_path, "w", encoding="utf-8") as srt, \
                open(txt_path, "w", encoding="utf-8") as txt:
            for index, segment in enumerate(segments, start=1):
                text = segment.text.strip()
                srt.write(f"{index}\n")
                srt.write(
                    f"{_format_timestamp(segment.start)} --> "
                    f"{_format_timestamp(segment.end)}\n"
                )
                srt.write(f"{text}\n\n")
                txt.write(f"{text}\n")

                # Report progress, but only on whole-percent changes to keep
                # DB writes cheap. Cap at 99% until fully done.
                if total > 0:
                    pct = min(99, int(segment.end / total * 100))
                    if pct > last_pct:
                        last_pct = pct
                        db.set_progress(job_id, pct)

        duration = time.time() - started
        db.mark_done(
            job_id,
            srt_path=srt_path,
            txt_path=txt_path,
            language=getattr(info, "language", config.WHISPER_LANGUAGE),
            duration=duration,
        )
        print(f"[worker] job {job_id} done in {duration:.1f}s -> {srt_path}", flush=True)
        return {"job_id": job_id, "status": "done"}

    except Exception as exc:  # noqa: BLE001 — any failure is a per-job failure
        # Clean up partial output so a failed job never leaves a half file.
        for path in (srt_path, txt_path):
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        db.mark_failed(job_id, f"{type(exc).__name__}: {exc}")
        print(f"[worker] job {job_id} FAILED: {exc}", flush=True)
        return {"job_id": job_id, "status": "failed"}
