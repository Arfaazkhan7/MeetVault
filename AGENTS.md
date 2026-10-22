# MeetVault Engineering Handoff

Verified orientation for future agents. Always inspect the current `main` branch, `git status`, and the owning implementation before editing. This file never replaces reading the code.

## Canonical Project

- Active backend: `cloudflare_native/src/index.js` (native JavaScript Worker).
  Read `cloudflare_native/README.md` before deploying. The old Python Worker
  exceeded Free CPU limits; do not redeploy it over the native API.
- Hosted browser code: `web/` plus `web/native-client.js`; Firebase deploys these
  files. Native tests use `cd cloudflare_native && npm ci && npm test`.
- Speaker attribution is manual/unverified by default. Paid diarization is off.
  Vault answers must come from authorized saved evidence, never sample text.
- The organization translation pilot is in `cloudflare_native/src/translation.js`
  and `web/translation-client.js`. Read `ORGANIZATION_TRANSLATION.md` first.
  It uses opt-in microphone capture and bounded shared AI; standard shared
  speech requires the separate `translation_speech/` host and private key.

- Repository: https://github.com/GOKUL5731/meetvault
- Remote: `origin`; primary branch: `main`
- Production frontend: https://ai-meet-f8fd0.web.app
- Production API target: https://meetvault-api-candidate.aeris-cloud.workers.dev/api/v1

Never commit `.env`, passwords, API keys, Firebase service-account JSON, LiveKit credentials, Supabase service-role keys, OpenAI keys, local databases, build output, or virtual environments.

## Product

MeetVault is a meeting intelligence application supporting personal and organization accounts, Firebase Email/Password and Google authentication, meeting creation, invite codes/links, LiveKit video rooms, attendance duration, recording storage, transcripts, diarization, summaries, topics, decisions, tasks, search, RAG, projects, companies, and administration.

## Repository Map

```text
backend/                 FastAPI API, SQLAlchemy, Alembic, tests
backend/app/api/v1/      HTTP route modules
backend/app/services/    Business logic and integrations
backend/app/models/      SQLAlchemy models
backend/app/schemas/     Pydantic contracts
backend/scripts/         Production database bootstrap
frontend/                Flutter web application
frontend/lib/core/       Theme, routing, auth, API client, shared shell
frontend/lib/features/   Auth, dashboard, meetings, room, AI, admin, settings
ai_worker/               Database-queue transcription/analysis worker
docker/                  Local Docker Compose files
.github/workflows/       Firebase Hosting deployment
render.yaml              Render PostgreSQL, API, and worker blueprint
firebase.json            Firebase Hosting configuration
run_project.cmd          Windows one-click launcher
run_project.sh           Unix-like launcher, when present
SETUP.md                 Local setup; DEPLOYMENT.md production setup
```

## Runtime Contracts

1. Firebase authenticates the browser. The frontend stores the application token through `ApiService` and sends `Authorization: Bearer <token>` to protected API routes.
2. Flutter receives `API_BASE_URL` at build time with `--dart-define`. Local development uses `http://localhost:8000/api/v1`; hosted default is `https://meetvault-api-candidate.aeris-cloud.workers.dev/api/v1`.
3. Meeting creation returns a public id and `invite_code` such as `MTG-XXXXXX`.
4. `POST /api/v1/meetings/join` with `{ "invite_code": "MTG-..." }` creates or reuses the participant and returns `meeting_id`, `room_name`, `livekit_url`, `token`, and participant data.
5. `MeetingRoomScreen` uses that LiveKit token, or requests one from `/meetings/{meeting_id}/room/connect` for direct entry.
6. Attendance timing is recorded through `/meetings/{meeting_id}/room/join` and `/room/leave`. Preserve this path because duration analytics and transcript workflows depend on it.
7. LiveKit supplies real-time media. It does not persist application transcripts. Recording/storage and AI processing are separate paths.

## Frontend Notes

- `frontend/lib/core/navigation/app_router.dart` handles normal routes and `/#/join/<code>` links.
- `join_meeting_screen.dart` accepts a short code or a pasted full invite URL.
- `meeting_details_screen.dart` provides copy-code and copy-link actions.
- `meeting_room_screen.dart` is responsive, records attendance, and allows Leave/Back even if the API attendance call fails.
- `dashboard_screen.dart` has a desktop layout and a compact mobile layout below 820px. Keep callbacks connected to real API/navigation behavior; do not replace live metrics with placeholders.
- `EnterpriseScaffold` provides desktop navigation and drawer/bottom navigation on smaller screens.

## Backend and Data

- Startup: `backend/app/main.py`.
- Config/session: `backend/app/core/config.py` and `backend/app/db/session.py`.
- Production requires `DATABASE_URL` and must not silently fall back to SQLite.
- Render startup runs `backend/scripts/bootstrap_db.py` before Uvicorn.
- Migrations are in `backend/alembic/versions/` and cover meetings, recordings, transcript fields, diarization, analysis, and AI jobs.
- Health endpoint: `GET /api/v1/health`.
- API dependencies: `backend/requirements.txt`; Render dependencies: `backend/requirements-render.txt`.
- Worker dependencies: `ai_worker/requirements.txt`.

