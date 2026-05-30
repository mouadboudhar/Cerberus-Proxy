# Cerberus Proxy — Project Rules for Claude Code

## Product
Cerberus Proxy is a self-hosted reverse proxy security gateway
for LLM applications. It sits between customer AI apps
and LLM providers, applying deterministic security guards.

## Architecture
- cerberus_proxy/proxy/    FastAPI reverse proxy (the product)
- cerberus_proxy/guards/   Input, Output, Retrieval AuthZ guards
- cerberus_proxy/adapters/ OpenAI, Anthropic, Ollama, Mistral
- cerberus_proxy/auth/     API key validation
- cerberus_proxy/audit/    Event log + WebSocket broadcast
- dashboard/         React + Vite admin dashboard

## Rules
- Ask before adding any dependency not in pyproject.toml
- Ask before adding any npm package not in package.json
- Never modify test files unless explicitly asked
- Never touch .github/workflows/ without explicit ask
- Show diffs only for modifications, never full rewrites
- Propose approach before implementing for non-trivial tasks
- Conventional commits: feat/fix/security/refactor/docs/ci/chore
