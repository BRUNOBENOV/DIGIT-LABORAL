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
    ai_enabled: bool = os.getenv("AI_ENABLED", "true").lower() == "true"
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    ai_store_responses: bool = os.getenv("AI_STORE_RESPONSES", "false").lower() == "true"
    max_logo_size: int = int(os.getenv("MAX_LOGO_SIZE", str(2 * 1024 * 1024)))
    allowed_hosts: tuple[str, ...] = tuple(
        host.strip() for host in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver,*.onrender.com").split(",") if host.strip()
    )


settings = Settings()
