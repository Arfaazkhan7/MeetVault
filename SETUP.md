# MeetVault Local Setup

## Clone

```bash
git clone https://github.com/GOKUL5731/meetvault.git
cd meetvault
```

## Environment

Copy `.env.example` to `.env` and fill only your local values.

Required for normal local development:

```env
DATABASE_URL=postgresql://user:password@localhost:5432/meetingdb
JWT_SECRET=change_me
API_BASE_URL=http://localhost:8000/api/v1
```

For Google sign-in, also set the Firebase Web API key from Firebase Console:

```env
FIREBASE_API_KEY=your_firebase_web_api_key
```

Do not commit `.env`, service account JSON files, database passwords, JWT secrets, LiveKit secrets, or Supabase service-role keys.

For a hosted Supabase database, replace `DATABASE_URL` with the PostgreSQL URI from Supabase **Connect**. `SUPABASE_URL` is only the project API URL and cannot be used as `DATABASE_URL`.

## Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000/login
```

## Flutter Frontend

Install Flutter first, then run:

```bash
cd frontend
flutter pub get
flutter run -d chrome --dart-define=API_BASE_URL=http://localhost:8000/api/v1 --dart-define=FIREBASE_API_KEY=your_firebase_web_api_key
```

## AI Worker

Start Redis, then:

```bash
cd ai_worker
python -m pip install -r requirements.txt
celery -A tasks worker --loglevel=info
```

## One Command Launcher

From the repository root:

```bat
run_project.cmd
```

The launcher checks the project structure and starts the local services it can find.
