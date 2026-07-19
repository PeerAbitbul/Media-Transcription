"""Celery task that transcribes a single media file with faster-whisper,
optionally with speaker diarization ("Speaker 1 / Speaker 2" labels).

Models are loaded lazily and cached per worker process. Each job is fully
isolated: a failure on one file marks that job failed and never blocks the
rest of the queue. A diarization failure downgrades the job to a plain
transcript instead of failing it.
"""
import os
import threading
import time

from celery.signals import worker_ready

from app import config, db
from app.celery_app import celery

# Whisper and pyannote both consume 16 kHz mono; decoding once serves both.
SAMPLE_RATE = 16000

# Ensure the jobs table exists on the worker side too, so the system is
# robust to start order and to the DB file being (re)created.
db.init_db()


def _heartbeat_loop():
    """Write a liveness timestamp to the DB every few seconds.

    The UI's "engine" light reads this from the shared DB, so it reflects the
    worker's health even when the API can't reach it over the broker.
    """
    while True:
        try:
            db.set_setting("worker_heartbeat", time.time())
        except Exception:  # noqa: BLE001 — never let the heartbeat kill anything
            pass
        time.sleep(config.WORKER_HEARTBEAT_INTERVAL)


@worker_ready.connect
def _start_heartbeat(**_kwargs):
    db.set_setting("worker_heartbeat", time.time())  # immediate, before the loop
    threading.Thread(target=_heartbeat_loop, daemon=True).start()
    db.add_log("worker", "Worker online")


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

# Loaded once per worker process (see _get_model / _get_diarizer). Heavy
# libraries are imported lazily so the API container never pulls them in.
_model = None
_model_name = None
_diarizer = None
_diarizer_failed = False


def _get_model(name: str):
    """Load (and cache) a faster-whisper model. Downloaded once into the cache.

    Only one model is kept in memory: switching languages (Hebrew fine-tune ↔
    multilingual) frees the previous model first — a large-v3 is ~3GB of RAM,
    and holding two would exceed a typical Docker memory budget.
    """
    global _model, _model_name
    if _model_name != name:
        _model = None
    if _model is None:
        from faster_whisper import WhisperModel

        print(
            f"[worker] loading model={name} "
            f"device={config.WHISPER_DEVICE} compute_type={config.WHISPER_COMPUTE_TYPE}",
            flush=True,
        )
        _model = WhisperModel(
            name,
            device=config.WHISPER_DEVICE,
            compute_type=config.WHISPER_COMPUTE_TYPE,
        )
        _model_name = name
    return _model


def _diarization_device() -> str:
    if config.DIARIZATION_DEVICE != "auto":
        return config.DIARIZATION_DEVICE
    import torch

    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


def _get_diarizer():
    """Load (and cache) the pyannote diarization pipeline; None if unavailable.

    A load failure is remembered so we don't retry (and re-fail) on every job.
    """
    global _diarizer, _diarizer_failed
    if _diarizer is None and not _diarizer_failed:
        try:
            import torch
            from pyannote.audio import Pipeline

            print(f"[worker] loading diarization pipeline={config.DIARIZATION_MODEL}",
                  flush=True)
            _diarizer = Pipeline.from_pretrained(config.DIARIZATION_MODEL)
            device = _diarization_device()
            if device != "cpu":
                try:
                    _diarizer.to(torch.device(device))
                    print(f"[worker] diarization on {device}", flush=True)
                except Exception as e:  # noqa: BLE001 — MPS/CUDA can be flaky; CPU works
                    print(f"[worker] diarization device {device} failed ({e}), using cpu",
                          flush=True)
        except Exception as e:  # noqa: BLE001
            _diarizer_failed = True
            _diarizer = None
            db.add_log("worker",
                       f"Speaker detection unavailable, continuing without it: {e}",
                       level="warn")
            print(f"[worker] diarization unavailable, continuing without it: {e}",
                  flush=True)
    return _diarizer


