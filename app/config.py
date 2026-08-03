from __future__ import annotations

import os
import secrets
from dataclasses import dataclass


def _bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Digit Laboral")
    environment: str = os.getenv("ENVIRONMENT", "development").strip().lower()
    secret_key: str = os.getenv("DIGIT_SECRET_KEY", "cambiar-esta-clave-en-produccion")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./data/digit_laboral.db")
    migration_database_url: str = os.getenv("MIGRATION_DATABASE_URL", os.getenv("DATABASE_URL", "sqlite:///./data/digit_laboral.db"))
    public_url: str = os.getenv("PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")
    secure_cookies: bool = _bool("SECURE_COOKIES")
    json_logs: bool = _bool("JSON_LOGS", "true")
    ai_enabled: bool = _bool("AI_ENABLED")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    ai_store_responses: bool = _bool("AI_STORE_RESPONSES")
    max_logo_size: int = int(os.getenv("MAX_LOGO_SIZE", str(2 * 1024 * 1024)))
    max_upload_size: int = int(os.getenv("MAX_UPLOAD_SIZE", str(10 * 1024 * 1024)))
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
    smtp_use_tls: bool = _bool("SMTP_USE_TLS", "true")
    rls_enabled: bool = _bool("RLS_ENABLED")
    rls_force: bool = _bool("RLS_FORCE")
    csrf_enabled: bool = _bool("CSRF_ENABLED")
    initial_admin_email: str = os.getenv("INITIAL_ADMIN_EMAIL", "")
    initial_admin_password: str = os.getenv("INITIAL_ADMIN_PASSWORD", "")
    initial_admin_name: str = os.getenv("INITIAL_ADMIN_NAME", "Administrador General")
    demo_admin_password: str = os.getenv("DEMO_ADMIN_PASSWORD") or secrets.token_urlsafe(18)
    demo_superadmin_password: str = os.getenv("DEMO_SUPERADMIN_PASSWORD") or secrets.token_urlsafe(18)
    storage_backend: str = os.getenv("STORAGE_BACKEND", "local").strip().lower()
    local_storage_path: str = os.getenv("LOCAL_STORAGE_PATH", "./data/uploads")
    s3_endpoint_url: str = os.getenv("S3_ENDPOINT_URL", "")
    s3_region: str = os.getenv("S3_REGION", "")
    s3_bucket: str = os.getenv("S3_BUCKET", "")
    s3_access_key_id: str = os.getenv("S3_ACCESS_KEY_ID", "")
    s3_secret_access_key: str = os.getenv("S3_SECRET_ACCESS_KEY", "")
    rei_direct_enabled: bool = _bool("REI_DIRECT_ENABLED")
    reop_direct_enabled: bool = _bool("REOP_DIRECT_ENABLED")
    compliance_dual_approval: bool = _bool("COMPLIANCE_DUAL_APPROVAL")
    allowed_hosts: tuple[str, ...] = tuple(
        host.strip()
        for host in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver,*.onrender.com").split(",")
        if host.strip()
    )

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def production_issues(self) -> list[str]:
        issues: list[str] = []
        if self.is_production and self.secret_key == "cambiar-esta-clave-en-produccion":
            issues.append("DIGIT_SECRET_KEY no está configurada.")
        if self.is_production and not self.database_url.startswith(("postgres://", "postgresql://", "postgresql+")):
            issues.append("Producción debe usar PostgreSQL.")
        if self.is_production and self.rls_force and self.migration_database_url == self.database_url:
            issues.append("RLS_FORCE requiere separar MIGRATION_DATABASE_URL de DATABASE_URL.")
        if self.is_production and self.storage_backend == "local":
            issues.append("El almacenamiento local no es persistente en la mayoría de los hostings.")
        if self.is_production and self.storage_backend == "s3":
            missing = [
                name for name, value in (
                    ("S3_BUCKET", self.s3_bucket),
                    ("S3_ACCESS_KEY_ID", self.s3_access_key_id),
                    ("S3_SECRET_ACCESS_KEY", self.s3_secret_access_key),
                ) if not value
            ]
            if missing:
                issues.append(f"Faltan credenciales de almacenamiento: {', '.join(missing)}.")
        if self.is_production and not self.secure_cookies:
            issues.append("SECURE_COOKIES debe estar activo en producción.")
        if self.is_production and not self.public_url.startswith("https://"):
            issues.append("PUBLIC_URL debe usar HTTPS en producción.")
        if self.is_production and (not self.smtp_host or not self.smtp_from_email):
            issues.append("SMTP no está completo; recuperación de contraseña y alertas no enviarán correos.")
        if self.is_production and self.rls_enabled and not self.rls_force:
            issues.append("RLS_FORCE permanece desactivado hasta separar el usuario de migración del usuario de aplicación.")
        if self.is_production and not self.compliance_dual_approval:
            issues.append("COMPLIANCE_DUAL_APPROVAL debe activarse antes de presentaciones oficiales.")
        if (self.rei_direct_enabled or self.reop_direct_enabled):
            issues.append("Los conectores directos no deben habilitarse sin especificación y autorización oficial.")
        if self.ai_enabled and not self.openai_api_key:
            issues.append("AI_ENABLED está activo pero OPENAI_API_KEY no está configurada.")
        return issues


settings = Settings()
