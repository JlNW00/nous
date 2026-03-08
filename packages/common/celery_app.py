"""Celery application — central broker config and task routing."""

from __future__ import annotations

from celery import Celery

from packages.common.config import settings

celery_app = Celery(
    "investigator",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.beat_schedule = {
    "poll-bags-launches": {
        "task": "workers.discovery.poll_bags_launches",
        "schedule": 300.0,  # Every 5 minutes
    },
    "reinvestigate-active-cases": {
        "task": "workers.discovery.reinvestigate_active_cases",
        "schedule": 86400.0,  # Every 24 hours
    },
}

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # Reliability
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,

    # Timeouts
    task_soft_time_limit=120,
    task_time_limit=180,

    # Result expiry
    result_expires=3600,

    # Routing — each worker type gets its own queue
    task_routes={
        "workers.discovery.*": {"queue": "discovery"},
        "workers.graph.*": {"queue": "graph"},
        "workers.signals.*": {"queue": "signals"},
        "workers.reasoning.*": {"queue": "reasoning"},
        "workers.reporting.*": {"queue": "reporting"},
        "agents.poster.*": {"queue": "reporting"},
    },

    # Default queue for anything unmatched
    task_default_queue="default",

    # Retry
    task_default_retry_delay=10,
    task_max_retries=3,
)

# Auto-discover tasks from worker modules
celery_app.autodiscover_tasks([
    "workers.discovery",
    "workers.graph",
    "workers.signals",
    "workers.reasoning",
    "workers.reporting",
    "agents.poster",
])
