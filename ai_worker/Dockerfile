FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY backend/requirements-render.txt ./backend-requirements.txt
COPY ai_worker/requirements.txt ./ai-worker-requirements.txt
RUN pip install --no-cache-dir -r backend-requirements.txt -r ai-worker-requirements.txt
COPY backend/app ./app
COPY ai_worker ./ai_worker

CMD ["python", "-m", "ai_worker"]
