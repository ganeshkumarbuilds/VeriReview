# VeriReview — AI Software Engineering Platform

VeriReview turns a plain-language task into a complete, verified software project.
Autonomous agents plan, architect, build, test, verify, and review the code —
then pause for your approval before fixing anything. The final build downloads
as a runnable ZIP with a live UI preview.

## Features

- **Agent pipeline** — Plan → Architect → Build → Test → Verify → Review → Complete,
  with an automatic fix-and-retest loop (up to 2 revision rounds).
- **Human approval gate** — verify + review results are shown first; the coding
  agent only fixes files after you click *Approve AI fix*. Skipping packages
  the build as-is.
- **Per-user workspaces** — every run is owned by its creator's account.
  Users only ever see their own history, stats, and downloads.
- **Runnable ZIP exports** — backend sources plus known-good scaffolding
  (`pom.xml` / `requirements.txt` / `package.json`), app config wired to env
  vars, `Dockerfile`, `docker-compose.yml` (app + Postgres), `.env` /
  `.env.example`, frontend Vite shell, and a standalone `preview.html`.
- **Live UI preview** — the generated React screen renders in-app (mocked API
  data) and inside the ZIP with zero setup.
- **Stack-aware generation** — Spring Boot, Django, Flask/FastAPI, Node/Express
  (or generic). Mention the stack in your task and it's auto-detected;
  otherwise enter it in the Tech stack field.
- **Per-run secrets** — Database URL and API keys are requested on every run
  and baked into the ZIP's `.env` (never exposed to other users or in
  `.env.example`).

## Tech Stack

| Layer    | Technology                                                              |
| -------- | ----------------------------------------------------------------------- |
| Backend  | Python, FastAPI, LangGraph (agent orchestration), SQLAlchemy, ChromaDB  |
| Frontend | React 18, Vite, React Router                                            |
| AI       | OpenRouter (free models) via LangChain                                  |
| Database | PostgreSQL                                                              |

## Project Structure

```text
backend/
  main.py            # FastAPI app: review pipeline, approval gate, export, preview
  app/
    graph.py         # agent nodes + phase orchestration (phase1 / fix loop / finalize)
    scaffold.py      # static ZIP scaffolding per stack (Docker, compose, env, README)
    database.py      # TaskRecord model + migrations
    rag.py           # local Spring/OWASP knowledge base (ChromaDB)
    config.py        # LLM client + model list
    state.py         # pipeline state schema
    file_utils.py    # multi-marker source-file parser (// FILE: and # FILE:)
  requirements.txt
  .env.example       # copy to .env and fill in (never commit .env)
frontend/
  src/
    pages/           # Dashboard (workspace + approval), Review, History, Auth
    components/      # ApprovalCard, PreviewModal, Navbar, Footer, ...
    utils/           # download, preview builder, tech-stack detection
    context/         # local demo auth
  .env.example       # VITE_API_URL (backend URL)
```

## Quickstart

### Prerequisites

- Python 3.11+ with a virtualenv, Node.js 18+, PostgreSQL 14+.

### 1. Backend

```powershell
cd backend
.\venv\Scripts\Activate.ps1   # or: python -m venv venv; venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env        # then set OPENROUTER_API_KEY and DATABASE_URL
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

### 2. Frontend

```powershell
cd frontend
npm install
copy .env.example .env        # VITE_API_URL=http://localhost:8000 for local dev
npm run dev                   # open http://localhost:5173
```

### 3. Run a task

1. Register / sign in.
2. On the Dashboard, describe the task (mention the stack, e.g. *“Django + React…”*,
   or fill the **Tech stack** field), add **Database URL** and **API keys** if the
   project needs them, and start the workflow.
3. When verify + review finish, an approval card shows every finding —
   **Approve AI fix** or **Finish without fixing**.
4. After the final re-verify, a clean *“No bugs or errors”* result unlocks the
   **Download ZIP** button; **Watch preview** renders the generated UI anytime.

## API Overview

| Method | Endpoint                  | Purpose                                              |
| ------ | ------------------------- | ---------------------------------------------------- |
| POST   | `/review/phase1`          | Build → test → verify → review, pause for approval   |
| GET    | `/review/pending/{id}`    | Resume data for a paused run                         |
| POST   | `/review/decide`          | Approve (fix + re-verify + package) or skip fixing   |
| POST   | `/review`                 | Legacy single-shot run (no approval gate)            |
| GET    | `/history`, `/stats`      | Per-user run history and totals (`?owner=` / header) |
| GET    | `/task/{id}`              | Full run details (owner-checked)                     |
| GET    | `/export/{id}`            | Runnable project ZIP (owner-checked)                 |
| GET    | `/preview/{id}`           | Standalone preview page (owner-checked)              |
| WS     | `/ws/review`              | Streaming run with in-band approval step             |

All user-scoped routes accept the identity via `?owner=` query or the
`X-User-Email` header. Calls without an owner receive empty results —
project data is never shared across accounts.

## Deployment

- **Backend** (Render / Railway / Fly, root `backend/`): build
  `pip install -r requirements.txt`, start
  `uvicorn main:app --host 0.0.0.0 --port $PORT`, with env vars
  `OPENROUTER_API_KEY` and `DATABASE_URL` (hosted Postgres).
- **Frontend** (Vercel / Netlify, root `frontend/`): build `npm run build`,
  output `dist`, env var `VITE_API_URL=https://<your-backend>` (rebuild after
  setting — Vite bakes it in at build time).

## Security Notes

- Never commit `.env` files — only `.env.example` templates are tracked.
- Rotate any API key or DB password that was ever committed or pasted into chat.
- Generated ZIPs embed the run's real secrets in `.env` (git-ignored inside the
  ZIP layout); share only `.env.example`.
- Auth is a local demo (localStorage); plug in real authentication before any
  public deployment.

## License

Proprietary — all rights reserved unless stated otherwise.
