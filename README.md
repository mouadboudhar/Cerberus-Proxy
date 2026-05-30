# Cerberus Proxy

Self-hosted security gateway for LLM applications.

Cerberus Proxy sits between your AI application and any LLM 
provider. It applies three deterministic security guards 
to every request, gives you full visibility through a 
dashboard, and runs entirely inside your own infrastructure.

## Quick Start

docker compose up

## Language Model Setup

The Input Guard detects non-English prompts and translates them
locally before running its pattern checks. After installation,
download the translation models:

    python scripts/download_models.py

Supported languages: English, French, Spanish, Arabic, German,
Portuguese, Italian, Dutch, Russian, Chinese, Japanese, Turkish.

Models are downloaded once and cached locally — approximately
100MB per language pair. No internet connection is required
after the initial download.

## Guards

- **Input Guard** — blocks prompt injection before forwarding
- **Output Guard** — redacts PII and secrets from responses  
- **Retrieval AuthZ** — enforces clearance-based RAG filtering

## Integration

One URL change in your application:

base_url = "http://your-cerberus_proxy/v1"

## Status

v0.1.0 — foundation in progress
