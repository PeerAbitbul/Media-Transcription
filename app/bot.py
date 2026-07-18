"""Telegram bot service for the video transcriber.

Runs as its own container. Reads its configuration from the `settings` table
(written by the web UI), so it can be configured and re-configured entirely
from localhost with no file editing. A supervisor loop starts/stops/reloads the
Telegram connection whenever the stored config changes — no container restart
needed for the token / allowed-ids / enable toggle.

Talks to a self-hosted local Bot API server (config.TELEGRAM_API_BASE) so it can
download videos up to 2GB and read them directly from disk.
"""
import asyncio
import os
import re

from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters,
)

from app import config, db
from app.celery_app import celery

# Remembers the last video each chat sent, so `/name <x>` knows what to rename.
LAST_RECEIVED: dict[str, str] = {}

# The running completion-notifier task (one bot connection at a time).
_NOTIFIER = None


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _settings() -> dict:
    return db.get_settings(config.TG_KEYS)


def _allowed_ids(s: dict) -> set[int]:
    ids = set()
    for part in re.split(r"[\s,]+", s.get("tg_allowed_ids") or ""):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids


def sanitize(name: str) -> str:
    """Filesystem-safe base name that KEEPS spaces and Hebrew, blocks traversal."""
    name = (name or "").strip()
    name = name.replace("\x00", "")
    name = re.sub(r"[\\/]", "", name)          # no path separators
    name = re.sub(r'[<>:"|?*]', "", name)       # chars illegal on some filesystems
    name = re.sub(r"\.{2,}", ".", name)         # collapse ".." to block traversal
    name = re.sub(r"\s+", " ", name).strip()    # normalize spaces, but keep them
    name = name.strip(". ")                      # no leading/trailing dot or space
    return (name or "video")[:120]


def _unique_path(directory: str, filename: str) -> str:
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(directory, filename)
    i = 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{base}-{i}{ext}")
        i += 1
    return candidate


def list_video_files() -> list[str]:
    root = config.VIDEOS_DIR
    out = []
    if os.path.isdir(root):
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                if os.path.splitext(name)[1].lower() in config.MEDIA_EXTENSIONS:
                    out.append(os.path.relpath(os.path.join(dirpath, name), root))
    return sorted(out)


STATUS_HE = {
    "queued": "בתור", "processing": "מעבד", "done": "הושלם", "failed": "נכשל",
}


