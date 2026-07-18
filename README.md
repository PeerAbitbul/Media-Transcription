# תמלול סרטונים — Local Video Transcription

מערכת תמלול וידאו מקומית עם ממשק web, רצה כולה ב-Docker Compose.
מבוססת על [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (מודל `large-v3` כברירת מחדל),
עם עיבוד ברקע בתור — אפשר לזרוק כמה סרטונים, לסגור את המחשב לישון, והעיבוד ממשיך כל הלילה.

## ארכיטקטורה

```
                 ┌──────────┐      HTTP       ┌──────────────┐
   דפדפן (localhost:8000) ─────────────────►  │  api (FastAPI)│
                 └──────────┘                 └──────┬───────┘
                                                     │ Celery task (Redis)
                                          ┌──────────▼───────┐
                                          │      redis       │
                                          └──────────┬───────┘
                                                     │
                                          ┌──────────▼───────┐   faster-whisper
                                          │  worker (Celery) │──────────────────► SRT + TXT
                                          └──────────────────┘
        api + worker חולקים DB (SQLite) ומודל Whisper דרך named volume (whisper-cache).
```

שלושה שירותים: **api** (ממשק + REST), **worker** (התמלול בפועל), **redis** (תור המשימות).

## דרישות מוקדמות

- Docker + Docker Compose (Docker Desktop, או `docker` + `docker compose` בלינוקס).
- אין צורך ב-Python או בהתקנות נוספות על המחשב — הכל רץ בקונטיינרים.

## הרצה מהירה

```bash
# 1. (אופציונלי) העתק את קובץ ההגדרות ושנה מה שצריך
cp .env.example .env

# 2. שים קבצי וידאו (mp4/mkv/avi/…) בתיקיית videos/
#    או הצבע על תיקייה אחרת — ראה "החלפת תיקיית וידאו" למטה.

# 3. הרם את המערכת
docker compose up --build
```

פתח בדפדפן: **http://localhost:8000**

בהרצה הראשונה, ה-worker יוריד את מודל Whisper (`large-v3`, כמה GB) לתוך ה-cache.
זה קורה **פעם אחת בכל מחשב** — ראה "Cache של המודל" למטה. תמלול ראשון יתחיל רק אחרי שההורדה תסתיים.

לעצירה: `Ctrl+C`, ואז `docker compose down` (הנתונים והמודל נשמרים).

## שימוש

- **רשימת קבצים** — כל קובצי הווידאו שבתיקיית `videos/` מוצגים בטבלה, עם סטטוס.
- **תמלל** — כפתור ליד כל קובץ מוסיף אותו לתור. הסטטוס עובר `בתור → מעבד → הושלם`.
- **עבד את הכל** — מוסיף לתור כל קובץ שעדיין לא תומלל.
- **התקדמות** — בזמן עיבוד מוצג אחוז התקדמות (מבוסס על זמן־האודיו שכבר תומלל).
- **תוצאה** — כשה-job מסתיים, מופיעים קישורי הורדה ל-**SRT** ול-**TXT**.
  הקבצים נשמרים גם בתיקיית `transcripts/` (בשם זהה לקובץ המקור).
- **תצוגה מקדימה** — לחיצה על כרטיס שהושלם פותחת חלון עם התמלול (טקסט או כתוביות SRT), עם כפתור העתקה.
- **עברית / English** — כפתור בפינה מחליף את שפת הממשק ואת כיוון הכתיבה (RTL/LTR). הבחירה נשמרת בדפדפן.
- הממשק מבצע polling כל 4 שניות, כך שהסטטוס מתעדכן לבד.

## בוט Telegram (אופציונלי)

אפשר לשלוח סרטונים לבוט טלגרם, והם יורדים, נשמרים בתיקייה ומתומללים אוטומטית — עם התראה בסיום ופקודות לניהול.

**הגדרה — הכל מהממשק, פעם אחת (נשמר לתמיד):**
1. פתח את http://localhost:8000 ולחץ על **⚙️** (למעלה).
2. עקוב אחר השלבים בחלון:
   - **חובה** — צור בוט ב-[@BotFather](https://t.me/BotFather) (`/newbot`) → קבל **Bot Token**.
   - **חובה** — קבל את ה-**User ID** שלך מ-[@userinfobot](https://t.me/userinfobot).
   - **אופציונלי** — צור אפליקציה ב-[my.telegram.org](https://my.telegram.org/auth) → **api_id** + **api_hash**.
3. הזן, סמן **הפעל את הבוט**, ושמור. חיווי החיבור יעבור ל**מחובר ✅**.

ההגדרות נשמרות ב-SQLite על ה-volume הקבוע — מזינים פעם אחת, וזה חוזר לבד גם אחרי `down/up` או rebuild.

**שני מצבים (לפי api_id/api_hash):**
| | בלי api_id/api_hash | עם api_id/api_hash |
|---|---|---|
| גודל סרטון מרבי | **20MB** (סרטונים קצרים) | **2GB** |
| דרך | api.telegram.org הרגיל | **Local Bot API Server** (שירות `telegram-bot-api`) |

לסרטונים קצרים — Token + User ID מספיקים. לסרטונים גדולים — הוסף api_id/api_hash. המצב הפעיל מוצג בחיווי החיבור (למשל "מחובר ✅ · עד 2GB").

> אם תשנה את api_id/api_hash בעתיד (נדיר), הרץ `docker compose restart telegram-bot-api`. שאר ההגדרות נטענות חם ללא restart.

**שימוש:**
- **שלח סרטון** (עדיף כ"קובץ/Document" לאיכות מלאה). צרף **כיתוב** כדי לקבוע שם, או שנה אח"כ.
- פקודות: `/status`, `/list`, `/get <שם או #>`, `/last`, `/all`, `/rename <# או שם> <שם חדש>`, `/name <שם חדש>`.

**אבטחה:** רק ה-User IDs שברשימת המורשים יכולים לדבר עם הבוט. אל תשאיר את הרשימה ריקה.

## החלפת תיקיית וידאו

ערוך את `.env` (או הגדר משתני סביבה) והצבע על כל תיקייה במחשב:

```bash
VIDEOS_DIR=/Users/me/Movies/lectures
TRANSCRIPTS_DIR=/Users/me/Movies/lectures/transcripts
```

התיקייה ממופה ל-`/app/videos` בתוך הקונטיינר כ-read-only (המערכת אף פעם לא כותבת אליה).
לאחר שינוי, הרץ מחדש: `docker compose up -d`.

## החלפת מודל

המודל נקבע דרך משתנה סביבה — **אין צורך לבנות מחדש את ה-image**:

```bash
# ב-.env, או בשורת הפקודה
WHISPER_MODEL=medium        # מהיר וקל יותר, איכות נמוכה יותר
WHISPER_MODEL=large-v3      # ברירת המחדל — האיכות הגבוהה ביותר
WHISPER_MODEL=turbo         # (large-v3-turbo) מהיר בהרבה, איכות קרובה ל-large
```

ואז: `docker compose up -d`. אפשר גם להחליף שפה: `WHISPER_LANGUAGE=en` (ריק = זיהוי אוטומטי).

מודלים נוספים שנתמכים: `tiny`, `base`, `small`, `medium`, `large-v3`, `turbo`.

## Cache של המודל (named volume)

המודל **לא** נאפה בתוך ה-image. במקום זה, `docker-compose.yml` מגדיר named volume בשם
`whisper-cache` הממופה ל-`/root/.cache/huggingface`. לכן:

- **הורדה חד-פעמית בכל מחשב** — בפעם הראשונה שה-worker רץ, המודל יורד ל-volume.
- **נשמר בין הרצות** — `restart`, `docker compose down/up`, ואפילו `--build` (rebuild של ה-image)
  לא מוחקים את ה-volume, כך שאין הורדה חוזרת.
- כל מי שמושך את הפרויקט מ-git עושה `clone + build` מקומי; המודל יורד אצלו פעם אחת ברשת.

למחיקת ה-cache (למשל לפינוי מקום): `docker compose down -v` (⚠️ ימחק גם את ה-DB).

## הגדרות (משתני סביבה)

| משתנה | ברירת מחדל | תיאור |
|---|---|---|
| `WHISPER_MODEL` | `large-v3` | מודל התמלול |
| `WHISPER_LANGUAGE` | `he` | שפת התמלול (ריק = זיהוי אוטומטי) |
| `WHISPER_COMPUTE_TYPE` | `int8` | קוונטיזציה ל-CPU |
| `WHISPER_BEAM_SIZE` | `8` | רוחב ה-beam search |
| `WORKER_CONCURRENCY` | `1` | כמה סרטונים לעבד במקביל |
| `VIDEOS_DIR` | `./videos` | תיקיית הקלט (host) |
| `TRANSCRIPTS_DIR` | `./transcripts` | תיקיית הפלט (host) |

הגדרות התמלול הקבועות לפי הדרישות: `vad_filter=True`, `condition_on_previous_text=True`,
`temperature=0.0`, `device="cpu"`.

## מבנה הפרויקט

```
.
├── docker-compose.yml      # api + worker + redis + named volume (whisper-cache)
├── Dockerfile              # image משותף ל-api ול-worker (כולל ffmpeg)
├── requirements.txt
├── .env.example            # כל משתני הסביבה
├── app/
│   ├── config.py           # קריאת הגדרות מ-env
│   ├── db.py               # שכבת SQLite (jobs + settings, timestamps)
│   ├── celery_app.py       # הגדרת Celery (broker/back­end = Redis)
│   ├── worker.py           # משימת התמלול (faster-whisper) — error handling per-job
│   ├── bot.py              # בוט Telegram (קליטה, פקודות, שינוי שם, התראות)
│   └── main.py             # FastAPI: רשימת וידאו, הפעלה, סטטוס, הורדות, הגדרות
├── scripts/
│   └── telegram-api-entrypoint.sh  # entrypoint לשרת ה-Bot API המקומי
├── frontend/
│   └── index.html          # ממשק (HTML/JS) עם polling + חלון הגדרות Telegram
├── videos/                 # קלט (mount, read-only)
├── transcripts/            # פלט (SRT + TXT)
└── data/                   # קובץ ה-SQLite (משותף בין api ל-worker)
```

## עמידות בפני כשלים

כל קובץ מעובד כ-job עצמאי. אם תמלול של קובץ נכשל (קובץ פגום, ללא אודיו וכו'),
ה-job מסומן `failed` עם הודעת השגיאה, פלט חלקי נמחק, **ושאר התור ממשיך לרוץ כרגיל**.
`task_acks_late` מבטיח שאם ה-worker קורס באמצע, ה-job חוזר לתור במקום ללכת לאיבוד.

## הערות

- זו מערכת פנימית לשימוש אישי — אין אימות/הרשאות, אין deployment לענן. אל תחשוף את הפורט לאינטרנט.
- ריצה על CPU: תמלול `large-v3` איטי (דקות עד עשרות דקות לסרטון, תלוי באורך ובחומרה). זה תקין — לכן העיבוד ברקע.
