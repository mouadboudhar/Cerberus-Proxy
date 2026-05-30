# syntax=docker/dockerfile:1

# ── Stage 1: install Python deps + package ──────────────────────────
FROM python:3.11-slim AS builder
WORKDIR /app
COPY pyproject.toml .
COPY cerberus_proxy/ ./cerberus_proxy/
# Installs cerberus_proxy and all runtime dependencies into /usr/local.
RUN pip install --no-cache-dir .

# ── Stage 2: runtime ────────────────────────────────────────────────
FROM python:3.11-slim
WORKDIR /app
# curl is needed by the compose healthcheck (GET /health).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
# Bring over the installed site-packages and console scripts from the builder.
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY cerberus_proxy/ ./cerberus_proxy/
EXPOSE 8000
CMD ["uvicorn", "cerberus_proxy.proxy.main:app", "--host", "0.0.0.0", "--port", "8000"]
