# MeetVault Deployment

## GitHub

Push all code to `main`:

```bash
git add .
git commit -m "Configure Firebase authentication and hosting"
git push origin main
```

## Firebase Hosting

This repository includes:

- `firebase.json`
- `.firebaserc`
- `.github/workflows/deploy-firebase-hosting.yml`

Firebase project:

```text
ai-meet-f8fd0
```

Enable these in Firebase Console:

- Authentication
- Google provider
- Authorized domains for localhost and your deployed Firebase Hosting domain

Set these GitHub repository secrets:

```text
FIREBASE_API_KEY
FIREBASE_SERVICE_ACCOUNT_AI_MEET_F8FD0
```

Run the workflow named `Deploy Flutter Web to Firebase Hosting` and provide the production backend API URL, for example:

```text
https://YOUR_CLOUD_RUN_BACKEND_URL/api/v1
```

The workflow builds Flutter web with `API_BASE_URL` and deploys `frontend/build/web`.

## FastAPI Backend

Build and deploy `backend/Dockerfile` to Google Cloud Run or another container host.

Required production environment variables:

```env
ENVIRONMENT=production
DATABASE_URL=your_postgres_url
JWT_SECRET=your_long_random_secret
BACKEND_CORS_ORIGINS=https://ai-meet-f8fd0.web.app,https://ai-meet-f8fd0.firebaseapp.com
FIREBASE_PROJECT_ID=ai-meet-f8fd0
LIVEKIT_URL=wss://your-livekit-url
LIVEKIT_API_KEY=your_livekit_api_key
LIVEKIT_API_SECRET=your_livekit_api_secret
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key
SUPABASE_STORAGE_BUCKET=meeting-recordings
OPENAI_API_KEY=your_openai_key
```

On Google Cloud Run, prefer Application Default Credentials for Firebase Admin. For local backend Firebase verification, set `FIREBASE_CREDENTIALS_PATH` to a local service account JSON path. Never commit that JSON file.

## AI Worker

Deploy the AI worker as a private worker service with the same Redis/database/storage/AI provider environment variables. It should not be publicly exposed.

## LiveKit

Keep `LIVEKIT_API_SECRET` only in backend and worker environments. The frontend should request meeting tokens from FastAPI.

## Supabase

Keep `SUPABASE_SERVICE_ROLE_KEY` only in backend and worker environments. Browser code must never receive the service-role key.

## Verification

Before calling production complete, verify:

- Firebase Hosting URL opens the Flutter app
- `/login` and `/dashboard` route refreshes do not 404
- Email/password login works
- Google login returns a MeetVault token from FastAPI
- Workspace login still requires valid workspace membership
- Backend health endpoint returns 200
- Frontend network calls point to the production backend, not localhost
