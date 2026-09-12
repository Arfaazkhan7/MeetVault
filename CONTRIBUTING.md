# Contributing

## Local Workflow

1. Create a branch from `main`.
2. Copy `.env.example` to `.env`.
3. Install backend and frontend dependencies.
4. Run backend tests before pushing.
5. Keep secrets out of commits.

## Backend Checks

```bash
cd backend
python -m pytest -q tests --ignore=tests/test_meeting.py
```

## Frontend Checks

```bash
cd frontend
flutter pub get
flutter analyze
flutter test
flutter build web --release --dart-define=API_BASE_URL=http://localhost:8000/api/v1
```

## Security Rules

Never commit:

- `.env`
- Firebase service account JSON
- JWT secrets
- database passwords
- LiveKit API secrets
- Supabase service-role keys
- OpenAI API keys
