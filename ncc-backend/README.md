# NCC Backend

The NCC Backend is the hosted control-plane for the New Control Center (NCC) platform. It is a FastAPI application that authenticates web users via Clerk JWTs, provisions multi-tenant accounts, stores game-server instance and agent configuration in PostgreSQL, relays lifecycle commands to remote NCC agents over WebSocket, and streams real-time status events back to the web dashboard. The backend never touches game-server machines directly — all heavy lifting is delegated to the agent process that runs on each machine.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | 3.12 recommended |
| PostgreSQL | 16 | asyncpg driver required at runtime |
| Clerk account | free tier | Must expose a JWKS endpoint for RS256 token verification |

---

## Environment variables

Copy `.env.example` to `.env` and fill in every value before running.

```bash
cp .env.example .env
```

| Variable | Required | Description | Example value |
|---|---|---|---|
| `DATABASE_URL` | Yes | Async PostgreSQL connection string — must use `postgresql+asyncpg://` scheme | `postgresql+asyncpg://ncc:secret@localhost:5432/ncc` |
| `CLERK_JWKS_URL` | Yes | JWKS endpoint from your Clerk application's API Keys page | `https://your-app.clerk.accounts.dev/.well-known/jwks.json` |
| `JWT_ALGORITHM` | Yes | JWT signing algorithm — must match the algorithm shown in Clerk | `RS256` |
| `BACKEND_URL` | Yes | Public URL of this server — used as the CORS allow-list in production; ignored in development | `http://localhost:8000` |
| `ENVIRONMENT` | Yes | `development` enables CORS allow-all origins; `production` restricts CORS to `BACKEND_URL` only | `development` |
| `SECRET_KEY` | Yes | Random secret used for internal signing — generate once and never change | *(generate, never commit)* |
| `NCC_CORE_PATH` | Yes | Absolute path to the root of the NCC core repository — used by `scripts/seed_plugin_catalog.py` to locate `plugins/` | `/opt/NewControlCenter` |

> **Tip:** `DATABASE_URL` must use the `postgresql+asyncpg://` scheme.
> The synchronous `postgresql://` (psycopg2) form will not work because SQLAlchemy is configured with the async engine.

---

## Setup

### 1. Clone and cd into ncc-backend/

```bash
git clone <repo-url>
cd NewControlCenter/ncc-backend
```

### 2. Create a virtual environment and activate it

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

> `psycopg2-binary` is included for Alembic offline tooling. The runtime async path uses `asyncpg`.

### 4. Create the PostgreSQL database

Connect to PostgreSQL as the superuser and run:

```sql
CREATE USER ncc WITH PASSWORD 'your-password';
CREATE DATABASE ncc OWNER ncc;
GRANT ALL PRIVILEGES ON DATABASE ncc TO ncc;
```

Using psql directly:

```bash
psql -U postgres -c "CREATE USER ncc WITH PASSWORD 'your-password';"
psql -U postgres -c "CREATE DATABASE ncc OWNER ncc;"
psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE ncc TO ncc;"
```

### 5. Copy `.env.example` to `.env` and fill in values

```bash
cp .env.example .env
# Edit .env — at minimum set DATABASE_URL, CLERK_JWKS_URL, and SECRET_KEY
```

Generate `SECRET_KEY` with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 6. Run migrations

```bash
alembic upgrade head
```

This applies two migrations:
- `0001_initial` — creates all six tables (`tenants`, `users`, `agents`, `instances`, `audit_logs`, `plugin_catalog`)
- `0002_add_indexes` — adds composite performance indexes on high-traffic query patterns

### 7. Seed the plugin catalog

```bash
python scripts/seed_plugin_catalog.py
```

This reads `{NCC_CORE_PATH}/plugins/ark/plugin.json` and upserts the ARK: Survival Ascended plugin into `plugin_catalog` with `available_in_plans: ["free", "basic", "pro"]`. Safe to re-run — it updates without overwriting plan assignments.

### 8. Verify the database

```bash
python scripts/db_verify.py
```

Expected output: all six tables listed with 0–1 rows each and the current Alembic revision shown. Any `MISSING ✗` entry means the migration did not apply cleanly — re-run `alembic upgrade head`.

### 8a. Reset a test user's cloud tenant data

To simulate a truly fresh cloud account for a Clerk user, you can preview or delete
that user's backend tenant data:

```bash
python scripts/reset_cloud_user.py --email test@example.com
python scripts/reset_cloud_user.py --user-id user_123 --confirm
```

This deletes the backend `tenants` row and cascading tenant-scoped cloud data.
It does not clear host-local agent settings or files on the user's machine.

### 9. Start the development server

```bash
uvicorn main:app --reload
```

The `--reload` flag watches for file changes and restarts automatically.

