# MeetVault Agent Handoff

## Canonical Repository

- GitHub: https://github.com/GOKUL5731/meetvault
- Remote: `origin`
- Production frontend: `https://ai-meet-f8fd0.web.app`
- Production API: `https://meetvault-api.onrender.com`
- API prefix: `/api/v1`

Always inspect the current `main` branch and local diff before editing. Treat this file as orientation, not a replacement for reading the implementation.

## Architecture

- `frontend/`: Flutter web application. Authentication, dashboard, meeting list, join flow, LiveKit room, transcripts, notes, search, projects, and settings live under `frontend/lib/`.
- `backend/`: FastAPI application. Routes are under `backend/app/api/v1/`; business logic is under `backend/app/services/`; SQLAlchemy models are under `backend/app/models/`.
- `ai_worker/`: database-queue worker for transcription and meeting analysis. It consumes jobs created by the backend and writes results to PostgreSQL.
- `backend/alembic/`: database migrations. Production startup uses `backend/scripts/bootstrap_db.py` before serving.
- `render.yaml`: Render PostgreSQL, API web service, and AI worker definitions.
- `.github/workflows/deploy-firebase-hosting.yml`: Firebase Hosting deployment workflow for the Flutter build.
- `firebase.json` and `.firebaserc`: Firebase Hosting configuration.

## Runtime Contracts

1. Users authenticate with Firebase Email/Password or Google. The frontend exchanges/uses the authenticated token with the FastAPI API.
2. Meeting creation returns an `invite_code` such as `MTG-XXXXXX`.
3. A participant joins with `POST /api/v1/meetings/join` and the invite code. The response supplies the meeting id, LiveKit URL, room name, and participant token.
4. The room records attendance through `/meetings/{id}/room/join` and `/room/leave`. Do not remove this timing path; transcript duration depends on it.
5. LiveKit handles real-time audio/video. Supabase handles recording storage when configured. The AI worker processes queued recording/transcription/analysis jobs.

## Configuration

- Copy `.env.example` to `.env` for local work. Never commit `.env`, Firebase service-account JSON, API keys, LiveKit credentials, Supabase service-role keys, JWT secrets, or OpenAI keys.
- Production secrets belong in Render environment variables or GitHub Actions secrets.
- The frontend production API is passed at build time with `--dart-define=API_BASE_URL=...`.
- Do not silently fall back to SQLite in production; `DATABASE_URL` must be supplied by Render PostgreSQL.

## Local Commands

Windows one-click launcher:

```text
run_project.cmd
```

Manual services:

```text
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000

cd frontend
flutter pub get
flutter run -d chrome --dart-define=API_BASE_URL=http://localhost:8000/api/v1

cd ai_worker
python -m pip install -r requirements.txt
python -m ai_worker
```

Use `SETUP.md` for the complete clean-machine procedure. Use `DEPLOYMENT.md` and `render.yaml` for production deployment.

## Verification Rules

- Run `git diff --check` and relevant backend tests before committing.
- When Flutter is available, run `flutter analyze`, `flutter test`, and a production web build.
- Verify `GET /api/v1/health` and test an authenticated meeting create/join flow.
- Verify a meeting invite works with both the short code and the full `/#/join/<code>` link.
- Do not claim hosting is updated until the deployment workflow is successful and the hosted frontend is loaded against the production API.
- Do not claim transcription or recording is complete unless the worker, storage, and database paths have been exercised.

## Change Discipline

- Preserve existing user changes and migrations.
- Prefer small fixes in the owning module.
- Update `run_project.cmd`, `run_project.sh`, `.env.example`, and docs whenever startup or configuration changes.
- Review `git status` and the complete diff before pushing. Push only to the configured repository and never force-push.
