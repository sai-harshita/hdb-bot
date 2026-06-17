# HDB Bot

`hdb-bot` is a production-style POC chatbot for Singapore HDB information. It combines local-model RAG, NeMo Guardrails, JWT auth, OpenTelemetry, MCP, NGINX, Docker Compose, CI/CD, and an optional Azure Functions agent.

This repo is intentionally simple:

- `app/`: FastAPI chatbot API, JWT auth, NeMo Guardrails, telemetry
- `ingest/`: pulls official HDB content into Qdrant
- `mcp/`: MCP server exposing HDB search tools
- `agent/`: optional Azure Functions eligibility/grants endpoint
- `nginx/`: reverse proxy and rate limiting
- `observability/`: OTel Collector, Tempo, Prometheus, Loki, Grafana
- `eval/`: RAGAS and garak evaluation harness

## Recommended Build Workflow

Use `Cursor` as the primary editor and chat surface for step-by-step vibe coding. Use `Codex` for repo scaffolding, review, refactors, and verification. This combination is pragmatic:

- `Cursor`: best for seeing files, diffs, and runtime errors while learning
- `Codex`: best for larger autonomous implementation passes and repo QA

## Stack

- `FastAPI` + `Uvicorn`
- `Ollama` with `qwen2.5:3b` and `nomic-embed-text`
- `Qdrant` for vector search
- `Postgres` for auth and chat logs
- `NeMo Guardrails` for harmful-content, jailbreak, topic, grounding, and agent-call controls
- `Presidio` for PII masking
- `NGINX` for reverse proxy and rate limiting
- `OpenTelemetry` + `Tempo` + `Prometheus` + `Loki` + `Grafana`
- `FastMCP` for external tool access
- `Azure Functions` for optional eligibility/grant logic
- `GitHub Actions` + `Trivy` for CI/CD and security scanning

## Repo Deliverables

- [HDB_Chatbot_VibeCoding_Spec.md](./HDB_Chatbot_VibeCoding_Spec.md)
- [HDB_Chatbot_Walkthrough.docx](./HDB_Chatbot_Walkthrough.docx)
- [docker-compose.yml](./docker-compose.yml)

## Quick Start

1. Copy `.env.example` to `.env`.
2. Set a real `JWT_SECRET`.
3. Start the core infra:

```powershell
docker compose up -d ollama qdrant postgres
docker compose exec ollama ollama pull qwen2.5:3b
docker compose exec ollama ollama pull nomic-embed-text
```

4. Ingest official HDB sources:

```powershell
docker compose run --rm ingest
```

5. Start the full stack:

```powershell
docker compose up -d --build
```

6. Get a token and test:

```powershell
$token = (Invoke-RestMethod -Method Post -Uri http://localhost/auth/token -Body @{
  username = "demo"
  password = "demo12345"
}).access_token

Invoke-RestMethod -Method Post -Uri http://localhost/chat `
  -Headers @{ Authorization = "Bearer $token" } `
  -ContentType "application/json" `
  -Body '{"message":"Who is eligible to buy an HDB flat as a family?"}'
```

## Production-Style POC Notes

- Keep retrieval limited to official HDB domains and curated PDFs.
- Keep eligibility/grant amounts config-driven and refresh them from official HDB pages before demos.
- Treat the Azure Function as optional. The local stack still demonstrates LLMOps and guardrails without it.
- Use Cloudflare Tunnel or a VM reverse proxy only after local validation is stable.

## GitHub Setup

This workspace is prepared for `https://github.com/sai-harshita`.

Local repo bootstrap:

```powershell
git init
git add -A
git commit -m "Initial scaffold for hdb-bot"
```

Create and push the public repo with GitHub CLI:

```powershell
gh repo create sai-harshita/hdb-bot --public --source . --remote origin --push
```

## Next Steps

1. Replace placeholder values in `.env`.
2. Run the ingest pipeline and verify data in Qdrant.
3. Bring the app up and test `/auth/token`, `/chat`, and `/docs`.
4. Add the Azure Function URL only after the agent is deployed.
5. Use the spec and walkthrough artifacts as the implementation guide.
