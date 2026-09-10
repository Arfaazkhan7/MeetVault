# PROJECT AUDIT

## 1. Current Architecture
MeetVault currently consists of three main components:
- **Backend**: FastAPI application with SQLAlchemy and PostgreSQL/SQLite (currently seems to use SQLite locally: `meetingdb.db` / `meetvault.db`). It contains routers for auth, companies, users, projects, meetings, recordings, cross_meeting analysis, etc.
- **Frontend**: A Flutter application (not React/Vite as typically assumed, but Flutter based on `pubspec.yaml`).
- **AI Worker**: A directory structure (`ai_worker/`) meant to handle transcription, diarization, summarization, embeddings, and RAG.

## 2. Existing Features
- User Auth & Companies models and basic endpoints exist.
- Meeting management endpoints (creating workspace meetings, personal meetings, joining).
- LiveKit token generation service is stubbed/available in `livekit_service.py`.
- Flutter frontend has screens for dashboard, meeting room, meetings list, etc.
- Storage service stub/implementations.

## 3. Broken Features
- **Meeting Creation Bug**: "Failed to start instant meeting: You are not a member of this company". This is likely due to the frontend not correctly distinguishing between personal and workspace modes, or the backend enforcing company membership on personal meetings due to incorrect API payload usage (`/companies/{company_id}/meetings` vs `/meetings/personal`).
- **LiveKit Integration**: There might be hardcoded URLs (like `wss://your-livekit-url`) in the `.env` / configuration that need actual values.
- **Meeting Room UI**: Needs to actually connect and render LiveKit participant video tiles rather than placeholders.

## 4. Missing Features
- **AI Worker implementation**: The `ai_worker` directory is entirely empty inside its subfolders. It lacks the actual pipeline for Transcription, Diarization, Analysis, Embeddings, and RAG.
- **Background Task System**: Proper orchestration for the AI Processing Pipeline (e.g., Celery, RQ, or FastAPI BackgroundTasks) triggering the `ai_worker`.
- **Recording to Storage Integration**: Egressing from LiveKit and saving the MP4/WAV to Supabase Storage, then dispatching the AI Job.
- **Admin System**: Proper system administration flow and role enforcement (System Admin vs Workspace Admin).
- **Cross-Meeting Intelligence**: The core feature needs to be fully implemented using embeddings and RAG spanning multiple meetings.

## 5. AI Worker Gaps
Currently, `ai_worker` has folders (`analysis/`, `core/`, `diarization/`, `embeddings/`, `rag/`, `tasks/`, `transcription/`) but no actual code implementations. Missing:
- Speech-to-Text implementation (e.g. Whisper).
- Speaker Diarization logic (e.g. Pyannote).
- LLM Prompts & Parsing for meeting analysis (topics, decisions, action items, speaker time analysis).
- Text Chunking & Embeddings generation.
- Vector search logic.

## 6. Database Gaps
The `backend/app/models/` directory contains a lot of the required schema (Meeting, TranscriptSegment, Task, Decision, Embedding, MeetingRecording, SpeakerMapping, etc.). Need to verify if relationships and migrations (Alembic) are fully configured and if any models are missing for background job tracking (e.g., `AIProcessingJob`).

## 7. API Gaps
The API has endpoints, but they need to be reviewed against the specific separation of Personal vs. Workspace logic, especially around RAG data retrieval (Tenant Isolation is critical) and ensuring RAG only searches within allowed scopes.

## 8. Frontend Gaps
- Distinguishing properly between Personal Login and Workspace Login visually and state-wise.
- Ensuring API calls for Personal meetings use the new `POST /api/v1/meetings/personal` route instead of the workspace route.
- Connecting the Flutter UI elements (like LiveKit video elements) using the `livekit_client` package correctly.
- Displaying real analysis (Speakers, Summaries, Action Items, Cross-meeting insights) fetched from the backend.

## 9. Security Gaps
- Need strict tenant isolation in all RAG and Retrieval endpoints (checking `company_id` and membership or `owner_id`).
- LiveKit API keys and Supabase Service Role keys must be strictly kept in the backend.

## 10. Dependency Gaps
- `backend/requirements.txt` needs to include background task managers (if any), vector DB drivers, or AI client libraries.
- `ai_worker/requirements.txt` is basically empty and needs the LLM, Audio Processing, and Vector DB libraries.

## Recommended Implementation Order (Phases)
As specified by the requirements, work should proceed incrementally:
1. PHASE 1: Repository audit (Completed - this document)
2. PHASE 2: Authentication and Personal/Workspace/Admin architecture
3. PHASE 3: Workspace/company membership authorization
4. PHASE 4: Meeting creation and invite code (Fixing the current bug)
5. PHASE 5: LiveKit room/token integration
6. PHASE 6: Meeting room UI
7. ... and so on up to PHASE 20.
