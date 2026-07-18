"""Celery application shared by the API (producer) and worker (consumer)."""
from celery import Celery

from app.config import REDIS_URL

celery = Celery(
    "transcriber",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["app.worker"],
)

celery.conf.update(
    task_track_started=True,
    # Transcription is long-running; acknowledge only after completion so a
    # crashed worker re-queues the job instead of losing it.
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
)
