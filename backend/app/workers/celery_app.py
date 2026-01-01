"""
Celery application with multi-queue architecture.

Queues:
- ingest: RSS, HN, Reddit fetching
- extract: Article text extraction
- embed: Embedding generation
- score: Dedup, relevance, signal scoring
- summarise: Briefing generation (LLM calls)
- email: Daily briefing delivery
"""

from celery import Celery
from celery.schedules import crontab
from kombu import Queue

from app.core.config import settings

# Create Celery app
celery_app = Celery(
    "signal_engine",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

# Define queues
celery_app.conf.task_queues = (
    Queue("ingest"),
    Queue("extract"),
    Queue("embed"),
    Queue("score"),
    Queue("summarise"),
    Queue("email"),
)

# Default queue
celery_app.conf.task_default_queue = "ingest"

# Task routing
celery_app.conf.task_routes = {
    # Ingestion tasks -> ingest queue
    "app.workers.tasks.ingest_tasks.*": {"queue": "ingest"},

    # Extraction tasks -> extract queue
    "app.workers.tasks.extract_tasks.*": {"queue": "extract"},

    # Embedding tasks -> embed queue
    "app.workers.tasks.embed_tasks.*": {"queue": "embed"},

    # Dedup and scoring tasks -> score queue
    "app.workers.tasks.dedup_tasks.*": {"queue": "score"},
    "app.workers.tasks.score_tasks.*": {"queue": "score"},

    # Briefing generation -> summarise queue (LLM heavy)
    "app.workers.tasks.briefing_tasks.*": {"queue": "summarise"},

    # Email sending -> email queue
    "app.workers.tasks.email_tasks.*": {"queue": "email"},
}

# Auto-discover tasks
celery_app.conf.imports = [
    "app.workers.tasks.ingest_tasks",
    "app.workers.tasks.extract_tasks",
    "app.workers.tasks.embed_tasks",
    "app.workers.tasks.dedup_tasks",
    "app.workers.tasks.score_tasks",
    "app.workers.tasks.briefing_tasks",
    "app.workers.tasks.email_tasks",
]

# General configuration
celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # Timezone
    timezone="UTC",
    enable_utc=True,

    # Task execution
    task_track_started=True,
    task_time_limit=600,  # 10 minutes max per task
    task_soft_time_limit=540,  # Soft limit at 9 minutes
    task_acks_late=True,
    worker_prefetch_multiplier=1,

    # Result backend
    result_expires=3600,  # Results expire after 1 hour

    # Retry policy
    task_default_retry_delay=60,  # 1 minute
    task_max_retries=3,
)

# Beat schedule (periodic tasks)
celery_app.conf.beat_schedule = {
    # =========================================================================
    # Ingestion - Every 30 minutes
    # =========================================================================
    "ingest-all-sources": {
        "task": "app.workers.tasks.ingest_tasks.ingest_all_sources",
        "schedule": crontab(minute=f"*/{settings.INGESTION_INTERVAL_MINUTES}"),
        "options": {"queue": "ingest"},
    },

    # =========================================================================
    # Extraction - Every 10 minutes
    # =========================================================================
    "extract-pending-items": {
        "task": "app.workers.tasks.extract_tasks.extract_pending_items",
        "schedule": crontab(minute="*/10"),
        "options": {"queue": "extract"},
    },

    # =========================================================================
    # Embedding & Clustering - Every 15 minutes
    # =========================================================================
    "embed-extracted-items": {
        "task": "app.workers.tasks.embed_tasks.embed_pending_items",
        "schedule": crontab(minute="*/15"),
        "options": {"queue": "embed"},
    },
    "cluster-embedded-items": {
        "task": "app.workers.tasks.dedup_tasks.cluster_pending_items",
        "schedule": crontab(minute="*/15"),
        "options": {"queue": "score"},
    },

    # =========================================================================
    # Scoring - Every 15 minutes
    # =========================================================================
    "score-pending-items": {
        "task": "app.workers.tasks.score_tasks.score_pending_items",
        "schedule": crontab(minute="*/15"),
        "options": {"queue": "score"},
    },

    # =========================================================================
    # Briefing Generation - Daily at 06:50 UTC
    # =========================================================================
    "generate-daily-briefing": {
        "task": "app.workers.tasks.briefing_tasks.generate_global_briefing",
        "schedule": crontab(hour=6, minute=50),
        "options": {"queue": "summarise"},
    },

    # =========================================================================
    # Email Briefings - Daily at 07:00 UTC
    # =========================================================================
    "send-daily-briefings": {
        "task": "app.workers.tasks.email_tasks.send_daily_briefings",
        "schedule": crontab(hour=7, minute=0),
        "options": {"queue": "email"},
    },
}
