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

# Still a single worker: chat_sessions is in-process memory, so a second worker would
# lose rooms. Threads are what scale here — one /api/message spends ~90 s blocked on
# sequential OpenAI calls, releasing the GIL the whole time, so a thread costs almost no
# CPU while it waits. 20 threads carries ~28 concurrent participants; measured headroom
# on shared-cpu-1x was 73 MB RSS of 1 GB, so memory is not the limit.
CMD ["gunicorn", "-b", "0.0.0.0:8080", "-w", "1", "--threads", "20", "--timeout", "180", "--access-logfile", "-", "--error-logfile", "-", "app:app"]
