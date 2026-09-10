# AI-Based Smart Meeting Memory and Management System
## Architecture Overview

### Components

1. **Frontend**: Flutter application (Web & Mobile).
2. **Backend**: FastAPI (Python) serving as the main REST API.
3. **Database**: PostgreSQL with pgvector for structured data, metadata, and embeddings.
4. **Cache & Queue**: Redis + Celery (or equivalent) for background jobs.
5. **Storage**: Amazon S3 (or local equivalent) for storing raw recordings, PDFs, PPTs, and generated artifacts.
6. **Real-time Communication**: LiveKit for WebRTC SFU infrastructure.
7. **AI Workers**:
    - **Speech-to-Text**: Whisper model.
    - **Diarization**: Pyannote.audio.
    - **NLP/LLM**: Processing for topics, decisions, actions, summary.
    - **Embeddings**: Generation and vectorization into pgvector.

### Data Flow

```mermaid
graph TD
    A[Flutter Client] -->|REST / WebSockets| B(FastAPI Backend)
    A -->|WebRTC| C(LiveKit Server)
    B -->|Metadata & Vector Queries| D[(PostgreSQL + pgvector)]
    B -->|Queue Jobs| E(Redis Job Queue)
    E --> F[AI Background Workers]
    F -->|Whisper Transcription| G(Audio Processing)
    F -->|Pyannote Diarization| G
    F -->|LLM Extraction| H(NLP Processing)
    F -->|Storage| I[(Amazon S3)]
    B -->|Pre-signed URLs| I
```
