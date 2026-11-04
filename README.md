# TouQA AI

An AI QA agent for **Spira** and **Jira**. It imports requirements, test cases, test sets, incidents and releases from Spira. AI analyses requirements, generates test cases you can review, and drafts incidents from your notes and screenshots. Nothing is created in Spira or Jira until a person reviews the exact payload and approves it.

| Path | What |
|------|------|
| `backend/` | FastAPI, SQLAlchemy, Alembic, PostgreSQL. Spira/Jira adapters, AI layer, background jobs, audit log |
| `frontend/` | React, TypeScript, Vite, Tailwind, TanStack Query |
| `docker-compose.yml` | PostgreSQL + backend + frontend for local use |
| `render.yaml` | Render blueprint for hosting the backend and its database |

---

## 1. Quick start with Docker

```bash
cp .env.example .env
# Edit .env locally: set ENCRYPTION_KEY and ADMIN_PASSWORD (see section 3)
docker compose up --build
```

Open http://localhost:8080 and sign in with `ADMIN_EMAIL` / `ADMIN_PASSWORD`. Then choose **Load demo project**, or go to **Integrations** to connect Spira.

## 2. Local development without Docker

**Requirements:** Python 3.12, Node 20+, and PostgreSQL (`docker compose up db` works). SQLite also works for quick trials, e.g. `DATABASE_URL=sqlite:///./touqa.db`.

```bash
# Backend
cd backend
python -m venv .venv
.venv/Scripts/activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
cp ../.env.example .env           # fill in locally
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Frontend (second terminal)
cd frontend
npm install
npm run dev                       # http://localhost:5173, proxies /api to :8000
```

## 3. Configuration

Configuration lives in `.env` (backend) and in the app's **Integrations** screen. **Never commit `.env`**, and never paste keys into chats or tickets.

| Setting | Purpose |
|---|---|
| `ENCRYPTION_KEY` | Encrypts the stored Spira/Jira credentials. Generate it with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. If you lose it, stored credentials must be re-entered. |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | The admin account, created on first start |
| `DATABASE_URL` | PostgreSQL URL. `postgres://` URLs from hosting providers are accepted. |
| `AI_PROVIDER`, `AI_MODEL` | `anthropic` (default `claude-opus-5-5`), `openai_compatible`, `local` (Ollama/LM Studio), or `simulated` |
| `ANTHROPIC_API_KEY` / `AI_API_KEY` | Key for the AI provider. Read from the environment only; never entered in the browser. |
| `DEMO_MODE` | `true` uses synthetic data and simulated AI, and blocks all external writes |
| `COOKIE_SECURE` | Set to `true` whenever the app is served over HTTPS |
| `COOKIE_SAMESITE` | Keep `lax`. Use `none` only if the UI and API are on different sites without a proxy. |
| `CORS_ORIGINS` | Comma-separated list of the UI origins |
| `VERIFY_TLS` | Leave `true` in production |

### Connecting Spira
1. In Spira, open your profile, enable **RSS Feeds** and copy the **RSS token**, including the `{ }` braces.
2. In TouQA, go to **Integrations → Spira**. Enter the URL (for example `https://toucan.spiraservice.net/`), your username and the token, then choose **Save & test**.
3. Under **Projects**, choose **Add** for each project you want to use.
4. Open **Synchronization** and start a sync.
5. Optionally, open **Settings & Mapping** to choose the custom field that holds acceptance criteria, the default test case status and type, and how priority/severity levels map to your project's values.

The token is encrypted at rest and is never sent back to the browser.

### Connecting Jira (optional)
For **Jira Cloud**, you need the site URL, your account email and an API token created at id.atlassian.com → Security → API tokens. For **Jira Data Center**, use a personal access token instead. Then set the project key and the issue type to use for bugs.

## 4. How the approval workflow works

1. **Analyse** a requirement. Acceptance criteria are marked as *imported* or *proposed*, and every statement as *grounded* in the source or an *inference*.
2. **Generate** test cases by category. Each draft is validated and checked for duplicates against existing and sibling test cases.
3. **Review** the drafts: edit steps, approve or reject them, and decide what to do with duplicates.
4. **Submit:** pick a folder, review the exact Spira payloads, and tick the approval box. The approval is tied to a hash of the payload, so any change requires a new review.
5. Submissions are idempotent. If a request times out, TouQA checks Spira before retrying instead of creating duplicates.

Incident Studio follows the same steps: notes and evidence, then an AI draft, then classification, then preview and approval, then submission to Spira, Jira or both.

Every sign-in, configuration change, AI run, approval and external write is recorded in the **Audit Log**. Secrets are redacted from logs.

## 5. Deployment

**Backend:** deploy to Render with `render.yaml` (New → Blueprint). It creates the `touqa-backend` web service and a PostgreSQL database. Enter the secret values in the Render dashboard when prompted. Any container host works (Railway, Fly.io, Azure Container Apps). The image honours `$PORT` and runs migrations on start.

**Frontend:** deploy to Vercel with the project root set to `frontend/`. `frontend/vercel.json` proxies `/api/*` to `https://touqa-backend.onrender.com`. Change that URL if your backend lives elsewhere. Because of the proxy, the API is same-origin and cookies keep working with `SameSite=Lax`. Set the backend's `CORS_ORIGINS` to the Vercel URL and `COOKIE_SECURE=true`.

## 6. Tests

```bash
cd backend && pytest            # unit + integration tests with fake Spira/Jira servers
cd frontend && npm test         # Vitest
```

Live Spira tests (`backend/tests/live`) are skipped unless `LIVE_TESTS_ENABLED=true` and a sandbox project is configured. They never touch production records.

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| "Backend unavailable" in the UI | Make sure the API is running on :8000. On Vercel, check the URL in `vercel.json`. |
| Signed in, but every request returns 401 | Cookie problem: serve over HTTPS with `COOKIE_SECURE=true`, use the `/api` proxy, and check `CORS_ORIGINS`. |
| Spira test returns 401 | The username or RSS token is wrong. The token must include the braces, and RSS must be enabled in your Spira profile. |
| Spira test returns 403 | Your Spira role lacks permission for that project or artifact. |
| "Encryption key missing" | Set `ENCRYPTION_KEY` and restart the backend. |
| The AI says it is not configured | Set the provider's API key in `.env`, or choose `simulated`. |
| Coverage shows "unreliable" | Run a requirements sync with coverage enabled. |
| Submit button disabled | Demo mode, unresolved validation errors, or the approval box isn't ticked. |
| Status "unknown outcome" after a timeout | Open the operation and retry. TouQA checks Spira for the record before creating anything. |
