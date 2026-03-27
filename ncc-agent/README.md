# NCC Agent

The NCC Agent is a lightweight Python process that runs on each game-server machine. It connects outbound to the NCC Backend over a persistent WebSocket, authenticates with a bcrypt-verified API key, listens for lifecycle commands (`start`, `stop`, `restart`, `update`, `install-deps`, `install-server`), executes them by calling the local NCC core `AdminAPI`, and pushes periodic status snapshots back to the backend every 15 seconds so the web dashboard always reflects live game-server state. The agent never exposes a listening port — all communication is initiated outbound from the agent toward the backend.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | 3.12 recommended |
| NCC core repo | any | Must be cloned and importable — see [NCC core dependency](#ncc-core-dependency) |
| NCC Backend | running | The agent registers with and maintains a WebSocket to the backend |

### NCC core dependency

The agent imports `core.admin_api.AdminAPI` from the NCC core repository at runtime. The recommended way to make this importable is an editable install:

```bash
pip install -e /path/to/NewControlCenter
```

Alternatively, set `NCC_REPO_ROOT` in your environment to the absolute path of the NCC repository root — `main.py` inserts it into `sys.path` automatically.

---

## Environment variables

Copy `.env.example` to `.env` and fill in every value before running.

```bash
cp .env.example .env
```

| Variable | Required | Description | Example value |
|---|---|---|---|
| `BACKEND_WS_URL` | Yes | WebSocket URL of the NCC Backend `/agent/ws` endpoint | `ws://your-backend-host:8000/agent/ws` |
| `BACKEND_HTTP_URL` | Yes | HTTP URL of the NCC Backend — used for first-run registration only | `http://your-backend-host:8000` |
| `API_KEY` | Yes (first run) | Bootstrap API key issued by the backend admin — used once to register; subsequent runs read from `agent_state.json` | *(from backend admin)* |
| `AGENT_ID` | Auto | Set automatically after registration — do not set manually | *(leave blank)* |
| `ENVIRONMENT` | Yes | `development` or `production` — controls log verbosity | `development` |
| `CLUSTER_ROOT` | Yes | Absolute path to the NCC game-server cluster root directory | `/srv/gameservers` |
| `AGENT_STATE_FILE` | No | Path where `agent_id` and `api_key` are persisted after registration | `agent_state.json` |

> **Tip:** `API_KEY` only needs to be present on the very first run. After registration `agent_state.json` stores the permanent credentials. You can blank out `API_KEY` in `.env` once the agent is registered.

---

## Setup

### 1. Clone and cd into ncc-agent/

```bash
git clone <repo-url>
cd NewControlCenter/ncc-agent
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

### 4. Install the NCC core package

```bash
pip install -e /path/to/NewControlCenter
```

### 5. Copy `.env.example` to `.env` and fill in values

```bash
cp .env.example .env
# Edit .env — at minimum set BACKEND_WS_URL, BACKEND_HTTP_URL, API_KEY, CLUSTER_ROOT
```

### 6. Run the agent

```bash
python main.py
```

On first run the agent registers itself with the backend and writes `agent_state.json`. On all subsequent runs it reads from that file and connects directly.

---

## First-run behavior

On the **first run** (no `agent_state.json` present) the agent:

1. Reads `BACKEND_HTTP_URL` and `API_KEY` from `.env`
2. Calls `POST {BACKEND_HTTP_URL}/agents/register` with body `{"machine_name": "<hostname>"}` and `Authorization: Bearer <API_KEY>`
3. Receives `{"agent_id": "...", "api_key": "..."}` from the backend
4. Writes those credentials to `agent_state.json` (path controlled by `AGENT_STATE_FILE`)
5. Proceeds to connect the WebSocket as normal

On all **subsequent runs**:

1. Reads `agent_state.json` — if it exists and contains an `agent_id`, registration is skipped
2. Connects directly with the stored credentials

`agent_state.json` example:
```json
{
  "agent_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "api_key": "plaintext-key-returned-by-backend"
}
```

> **Keep `agent_state.json` secret.** It contains the plaintext API key. Add it to `.gitignore` and set filesystem permissions accordingly (`chmod 600`).

### What the agent does every 15 seconds

The status reporter calls `AdminAPI.get_dashboard_status_snapshot()` every 15 seconds and sends a `status_update` frame to the backend:

```json
{
  "type": "status_update",
  "agent_id": "...",
  "data": {
    "instances": [
      {"instance_id": "...", "status": "running", "install_status": "installed"}
    ]
  }
}
```

The backend's two-phase write immediately persists this to the database so `GET /instances` always returns the last-known status — even when the agent is offline.

A `heartbeat` frame is also sent every 30 seconds when no backend message arrives, to keep NAT and load-balancer connections alive.

### Commands the agent accepts

| Command | What it does |
|---|---|
| `start` | Start the game server process |
| `stop` | Stop the game server process |
| `restart` | Stop then start the game server process |
| `install_deps` | Install system-level game dependencies |
| `install_server` | Run a full initial server installation via SteamCMD |
| `get_status` | Return the current cached instance status |
| `fetch_logs` | Return the tail of a log file (default: last 100 lines of `ShooterGame` log) |

---

## Troubleshooting

### The backend rejected the connection: "version too old"

The backend enforces a minimum agent version. If the `hello_ack` response contains `"status": "rejected"`, your agent version is below the minimum supported version.

**Fix:** Pull the latest `ncc-agent` code and restart.

```bash
git pull
python main.py
```

If the status is `"warn"` instead of `"rejected"`, the agent continues running but you should upgrade soon.

### `agent_state.json` is corrupted or missing credentials

If the agent fails to start with an error about missing `agent_id` or a JSON parse error:

**Fix:** Delete `agent_state.json` and re-register.

```bash
rm agent_state.json
# Make sure API_KEY is set in .env to a valid bootstrap key
python main.py
```

The agent will perform a fresh registration and write a new `agent_state.json`.

### The backend is unreachable

If the backend is down or the network is unavailable, the agent retries automatically with exponential backoff: 5 s → 10 s → 20 s → 40 s → 60 s (capped). It will keep retrying indefinitely — no manual intervention is needed once the backend comes back online.

Check the agent logs for lines like:

```
Connection failed. Retrying in 10s...
```

If the agent never connects, verify that `BACKEND_WS_URL` and `BACKEND_HTTP_URL` are correct in `.env` and that the backend is reachable from the agent machine:

```bash
curl http://your-backend-host:8000/health
```

### The agent connects but instances show as offline in the dashboard

The agent pushes status every 15 seconds. If instances appear offline immediately after the agent connects, wait one status cycle. If they remain offline:

1. Check that `CLUSTER_ROOT` points to the correct directory where game servers are installed.
2. Check that `pip install -e /path/to/NewControlCenter` was run successfully — the agent needs `AdminAPI` from NCC core.
3. Run `python main.py` in a terminal and watch for `AdminAPI initialised` in the output.

---

## Code layout

```
ncc-agent/
├── main.py                  Entry point — loads settings, registers, starts tasks
├── requirements.txt
├── .env.example
│
└── core/
    ├── settings.py          Pydantic BaseSettings — reads .env
    ├── version.py           AGENT_VERSION constant ("0.1.0")
    ├── machine_info.py      get_public_ip() — best-effort via ipify.org
    ├── registration.py      ensure_registered() — POST /agents/register + state file
    ├── connection.py        AgentConnection — WebSocket connect/reconnect loop
    ├── dispatcher.py        dispatch_command() — routes backend commands to AdminAPI
    └── status_reporter.py   run_status_reporter() — periodic status snapshot push
```
