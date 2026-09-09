# VeriReview

**An AI-powered Software Engineering Platform that transforms natural language prompts into production-ready, self-verified full-stack applications using a coordinated team of eleven AI agents.**

Built for **InnoGenesis Hackathon 5.0 — Agentic AI Track**, hosted by the School of Computer Studies, Dr. RVR & Dr. HS MIC College / NRI Institute of Technology.

---

## Overview

VeriReview goes a step beyond typical "prompt-to-app" generators. Most AI app builders hand you code and hope it's correct. VeriReview doesn't hope — it **verifies**.

Describe an application idea in plain English, and VeriReview coordinates a pipeline of specialized AI agents to:

- Turn your idea into a concrete product spec
- Design the system architecture and data model
- Generate real, compilable Spring Boot backend code
- **Review its own generated code** against Spring Boot and OWASP best practices
- **Independently re-verify every flagged issue**, rejecting false alarms before you ever see them
- **Automatically loop back and fix confirmed high-severity issues**, up to a capped number of revisions
- Build a matching React frontend once the backend is trustworthy
- Review test coverage, write documentation, and prepare a deployment config
- Package everything into a downloadable ZIP

The result: an agent pipeline where the **Reviewer and Verifier agents act as the quality gate**, not just a final formality — genuinely agentic, conditional, self-correcting behavior, not a fixed one-shot pipeline.

---

## Why This Is Different

Most AI code reviewers confidently flag issues that aren't real. VeriReview's Reviewer Agent proposes findings; its Verifier Agent independently re-examines each one against the code and knowledge base and **rejects anything that doesn't hold up** — before the developer ever sees it.

On an internal evaluation harness of 10 labeled Spring Boot code samples:

| Metric | Result |
|---|---|
| Actual bugs caught | 5 / 5 |
| False alarms raised | 0 |
| Bugs missed | 0 |
| Correctly identified clean code | 5 / 5 |

---


## The Agent Pipeline

Eleven specialized agents, one shared state, working in sequence — with a genuine conditional loop back to the Backend Engineer when the Verifier confirms high-severity issues.

| # | Agent | Role |
|---|---|---|
| 1 | **Product Manager** | Turns the raw idea into a precise, buildable product spec |
| 2 | **Architect** | Designs the system architecture, API endpoints, and page structure |
| 3 | **Database Engineer** | Designs the data model, entities, and relationships |
| 4 | **Backend Engineer** | Generates the complete Spring Boot backend (Entity, Repository, Service, Controller) |
| 5 | **Retriever (RAG)** | Retrieves relevant Spring Boot and OWASP knowledge for the review step |
| 6 | **Reviewer** *(main agent)* | Scans every generated file individually and flags potential issues |
| 7 | **Verifier** | Skeptically re-examines each flagged issue and confirms or rejects it |
| ↩ | **Revision Loop** | If high-severity issues are confirmed, sends targeted feedback back to the Backend Engineer (capped at 2 revisions) |
| 8 | **Frontend Engineer** | Builds a React UI once the backend is verified |
| 9 | **QA Engineer** | Reviews the app for test coverage gaps |
| 10 | **Documentation Engineer** | Writes the project README |
| 11 | **Deployment Engineer** | Generates a Dockerfile for deployment |

The Reviewer → Verifier → conditional revise-or-continue step is implemented as a genuine **LangGraph conditional edge** — a real decision point, not a scripted sequence.

---

## Features

- Multi-agent AI software engineering pipeline (11 agents)
- Natural language to full-stack application generation
- Self-verifying code review with false-positive rejection
- Autonomous revision loop — the Reviewer can send code back to the Backend Engineer
- RAG-grounded reviews (Spring Boot + OWASP knowledge base via ChromaDB)
- Live agent status streaming over WebSocket
- Per-file bug detection with confirmed/rejected verdicts
- Automatic Spring Boot backend generation
- Automatic React frontend generation
- Automatic README and Dockerfile generation
- PostgreSQL-backed project history and stats dashboard
- Downloadable ZIP export of the full generated project
- Internal evaluation harness with measurable accuracy metrics
- Automatic fallback across multiple free-tier LLMs for reliability

---

## Tech Stack

**Backend**
- Python, FastAPI
- LangGraph (agent orchestration)
- ChromaDB (RAG vector store)
- OpenRouter API (free-tier LLMs with automatic fallback)
- SQLAlchemy + PostgreSQL
- WebSockets (live agent streaming)

**Frontend**
- React + Vite
- Tailwind CSS
- React Router

**AI**
- OpenRouter free-tier models (automatic multi-model fallback for reliability)
- Retrieval-Augmented Generation grounded in Spring Boot and OWASP documentation

---

## Project Structure

```
verireview/
│
├── backend/
│   ├── app/
│   │   ├── config.py         # LLM client + free-model fallback list
│   │   ├── state.py          # LangGraph shared state schema
│   │   ├── graph.py          # 11-agent LangGraph pipeline
│   │   ├── rag.py            # ChromaDB retrieval (Spring/OWASP knowledge)
│   │   ├── file_utils.py     # Multi-file code parsing
│   │   └── database.py       # PostgreSQL models
│   ├── eval/
│   │   ├── cases.py          # Labeled evaluation test cases
│   │   └── run_eval.py       # Evaluation harness runner
│   ├── main.py                # FastAPI app + WebSocket endpoint
│   ├── requirements.txt
│   └── .env
│
├── frontend/
│   ├── src/
│   │   ├── components/       # Navbar, Footer, AgentStatusPanel
│   │   ├── context/          # Auth context
│   │   ├── pages/            # Home, Login, Register, Review, History, Dashboard
│   │   ├── App.jsx
│   │   └── index.css
│   └── package.json
│
├── screenshots/
└── README.md
```

Run the backend:

```bash
uvicorn main:app --reload
```

### Frontend setup

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` in your browser.

### Run the evaluation harness

```bash
cd backend
python eval/run_eval.py
```

---

## How Verification Works

1. The **Backend Engineer** generates multiple Java files (Entity, Repository, Service, Controller).
2. The **Reviewer** scans each file independently against retrieved Spring Boot and OWASP knowledge, producing candidate findings tagged by file, category, and severity.
3. The **Verifier** re-examines every candidate finding in isolation, asking: *is this a real, justified issue, or a false alarm?* Only confirmed findings survive.
4. If any confirmed finding is high severity and revision budget remains, the **Reviewer's decision routes the pipeline back to the Backend Engineer** with the specific issues to fix — a real conditional edge in the LangGraph, not a fixed script.
5. Once the backend passes verification (or the revision cap is reached), the **Frontend Engineer** builds the UI against the trustworthy backend.

---

## Roadmap

- [ ] GitHub PR import — review real production pull requests
- [ ] Automated test generation and execution (self-verifying via real test runs)
- [ ] Multiple LLM provider selection in-app
- [ ] Team collaboration and shared project workspaces
- [ ] One-click cloud deployment
- [ ] CI/CD pipeline generation
- [ ] Project versioning and diff comparison across generations

---

## Hackathon

This project was built for **InnoGenesis Hackathon 5.0**, Agentic AI Track, organized by the School of Computer Studies, Dr. RVR & Dr. HS MIC College (Deemed to be University), held on 7th–8th August 2026.

## Developer

**Ch. Ganesh Kumar**
Java Full-Stack Developer
[github.com/ganeshkumarbuilds](https://github.com/ganeshkumarbuilds)

## License

This project was developed for InnoGenesis Hackathon 5.0.