def restricted(handler):
    """Wrap a handler so only allow-listed Telegram users can trigger it."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else None
        if uid not in _allowed_ids(_settings()):
            return  # silently ignore strangers
        return await handler(update, context)
    return wrapper


# --------------------------------------------------------------------------
# Enqueue + rename core (shared logic)
# --------------------------------------------------------------------------
def _enqueue(filename: str, chat_id: str) -> int:
    job_id = db.create_job(filename, source="telegram", chat_id=chat_id)
    result = celery.send_task("app.worker.transcribe", args=[job_id, filename])
    db.set_task_id(job_id, result.id)
    return job_id


def _resolve_target(identifier: str):
    """Return (current_filename, job_or_None) for a job number or a file name."""
    identifier = identifier.strip()
    if identifier.isdigit():
        job = db.get_job(int(identifier))
        return (job["filename"], job) if job else (None, None)
    low = identifier.lower()
    for f in list_video_files():
        base = os.path.splitext(f)[0]
        if low in (f.lower(), base.lower()):
            return f, db.latest_job_for_file(f)
    return None, None


def perform_rename(current_filename: str, job, new_base: str):
    """Rename video + its transcripts + DB row. Returns (ok, message)."""
    if job and job.get("status") == db.STATUS_PROCESSING:
        return False, "⏳ הסרטון מתומלל כרגע — אפשר לשנות שם רק אחרי שהתמלול מסתיים."

    src = os.path.join(config.VIDEOS_DIR, current_filename)
    if not os.path.isfile(src):
        return False, "❌ הקובץ לא נמצא."

    ext = os.path.splitext(current_filename)[1]
    new_name = sanitize(os.path.splitext(new_base)[0]) + ext
    dest = os.path.join(config.VIDEOS_DIR, new_name)
    if os.path.abspath(dest) == os.path.abspath(src):
        return False, "השם זהה לשם הנוכחי."
    if os.path.exists(dest):
        return False, f"⚠️ השם `{new_name}` כבר תפוס — בחר שם אחר."

    os.rename(src, dest)

    new_srt = new_txt = None
    if job and job.get("status") == db.STATUS_DONE:
        new_base_only = os.path.splitext(new_name)[0]
        for kind in ("srt", "txt"):
            old = job.get(f"{kind}_path")
            if old and os.path.exists(old):
                newp = os.path.join(config.TRANSCRIPTS_DIR, f"{new_base_only}.{kind}")
                os.rename(old, newp)
                if kind == "srt":
                    new_srt = newp
                else:
                    new_txt = newp

    if job:
        db.rename_job_paths(job["id"], new_name, new_srt, new_txt)
    return True, f"✏️ שונה ל-`{new_name}`"


# --------------------------------------------------------------------------
# Handlers
# --------------------------------------------------------------------------
HELP_TEXT = (
    "🎬 *בוט תמלול סרטונים*\n\n"
    "שלח לי סרטון או הקלטה/אודיו (mp3, wav, m4a, voice note…) — עדיף כ*קובץ/Document* "
    "לאיכות מלאה — ואני אוריד, אשמור ואתמלל.\n"
    "אפשר לצרף *כיתוב* להודעה — הוא יהפוך לשם הקובץ.\n\n"
    "*פקודות:*\n"
    "/status — מה בעיבוד / בתור / הושלם\n"
    "/list — כל הסרטונים והסטטוס\n"
    "/get — רשימת התמלולים המוכנים; /get <שם או #> — שלח תמלול (חיפוש לפי שם חלקי)\n"
    "/last — התמלול האחרון שהסתיים\n"
    "/all — תמלל את כל מה שעדיין לא תומלל\n"
    "/redo <שם או #> — תמלל מחדש קובץ קיים (גם אם כבר תומלל)\n"
    "/rename <# או שם> <שם חדש> — שנה שם\n"
    "/name <שם חדש> — תן שם לסרטון האחרון ששלחת\n"
    "/delete <שם או #> — מחק סרטון + תמלולים (עם אישור)\n"
)

# Registered with Telegram so typing "/" pops up a menu of commands.
BOT_COMMANDS = [
    BotCommand("status", "מה בעיבוד / בתור / הושלם"),
    BotCommand("list", "רשימת כל הסרטונים והסטטוס"),
    BotCommand("get", "תמלולים מוכנים / שלח לפי שם חלקי או מספר"),
    BotCommand("last", "התמלול האחרון שהסתיים"),
    BotCommand("all", "תמלל את כל מה שעדיין לא תומלל"),
    BotCommand("redo", "תמלל מחדש קובץ קיים — /redo <שם או #>"),
    BotCommand("rename", "שנה שם — /rename <# או שם> <שם חדש>"),
    BotCommand("name", "תן שם לסרטון האחרון — /name <שם חדש>"),
    BotCommand("delete", "מחק סרטון + תמלולים — /delete <שם או #>"),
    BotCommand("help", "עזרה ורשימת פקודות"),
]


@restricted
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


@restricted
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    jobs = db.list_jobs()
    counts = {"queued": 0, "processing": 0, "done": 0, "failed": 0}
    processing = []
    for j in jobs:
        counts[j["status"]] = counts.get(j["status"], 0) + 1
        if j["status"] == "processing":
            processing.append(f"• `{j['filename']}` — {round(j.get('progress') or 0)}%")
    lines = [
        f"⚙️ הושלמו: {counts['done']} · מעבד: {counts['processing']} · "
        f"בתור: {counts['queued']} · נכשלו: {counts['failed']}"
    ]
    if processing:
        lines.append("\n*כרגע בעיבוד:*")
        lines += processing
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@restricted
async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    files = list_video_files()
    if not files:
        await update.message.reply_text("אין סרטונים בתיקייה.")
        return
    lines = []
    for i, f in enumerate(files, start=1):
        job = db.latest_job_for_file(f)
        st = STATUS_HE.get(job["status"], "—") if job else "לא תומלל"
        num = f"#{job['id']} " if job else ""
        lines.append(f"{i}. `{f}` — {num}{st}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def _send_results(context, chat_id, job):
    """Send a job's SRT + TXT files to a chat."""
    sent = False
    for key in ("srt_path", "txt_path"):
        path = job.get(key)
        if path and os.path.isfile(path):
            with open(path, "rb") as fh:
                await context.bot.send_document(chat_id, document=fh,
                                                filename=os.path.basename(path))
            sent = True
    return sent


