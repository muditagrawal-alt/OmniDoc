# OmniDoc in one container: the FastAPI server also serves the built web app on port 8000.
# Models: free hosted APIs (keys in .env, see .env.example) or a separate Ollama (OLLAMA_HOST).
# Data (library, indexes, uploads, model caches) lives in /data: mount a volume there.

# ---- 1. Web app --------------------------------------------------------------
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 2. Server ---------------------------------------------------------------
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OMNIDOC_DATA_DIR=/data \
    OMNIDOC_HOST=0.0.0.0 \
    OMNIDOC_PORT=8000 \
    HF_HOME=/data/cache/huggingface

# OCR (with Indian languages), audio extraction for transcripts, Pango for PDF reports.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-osd tesseract-ocr-eng tesseract-ocr-hin tesseract-ocr-mar tesseract-ocr-ben \
        tesseract-ocr-tam tesseract-ocr-tel tesseract-ocr-kan tesseract-ocr-guj tesseract-ocr-pan tesseract-ocr-mal \
        ffmpeg libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b fonts-dejavu-core fonts-noto-core curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements-deploy.txt .
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements-deploy.txt

COPY . .
COPY --from=web /web/dist /app/frontend/dist

RUN useradd --create-home --uid 1000 omnidoc && mkdir -p /data && chown -R omnidoc:omnidoc /data /app
USER omnidoc

EXPOSE 8000
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD curl -fs http://127.0.0.1:8000/api/health || exit 1
CMD ["python", "server.py"]
