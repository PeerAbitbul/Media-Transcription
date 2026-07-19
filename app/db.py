"""Tiny SQLite persistence layer for job status/metadata.

Uses short-lived connections in WAL mode so the api and worker containers can
safely read/write the same DB file concurrently over the shared volume.
"""
import os
import sqlite3
import time
from contextlib import contextmanager

from app.config import DB_PATH, TRANSCRIPTS_DIR

# Valid job lifecycle states.
STATUS_QUEUED = "queued"
STATUS_PROCESSING = "processing"
STATUS_DONE = "done"
STATUS_FAILED = "failed"


@contextmanager
def _connect():
    """Yield a WAL-mode connection with row access by column name."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Create the jobs table if it does not exist. Safe to call repeatedly."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                filename     TEXT NOT NULL,
                status       TEXT NOT NULL,
                task_id      TEXT,
                error        TEXT,
                srt_path     TEXT,
                txt_path     TEXT,
                language     TEXT,
                duration     REAL,
                progress     REAL NOT NULL DEFAULT 0,
                created_at   REAL NOT NULL,
                updated_at   REAL NOT NULL,
                started_at   REAL,
                finished_at  REAL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_filename ON jobs(filename)")
        # Simple key/value store for settings (Telegram config, etc.). Lives on
        # the same persistent volume, so it survives restarts and rebuilds.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        # Shared event log — every service (api, worker, bot) appends here and
        # the UI reads it, giving one log view across all of them.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS logs (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                ts      REAL NOT NULL,
                source  TEXT NOT NULL,
                level   TEXT NOT NULL,
                message TEXT NOT NULL
            )
            """
        )
        # Migrations: add columns to tables created before they existed.
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
        if "progress" not in cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN progress REAL NOT NULL DEFAULT 0")
        if "source" not in cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN source TEXT NOT NULL DEFAULT 'web'")
        if "chat_id" not in cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN chat_id TEXT")
        if "notified" not in cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN notified INTEGER NOT NULL DEFAULT 0")
        if "speakers" not in cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN speakers INTEGER")
        if "stage" not in cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN stage TEXT")


def create_job(filename: str, source: str = "web", chat_id: str | None = None) -> int:
    """Insert a new queued job for a filename and return its id.

    source tracks where the job came from (web / telegram); chat_id is the
    Telegram chat to notify on completion (None for web jobs).
    """
    now = time.time()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO jobs (filename, status, source, chat_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (filename, STATUS_QUEUED, source, chat_id, now, now),
        )
        return cur.lastrowid


def set_task_id(job_id: int, task_id: str):
    with _connect() as conn:
        conn.execute(
            "UPDATE jobs SET task_id = ?, updated_at = ? WHERE id = ?",
            (task_id, time.time(), job_id),
        )


def mark_processing(job_id: int):
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "UPDATE jobs SET status = ?, started_at = ?, updated_at = ?, "
            "progress = 0, stage = NULL, error = NULL WHERE id = ?",
            (STATUS_PROCESSING, now, now, job_id),
        )


def set_progress(job_id: int, progress: float):
    """Update the 0–100 progress percentage of a running job."""
    with _connect() as conn:
        conn.execute(
            "UPDATE jobs SET progress = ?, updated_at = ? WHERE id = ?",
            (progress, time.time(), job_id),
        )


def set_stage(job_id: int, stage: str | None):
    """Set the current phase of a running job (diarizing / downloading_model /
    loading_model / transcribing) so the UI can show what it's doing."""
    with _connect() as conn:
        conn.execute(
            "UPDATE jobs SET stage = ?, updated_at = ? WHERE id = ?",
            (stage, time.time(), job_id),
        )


def mark_done(job_id: int, srt_path: str, txt_path: str, language: str, duration: float,
              speakers: int | None = None):
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "UPDATE jobs SET status = ?, srt_path = ?, txt_path = ?, language = ?, "
            "duration = ?, speakers = ?, progress = 100, finished_at = ?, updated_at = ? "
            "WHERE id = ?",
            (STATUS_DONE, srt_path, txt_path, language, duration, speakers, now, now, job_id),
        )


def resolve_output_path(path: str | None) -> str | None:
    """Return a transcript path that exists, tolerating a moved transcripts dir.

    Jobs store the absolute path the worker wrote to; if that exact path is
    gone (e.g. TRANSCRIPTS_DIR was remapped) fall back to the same basename
    inside the current transcripts folder.
    """
    if not path:
        return None
    if os.path.isfile(path):
        return path
    fallback = os.path.join(TRANSCRIPTS_DIR, os.path.basename(path))
    return fallback if os.path.isfile(fallback) else None


def mark_failed(job_id: int, error: str):
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "UPDATE jobs SET status = ?, error = ?, finished_at = ?, updated_at = ? "
            "WHERE id = ?",
            (STATUS_FAILED, error[:2000], now, now, job_id),
        )