### 10. Verify the API is running

Open `http://localhost:8000/docs` in your browser. The Swagger UI should load and show all routes. `GET /health` should return `{"status": "ok"}`.

---

## Running tests

```bash
pytest tests/ -v
```

The test suite uses mock DB sessions and does not require a live database or auth provider. To run a specific file:

```bash
pytest tests/test_plan_limits.py -v
pytest tests/test_status_persistence.py -v
pytest tests/test_version_handshake.py -v
```

**Integration tests** (marked `integ_`) require a live PostgreSQL instance. Set `DATABASE_URL_TEST` to a throwaway database URL before running — the fixture creates the database, runs migrations against it, and drops it on teardown:

```bash
DATABASE_URL_TEST=postgresql://ncc:secret@localhost:5432/ncc_test pytest tests/ -v
```

Without `DATABASE_URL_TEST` the integration tests are automatically skipped.

---

## Route summary

| Method | Path | Auth required | Description |
|---|---|---|---|
| `GET` | `/health` | No | Liveness probe — always returns `{"status":"ok"}` |
| `GET` | `/ready` | No | Readiness probe — issues `SELECT 1` and returns 503 if the DB is unreachable |
| `POST` | `/auth/provision` | JWT | First-login provisioning — creates a `Tenant` and `User` if they do not exist; returns `tenant_id` and `role` |
| `GET` | `/plugins` | JWT | List plugins available in the tenant's plan; pro tenants receive all catalog entries unconditionally |
| `GET` | `/agents` | JWT | List all agents for this tenant including live connection state and last-seen timestamp |
| `GET` | `/agents/{id}` | JWT | Get a single agent |
| `POST` | `/agents/register` | JWT | Register a new agent — bcrypt-hashes the generated key and returns the plaintext only once |
| `DELETE` | `/agents/{id}/key` | JWT | Revoke and reissue an agent's API key |
| `GET` | `/instances` | JWT | List all instances with last-known status and `agent_online` flag |
| `GET` | `/instances/{id}` | JWT | Get a single instance |
| `POST` | `/instances` | JWT | Create an instance — enforces plan instance limit before writing |
| `DELETE` | `/instances/{id}` | JWT | Delete an instance |
| `POST` | `/instances/{id}/start` | JWT | Start the game server — requires agent to be connected |
| `POST` | `/instances/{id}/stop` | JWT | Stop the game server |
| `POST` | `/instances/{id}/restart` | JWT | Restart the game server |
| `POST` | `/instances/{id}/update` | JWT | Update game server files via SteamCMD |
| `POST` | `/instances/{id}/install-deps` | JWT | Install system-level game dependencies |
| `POST` | `/instances/{id}/install-server` | JWT | Full initial server installation |
| `WS` | `/ws/events` | JWT (query param) | Web dashboard real-time event stream — receives `status_update` frames as agents push snapshots |
| `WS` | `/agent/ws` | Agent API key (in hello frame) | Persistent agent connection — handles hello/heartbeat/status_update/command_result |

---

## Plan limits

| Plan | Max instances | Max agents | Plugins |
|---|---|---|---|
| `free` | 1 | 1 | ARK: Survival Ascended only |
| `basic` | 3 | 2 | All catalog plugins |
| `pro` | Unlimited | Unlimited | All catalog plugins |

Exceeding a limit returns `HTTP 402` with body:
```json
{
  "error": "plan_limit_reached",
  "code": "plan_limit_reached",
  "limit_type": "instances",
  "current": 1,
  "max": 1
}
```

---

## Authentication flow

```
Browser                  NCC Backend                  Clerk
  │                           │                          │
  │──── POST /auth/provision ──►                          │
  │      Authorization: Bearer <JWT>                      │
  │                           │── GET JWKS ──────────────►│
  │                           │◄── JWKS (cached 1 h) ────│
  │                           │ validate token            │
  │                           │ create Tenant + User      │
  │◄─── {tenant_id, role} ───│                          │
  │                           │                          │
  │   (all subsequent requests carry the same JWT)        │
  │──── GET /instances ───────►                          │
  │      JWTAuthMiddleware validates + attaches state     │
  │◄─── [...] ────────────────│                          │
```

---

## Response conventions

- Every response includes `X-Request-ID: <uuid4>` for distributed tracing.
- Error bodies follow `{"error": "<message>", "code": "<SCREAMING_SNAKE>"}`.
- All DB queries are scoped to the authenticated `tenant_id` — cross-tenant reads are structurally impossible.
- The audit log is append-only; no rows are ever updated or deleted.
- Agent API keys are bcrypt-hashed in the DB; plaintext is only returned once (at `POST /agents/register` or `DELETE /agents/{id}/key`).
