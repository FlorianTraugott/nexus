# Nexus AI

> A full-stack, multimodal AI research assistant — chat with your documents (including their images), run autonomous multi-agent research, and interact by voice.

[![CI](https://github.com/YOUR_USERNAME/nexus/actions/workflows/ci.yml/badge.svg)](https://github.com/YOUR_USERNAME/nexus/actions/workflows/ci.yml)

> ⚠️ **Status: in development.** Building in public, one part at a time. See [Roadmap](#roadmap).

---

## Features

Planned capabilities (built incrementally — see roadmap):

- **Multimodal RAG** — ingest PDFs, text, YouTube, and web pages *including embedded images and charts*, then chat with cited answers
- **Multi-agent research** — a LangGraph pipeline that searches the web, queries your knowledge base, and writes structured reports
- **MCP tools** — expose web search and knowledge-base retrieval over the Model Context Protocol, so any MCP client (Claude Desktop, IDE assistants) can call them
- **Voice + vision interface** — speak to it (Whisper), hear it back (TTS), and ask questions about images in your documents
- **Production-grade** — JWT auth, evaluation harness, observability, full test coverage, CI/CD

---

## Tech Stack

| Layer | Tools |
|---|---|
| Backend | FastAPI, SQLAlchemy (async), PostgreSQL, ChromaDB |
| AI | LangChain, LangGraph, OpenAI GPT-4o, Whisper |
| Frontend | Next.js 14, TypeScript, shadcn/ui |
| Infra | Docker, GitHub Actions, Railway |

---

## Getting Started

### Prerequisites

- Docker and Docker Compose
- (Optional, for local non-Docker dev) Python 3.12

### Installation

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/nexus.git
cd nexus

# 2. Create your environment file
cp .env.example .env
# Then edit .env and fill in values (database password, API keys as needed)

# 3. Start the stack
make up
```

The backend will be available at:

- API root: http://localhost:8000
- Health check: http://localhost:8000/health
- Interactive API docs: http://localhost:8000/docs

### Common Commands

```bash
make help      # list all commands
make up        # start the dev stack
make down      # stop it
make lint      # run ruff, black, mypy
make format    # auto-format code
make test      # run the test suite
make hooks     # install pre-commit git hooks
```

---

## MCP server

The backend doubles as an [MCP](https://modelcontextprotocol.io) server, exposing two tools — `web_search` and `kb_search` (owner-scoped retrieval over your own corpus) — to any MCP client over stdio.

**Run it directly:**

```bash
cd backend
python -m app.mcp.server      # or: python -m app.mcp
```

**Register it with a client** (e.g. Claude Code / Claude Desktop) via an `.mcp.json` at the repo root. That file is git-ignored — it's local, machine-specific config — so copy this template and fill in your values:

```json
{
  "mcpServers": {
    "nexus": {
      "command": "/path/to/nexus/venv/bin/python",
      "args": ["-m", "app.mcp.server"],
      "cwd": "/path/to/nexus/backend",
      "env": {
        "NEXUS_MCP_USER_ID": "<your-user-uuid>"
      }
    }
  }
}
```

- **Secrets stay in `backend/.env`.** The server runs with `cwd: backend`, so it loads `POSTGRES_*`, `OPENAI_API_KEY`, etc. from there — keep them out of `.mcp.json`.
- **`NEXUS_MCP_USER_ID` is required for `kb_search`** and must be set in this `env` block (it's read from the process environment, not `.env`). It scopes retrieval to one user; an unset, malformed, or inactive value makes `kb_search` fail loudly rather than search across users.
- `web_search` needs no identity; with the default offline search provider it returns empty results until a real provider is configured.

To confirm `kb_search` end-to-end against your data, register the server with a real user id and a populated corpus, then ask the client to search it — the offline test suite covers tool discovery and a `web_search` round-trip, but not a live `kb_search` query.

---

## Project Structure

```
nexus/
├── backend/           # FastAPI application
│   ├── app/
│   │   ├── api/        # route handlers
│   │   ├── core/       # config, logging, security
│   │   ├── db/         # models, sessions
│   │   ├── mcp/        # MCP server: tools exposed over the Model Context Protocol
│   │   ├── services/   # business logic (RAG, agents, voice)
│   │   └── main.py     # entry point
│   ├── evals/          # evaluation datasets + runners
│   └── tests/          # unit + integration tests
├── frontend/          # Next.js app (added in Part 8)
├── docker-compose.yml
└── Makefile
```

---

## Roadmap

| Phase | Parts | Status |
|---|---|---|
| Foundation | Project setup, backend, auth | 🟡 In progress |
| Core AI | Ingestion, RAG, agents, multimodal | 🟡 In progress |
| Interface | Frontend foundation + features | ⚪ Planned |
| Production | Evaluation, testing, deployment | ⚪ Planned |

**Recently shipped:** multimodal ingestion, RAG query, the multi-agent research pipeline, and an **MCP server** exposing `web_search` + `kb_search` over stdio.

---

## Contributing / Workflow

This project follows **GitFlow** and **Conventional Commits**.

- Branch off `develop`: `git checkout -b feature/my-feature`
- Commit format: `feat(scope): description`
- Open a PR into `develop`; CI must pass before merge

---

## License

MIT
