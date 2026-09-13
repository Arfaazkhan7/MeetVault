FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

ARG REQUIREMENTS_FILE=requirements-render.txt
COPY requirements.txt requirements-render.txt ./
RUN pip install --no-cache-dir -r ${REQUIREMENTS_FILE}

COPY app ./app
COPY alembic.ini .
COPY alembic ./alembic

ENV PORT=8080

CMD ["sh", "-c", "python -c 'from app.db.session import engine; from app.models.base import Base; Base.metadata.create_all(bind=engine)' && alembic stamp head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
