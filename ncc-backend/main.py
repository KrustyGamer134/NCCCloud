from __future__ import annotations

import uuid

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from api.agent_ws import agent_ws_endpoint
from api.routes.agents import router as agents_router
from api.routes.auth import router as auth_router
from api.routes.health import router as health_router
from api.routes.instances import router as instances_router
from api.routes.plugins import router as plugins_router
from api.routes.settings import router as settings_router
from api.websocket import ws_events_endpoint
from core.auth import JWTAuthMiddleware
from core.settings import settings


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------
def create_app() -> FastAPI:
    app = FastAPI(
        title="NCC Backend",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # CORS — always allow the frontend origin.
    # In development this defaults to http://localhost:3000.
    # In production set FRONTEND_URL in the backend .env to the deployed frontend domain.
    origins = [settings.frontend_url]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request-ID middleware (must be added BEFORE JWTAuthMiddleware so it always runs)
    class RequestIDMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):  # type: ignore[override]
            response = await call_next(request)
            response.headers["X-Request-ID"] = str(uuid.uuid4())
            return response

    app.add_middleware(RequestIDMiddleware)

    # JWT auth middleware
    app.add_middleware(JWTAuthMiddleware)

    # ---------------------------------------------------------------------------
    # Routers
    # ---------------------------------------------------------------------------
    # Health — no prefix
    app.include_router(health_router)

    # Auth
    app.include_router(auth_router, prefix="/auth")

    # Plugins
    app.include_router(plugins_router, prefix="/plugins")

    # Agents
    app.include_router(agents_router, prefix="/agents")

    # Instances
    app.include_router(instances_router, prefix="/instances")

    # Settings
    app.include_router(settings_router, prefix="/settings")

    # ---------------------------------------------------------------------------
    # WebSocket endpoints
    # ---------------------------------------------------------------------------
    @app.websocket("/ws/events")
    async def websocket_events(websocket: WebSocket) -> None:
        await ws_events_endpoint(websocket)

    @app.websocket("/agent/ws")
    async def websocket_agent(websocket: WebSocket) -> None:
        await agent_ws_endpoint(websocket)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
