"""
Celery App — Background task queue
"""

from celery import Celery
from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "veo3_worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Ho_Chi_Minh",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=50,  # Restart worker sau 50 tasks (tránh memory leak)
    worker_concurrency=settings.WORKER_CONCURRENCY,
    task_soft_time_limit=600,   # 10 phút soft limit
    task_time_limit=900,        # 15 phút hard limit
)

# Import tasks sau khi Celery khởi tạo
celery_app.autodiscover_tasks(["app"])
