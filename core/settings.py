"""Configuration that differs between deployments, read once from the environment.

One object, checked when it loads, instead of variables read from the
environment wherever they happened to be needed. Production, staging and a local
copy differ only in what is set here.

    DATABASE_URL     the database server and login
    DATABASE_NAME    which database on it - mappa (live) or mappa_staging
    APP_ENV          production | staging | local
    CORS_ORIGINS     other websites allowed to call the API, comma-separated
    SERVE_FRONTEND   false when the web page is hosted separately
    DB_POOL_MAX      database connections per process (default 4)
    RATE_LIMIT_PER_MINUTE / RATE_LIMIT_PER_HOUR   questions per address (15 / 150)
    LLM_MODEL, GCP_PROJECT, VERTEX_LOCATION        the answering model on Vertex AI
    TILE_TIMEOUT_MS, TILE_TIMEOUT_LOWZOOM_MS, TILE_CACHE_ENTRIES, TILE_CONCURRENCY
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    database_url: str | None = None
    app_env: Literal["production", "staging", "local"] = "production"
    api_prefix: str = "/api/v1"
    cors_origins: tuple[str, ...] = ()
    serve_frontend: bool = True
    # Each container holds this many connections; the server allows 100 in all,
    # so containers x pool must stay well under that.
    db_pool_max: int = 4
    db_statement_timeout_ms: int = 20_000
    db_checkout_timeout_s: float = 15.0
    rate_limit_per_minute: int = 15
    rate_limit_per_hour: int = 150
    llm_model: str = "gemini-2.5-flash"
    # Tokens the model may spend reasoning before each reply. Off (0) answers
    # the 100 test questions as well and twice as fast; -1 lets the model decide.
    llm_thinking_budget: int = 0
    gcp_project: str = "mappa-lamarana-aecc"
    vertex_location: str = "us-central1"
    tile_timeout_ms: int = 8_000
    tile_timeout_lowzoom_ms: int = 45_000
    tile_cache_entries: int = 600
    tile_concurrency: int = 3

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Settings:
        url = env.get("DATABASE_URL")
        name = env.get("DATABASE_NAME")
        if url and name:
            # Staging and production share one server and one stored address;
            # the name picks the database.
            url = urlunsplit(urlsplit(url)._replace(path="/" + name))
        return cls(
            database_url=url,
            app_env=env.get("APP_ENV", "production"),
            cors_origins=tuple(
                o.strip() for o in env.get("CORS_ORIGINS", "").split(",") if o.strip()
            ),
            serve_frontend=env.get("SERVE_FRONTEND", "true").lower() != "false",
            db_pool_max=int(env.get("DB_POOL_MAX", "4")),
            db_statement_timeout_ms=int(env.get("DB_STATEMENT_TIMEOUT_MS", "20000")),
            db_checkout_timeout_s=float(env.get("DB_CHECKOUT_TIMEOUT_S", "15")),
            rate_limit_per_minute=int(env.get("RATE_LIMIT_PER_MINUTE", "15")),
            rate_limit_per_hour=int(env.get("RATE_LIMIT_PER_HOUR", "150")),
            llm_model=env.get("LLM_MODEL", "gemini-2.5-flash"),
            llm_thinking_budget=int(env.get("LLM_THINKING_BUDGET", "0")),
            gcp_project=env.get("GCP_PROJECT", "mappa-lamarana-aecc"),
            vertex_location=env.get("VERTEX_LOCATION", "us-central1"),
            tile_timeout_ms=int(env.get("TILE_TIMEOUT_MS", "8000")),
            tile_timeout_lowzoom_ms=int(env.get("TILE_TIMEOUT_LOWZOOM_MS", "45000")),
            tile_cache_entries=int(env.get("TILE_CACHE_ENTRIES", "600")),
            tile_concurrency=int(env.get("TILE_CONCURRENCY", "3")),
        )


settings = Settings.from_env()
