FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app
ENV PYTHONPATH=/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

ARG REQUIREMENTS_FILE=requirements-render.txt
COPY requirements.txt requirements-render.txt ./
RUN pip install --no-cache-dir -r ${REQUIREMENTS_FILE}

COPY app ./app
COPY scripts ./scripts
COPY seed.py .
COPY alembic.ini .
COPY alembic ./alembic

ENV PORT=8080

# bootstrap_db creates the complete current ORM schema before optional historical
# migrations; running Alembic first breaks on a fresh Supabase database.
CMD ["sh", "-c", "python scripts/bootstrap_db.py && uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
