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

# The model being in the image was not enough. At runtime the library still asked
# huggingface.co whether its copy was current, and on 2026-10-03 Hugging Face
# answered 429 to our unauthenticated request. The retry policy is to sleep 222
# seconds, so a question sat unanswered for the best part of four minutes while
# the model it needed was already on disk a few inches away.
#
# Offline mode uses the baked cache and never opens a socket. The model is
# pinned by the image, which is where a dependency of this kind belongs: the
# assistant must not stop working because a third party is having a busy day.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

COPY core ./core
COPY api ./api
COPY frontend ./frontend
COPY data ./data

# Cloud Run provides $PORT (defaults to 8080).
ENV PORT=8080
CMD exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT}
