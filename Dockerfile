# syntax=docker/dockerfile:1.7
#
# Thicket: one container serving the API (/api/v1) and the built frontend (/).
#
#   docker build -t thicket:local .
#   docker run --rm -p 8000:8000 -v thicket-data:/data thicket:local
#
# One uvicorn worker on purpose: BirdNET loads once per worker process (about
# 300 MB), and analyses run on a bounded thread pool (WORKER_CONCURRENCY).

ARG PYTHON_VERSION=3.11
ARG NODE_VERSION=22

# ---------------------------------------------------------------- frontend
FROM node:${NODE_VERSION}-slim AS frontend
WORKDIR /app
COPY shared/ ./shared/
COPY frontend/ ./frontend/
WORKDIR /app/frontend
# Builds frontend/dist when the frontend exists; otherwise leaves an empty dist.
RUN if [ -f package.json ]; then \
      if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; else npm install --no-audit --no-fund; fi \
      && npm run build; \
    else \
      mkdir -p dist; \
    fi

# ------------------------------------------------------------ python build
FROM python:${PYTHON_VERSION}-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /src/backend
COPY backend/pyproject.toml backend/README.md ./
COPY backend/thicket ./thicket
RUN pip install --upgrade pip && pip install ".[birdnet]"

# ----------------------------------------------------------------- runtime
FROM python:${PYTHON_VERSION}-slim AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin thicket

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENVIRONMENT=production \
    THICKET_DATA_DIR=/data \
    THICKET_CACHE_DIR=/opt/thicket-cache \
    SERVE_FRONTEND_DIR=/app/frontend/dist \
    FORWARDED_ALLOW_IPS=127.0.0.1

COPY --from=builder /opt/venv /opt/venv

# Bake the dual-output BirdNET model (logits + embeddings) into the image so
# the first start does not rewrite it and the cache can be read-only.
RUN python -c "from thicket.models.birdnet_runtime import BirdNETRuntime; BirdNETRuntime().load()" \
    && chmod -R a+rX /opt/thicket-cache

COPY --from=frontend /app/frontend/dist /app/frontend/dist

RUN mkdir -p /data && chown thicket:thicket /data
VOLUME ["/data"]

USER thicket
WORKDIR /app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "thicket.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--no-access-log", "--timeout-keep-alive", "5"]
