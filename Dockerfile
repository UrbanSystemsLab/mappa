# MAPPA API — container for Cloud Run (or any host).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_DISABLE_TELEMETRY=1

WORKDIR /app

COPY requirements-api.txt .
RUN pip install -r requirements-api.txt

# Pre-download the multilingual embedding model so cold starts don't wait on it.
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"

COPY api ./api
COPY frontend ./frontend
COPY data ./data

# Cloud Run provides $PORT (defaults to 8080).
ENV PORT=8080
CMD exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT}
