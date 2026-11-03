# TouQA AI

AI QA agent for Spira and Jira: analyse requirements, generate reviewable test cases, draft incidents from notes and screenshots, and create them in Spira/Jira only after explicit human approval.

> Full setup, configuration and troubleshooting docs are coming in the README phase. This is the quick start.

## Layout

| Path | What |
|------|------|
| `backend/` | FastAPI + SQLAlchemy + Alembic API, Spira/Jira adapters, AI layer, background jobs |
| `frontend/` | React + TypeScript + Vite + Tailwind web interface |

## Run locally (demo mode, no external systems)

**Backend** (Python 3.12):

```bash
cd backend
python -m venv .venv && .venv/Scripts/activate   # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
cp ../.env.example .env                           # then set ENCRYPTION_KEY and ADMIN_PASSWORD locally
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Set `DEMO_MODE=true` in `.env` to use the simulated AI and block all external writes.

**Frontend** (Node 20+):

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 — proxies /api to localhost:8000
```

Sign in with `ADMIN_EMAIL` / `ADMIN_PASSWORD` from your `.env`, then choose **Load demo project**, or connect Spira under **Integrations**.

## Tests

```bash
cd backend && pytest          # 44 tests; live Spira tests are skipped unless configured
cd frontend && npm test       # Vitest
```

## Deploying the frontend (Vercel)

Set the Vercel project root to `frontend/` and set `VITE_API_URL` to the public backend URL. The backend must be hosted separately (container host + PostgreSQL), with `CORS_ORIGINS` including the Vercel domain and `COOKIE_SECURE=true`.
