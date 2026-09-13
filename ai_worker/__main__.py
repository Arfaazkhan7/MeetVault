from .config import settings

if settings.queue_backend.lower() == "celery":
    from .tasks import celery_app

    celery_app.worker_main(["worker", "--loglevel=INFO"])
else:
    from .db_worker import run_database_worker

    run_database_worker()
