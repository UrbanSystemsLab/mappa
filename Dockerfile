# MAPPA API — container for Cloud Run (or any host).

# Stage 1: the Next.js frontend (frontend/), built to static files the API serves.
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend ./
RUN npm run build

# Stage 2: the API, which serves those files at / and the earlier page at /classic.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_DISABLE_TELEMETRY=1

WORKDIR /app

COPY requirements-api.txt .
# PyTorch for CPU only. The default Linux wheel brings the NVIDIA GPU libraries,
# several gigabytes this service never uses, and a larger image starts slower.
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install -r requirements-api.txt

# The multilingual embedding model, baked into the image.
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"

# Offline mode: the model is read from the copy baked in above, and the library
# never asks huggingface.co whether it is current - so the assistant does not
# depend on a third party being reachable, or on its rate limits.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

COPY core ./core
COPY api ./api
COPY frontend/classic ./frontend/classic
COPY --from=web /web/out ./frontend/out
COPY data ./data

# Cloud Run provides $PORT (defaults to 8080).
ENV PORT=8080
CMD exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT}
