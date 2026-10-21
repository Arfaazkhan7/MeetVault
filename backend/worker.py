"""Cloudflare entrypoint for the existing FastAPI route tree.

This is a candidate runtime. Do not cut over until CPU-heavy requests have
been measured on Workers Free and the migration checklist is complete.
"""
import asyncio
from urllib.parse import urlparse

from workers import WorkerEntrypoint, Response, asgi
from sqlalchemy import text

from app.main import app
from app.core.config import settings, refresh_worker_settings
from app.db.session import SessionLocal
from app.core.workers_routes import configure_worker_routes
from app.core.runtime import IS_WORKERS

if IS_WORKERS:
    configure_worker_routes(app)

# Python's synchronous database operations can suspend through the Workers
# socket bridge. Serialize requests as recommended by the Hyperdrive docs.
_request_lock = asyncio.Lock()


def configuration_ready(env) -> bool:
    return bool(
        getattr(env, "HYPERDRIVE", None)
        and getattr(env, "JWT_SECRET", "")
        and settings.JWT_SECRET != "change-this-to-a-very-long-random-secret-in-production"
        and getattr(env, "SUPABASE_URL", "")
        and getattr(env, "SUPABASE_SERVICE_ROLE_KEY", "")
        and getattr(env, "LIVEKIT_URL", "")
        and getattr(env, "LIVEKIT_API_KEY", "")
        and getattr(env, "LIVEKIT_API_SECRET", "")
        and getattr(env, "CLOUDFLARE_AI_CALLBACK_SECRET", "")
    )


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        async with _request_lock:
            refresh_worker_settings(self.env)
            if not configuration_ready(self.env):
                return Response.json({"status": "not_configured"}, status=503)
            if urlparse(request.url).path in ("/health", "/api/v1/health"):
                try:
                    with SessionLocal() as db:
                        db.execute(text("SELECT 1"))
                    return Response.json({"status": "ok", "runtime": "cloudflare"})
                except Exception:
                    return Response.json({"status": "database_unavailable"}, status=503)
            return await asgi.fetch(app, request, self.env)
