from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.v1 import health, auth, admin, companies, users, projects, meetings, recordings, transcripts, diarization, analytics, documents, project_memory, cross_meeting, search, rag, analysis

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    docs_url=f"{settings.API_V1_PREFIX}/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router,          prefix=settings.API_V1_PREFIX)
app.include_router(auth.router,            prefix=settings.API_V1_PREFIX)
app.include_router(admin.router,           prefix=settings.API_V1_PREFIX)
app.include_router(companies.router,       prefix=settings.API_V1_PREFIX)
app.include_router(users.router,           prefix=settings.API_V1_PREFIX)
app.include_router(projects.router,        prefix=settings.API_V1_PREFIX)
app.include_router(meetings.router,        prefix=settings.API_V1_PREFIX)
app.include_router(recordings.router,      prefix=settings.API_V1_PREFIX)
app.include_router(transcripts.router,     prefix=settings.API_V1_PREFIX)
app.include_router(diarization.router,     prefix=settings.API_V1_PREFIX)
app.include_router(analytics.router,       prefix=settings.API_V1_PREFIX)
app.include_router(documents.router,       prefix=settings.API_V1_PREFIX)
app.include_router(project_memory.router,  prefix=settings.API_V1_PREFIX)
app.include_router(cross_meeting.router,   prefix=settings.API_V1_PREFIX)
app.include_router(search.router,          prefix=settings.API_V1_PREFIX)
app.include_router(rag.router,             prefix=settings.API_V1_PREFIX)
app.include_router(analysis.router,        prefix=settings.API_V1_PREFIX)

# ── Serve Web UI at root / ───────────────────────────────────────────────
import os
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

def _get_web_dir():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    flutter_build = os.path.join(base_dir, "frontend", "build", "web")
    web_standalone = os.path.join(base_dir, "web")
    if os.path.exists(flutter_build) and os.path.exists(os.path.join(flutter_build, "index.html")):
        return flutter_build
    return web_standalone

@app.get("/")
async def serve_root():
    # Make the browser entry point the unauthenticated login screen.
    return RedirectResponse(url="/login", status_code=307)

@app.get("/health")
async def root_health_check():
    return {"status": "ok"}

@app.get("/docs", include_in_schema=False)
async def root_docs():
    return RedirectResponse(url=f"{settings.API_V1_PREFIX}/docs", status_code=307)

@app.get("/login")
async def serve_login():
    return FileResponse(os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")), "web", "login.html"))

@app.get("/signup")
async def serve_signup():
    return FileResponse(os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")), "web", "signup.html"))

@app.get("/{full_path:path}")
async def serve_ui(full_path: str):
    if full_path.startswith("api") or full_path.startswith("docs") or full_path.startswith("openapi"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    web_dir = _get_web_dir()
    target_file = os.path.join(web_dir, full_path)
    if os.path.isfile(target_file):
        return FileResponse(target_file)

    index_path = os.path.join(web_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return JSONResponse({"detail": "Not Found"}, status_code=404)



