"""Configuration that differs between deployments, read once from the environment.

One object, checked when it loads, instead of variables read from the
environment wherever they happened to be needed. Production, staging and a local
copy differ only in what is set here.

    DATABASE_URL     the database server and login
    DATABASE_NAME    which database on it - mappa (live) or mappa_staging
    APP_ENV          production | staging | local
    CORS_ORIGINS     other websites allowed to call the API, comma-separated
    SERVE_FRONTEND   false when the web page is hosted separately
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
        )


settings = Settings.from_env()