def get_job(job_id: int):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def list_jobs() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]


def active_job_for_file(filename: str):
    """Return an existing queued/processing job for this file, if any.

    Prevents enqueuing the same video twice while a run is already pending.
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE filename = ? AND status IN (?, ?) "
            "ORDER BY id DESC LIMIT 1",
            (filename, STATUS_QUEUED, STATUS_PROCESSING),
        ).fetchone()
        return dict(row) if row else None


def jobs_to_resume() -> list[dict]:
    """Jobs that were pending when the system stopped (queued or mid-transcription).

    Used on worker startup to re-queue everything so nothing is orphaned after a
    shutdown/reboot. The DB is the source of truth for the queue.
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status IN (?, ?) ORDER BY id ASC",
            (STATUS_QUEUED, STATUS_PROCESSING),
        ).fetchall()
        return [dict(r) for r in rows]


def reset_to_queued(job_id: int):
    """Return a job to the queue (clears progress/started/error)."""
    with _connect() as conn:
        conn.execute(
            "UPDATE jobs SET status = ?, progress = 0, started_at = NULL, "
            "error = NULL, updated_at = ? WHERE id = ?",
            (STATUS_QUEUED, time.time(), job_id),
        )


def latest_job_for_file(filename: str):
    """Return the most recent job for a filename, regardless of status."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE filename = ? ORDER BY id DESC LIMIT 1",
            (filename,),
        ).fetchone()
        return dict(row) if row else None


def jobs_for_file(filename: str) -> list[dict]:
    """All job rows for a filename (used to find transcript files to remove)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE filename = ? ORDER BY id DESC", (filename,)
        ).fetchall()
        return [dict(r) for r in rows]


def delete_jobs_for_file(filename: str):
    """Remove all job rows for a filename."""
    with _connect() as conn:
        conn.execute("DELETE FROM jobs WHERE filename = ?", (filename,))


# --------------------------------------------------------------------------
# Telegram notifications
# --------------------------------------------------------------------------
def jobs_pending_notification() -> list[dict]:
    """Finished Telegram jobs whose completion has not been announced yet."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE source = 'telegram' AND chat_id IS NOT NULL "
            "AND notified = 0 AND status IN (?, ?) ORDER BY id ASC",
            (STATUS_DONE, STATUS_FAILED),
        ).fetchall()
        return [dict(r) for r in rows]


def mark_notified(job_id: int):
    with _connect() as conn:
        conn.execute("UPDATE jobs SET notified = 1 WHERE id = ?", (job_id,))


# --------------------------------------------------------------------------
# Rename (file + transcript paths, all in one transaction)
# --------------------------------------------------------------------------
def rename_job_paths(job_id: int, new_filename: str, new_srt: str | None, new_txt: str | None):
    """Update a job's filename and result paths after files are moved on disk."""
    with _connect() as conn:
        conn.execute(
            "UPDATE jobs SET filename = ?, srt_path = ?, txt_path = ?, updated_at = ? "
            "WHERE id = ?",
            (new_filename, new_srt, new_txt, time.time(), job_id),
        )


# --------------------------------------------------------------------------
# Settings (key/value)
# --------------------------------------------------------------------------
def get_setting(key: str, default=None):
    with _connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, None if value is None else str(value)),
        )


def get_settings(keys: list[str]) -> dict:
    with _connect() as conn:
        placeholders = ",".join("?" for _ in keys)
        rows = conn.execute(
            f"SELECT key, value FROM settings WHERE key IN ({placeholders})", keys
        ).fetchall()
        return {r["key"]: r["value"] for r in rows}


# --------------------------------------------------------------------------
# Event log (shared ring buffer)
# --------------------------------------------------------------------------
# Keep only the most recent lines so the table never grows without bound.
LOG_MAX_ROWS = 500


def add_log(source: str, message: str, level: str = "info"):
    """Append one line to the shared event log and trim old rows. Best-effort."""
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO logs (ts, source, level, message) VALUES (?, ?, ?, ?)",
                (time.time(), source, level, str(message)[:1000]),
            )
            # Trim: delete everything older than the newest LOG_MAX_ROWS rows.
            conn.execute(
                "DELETE FROM logs WHERE id <= "
                "(SELECT MAX(id) FROM logs) - ?",
                (LOG_MAX_ROWS,),
            )
    except Exception:  # noqa: BLE001 — logging must never break the caller
        pass


def get_logs(limit: int = 200, source: str | None = None) -> list[dict]:
    """Return the most recent log lines (newest first), optionally by source."""
    with _connect() as conn:
        if source and source != "all":
            rows = conn.execute(
                "SELECT * FROM logs WHERE source = ? ORDER BY id DESC LIMIT ?",
                (source, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
