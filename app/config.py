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
    max_import_rows: int = int(os.getenv("MAX_IMPORT_ROWS", "2000"))
    login_max_attempts: int = int(os.getenv("LOGIN_MAX_ATTEMPTS", "5"))
    login_lock_minutes: int = int(os.getenv("LOGIN_LOCK_MINUTES", "15"))
    password_reset_minutes: int = int(os.getenv("PASSWORD_RESET_MINUTES", "30"))
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_username: str = os.getenv("SMTP_USERNAME", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from_email: str = os.getenv("SMTP_FROM_EMAIL", "")
    smtp_from_name: str = os.getenv("SMTP_FROM_NAME", "Digit Laboral")
    smtp_use_tls: bool = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
    rls_enabled: bool = os.getenv("RLS_ENABLED", "false").lower() == "true"
    csrf_enabled: bool = os.getenv("CSRF_ENABLED", "false").lower() == "true"
    initial_admin_email: str = os.getenv("INITIAL_ADMIN_EMAIL", "")
    initial_admin_password: str = os.getenv("INITIAL_ADMIN_PASSWORD", "")
    initial_admin_name: str = os.getenv("INITIAL_ADMIN_NAME", "Administrador General")
    allowed_hosts: tuple[str, ...] = tuple(
        host.strip() for host in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver,*.onrender.com").split(",") if host.strip()
    )


settings = Settings()
