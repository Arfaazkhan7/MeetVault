FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libsndfile1 && rm -rf /var/lib/apt/lists/*
COPY requirements.lock ./requirements.lock
RUN pip install --no-cache-dir -r requirements.lock
COPY server.py ./server.py
RUN useradd --create-home speech
USER speech
ENV BIND_HOST=0.0.0.0 PORT=8090 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
EXPOSE 8090
CMD ["python", "server.py"]