def _diarize(audio, job_id: int) -> list[tuple[float, float, int]]:
    """Run speaker diarization; return (start, end, speaker_number) turns.

    Speaker numbers are 1-based in order of first appearance. Returns [] when
    the pipeline is unavailable or fails — the job then proceeds unlabeled.
    """
    pipeline = _get_diarizer()
    if pipeline is None:
        return []
    try:
        import numpy as np
        import torch

        waveform = torch.from_numpy(np.ascontiguousarray(audio)).unsqueeze(0)

        # Map pipeline internals onto the job's 0–14% progress window so the UI
        # moves during diarization too (transcription then covers 15–99%).
        spans = {"segmentation": (0, 7), "embeddings": (7, 14)}
        last = {"pct": -1}

        def hook(step_name, _artifact, file=None, total=None, completed=None):
            if total and step_name in spans:
                lo, hi = spans[step_name]
                pct = lo + int((hi - lo) * (completed or 0) / total)
                if pct > last["pct"]:
                    last["pct"] = pct
                    db.set_progress(job_id, pct)

        annotation = pipeline({"waveform": waveform, "sample_rate": SAMPLE_RATE},
                              hook=hook)

        order: dict[str, int] = {}
        turns: list[tuple[float, float, int]] = []
        for segment, _track, label in annotation.itertracks(yield_label=True):
            if label not in order:
                order[label] = len(order) + 1
            turns.append((segment.start, segment.end, order[label]))
        turns.sort(key=lambda t: t[0])
        return turns
    except Exception as e:  # noqa: BLE001 — diarization is best-effort
        print(f"[worker] diarization failed, continuing without it: {e}", flush=True)
        return []


def _speaker_for(start: float, end: float, turns: list[tuple[float, float, int]]):
    """Speaker number whose turn overlaps this segment the most (nearest if none)."""
    best, best_overlap = None, 0.0
    for t_start, t_end, spk in turns:
        overlap = min(end, t_end) - max(start, t_start)
        if overlap > best_overlap:
            best, best_overlap = spk, overlap
    if best is None and turns:
        mid = (start + end) / 2
        best = min(turns, key=lambda t: min(abs(t[0] - mid), abs(t[1] - mid)))[2]
    return best


