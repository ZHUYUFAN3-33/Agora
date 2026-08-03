# Multi-stage: build React SPA, then run Flask + gunicorn (same origin /api).

FROM node:22-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    AGORA_DATA_DIR=/data \
    AGORA_DB_PATH=/data/agora.db \
    AGORA_STATIC_DIR=/app/frontend/dist \
    FLASK_DEBUG=0

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY --from=frontend /frontend/dist /app/frontend/dist

RUN mkdir -p /data/logs /data/profiles /data/memory

EXPOSE 8080

# Single worker: chat_sessions is in-process memory. Long LLM turns need a high timeout.
CMD ["gunicorn", "-b", "0.0.0.0:8080", "-w", "1", "--threads", "4", "--timeout", "180", "--access-logfile", "-", "--error-logfile", "-", "app:app"]