## Configuration

Copy `.env.example` to `.env`. Required deployment values include `DATABASE_URL`, `JWT_SECRET`, `BACKEND_CORS_ORIGINS`, frontend/API URLs, Firebase browser and backend verification config, `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, Supabase URL/service key/bucket, and the configured LLM key.

The Upstash REST Python snippet is not a Redis protocol URL for this worker. Redis mode requires `redis://` or `rediss://`; the current Render blueprint uses the database queue.

## Local Run

Preferred Windows entry point:

```text
run_project.cmd
```

It locates its own directory, checks Python, creates/repairs `backend/venv`, installs requirements, creates `backend/.env` from the safe template if needed, starts Uvicorn on port 8000, waits for `/api/v1/health`, and serves a local Flutter web build on port 3000 when Flutter/build output exists. Without Flutter or `frontend/build/web`, it opens the published frontend and reports that local frontend serving was skipped.

Manual commands:

```powershell
cd backend
python -m venv venv
venv\Scripts\python -m pip install -r requirements.txt
venv\Scripts\python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

cd frontend
flutter pub get
flutter run -d chrome --dart-define=API_BASE_URL=http://localhost:8000/api/v1

cd ai_worker
python -m pip install -r requirements.txt
python -m ai_worker
```

## Production Deployment

### Cloudflare migration candidate

- `cloudflare_backend/` stages `backend/app` and `backend/worker.py` for Python Workers.
- Read `CLOUDFLARE_BACKEND_MIGRATION.md` before changing hosts. This is a candidate,
  not a verified production deployment or proof that every endpoint fits Workers Free.
- Workers use Hyperdrive/pg8000 and delegate password bcrypt to existing PostgreSQL
  pgcrypto. Keep the SHA-256/base64 prehash and cost factor 12.
- New Worker document uploads require a private bucket; old local binaries must
  be copied before Render is retired.
- Firebase serves `web/` via `firebase.json`. Its deployment workflow injects
  the Cloudflare API URL. Verify the actual workflow run and hosted output.
- The user authorized live cutover on 2026-10-21 after Firebase token exchange,
  profile, workspace, project, and meeting-list checks returned 200. The AI
  worker callback now targets Cloudflare. Both Supabase buckets are private;
  no active document records needed copying at cutover. File roundtrip, two-user
  media, AI-job completion and workload CPU checks still require live validation.
- Retain Render resources until those checks and backups are complete. Do not
  interpret a passing health response as proof that every feature works.

### Existing Render deployment

- `render.yaml` defines Render PostgreSQL, `meetvault-api`, and `meetvault-ai-worker`. Secrets marked `sync: false` are entered in Render only.
- API image: `backend/Dockerfile`; worker image: `ai_worker/Dockerfile`.
- `.github/workflows/deploy-firebase-hosting.yml` runs on pushes to `main` or manual dispatch. It installs Flutter dependencies, analyzes/tests, builds with the production API URL, and deploys Firebase Hosting.
- Required GitHub secrets include `FIREBASE_API_KEY` and `FIREBASE_SERVICE_ACCOUNT_AI_MEET_F8FD0`.
- A GitHub push does not prove Firebase was deployed. Inspect the workflow run and load the hosted URL.
- A blueprint worker does not prove the worker exists or processes jobs. Verify it in Render and observe a database job move through processing.

## Current Build and Verification State

- Use `git log -1 --oneline` for the authoritative current source commit.
- Recent source includes responsive dashboard work, reliable room exit, invite code/link sharing, and pasted-link join parsing.
- Backend source compilation and `git diff --check` have been used as focused checks; verify again after edits.
- The production API health endpoint has returned HTTP 200.
- Flutter analysis, tests, and release build require the Flutter SDK. If `flutter` is unavailable locally, GitHub Actions is the authoritative frontend build.
- Do not claim the hosted UI, AI worker, recording, or transcription pipeline is complete without direct deployment/runtime evidence.

## Verification Before Completion

```powershell
git diff --check
python -m compileall -q backend/app
cd backend; python -m pytest -q
cd ..\frontend; flutter analyze --no-fatal-infos --no-fatal-warnings; flutter test; flutter build web --release --dart-define=API_BASE_URL=https://meetvault-api.onrender.com/api/v1
```

For meeting changes, verify two authenticated users can use the same code, a full `/#/join/<code>` link opens the join screen, both receive LiveKit tokens for the same room, Leave/Back returns to dashboard, timestamps produce non-negative duration, and configured recording/AI jobs are consumed.

## Change Discipline

- Inspect before modifying and preserve unrelated user changes.
- Use `apply_patch` for manual edits; keep changes in the owning module.
- Update launchers/docs when startup, ports, dependencies, or environment variables change.
- Review `git status`, the relevant complete diff, and secret exclusion before committing.
- Commit meaningful changes and push only to `origin`/`main` when authorized. Never force-push or rewrite history.
- Never claim deployment or real-time/AI behavior without evidence.

