# Nexus AI

> A full-stack, multimodal AI research assistant — chat with your documents (including their images), run autonomous multi-agent research, and interact by voice.

[![CI](https://github.com/YOUR_USERNAME/nexus/actions/workflows/ci.yml/badge.svg)](https://github.com/YOUR_USERNAME/nexus/actions/workflows/ci.yml)

> ⚠️ **Status: in development.** Building in public, one part at a time. See [Roadmap](#roadmap).

---

## Features

Planned capabilities (built incrementally — see roadmap):

- **Multimodal RAG** — ingest PDFs, text, YouTube, and web pages *including embedded images and charts*, then chat with cited answers
- **Multi-agent research** — a LangGraph pipeline that searches the web, queries your knowledge base, and writes structured reports
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

## Project Structure

```
nexus/
├── backend/           # FastAPI application
│   ├── app/
│   │   ├── api/        # route handlers
│   │   ├── core/       # config, logging, security
│   │   ├── db/         # models, sessions
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
| Core AI | Ingestion, RAG, agents, multimodal | ⚪ Planned |
| Interface | Frontend foundation + features | ⚪ Planned |
| Production | Evaluation, testing, deployment | ⚪ Planned |

---

## Contributing / Workflow

This project follows **GitFlow** and **Conventional Commits**.

- Branch off `develop`: `git checkout -b feature/my-feature`
- Commit format: `feat(scope): description`
- Open a PR into `develop`; CI must pass before merge

---

## License

MIT