def _transcribe_segments(audio, lang):
    """Run faster-whisper on decoded audio.

    Returns (segments, language) where segments is a generator of dicts with
    start/end/text, streamed so a long file never has to fit fully in memory.
    """
    # Hebrew → the Hebrew fine-tune; other languages / auto → the original
    # multilingual model, which is stronger outside Hebrew.
    model_name = config.model_for_language(lang)

    model = _get_model(model_name)
    segments, info = model.transcribe(
        audio,
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
    stream = ({"start": s.start, "end": s.end, "text": s.text} for s in segments)
    return stream, getattr(info, "language", lang or "")


def _model_is_cached(repo: str) -> bool:
    """Best-effort: is this HF model already downloaded (so no download wait)?

    Returns True for non-repo shorthand names we can't easily check, so we don't
    wrongly claim a download. Used only to label the job's stage in the UI.
    """
    if "/" not in repo:
        return True
    try:
        from huggingface_hub.constants import HF_HUB_CACHE

        base = os.path.join(HF_HUB_CACHE, "models--" + repo.replace("/", "--"))
        if not os.path.isdir(base):
            return False
        blobs = os.path.join(base, "blobs")
        if os.path.isdir(blobs):
            for name in os.listdir(blobs):
                if name.endswith(".incomplete"):
                    return False  # a partial file → still downloading
        return True
    except Exception:  # noqa: BLE001
        return True


def _log_download_progress(repo: str, stop: "threading.Event"):
    """While a model downloads, log its growing size so the UI's log shows
    install progress (there's no total to show a %, so we report MB/GB)."""
    try:
        from huggingface_hub.constants import HF_HUB_CACHE
        base = os.path.join(HF_HUB_CACHE, "models--" + repo.replace("/", "--"))
    except Exception:  # noqa: BLE001
        return
    last_mb = -50
    while not stop.wait(8):
        try:
            total = 0
            for dirpath, _dirs, files in os.walk(base):
                for name in files:
                    try:
                        total += os.path.getsize(os.path.join(dirpath, name))
                    except OSError:
                        pass
            mb = total / (1024 * 1024)
            if mb - last_mb >= 50:  # only log every ~50MB of progress
                last_mb = mb
                size = f"{mb/1024:.1f} GB" if mb >= 1024 else f"{mb:.0f} MB"
                db.add_log("worker", f"Downloading model… {size}")
        except Exception:  # noqa: BLE001
            pass


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
    """Transcribe one media file into SRT + TXT under /app/transcripts."""
    # Dedup guard: if this exact job already finished with its output on disk,
    # a duplicate delivery (e.g. a late-acked message resurfacing after repeated
    # restarts) must NOT redo the work — that would truncate the good transcript.
    # A real re-transcription (/redo, "transcribe again") always uses a NEW job
    # id, so this only ever skips genuine duplicates.
    existing = db.get_job(job_id)
    if existing and existing.get("status") == db.STATUS_DONE \
            and db.resolve_output_path(existing.get("srt_path")) \
            and db.resolve_output_path(existing.get("txt_path")):
        db.add_log("worker", f"Skipped duplicate run of '{filename}' (#{job_id}) — already done")
        print(f"[worker] job {job_id} already done — skipping duplicate task", flush=True)
        return {"job_id": job_id, "status": "done"}

    db.mark_processing(job_id)
    started = time.time()

    video_path = os.path.join(config.VIDEOS_DIR, filename)
    if not os.path.isfile(video_path):
        db.mark_failed(job_id, f"Video file not found: {video_path}")
        return {"job_id": job_id, "status": "failed"}

    # Keep any subdirectory structure from the videos folder, so two files with
    # the same name in different subfolders never overwrite each other.
    rel_base = os.path.splitext(filename)[0]
    srt_path = os.path.join(config.TRANSCRIPTS_DIR, f"{rel_base}.srt")
    txt_path = os.path.join(config.TRANSCRIPTS_DIR, f"{rel_base}.txt")
    os.makedirs(os.path.dirname(srt_path), exist_ok=True)

    try:
        # Decode once to 16 kHz mono — feeds both diarization and Whisper.
        from faster_whisper.audio import decode_audio

        audio = decode_audio(video_path, sampling_rate=SAMPLE_RATE)
        total = len(audio) / SAMPLE_RATE

        # Diarization is chosen in the UI and stored in the DB (falls back to
        # the env default). Best-effort: failure never fails the job.
        db.add_log("worker", f"Transcribing '{filename}' (#{job_id})")
        diarize_on = db.get_setting("diarization", config.DIARIZATION_DEFAULT) == "1"
        if diarize_on:
            db.set_stage(job_id, "diarizing")
        turns = _diarize(audio, job_id) if diarize_on else []

        # Language is chosen in the UI and stored in the DB (falls back to the
        # env default). "auto"/empty → let Whisper detect the language.
        lang = db.get_setting("whisper_language", config.WHISPER_LANGUAGE)
        lang = None if not lang or lang == "auto" else lang

        # Tell the UI whether we're about to download the model (first run, can
        # take minutes for a multi-GB model) or just load a cached one. The
        # download itself is a system/install concern, so its progress goes to
        # the log (as growing MB), not onto the file's transcription row.
        model_name = config.model_for_language(lang)
        dl_stop = None
        if not _model_is_cached(model_name):
            db.set_stage(job_id, "downloading_model")
            db.add_log("worker", f"Downloading model {model_name} (first run)…")
            dl_stop = threading.Event()
            threading.Thread(target=_log_download_progress,
                             args=(model_name, dl_stop), daemon=True).start()
        else:
            db.set_stage(job_id, "loading_model")
        segments, language = _transcribe_segments(audio, lang)
        if dl_stop:
            dl_stop.set()
        db.set_stage(job_id, "transcribing")

        speaker_word = "דובר" if language == "he" else "Speaker"
        # Diarization owns 0–14% of the progress bar; transcription the rest.
        base_pct = 14 if turns else 0
        last_pct = base_pct - 1

        # ct2 segments stream from a generator — write as we go so a very long
        # file never has to hold its full transcript in memory.
        with open(srt_path, "w", encoding="utf-8") as srt, \
                open(txt_path, "w", encoding="utf-8") as txt:
            for index, segment in enumerate(segments, start=1):
                text = segment["text"].strip()
                spk = _speaker_for(segment["start"], segment["end"], turns) if turns else None
                label = f"{speaker_word} {spk}: " if spk else ""
                srt.write(f"{index}\n")
                srt.write(
                    f"{_format_timestamp(segment['start'])} --> "
                    f"{_format_timestamp(segment['end'])}\n"
                )
                srt.write(f"{label}{text}\n\n")
                txt.write(f"{label}{text}\n")

                # Report progress, but only on whole-percent changes to keep
                # DB writes cheap. Cap at 99% until fully done.
                if total > 0:
                    span = 99 - base_pct
                    pct = base_pct + min(span, int(segment["end"] / total * span))
                    if pct > last_pct:
                        last_pct = pct
                        db.set_progress(job_id, pct)

        duration = time.time() - started
        speakers = len({t[2] for t in turns}) or None
        db.mark_done(
            job_id,
            srt_path=srt_path,
            txt_path=txt_path,
            language=language or config.WHISPER_LANGUAGE,
            duration=duration,
            speakers=speakers,
        )
        spk_note = f", {speakers} speakers" if speakers else ""
        db.add_log("worker",
                   f"Done '{filename}' (#{job_id}) in {duration:.0f}s{spk_note}")
        print(f"[worker] job {job_id} done in {duration:.1f}s "
              f"(speakers={speakers}) -> {srt_path}", flush=True)
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
        db.add_log("worker", f"FAILED '{filename}' (#{job_id}): {exc}", level="error")
        print(f"[worker] job {job_id} FAILED: {exc}", flush=True)
        return {"job_id": job_id, "status": "failed"}
