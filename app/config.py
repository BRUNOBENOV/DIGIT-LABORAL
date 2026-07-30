from __future__ import annotations

import os
from dataclasses import dataclass


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, "true" if default else "false").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Digit Laboral")
    environment: str = os.getenv("ENVIRONMENT", "development")
    secret_key: str = os.getenv("DIGIT_SECRET_KEY", "cambiar-esta-clave-en-produccion")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./data/digit_laboral.db")
    public_url: str = os.getenv("PUBLIC_URL", "http://127.0.0.1:8000")
    secure_cookies: bool = env_bool("SECURE_COOKIES", False)
    seed_demo_data: bool = env_bool("SEED_DEMO_DATA", True)
    files_enabled: bool = env_bool("FILES_ENABLED", True)
    admin_email: str = os.getenv("ADMIN_EMAIL", "").strip().lower()
    admin_password: str = os.getenv("ADMIN_PASSWORD", "")
    system_admin_email: str = os.getenv("SYSTEM_ADMIN_EMAIL", "").strip().lower()
    system_admin_password: str = os.getenv("SYSTEM_ADMIN_PASSWORD", "")


settings = Settings()
