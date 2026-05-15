# syntax=docker/dockerfile:1.7
# Research Agent — FastAPI + Mongo + vendored frontend.
# uv is used for fast, lockfile-pinned installs from pyproject.toml / uv.lock.

ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# libgomp1 is required by hdbscan / scikit-learn / umap at import time.
# curl is used by the HEALTHCHECK below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5.20 /uv /usr/local/bin/uv

WORKDIR /app

# Cache layer: install deps before copying source so code edits don't bust it.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY frontend ./frontend
COPY scripts ./scripts
COPY data ./data

RUN useradd --uid 1001 --create-home --shell /bin/bash app \
    && chown -R app:app /app /opt/venv
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl --fail --silent --show-error http://localhost:8000/ > /dev/null || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
