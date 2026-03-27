from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    clerk_jwks_url: str
    jwt_algorithm: str = "RS256"
    backend_url: str = "http://localhost:8000"
    # URL of the Next.js frontend — used as the CORS allowed origin in production.
    frontend_url: str = "http://localhost:3000"
    environment: str = "development"
    secret_key: str
    ncc_core_path: str
    # Bootstrap key used by the agent to self-register without a Clerk JWT.
    # Set this to a long random secret shared with the agent's .env (BOOTSTRAP_API_KEY).
    bootstrap_api_key: str = ""


settings = Settings()
