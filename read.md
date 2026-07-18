בנה עבורי מערכת תמלול וידאו מקומית עם ממשק web, בפייתון, רצה כולה ב-Docker Compose.

## דרישות פונקציונליות
- קלט: תיקייה מקומית עם קבצי וידאו (mp4/mkv/avi), מגיעה כ-volume mount ל-Docker.
  לא צריך upload — המערכת ניגשת ישירות לקבצים לפי path.
- ממשק web (localhost) שמציג:
  - רשימת קבצי וידאו בתיקייה
  - כפתור להפעלת תמלול על קובץ בודד או "עבד את הכל"
  - סטטוס לכל job: queued / processing / done / failed
  - קישור להורדה/צפייה בתוצאה (SRT + TXT) כשה-job מסתיים
- עיבוד ברקע (asynchronous) כך שאפשר לזרוק כמה סרטונים ולסגור את המחשב לישון —
  התהליך ממשיך לרוץ כל הלילה, מעבד לפי תור.

## סטאק טכני
- Backend: FastAPI
- Task queue: Celery + Redis (worker נפרד מה-API)
- DB: SQLite (מספיק, לא צריך Postgres) — לשמירת job status, metadata, timestamps
- תמלול: faster-whisper, מודל large-v3, compute_type="int8", device="cpu"
  - vad_filter=True
  - beam_size=8
  - condition_on_previous_text=True
  - temperature=0.0
  - language="he" (עם אפשרות להחליף שפה דרך environment variable)
- Frontend: HTML/JS פשוט (לא צריך React) — polling כל כמה שניות לסטטוס jobs
- הכל ב-docker-compose.yml: שירותי api, worker, redis

## Cache של מודל Whisper — named volume, לא baked-in image
- הפרויקט עולה ל-git כקוד (Dockerfile + docker-compose.yml), כל מחשב עושה clone + build מקומי,
  ולכולם יש רשת — אז אין טעם לאפות את המודל בתוך ה-image (זה רק חוזר להורדה בזמן build, בלי יתרון).
- במקום זה: named volume ב-docker-compose (למשל whisper-cache) שממופה ל-
  /root/.cache/huggingface (או לנתיב ה-cache של faster-whisper/ctranslate2) בתוך כל שירות
  שמריץ תמלול.
- כך שהמודל מורד פעם אחת בכל מחשב חדש (בהרצה הראשונה), ולא מתבצעת הורדה חוזרת
  ב-restart, docker compose down/up, או אפילו אחרי rebuild של ה-image — כי volumes
  נשארים בין builds.

## Volumes
- תיקיית וידאו מקומית → /app/videos (read-only מספיק)
- תיקיית פלט תמלולים → /app/transcripts
- whisper-cache (named volume) → /root/.cache/huggingface

## דגשים חשובים
- זו מערכת פנימית לשימוש אישי בלבד, ללא אימות/הרשאות מורכבות, אין deployment לענן.
- חשוב שקובץ שנכשל בתמלול לא יעצור את שאר התור (error handling per-job).
- תעד ב-README: איך להריץ (docker compose up), איך להחליף תיקיית וידאו,
  איך להחליף מודל (medium/large-v3/turbo) דרך environment variable,
  והסבר קצר שהמודל יורד אוטומטית בפעם הראשונה בלבד בכל מחשב.
- תבנה קודם מבנה פרויקט מלא, ואז תתחיל להטמיע קובץ-קובץ (Dockerfile, main.py, worker.py, db.py,
  docker-compose.yml, frontend/index.html), עם בדיקה שהכל עולה ורץ end-to-end לפני שמסמנים כגמור.

תתחיל בלבנות את מבנה הפרויקט וה-docker-compose (כולל named volume ל-cache), ואז תמשיך שכבה-שכבה.