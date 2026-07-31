from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Digit Laboral")
    environment: str = os.getenv("ENVIRONMENT", "development")
    secret_key: str = os.getenv("DIGIT_SECRET_KEY", "cambiar-esta-clave-en-produccion")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./data/digit_laboral.db")
    public_url: str = os.getenv("PUBLIC_URL", "http://127.0.0.1:8000")
    secure_cookies: bool = os.getenv("SECURE_COOKIES", "false").lower() == "true"
    allowed_hosts: tuple[str, ...] = tuple(
        host.strip() for host in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",") if host.strip()
    )


settings = Settings()
