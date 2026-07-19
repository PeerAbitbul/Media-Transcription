"""Central configuration, read from environment variables.

Every tunable comes from the environment so the same image can be reused for
api and worker, and so the model / language can be swapped without a rebuild.
"""
import os

# --- Infrastructure ---------------------------------------------------------
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
DB_PATH = os.getenv("DB_PATH", "/app/data/jobs.db")

# Worker liveness. The worker writes a heartbeat every INTERVAL seconds; the UI
# treats the worker as online if the last heartbeat is within STALE seconds.
# STALE has generous slack so a long transcription step never flips it to red.
WORKER_HEARTBEAT_INTERVAL = float(os.getenv("WORKER_HEARTBEAT_INTERVAL", "5"))
WORKER_HEARTBEAT_STALE = float(os.getenv("WORKER_HEARTBEAT_STALE", "30"))

# --- Paths ------------------------------------------------------------------
VIDEOS_DIR = os.getenv("VIDEOS_DIR", "/app/videos")
TRANSCRIPTS_DIR = os.getenv("TRANSCRIPTS_DIR", "/app/transcripts")

# Media extensions we expose in the UI and allow transcribing. Whisper (via
# ffmpeg) decodes audio from any of these, so audio-only files work too.
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".mpg", ".mpeg"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".oga", ".opus",
                    ".flac", ".wma", ".aiff", ".aif", ".amr"}
MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS

# --- Whisper / transcription ------------------------------------------------
# The model is picked automatically per job based on the selected language:
#   Hebrew                → WHISPER_MODEL (ivrit.ai's Hebrew fine-tune of large-v3)
#   anything else / auto  → WHISPER_MODEL_MULTILINGUAL (original OpenAI large-v3,
#                           which is stronger outside Hebrew and detects language)
# Both accept any faster-whisper model name or CTranslate2 HF repo.
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "ivrit-ai/whisper-large-v3-ct2")
WHISPER_MODEL_MULTILINGUAL = os.getenv("WHISPER_MODEL_MULTILINGUAL", "large-v3")


def model_for_language(language: str | None) -> str:
    """Model to use for a given language code (None/"auto" → multilingual)."""
    return WHISPER_MODEL if language == "he" else WHISPER_MODEL_MULTILINGUAL


WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "he")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
WHISPER_BEAM_SIZE = int(os.getenv("WHISPER_BEAM_SIZE", "8"))

# --- Speaker diarization ------------------------------------------------------
# "Speaker 1 / Speaker 2" labels via pyannote. The default pipeline is ivrit.ai's
# open mirror of pyannote/speaker-diarization-3.1, so no HF token is needed.
# DIARIZATION sets the default on/off; the live value is toggled from the web UI
# (stored in the settings table, applies to new jobs without a restart).
DIARIZATION_MODEL = os.getenv("DIARIZATION_MODEL", "ivrit-ai/pyannote-speaker-diarization-3.1")
DIARIZATION_DEFAULT = "1" if os.getenv("DIARIZATION", "1").lower() in ("1", "true", "yes") else "0"
# Device for the diarization pipeline: auto = cuda → mps → cpu.
DIARIZATION_DEVICE = os.getenv("DIARIZATION_DEVICE", "auto")

# Anti-hallucination / anti-loop decoding controls. Whisper is prone to getting
# stuck repeating a phrase; these defaults prevent that:
#   - temperature list re-enables the fallback that retries a looped segment
#   - condition_on_previous_text=False stops a loop from feeding itself
#   - repetition_penalty gently discourages repeats
#   - no_repeat_ngram_size (0=off) hard-blocks repeated n-grams if loops persist
_temps = os.getenv("WHISPER_TEMPERATURE", "0.0,0.2,0.4,0.6,0.8,1.0")
WHISPER_TEMPERATURE = [float(x) for x in _temps.split(",") if x.strip() != ""]
WHISPER_CONDITION_PREVIOUS = os.getenv(
    "WHISPER_CONDITION_PREVIOUS", "false").lower() in ("1", "true", "yes")
WHISPER_REPETITION_PENALTY = float(os.getenv("WHISPER_REPETITION_PENALTY", "1.1"))
WHISPER_NO_REPEAT_NGRAM = int(os.getenv("WHISPER_NO_REPEAT_NGRAM", "0"))

# --- Telegram bot -----------------------------------------------------------
# URL of the self-hosted local Bot API server (raises the download limit to 2GB
# and returns local file paths). The `bot` service talks to this instead of the
# public api.telegram.org.
TELEGRAM_API_BASE = os.getenv("TELEGRAM_API_BASE", "http://telegram-bot-api:8081")
# File written by the API when the user saves credentials in the web UI; the
# local Bot API server's entrypoint reads api_id/api_hash from here on startup.
TELEGRAM_CREDS_FILE = os.getenv("TELEGRAM_CREDS_FILE", "/app/data/telegram-api.env")
# How long to wait for a file download. In local mode the Bot API server first
# downloads big files from Telegram before getFile returns, which can take a
# while — the PTB default of 5s is far too short. Default: 30 minutes.
TELEGRAM_DOWNLOAD_TIMEOUT = float(os.getenv("TELEGRAM_DOWNLOAD_TIMEOUT", "1800"))
# Settings keys used in the `settings` table.
TG_KEYS = ["tg_bot_token", "tg_api_id", "tg_api_hash", "tg_allowed_ids",
           "tg_enabled", "tg_status", "tg_bot_username", "tg_last_error",
           "tg_updated_at", "tg_mode"]
