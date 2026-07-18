# Media Transcription · תמלול מדיה

A local, private, self-hosted transcription system with a web UI and a Telegram
bot. Drop in videos or audio and get **SRT + TXT** transcripts, powered by
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) (`large-v3` by
default). Everything runs on your machine in Docker — no cloud, no uploads to
third parties.

> **English first, then עברית below** · [דלג לעברית ↓](#עברית)

---

## English

### Features

- 🎬 **Video & audio** — mp4, mkv, avi, mov, webm… and mp3, wav, m4a, ogg, flac, voice notes.
- 🌐 **Web UI (Hebrew / English)** — list media, transcribe one or all, watch live progress, preview the text, download SRT/TXT, rename, and delete.
- 🗣️ **Language selector** — choose the transcription language (default Hebrew) or auto-detect; saved persistently.
- 🤖 **Telegram bot** — send a video/audio/voice note and it downloads, transcribes, and notifies you. Full command set. Configured entirely from the web UI.
- ⏳ **Background queue** — throw in many files and close the lid; jobs run one after another. Per-job error handling: one bad file never stops the rest.
- ♻️ **Survives restart/reboot** — Redis persistence + startup re-queue means pending jobs resume on their own.
- 📦 **Model cached per machine** — the Whisper model downloads once into a named volume (not baked into the image), and survives rebuilds.
- 🔒 **Local & private** — personal use, no auth, nothing leaves your computer.

### Architecture

```
   Browser (localhost:8000) ──HTTP──►  api (FastAPI)  ──enqueue──►  redis  ──►  worker (Celery)
                                            │                                       │ faster-whisper
   Telegram app ──►  telegram-bot-api  ──►  bot  ──────────────────────────────────►  SRT + TXT
                     (local, up to 2GB)      │
                          all services share  SQLite (jobs + settings)  +  a Whisper model cache volume
```

Five services (all in `docker-compose.yml`): **api** (UI + REST), **worker**
(the transcription), **redis** (the queue), **bot** (Telegram), and
**telegram-bot-api** (a self-hosted local Bot API server for large downloads).

### Requirements

- Docker + Docker Compose (Docker Desktop, or `docker` + `docker compose` on Linux).
- No Python or other installs needed — everything runs in containers.

### Quick start

```bash
# 1. (optional) copy the settings file and adjust
cp .env.example .env

# 2. put video/audio files in ./videos  (or point VIDEOS_DIR elsewhere)

# 3. bring it up
docker compose up --build
```

Open **http://localhost:8000**.

On the first run the worker downloads the Whisper model (`large-v3`, a few GB)
into a cache volume — **once per machine**. The first transcription starts after
that finishes. Stop with `Ctrl+C`, then `docker compose down` (your data and the
model are kept).

> **Note on paths with non-ASCII characters:** if the project folder name is not
> plain ASCII, disable BuildKit so the build works:
> `DOCKER_BUILDKIT=0 COMPOSE_DOCKER_CLI_BUILD=0 docker compose up --build`
> (or clone into an ASCII path).

### Using the web interface

- Each media file in `./videos` appears as a row with its status.
- **Transcribe** queues a file; status goes `queued → processing → done`, with a live **percentage** while processing.
- **Process all** queues everything not yet done.
- **Preview** opens the transcript (plain text or SRT with timecodes) with a copy button.
- **SRT / TXT** download the results (also saved in `./transcripts`).
- **🗑 Delete** removes a media file, its transcripts, and its records (with confirmation).
- **Language dropdown** (top bar) chooses the transcription language; **⚙️** opens Telegram setup.
- The page polls every few seconds, so status updates on its own.

### Telegram bot (optional)

Send media to a bot and get it transcribed, with completion notifications.

**Setup — all from the web UI, once (saved forever):**

1. Open http://localhost:8000 and click **⚙️**.
2. Follow the steps in the dialog:
   - **Required** — create a bot with [@BotFather](https://t.me/BotFather) (`/newbot`) → **Bot Token**.
   - **Required** — get your **User ID** from [@userinfobot](https://t.me/userinfobot).
   - **Optional** — create an app at [my.telegram.org](https://my.telegram.org/auth) → **api_id** + **api_hash**.
3. Fill the fields, tick **Enable the bot**, and Save. The badge turns **Connected ✅**.

Settings are stored in SQLite on a persistent volume — enter once, and it comes
back on its own after `down/up` or a rebuild.

**Two modes (based on api_id/api_hash):**

|                    | Without api_id/api_hash | With api_id/api_hash          |
| ------------------ | ----------------------- | ----------------------------- |
| Max file size      | **20 MB** (short clips) | **2 GB**                      |
| How                | api.telegram.org        | **Local Bot API server**      |

For short clips, Token + User ID are enough. For large files, add api_id/api_hash.
(Changing api_id/api_hash later needs `docker compose restart telegram-bot-api`;
everything else is applied live.)

**Commands:** send a video/audio/voice note (as a **Document/file** for best
quality), then use:

- `/status` — what's processing / queued / done
- `/list` — all files and their status
- `/get [name|#]` — list ready transcripts, or send one (partial-name search)
- `/last` — the most recent finished transcript
- `/all` — transcribe everything not yet done
- `/redo <name|#>` — re-transcribe an existing file
- `/rename <#|name> <new name>` — rename a file (and its transcripts)
- `/name <new name>` — name the file you just sent
- `/delete <name|#>` — delete a file + transcripts (with confirmation)

**Security:** only allow-listed User IDs can talk to the bot. Don't leave the
allow-list empty, and don't expose the port to the internet.

### Choosing the transcription language

Use the **language dropdown** in the top bar: Hebrew (default), auto-detect, or
one of the built-in languages. It's saved and applies to new jobs immediately —
no restart. To fix an already-done file, pick a language and then re-transcribe
it (UI "Transcribe again", or `/redo` in the bot).

### Changing the model

Set an env var — **no rebuild needed**:

```bash
WHISPER_MODEL=medium     # faster/lighter, lower quality
WHISPER_MODEL=large-v3   # default — best quality
WHISPER_MODEL=turbo      # (large-v3-turbo) much faster, near-large quality
```

Then `docker compose up -d`. Supported: `tiny`, `base`, `small`, `medium`,
`large-v3`, `turbo`.

### Model cache (named volume)

The model is **not** baked into the image. `docker-compose.yml` defines a named
volume `whisper-cache` mapped to `/root/.cache/huggingface`, so the model
downloads **once per machine** and survives restarts, `down/up`, and even image
rebuilds. To wipe everything (including the DB): `docker compose down -v`.

### Configuration (environment variables)

| Variable                     | Default              | Description                                   |
| ---------------------------- | -------------------- | --------------------------------------------- |
| `WHISPER_MODEL`              | `large-v3`           | Transcription model                           |
| `WHISPER_LANGUAGE`           | `he`                 | Default language (overridden by the UI picker)|
| `WHISPER_COMPUTE_TYPE`       | `int8`               | CPU quantization                              |
| `WHISPER_BEAM_SIZE`          | `8`                  | Beam search width                             |
| `WHISPER_TEMPERATURE`        | `0.0,0.2,…,1.0`      | Temperature fallback (anti-loop)              |
| `WHISPER_CONDITION_PREVIOUS` | `false`              | Feed previous text (false reduces loops)      |
| `WHISPER_REPETITION_PENALTY` | `1.1`                | Penalty on repeats                            |
| `WHISPER_NO_REPEAT_NGRAM`    | `0`                  | Hard-block repeated n-grams (0=off)           |
| `WORKER_CONCURRENCY`         | `1`                  | Files transcribed in parallel                 |
| `VIDEOS_DIR`                 | `./videos`           | Input folder (host)                           |
| `TRANSCRIPTS_DIR`            | `./transcripts`      | Output folder (host)                          |
| `TELEGRAM_DOWNLOAD_TIMEOUT`  | `1800`               | Max seconds to download a file via the bot    |

### Project structure

```
.
├── docker-compose.yml      # api + worker + redis + bot + telegram-bot-api + volumes
├── Dockerfile              # shared image (includes ffmpeg)
├── requirements.txt
├── .env.example
├── LICENSE                 # MIT
├── app/
│   ├── config.py           # settings from env
│   ├── db.py               # SQLite layer (jobs + settings)
│   ├── celery_app.py       # Celery config (broker/backend = Redis)
│   ├── worker.py           # transcription task + startup resume
│   ├── bot.py              # Telegram bot (receive, commands, rename, delete, notify)
│   └── main.py             # FastAPI: media list, transcribe, status, downloads, settings
├── scripts/
│   └── telegram-api-entrypoint.sh  # entrypoint for the local Bot API server
├── frontend/
│   └── index.html          # single-file UI (bilingual, polling, settings modal)
├── videos/                 # input (mounted)
├── transcripts/            # output (SRT + TXT)
└── data/                   # SQLite DB + telegram creds (git-ignored)
```

### Resilience

Every file is an independent job. If one fails (corrupt file, no audio…), it's
marked `failed` with the error, partial output is cleaned up, and the rest of
the queue continues. On restart/reboot, pending jobs are re-queued automatically
(an interrupted file restarts from the beginning — Whisper has no mid-file
checkpoint).

### Disclaimer

This is a personal, open-source project provided **"as is", without warranty of
any kind** (see [LICENSE](LICENSE)). Use it at your own risk. You alone are
responsible for the media you transcribe and for complying with applicable laws —
including recording/consent rules, privacy, and copyright. The authors are not
liable for any misuse of, or damage arising from, the software.

### License & acknowledgements

Licensed under the [MIT License](LICENSE) © 2026 Peer Abitbul.

Everything this project builds on is open source, each under its own license,
used as unmodified dependencies/tools (this project does not bundle or alter
their source):

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — MIT · Whisper `large-v3` weights — MIT (OpenAI)
- [FastAPI](https://fastapi.tiangolo.com/) — MIT · [Uvicorn](https://www.uvicorn.org/) — BSD
- [Celery](https://docs.celeryq.dev/) — BSD · [Redis](https://redis.io/) — BSD / SSPL (per version)
- [python-telegram-bot](https://python-telegram-bot.org/) — LGPL-3.0
- [telegram-bot-api](https://github.com/tdlib/telegram-bot-api) — Boost Software License
- [FFmpeg](https://ffmpeg.org/) — LGPL/GPL

---

## עברית

מערכת תמלול מקומית ופרטית עם ממשק web ובוט טלגרם. זורקים סרטונים או אודיו ומקבלים
תמלול **SRT + TXT**, מבוסס [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
(מודל `large-v3` כברירת מחדל). הכול רץ אצלך ב-Docker — בלי ענן, בלי העלאה לגורם חיצוני.

### יכולות

- 🎬 **וידאו ואודיו** — mp4, mkv, avi… וגם mp3, wav, m4a, ogg, הקלטות קוליות.
- 🌐 **ממשק web (עברית / אנגלית)** — רשימת מדיה, תמלול בודד או "עבד את הכל", התקדמות חיה, תצוגה מקדימה, הורדת SRT/TXT, שינוי שם ומחיקה.
- 🗣️ **בורר שפה** — בחירת שפת התמלול (ברירת מחדל עברית) או זיהוי אוטומטי; נשמר.
- 🤖 **בוט טלגרם** — שולחים סרטון/אודיו/הקלטה והוא מוריד, מתמלל ומודיע בסיום. פקודות מלאות. מוגדר לגמרי מהממשק.
- ⏳ **תור ברקע** — זורקים הרבה קבצים וסוגרים את המחשב; העבודות רצות אחת אחרי השנייה. טיפול בשגיאות פר-קובץ: קובץ פגום לא עוצר את השאר.
- ♻️ **עמיד לכיבוי/reboot** — Redis קבוע + הרצה-מחדש בהפעלה מחזירים עבודות ממתינות לבד.
- 📦 **מודל נשמר לכל מחשב** — יורד פעם אחת ל-volume (לא אפוי ב-image) ושורד rebuild.
- 🔒 **מקומי ופרטי** — לשימוש אישי, בלי אימות, שום דבר לא עוזב את המחשב.

### ארכיטקטורה

חמישה שירותים (ב-`docker-compose.yml`): **api** (ממשק + REST), **worker** (התמלול),
**redis** (התור), **bot** (טלגרם), ו-**telegram-bot-api** (שרת Bot API מקומי להורדות גדולות).

### דרישות מוקדמות

- Docker + Docker Compose. אין צורך ב-Python או בהתקנות נוספות — הכול בקונטיינרים.

### הרצה מהירה

```bash
cp .env.example .env          # אופציונלי
# שים קבצי וידאו/אודיו ב-./videos
docker compose up --build
```

פתח **http://localhost:8000**. בהרצה הראשונה המודל (`large-v3`, כמה GB) יורד
פעם אחת ל-cache; התמלול הראשון מתחיל אחרי שההורדה מסתיימת. לעצירה: `Ctrl+C` ואז
`docker compose down` (הנתונים והמודל נשמרים).

> **נתיב עם תווים לא-אנגליים:** אם שם התיקייה אינו אנגלי, הרץ עם BuildKit מכובה:
> `DOCKER_BUILDKIT=0 COMPOSE_DOCKER_CLI_BUILD=0 docker compose up --build`
> (או שים את הפרויקט בנתיב באנגלית).

### שימוש בממשק

- כל קובץ מדיה מוצג בשורה עם סטטוס. **תמלל** מכניס לתור (`בתור → מעבד → הושלם`) עם **אחוז** חי.
- **עבד את הכל** — מכניס לתור כל מה שלא תומלל. **תצוגה מקדימה** — פותח את הטקסט (רגיל או SRT).
- **SRT / TXT** — הורדה (נשמר גם ב-`./transcripts`). **🗑 מחיקה** — מסיר קובץ + תמלולים (עם אישור).
- **בורר שפה** למעלה בוחר את שפת התמלול; **⚙️** פותח את הגדרות הטלגרם.

### בוט טלגרם (אופציונלי)

**הגדרה — הכל מהממשק, פעם אחת (נשמר לתמיד):**

1. פתח את http://localhost:8000 ולחץ **⚙️**.
2. עקוב אחר השלבים:
   - **חובה** — בוט ב-[@BotFather](https://t.me/BotFather) (`/newbot`) → **Bot Token**.
   - **חובה** — ה-**User ID** שלך מ-[@userinfobot](https://t.me/userinfobot).
   - **אופציונלי** — אפליקציה ב-[my.telegram.org](https://my.telegram.org/auth) → **api_id** + **api_hash**.
3. מלא, סמן **הפעל את הבוט**, ושמור. החיווי יעבור ל**מחובר ✅**.

**שני מצבים:** בלי api_id/api_hash — עד **20MB** (קצרים). עם api_id/api_hash — עד **2GB**
(דרך שרת Bot API מקומי). שינוי api_id/api_hash בעתיד דורש `docker compose restart telegram-bot-api`;
שאר ההגדרות נטענות חם.

**פקודות:** שלח וידאו/אודיו/הקלטה (עדיף כ"קובץ/Document" לאיכות), ואז:
`/status` · `/list` · `/get [שם|#]` · `/last` · `/all` · `/redo <שם|#>` ·
`/rename <#|שם> <שם חדש>` · `/name <שם חדש>` · `/delete <שם|#>`.

**אבטחה:** רק User IDs מורשים יכולים לדבר עם הבוט. אל תשאיר את הרשימה ריקה, ואל תחשוף את הפורט לאינטרנט.

### בחירת שפת תמלול

בורר השפה למעלה: עברית (ברירת מחדל), זיהוי אוטומטי, או שפה מובנית. נשמר וחל מיד על
עבודות חדשות בלי restart. לתיקון קובץ שכבר תומלל — בחר שפה ואז תמלל מחדש ("תמלל שוב" בממשק, או `/redo` בבוט).

### החלפת מודל

משתנה סביבה, **בלי rebuild**: `WHISPER_MODEL=medium|large-v3|turbo`, ואז `docker compose up -d`.
נתמכים: `tiny`, `base`, `small`, `medium`, `large-v3`, `turbo`.

### Cache של המודל

המודל **לא** אפוי ב-image. `whisper-cache` (named volume) ממופה ל-`/root/.cache/huggingface`,
כך שהמודל יורד **פעם אחת בכל מחשב** ושורד restart, `down/up` ו-rebuild. למחיקת הכול (כולל DB):
`docker compose down -v`.

### הגדרות (משתני סביבה)

ראה את הטבלה בחלק האנגלי (§Configuration) ואת `.env.example`. עיקרי: `WHISPER_MODEL`,
`WHISPER_LANGUAGE`, `WORKER_CONCURRENCY`, `VIDEOS_DIR`, `TRANSCRIPTS_DIR`, `TELEGRAM_DOWNLOAD_TIMEOUT`.

### עמידות בפני כשלים

כל קובץ הוא job עצמאי. כשל בקובץ (פגום/בלי אודיו) מסומן `failed` עם השגיאה, פלט חלקי נמחק,
והתור ממשיך. בהפעלה מחדש עבודות ממתינות חוזרות לתור אוטומטית (קובץ שנקטע מתחיל מ-0 — ל-Whisper אין checkpoint).

### כתב ויתור (Disclaimer)

זהו פרויקט אישי בקוד פתוח, מסופק **"כמות שהוא", ללא כל אחריות** (ראה [LICENSE](LICENSE)).
השימוש על אחריותך בלבד. אתה האחראי הבלעדי לתוכן שאתה מתמלל ולעמידה בחוק — כולל כללי
הקלטה/הסכמה, פרטיות וזכויות יוצרים. היוצרים אינם אחראים לשימוש לרעה או לכל נזק שייגרם מהתוכנה.

### רישיון וקרדיטים

תחת רישיון [MIT](LICENSE) © 2026 Peer Abitbul. כל מה שהפרויקט מבוסס עליו הוא קוד פתוח,
כל אחד תחת הרישיון שלו, בשימוש כתלויות/כלים ללא שינוי: faster-whisper (MIT), מודל Whisper
(MIT), FastAPI (MIT), Uvicorn (BSD), Celery (BSD), Redis (BSD/SSPL), python-telegram-bot
(LGPL-3.0), telegram-bot-api (Boost), FFmpeg (LGPL/GPL).