def _done_jobs() -> list[dict]:
    """Latest completed job per filename, newest first."""
    seen, out = set(), []
    for j in db.list_jobs():  # newest first
        if j["status"] == "done" and j["filename"] not in seen:
            seen.add(j["filename"])
            out.append(j)
    return out


def _format_done_list(jobs: list[dict]) -> str:
    return "\n".join(f"• #{j['id']} `{j['filename']}`" for j in jobs)


@restricted
async def cmd_get(update: Update, context: ContextTypes.DEFAULT_TYPE):
    done = _done_jobs()

    # No argument → list every completed transcription to pick from.
    if not context.args:
        if not done:
            await update.message.reply_text("אין עדיין תמלולים שהושלמו.")
        else:
            await update.message.reply_text(
                "📄 תמלולים מוכנים — שלח /get עם השם או המספר:\n" + _format_done_list(done),
                parse_mode="Markdown")
        return

    query = " ".join(context.args).strip()

    # By job number.
    if query.isdigit():
        job = db.get_job(int(query))
        if not job or job["status"] != "done":
            await update.message.reply_text("לא מצאתי תמלול מוכן במספר הזה.")
            return
        if not await _send_results(context, update.message.chat_id, job):
            await update.message.reply_text("קבצי התמלול לא נמצאו.")
        return

    # By name — partial, case-insensitive match among completed files.
    matches = [j for j in done if query.lower() in j["filename"].lower()]
    if not matches:
        await update.message.reply_text(
            "לא מצאתי תמלול מוכן בשם כזה. שלח /get בלי טקסט כדי לראות את הרשימה.")
    elif len(matches) == 1:
        if not await _send_results(context, update.message.chat_id, matches[0]):
            await update.message.reply_text("קבצי התמלול לא נמצאו.")
    else:
        await update.message.reply_text(
            "נמצאו כמה התאמות — בחר לפי מספר (/get <מספר>):\n" + _format_done_list(matches),
            parse_mode="Markdown")


@restricted
async def cmd_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for job in db.list_jobs():  # newest first
        if job["status"] == "done":
            if not await _send_results(context, update.message.chat_id, job):
                await update.message.reply_text("קבצי התמלול לא נמצאו.")
            return
    await update.message.reply_text("אין עדיין תמלול שהושלם.")


@restricted
async def cmd_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.message.chat_id)
    enqueued = 0
    for f in list_video_files():
        latest = db.latest_job_for_file(f)
        if latest and latest["status"] in ("done", "queued", "processing"):
            continue
        _enqueue(f, chat_id)
        enqueued += 1
    await update.message.reply_text(
        f"נוספו {enqueued} עבודות לתור." if enqueued else "אין קבצים חדשים לעיבוד.")


@restricted
async def cmd_redo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Re-transcribe an existing file (e.g. after fixing settings), even if done."""
    if not context.args:
        await update.message.reply_text("שימוש: /redo <שם או מספר>")
        return
    current, _job = _resolve_target(" ".join(context.args))
    if not current:
        await update.message.reply_text("לא מצאתי סרטון כזה. שלח /list לרשימה.")
        return
    active = db.active_job_for_file(current)
    if active:
        await update.message.reply_text(
            f"`{current}` כבר {STATUS_HE.get(active['status'], active['status'])}.",
            parse_mode="Markdown")
        return
    if not os.path.isfile(os.path.join(config.VIDEOS_DIR, current)):
        await update.message.reply_text("קובץ הווידאו לא נמצא.")
        return
    job_id = _enqueue(current, str(update.message.chat_id))
    await update.message.reply_text(
        f"🔁 מתמלל מחדש `{current}` (#{job_id}).", parse_mode="Markdown")


# Short tokens for delete-confirm buttons (callback_data is limited to 64 bytes,
# and filenames can be long / Hebrew, so we map them to a small counter).
_DELETE_TOKENS: dict[str, str] = {}
_DELETE_SEQ = 0


def _delete_video_and_outputs(filename: str):
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
    if vpath.startswith(videos_root + os.sep) and os.path.isfile(vpath):
        try:
            os.remove(vpath)
        except OSError:
            pass
    db.delete_jobs_for_file(filename)


@restricted
async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _DELETE_SEQ
    if not context.args:
        await update.message.reply_text("שימוש: /delete <שם או מספר>")
        return
    current, _job = _resolve_target(" ".join(context.args))
    if not current:
        await update.message.reply_text("לא מצאתי סרטון כזה. שלח /list לרשימה.")
        return
    if db.active_job_for_file(current):
        await update.message.reply_text("אי אפשר למחוק בזמן שהסרטון בתור/בעיבוד.")
        return
    _DELETE_SEQ += 1
    token = str(_DELETE_SEQ)
    _DELETE_TOKENS[token] = current
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🗑 מחק", callback_data=f"del:{token}"),
        InlineKeyboardButton("ביטול", callback_data="del:cancel"),
    ]])
    await update.message.reply_text(
        f"למחוק את `{current}`?\nזה ימחק את הסרטון ואת התמלולים שלו — בלתי הפיך.",
        reply_markup=kb, parse_mode="Markdown")


@restricted
async def on_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if data == "del:cancel":
        await query.edit_message_text("בוטל.")
        return
    token = data.split(":", 1)[1] if ":" in data else ""
    filename = _DELETE_TOKENS.pop(token, None)
    if not filename:
        await query.edit_message_text("פג תוקף הבקשה — שלח /delete שוב.")
        return
    if db.active_job_for_file(filename):
        await query.edit_message_text("אי אפשר למחוק בזמן שהסרטון בתור/בעיבוד.")
        return
    _delete_video_and_outputs(filename)
    await query.edit_message_text(f"🗑 נמחק: `{filename}`", parse_mode="Markdown")


@restricted
async def cmd_rename(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("שימוש: /rename <# או שם נוכחי> <שם חדש>")
        return
    identifier, new_base = context.args[0], " ".join(context.args[1:])
    current, job = _resolve_target(identifier)
    if not current:
        await update.message.reply_text("לא מצאתי סרטון כזה.")
        return
    ok, msg = perform_rename(current, job, new_base)
    await update.message.reply_text(msg, parse_mode="Markdown")


@restricted
async def cmd_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("שימוש: /name <שם חדש>")
        return
    chat_id = str(update.message.chat_id)
    current = LAST_RECEIVED.get(chat_id)
    if not current or not os.path.isfile(os.path.join(config.VIDEOS_DIR, current)):
        await update.message.reply_text("לא זכור לי סרטון אחרון בצ'אט הזה — נסה /rename <שם> <שם חדש>.")
        return
    job = db.latest_job_for_file(current)
    ok, msg = perform_rename(current, job, " ".join(context.args))
    if ok:
        LAST_RECEIVED[chat_id] = sanitize(os.path.splitext(" ".join(context.args))[0]) + os.path.splitext(current)[1]
    await update.message.reply_text(msg, parse_mode="Markdown")


@restricted
async def on_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    # Accept video, audio files, and voice notes.
    obj = msg.video or msg.audio or msg.voice or msg.document
    if obj is None:
        return

    orig_name = getattr(obj, "file_name", None)
    if orig_name:
        ext = os.path.splitext(orig_name)[1].lower()
    elif msg.voice:
        ext = ".ogg"        # Telegram voice notes are opus/ogg
    elif msg.audio:
        ext = ".mp3"
    else:
        ext = ".mp4"
    if not ext:
        ext = ".mp4"
    if ext not in config.MEDIA_EXTENSIONS:
        await msg.reply_text(
            f"סוג קובץ לא נתמך ({ext}). נתמכים וידאו ואודיו, למשל: mp4, mkv, mp3, wav, m4a.")
        return

    caption = (msg.caption or "").strip()
    base = caption or (os.path.splitext(orig_name)[0] if orig_name else f"media_{obj.file_unique_id}")
    dest = _unique_path(config.VIDEOS_DIR, sanitize(base) + ext)

    note = await msg.reply_text("📥 מוריד…")
    try:
        # Generous timeouts: in local mode the Bot API server downloads big files
        # from Telegram before getFile returns, which can take minutes.
        dl_timeout = config.TELEGRAM_DOWNLOAD_TIMEOUT
        tg_file = await context.bot.get_file(
            obj.file_id, read_timeout=dl_timeout, write_timeout=dl_timeout,
            connect_timeout=60, pool_timeout=60)
        # Local mode returns a local path; download_to_drive copies it. In cloud
        # mode it downloads over HTTP (capped at 20MB by Telegram).
        await tg_file.download_to_drive(
            custom_path=dest, read_timeout=dl_timeout, write_timeout=dl_timeout,
            connect_timeout=60, pool_timeout=60)
    except Exception as e:  # noqa: BLE001
        if "too big" in str(e).lower():
            await note.edit_text(
                "❌ הקובץ גדול מ-20MB. במצב הנוכחי (בלי api_id/api_hash) אפשר רק "
                "סרטונים קצרים. כדי לתמלל סרטונים גדולים (עד 2GB), הזן api_id ו-api_hash "
                "בהגדרות ⚙️.")
        else:
            await note.edit_text(f"❌ ההורדה נכשלה: {e}")
        return

    filename = os.path.basename(dest)
    chat_id = str(msg.chat_id)
    LAST_RECEIVED[chat_id] = filename
    job_id = _enqueue(filename, chat_id)
    await note.edit_text(
        f"📥 התקבל `{filename}` · נוסף לתור (#{job_id}).\n"
        f"לשינוי שם: השב `/name <שם>`",
        parse_mode="Markdown",
    )


def register_handlers(application):
    application.add_handler(CommandHandler(["start", "help"], cmd_start))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("list", cmd_list))
    application.add_handler(CommandHandler("get", cmd_get))
    application.add_handler(CommandHandler("last", cmd_last))
    application.add_handler(CommandHandler("all", cmd_all))
    application.add_handler(CommandHandler("redo", cmd_redo))
    application.add_handler(CommandHandler("rename", cmd_rename))
    application.add_handler(CommandHandler("name", cmd_name))
    application.add_handler(CommandHandler("delete", cmd_delete))
    application.add_handler(CallbackQueryHandler(on_delete_callback, pattern=r"^del:"))
    application.add_handler(MessageHandler(
        filters.VIDEO | filters.AUDIO | filters.VOICE | filters.Document.ALL, on_media))


# --------------------------------------------------------------------------
# Completion notifications (runs while the bot is connected)
# --------------------------------------------------------------------------
async def notify_loop(application):
    while True:
        try:
            for job in db.jobs_pending_notification():
                chat_id = job["chat_id"]
                if job["status"] == db.STATUS_DONE:
                    await application.bot.send_message(
                        chat_id, f"✅ הושלם: `{job['filename']}`", parse_mode="Markdown")
                    await _send_results(application, chat_id, job)
                else:
                    await application.bot.send_message(
                        chat_id,
                        f"❌ נכשל: `{job['filename']}`\n{(job.get('error') or '')[:300]}",
                        parse_mode="Markdown")
                db.mark_notified(job["id"])
        except Exception as e:  # noqa: BLE001 — never let the loop die
            print(f"[bot] notify_loop error: {e}", flush=True)
        await asyncio.sleep(5)


# --------------------------------------------------------------------------
# Supervisor: start/stop/reload the Telegram connection on config changes
# --------------------------------------------------------------------------
async def _start(s: dict):
    global _NOTIFIER
    builder = ApplicationBuilder().token(s["tg_bot_token"])
    api_id = (s.get("tg_api_id") or "").strip()
    api_hash = (s.get("tg_api_hash") or "").strip()
    if api_id and api_hash:
        # Local Bot API server → downloads up to 2GB, files read straight off disk.
        base = config.TELEGRAM_API_BASE
        builder = (builder.base_url(f"{base}/bot")
                          .base_file_url(f"{base}/file/bot")
                          .local_mode(True))
        db.set_setting("tg_mode", "local")
    else:
        # Public api.telegram.org → simplest, but limited to 20MB downloads.
        db.set_setting("tg_mode", "cloud")
    application = builder.build()
    register_handlers(application)
    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    # Register the command menu so typing "/" shows a picker in the chat.
    try:
        await application.bot.set_my_commands(BOT_COMMANDS)
    except Exception as e:  # noqa: BLE001 — non-critical
        print(f"[bot] set_my_commands failed: {e}", flush=True)
    _NOTIFIER = asyncio.create_task(notify_loop(application))
    return application


async def _shutdown(application):
    global _NOTIFIER
    if _NOTIFIER:
        _NOTIFIER.cancel()
        _NOTIFIER = None
    try:
        if application.updater and application.updater.running:
            await application.updater.stop()
        await application.stop()
        await application.shutdown()
    except Exception as e:  # noqa: BLE001
        print(f"[bot] shutdown error: {e}", flush=True)


async def run():
    db.init_db()
    print("[bot] supervisor started; waiting for configuration…", flush=True)
    application = None
    version = None

    while True:
        s = _settings()
        enabled = s.get("tg_enabled") == "1"
        token = s.get("tg_bot_token")
        new_version = s.get("tg_updated_at")
        want = enabled and bool(token)

        # Tear down on config change or disable.
        if application is not None and (new_version != version or not want):
            print("[bot] config changed / disabled — stopping.", flush=True)
            await _shutdown(application)
            application = None

        # Start when wanted and not running.
        if application is None and want:
            version = new_version
            try:
                application = await _start(s)
                me = await application.bot.get_me()
                db.set_setting("tg_bot_username", me.username or "")
                db.set_setting("tg_status", "connected")
                db.set_setting("tg_last_error", "")
                print(f"[bot] connected as @{me.username}", flush=True)
            except Exception as e:  # noqa: BLE001
                db.set_setting("tg_status", "error")
                db.set_setting("tg_last_error", str(e)[:500])
                print(f"[bot] connect failed: {e}", flush=True)
                if application:
                    await _shutdown(application)
                application = None
                await asyncio.sleep(10)
                continue

        # Idle status when not running.
        if application is None and not want:
            db.set_setting("tg_status", "disabled" if not enabled else "not_configured")

        await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(run())
