from __future__ import annotations

import asyncio
import csv
import calendar
import hmac
import io
import json
import math
import logging
import os
import re
import secrets
import uuid
import zipfile
from collections import OrderedDict
from decimal import Decimal
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated
from urllib.parse import parse_qs, quote, urlencode

from PIL import Image, ImageChops, ImageOps

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import String, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .ai_service import generate_assistance
from .auth import hash_password, verify_password
from .labor_calculator import amount as round_gs, anniversary as labor_anniversary
from .salary_history import salary_for_period
from .config import settings
from .database import Base, SessionLocal, apply_session_tenant_context, engine, postgres_rls_role_issues
from .document_export import (
    DOCUMENT_LABELS,
    ExportData,
    build_document_body,
    document_detail_table_data,
    document_signature_mode,
    document_receipt_mode,
    build_docx_bytes,
    build_pdf_bytes,
    decode_metadata,
    encode_metadata,
    export_data_from_certificate,
    format_date_long_es,
    safe_download_name,
)
from .period_coverage import build_annual_coverage, current_paraguay_date
from .paraguay_locations import PARAGUAY_CITIES, PARAGUAY_CITY_NAMES, PARAGUAY_DEPARTMENTS
from .models import (
    ActivationRequest,
    AIInteraction,
    Aguinaldo,
    AuditLog,
    Branch,
    BranchComplianceProfile,
    Company,
    CompanyBranding,
    CompanyComplianceProfile,
    CompanySection,
    ComplianceEvent,
    CompanyRequest,
    CalculationRecord,
    Document,
    Employee,
    MedicalExam,
    EmployeeEvent,
    EmployeeComplianceProfile,
    GeneratedCertificate,
    LaborArticle,
    LaborDeadline,
    LaborOperation,
    IntegrationBatch,
    IntegrationBatchItem,
    LaborParameter,
    Payroll,
    PayrollLine,
    PayrollComplianceDetail,
    PasswordResetToken,
    RequestAttachment,
    RequestComment,
    RequestWorkflow,
    Notification,
    NotificationDelivery,
    OfficialCertificateRecord,
    SalaryHistory,
    SecurityEvent,
    Studio,
    StudioPayment,
    User,
    UserSecurity,
    Vacation,
)
from .labor_operation_service import (
    OPERATION_LABELS,
    OPERATION_STATUSES,
    OPERATION_TYPES,
    operation_to_dict,
    validate_labor_operation,
)
from .medical_exam_service import (
    MEDICAL_EXAM_RESULTS,
    MEDICAL_EXAM_TYPES,
    MEDICAL_EXAM_WARNING_DAYS,
    generate_medical_exam_code,
    medical_exam_expiry_state,
    validate_medical_exam_fields,
)
from .notification_service import create_notification, dispatch_notification_outbox, send_notification_delivery
from .official_certificates import (
    OFFICIAL_CERTIFICATE_RESULTS,
    OFFICIAL_CERTIFICATE_STATUSES,
    OFFICIAL_CERTIFICATE_TYPES,
    days_until_expiry,
    default_expiry_date,
    official_certificate_state,
)
from .notification_worker import (
    create_due_official_certificate_notifications,
    create_due_request_notifications,
)

from .report_export import build_employee_report_pdf
from .report_center import REPORTS, REPORT_GROUPS, fetch_report, get_report, make_pdf, make_xlsx, report_sort_options
from .backup_service import build_studio_export
from .seed import seed_database
from .labor_code_sync import (
    SOURCE_REGISTRY,
    article_sort_key,
    normalize_search,
    sync_labor_code,
)
from .import_service import (
    ImportPreview,
    build_employee_template,
    load_preview,
    normalize_document_number,
    parse_employee_import,
    save_preview,
)
from .tenant_security import apply_postgres_rls
from .migration_service import migration_engine, run_migrations
from .observability import configure_logging, request_context_middleware
from .storage_service import storage
from .form_utils import OptionalQueryId, optional_int, optional_date, clean_text
from .compliance_service import (
    COMPLIANCE_STATUS_TRANSITIONS,
    INTEGRATION_BATCH_STATUS_TRANSITIONS,
    OFFICIAL_SOURCES,
    REI_EVENT_TYPES,
    REOP_EVENT_TYPES,
    build_event_workbook,
    build_reop_annual_workbook,
    can_transition_compliance_status,
    create_compliance_event,
    ensure_compliance_event,
    register_batch,
    validate_company_for_authority,
)
from .security_service import (
    build_totp_qr_svg,
    build_totp_secret,
    create_password_reset,
    get_or_create_security,
    is_locked,
    password_strength_error,
    record_failed_login,
    reset_login_failures,
    send_deadline_summary,
    send_password_reset_email,
    validate_password_reset,
    verify_totp,
)

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
IMPORT_DIR = BASE_DIR / "data" / "imports"
IMPORT_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_UPLOAD_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
MAX_UPLOAD_SIZE = settings.max_upload_size


def _trim_logo_margins(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    alpha_bbox = rgba.getchannel("A").getbbox()
    if alpha_bbox:
        rgba = rgba.crop(alpha_bbox)
    white_bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    diff = ImageChops.difference(rgba, white_bg)
    bbox = diff.getbbox()
    if bbox:
        candidate = rgba.crop(bbox)
        if candidate.width >= max(40, rgba.width // 5) and candidate.height >= max(40, rgba.height // 5):
            rgba = candidate
    return rgba


def smart_normalize_logo(content: bytes) -> tuple[bytes, str]:
    with Image.open(io.BytesIO(content)) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGBA")
    image = _trim_logo_margins(image)
    target_box = (980, 280)
    canvas_size = (1100, 360)
    contained = ImageOps.contain(image, target_box, method=Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", canvas_size, (255, 255, 255, 0))
    offset = ((canvas.width - contained.width) // 2, (canvas.height - contained.height) // 2)
    canvas.paste(contained, offset, contained)
    output = io.BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    return output.getvalue(), "image/png"


def detect_logo_content_type(content: bytes) -> str | None:
    """Detect supported image types by file signature rather than browser MIME metadata."""
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


configure_logging(settings.json_logs)
logger = logging.getLogger("digit.main")


async def _periodic_notification_sweep() -> None:
    """Run reminder sweeps hourly while the web service process is awake."""
    await asyncio.sleep(60)
    while True:
        try:
            await asyncio.to_thread(create_due_request_notifications)
            await asyncio.to_thread(create_due_official_certificate_notifications)
            await asyncio.to_thread(dispatch_notification_outbox)
        except Exception:
            logger.exception("Scheduled notification sweep failed")
        await asyncio.sleep(60 * 60)


@asynccontextmanager
async def lifespan(_: FastAPI):
    run_migrations()
    seed_database()
    if settings.rls_enabled:
        apply_postgres_rls(migration_engine)
    issues = settings.production_issues()
    issues.extend(postgres_rls_role_issues())
    if issues:
        logger.warning("Production readiness issues: %s", " | ".join(issues))
    reminder_task = asyncio.create_task(_periodic_notification_sweep())
    try:
        yield
    finally:
        reminder_task.cancel()
        try:
            await reminder_task
        except asyncio.CancelledError:
            pass


if settings.is_production and settings.secret_key == "cambiar-esta-clave-en-produccion":
    raise RuntimeError("DIGIT_SECRET_KEY debe configurarse con una clave segura en producción.")

class CSRFMiddleware:
    """Double-submit style session token validation for authenticated form posts."""

    def __init__(self, app):  # noqa: ANN001
        self.app = app

    async def __call__(self, scope, receive, send):  # noqa: ANN001
        if scope.get("type") != "http" or not settings.csrf_enabled:
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "GET").upper()
        path = scope.get("path", "")
        protected = method in {"POST", "PUT", "PATCH", "DELETE"} and path not in {"/health", "/health/live", "/health/ready", "/internal/cron/notifications"}
        session = scope.get("session") or {}
        expected = session.get("csrf_token", "")
        if not protected:
            await self.app(scope, receive, send)
            return

        body_parts: list[bytes] = []
        body_size = 0
        more = True
        while more:
            message = await receive()
            if message.get("type") == "http.disconnect":
                return
            if message.get("type") != "http.request":
                continue
            body_size += len(message.get("body", b""))
            if (path.startswith("/herramientas/") or path.startswith("/app/liquidaciones/")) and body_size > 64000:
                await Response("Formulario demasiado grande.", status_code=413)(scope, receive, send)
                return
            body_parts.append(message.get("body", b""))
            more = message.get("more_body", False)
        body = b"".join(body_parts)
        headers = {key.decode("latin1").lower(): value.decode("latin1") for key, value in scope.get("headers", [])}
        supplied = headers.get("x-csrf-token", "")
        content_type = headers.get("content-type", "")
        if not supplied and content_type.startswith("application/x-www-form-urlencoded"):
            parsed = parse_qs(body.decode("utf-8", errors="replace"))
            supplied = (parsed.get("csrf_token") or [""])[0]
        elif not supplied and content_type.startswith("multipart/form-data"):
            # Bind the token to its own multipart field. The previous expression
            # could cross the blank separator and match later binary file bytes;
            # compare_digest(str, str) then raised TypeError on non-ASCII bytes,
            # turning image uploads into HTTP 500 responses.
            match = re.search(
                rb'Content-Disposition:\s*form-data;\s*name="csrf_token"[^\r\n]*\r?\n\r?\n([A-Za-z0-9_-]{20,256})\r?\n',
                body,
            )
            if match:
                supplied = match.group(1).decode("ascii")
        expected_token = str(expected or "")
        supplied_token = str(supplied or "")
        if (
            not expected_token
            or not supplied_token
            or not expected_token.isascii()
            or not supplied_token.isascii()
            or not hmac.compare_digest(expected_token, supplied_token)
        ):
            response = Response("Solicitud rechazada por protección CSRF.", status_code=403)
            await response(scope, receive, send)
            return

        sent = False

        async def replay_receive():
            nonlocal sent
            if sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay_receive, send)


try:
    _VERSION_FILE = Path(__file__).resolve().parents[1] / "VERSION"
    _DEFAULT_APP_VERSION = _VERSION_FILE.read_text(encoding="utf-8").strip() or "2.4.0"
except OSError:
    _DEFAULT_APP_VERSION = "2.4.0"
APP_VERSION = (os.getenv("DIGIT_APP_VERSION", _DEFAULT_APP_VERSION).strip() or _DEFAULT_APP_VERSION)
APP_COMMIT = os.getenv("RENDER_GIT_COMMIT", os.getenv("GITHUB_SHA", "")).strip()
APP_BUILD = APP_COMMIT[:7] if APP_COMMIT else "LOCAL"
APP_BRANCH = os.getenv("RENDER_GIT_BRANCH", os.getenv("GITHUB_REF_NAME", "")).strip() or "local"

app = FastAPI(title="Digit Laboral", version=APP_VERSION, lifespan=lifespan)
app.add_middleware(CSRFMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    same_site="lax",
    https_only=settings.secure_cookies,
    max_age=60 * 60 * 12,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))
app.middleware("http")(request_context_middleware)

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; font-src 'self'; connect-src 'self'; frame-ancestors 'self'",
    )
    if settings.secure_cookies:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    content_type = request.headers.get("content-type", "")
    is_form = content_type.startswith(("application/x-www-form-urlencoded", "multipart/form-data"))
    if is_form:
        messages = []
        for error in exc.errors():
            location = " → ".join(str(part) for part in error.get("loc", []) if part != "body")
            detail = error.get("msg", "Valor inválido")
            messages.append(f"{location}: {detail}" if location else detail)
        back = request.headers.get("referer", "")
        if not back.startswith(str(request.base_url)):
            back = "/app"
        body = templates.get_template("form_error.html").render(
            request=request, messages=messages, back=back, request_id=getattr(request.state, "request_id", "")
        )
        return HTMLResponse(body, status_code=422)
    return JSONResponse({"detail": exc.errors()}, status_code=422)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    location = (exc.headers or {}).get("Location")
    if location and 300 <= exc.status_code < 400:
        return RedirectResponse(location, status_code=exc.status_code)
    if request.url.path.startswith("/health"):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
    body = templates.get_template("http_error.html").render(
        request=request,
        status_code=exc.status_code,
        detail=str(exc.detail or "No se pudo completar la solicitud."),
        request_id=getattr(request.state, "request_id", ""),
    )
    return HTMLResponse(body, status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled application error", exc_info=exc)
    if request.url.path.startswith("/health"):
        return JSONResponse({"detail": "Internal server error"}, status_code=500)
    body = templates.get_template("http_error.html").render(
        request=request,
        status_code=500,
        detail="Ocurrió un error inesperado. La incidencia quedó registrada.",
        request_id=getattr(request.state, "request_id", ""),
    )
    return HTMLResponse(body, status_code=500)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_user(request: Request, db: Session) -> User | None:
    session_user_id = request.session.get("user_id")
    if not session_user_id:
        return None
    try:
        user_id = int(session_user_id)
    except (TypeError, ValueError):
        request.session.clear()
        return None

    # RLS must allow the signed-in user's row to be loaded before the user's
    # studio and role are known. The session cookie is signed by SessionMiddleware;
    # only the user ID is supplied at this stage, never a client-provided role.
    db.info["user_id"] = user_id
    db.info["user_role"] = ""
    db.info["studio_id"] = None
    db.info["is_superadmin"] = False
    apply_session_tenant_context(db)

    user = db.get(User, user_id)
    if not user:
        request.session.clear()
        return None
    security = get_or_create_security(db, user)
    session_version = int(request.session.get("security_version", 0) or 0)
    if session_version != security.session_version:
        request.session.clear()
        return None

    # Populate the remaining RLS context only after reading the canonical user
    # record from PostgreSQL, so tenant and role values cannot come from a form.
    db.info["studio_id"] = user.studio_id
    db.info["user_role"] = user.role
    db.info["is_superadmin"] = user.role == "superadmin"
    apply_session_tenant_context(db)
    return user


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = current_user(request, db)
    if not user or not user.active:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    if user.role != "superadmin" and user.studio and (not user.studio.active or user.studio.payment_status != "Activo"):
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login?inactive=1"})
    return user


def require_roles(*roles: str):
    def dependency(user: User = Depends(require_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "No tiene permiso para realizar esta acción.")
        return user

    return dependency


def company_ids_for_user(db: Session, user: User) -> list[int]:
    if user.role == "empresa":
        if not user.company_id or not user.studio_id:
            return []
        return list(db.scalars(select(Company.id).where(Company.id == user.company_id, Company.studio_id == user.studio_id)))
    if user.role == "abogado":
        if not user.id or not user.studio_id:
            return []
        return list(db.scalars(
            select(CompanyRequest.company_id)
            .join(RequestWorkflow, RequestWorkflow.request_id == CompanyRequest.id)
            .join(Company, Company.id == CompanyRequest.company_id)
            .where(
                Company.studio_id == user.studio_id,
                RequestWorkflow.assigned_user_id == user.id,
            )
            .distinct()
            .order_by(CompanyRequest.company_id)
        ))
    if user.studio_id:
        return list(db.scalars(select(Company.id).where(Company.studio_id == user.studio_id)))
    return []


def company_allowed(db: Session, user: User, company_id: int) -> Company:
    company = db.get(Company, company_id)
    if not company or company_id not in company_ids_for_user(db, user):
        raise HTTPException(404, "Empresa no encontrada.")
    return company


def _ruc_digits(value: str | None) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def ruc_check_digit(base_ruc: str) -> int:
    """Return the Paraguayan RUC verifier using the DNIT module-11 rule."""
    total = 0
    factor = 2
    for digit in reversed(base_ruc):
        total += int(digit) * factor
        factor = 2 if factor == 11 else factor + 1
    remainder = total % 11
    return 0 if remainder <= 1 else 11 - remainder


def normalize_company_ruc(value: str | None) -> str | None:
    """Normalize a Paraguayan RUC and verify its module-11 check digit.

    DNIT's SIFEN technical manual defines the RUC base field separately from
    its one-digit verifier. This local check validates the formula only; it
    does not query DNIT to confirm registration or current taxpayer status.
    """
    digits = _ruc_digits(value)
    if not 4 <= len(digits) <= 9:
        return None
    base_ruc, check_digit = digits[:-1], int(digits[-1])
    if not 3 <= len(base_ruc) <= 8 or ruc_check_digit(base_ruc) != check_digit:
        return None
    return f"{base_ruc}-{check_digit}"


def _company_profile(db: Session, company_id: int) -> CompanyComplianceProfile | None:
    return db.scalar(select(CompanyComplianceProfile).where(CompanyComplianceProfile.company_id == company_id))


def _company_api_record(db: Session, company: Company) -> dict:
    profile = _company_profile(db, company.id)
    updated_at = company.updated_at or company.created_at
    return {
        "id": company.id,
        "company_code": company.company_code,
        "legal_name": company.legal_name,
        "trade_name": company.trade_name or "",
        "owner_name": company.owner_name or "",
        "legal_representative": company.legal_representative or "",
        "address": company.address or "",
        "city": company.city or "",
        "department": profile.department if profile else "",
        "work_sector": company.work_sector or "",
        "work_location": company.work_location or "",
        "economic_activity": profile.economic_activity if profile else "",
        "phone": company.phone or "",
        "contact_name": company.contact_name or "",
        "email": company.email or "",
        "ips_employer_number": company.ips_employer_number or "",
        "mtess_employer_number": company.mtess_employer_number or "",
        "ruc": company.ruc or "",
        "legal_representative_document": profile.legal_representative_document if profile else "",
        "responsible_name": company.responsible_name or "",
        "notes": company.notes or "",
        "status": company.status or "Activa",
        "updated_at": updated_at.isoformat() if updated_at else None,
    }


def _validate_company_payload(db: Session, payload: dict, existing: Company | None = None) -> dict:
    profile = _company_profile(db, existing.id) if existing else None
    raw_code = payload.get("company_code")
    if raw_code in (None, "") and existing:
        raw_code = existing.company_code
    try:
        company_code = int(str(raw_code).strip())
    except (TypeError, ValueError):
        raise HTTPException(422, "El Código Empresa es obligatorio y debe ser numérico.")
    if company_code <= 0 or company_code > 2_147_483_647:
        raise HTTPException(422, "El Código Empresa debe ser un entero positivo.")

    legal_name = str(payload.get("legal_name", existing.legal_name if existing else "") or "").strip()
    if not legal_name:
        raise HTTPException(422, "El nombre de la empresa es obligatorio.")
    if len(legal_name) > 200:
        raise HTTPException(422, "El nombre de la empresa no puede superar los 200 caracteres.")

    raw_ruc = payload.get("ruc", existing.ruc if existing else "")
    if raw_ruc in (None, "") and existing:
        raw_ruc = existing.ruc
    ruc = normalize_company_ruc(str(raw_ruc or ""))
    if not ruc and existing and _ruc_digits(str(raw_ruc or "")) == _ruc_digits(existing.ruc):
        # Legacy records were not all digit-verified. Let users edit other fields
        # without forcing an unverified historical RUC to change.
        ruc = existing.ruc
    if not ruc:
        raise HTTPException(
            422,
            "El RUC debe tener entre 3 y 8 dígitos base y un dígito verificador válido (módulo 11).",
        )

    city = str(payload.get("city", existing.city if existing else "Ciudad del Este") or "").strip()
    if city and city not in PARAGUAY_CITY_NAMES and not (existing and city == existing.city):
        raise HTTPException(422, "Seleccioná una ciudad de la lista de localidades paraguayas.")
    department = str(payload.get("department", profile.department if profile else "") or "").strip()
    if department and department not in PARAGUAY_DEPARTMENTS and not (profile and department == profile.department):
        raise HTTPException(422, "Seleccioná un departamento válido de Paraguay.")
    if city and department and not any(
        item["name"] == city and item["department"] == department for item in PARAGUAY_CITIES
    ):
        if not (existing and profile and city == existing.city and department == profile.department):
            raise HTTPException(422, "La ciudad seleccionada no corresponde al departamento indicado.")

    ips = re.sub(r"[\s.-]+", "", str(payload.get("ips_employer_number", existing.ips_employer_number if existing else "") or ""))
    mjt = re.sub(r"[\s.-]+", "", str(payload.get("mtess_employer_number", existing.mtess_employer_number if existing else "") or ""))
    ci = re.sub(r"[\s.-]+", "", str(payload.get("legal_representative_document", profile.legal_representative_document if profile else "") or ""))
    if ips and not ips.isdigit():
        raise HTTPException(422, "El número patronal IPS debe contener solamente dígitos.")
    if mjt and not mjt.isdigit():
        raise HTTPException(422, "El número patronal MJT debe contener solamente dígitos.")
    if ci and not ci.isdigit():
        raise HTTPException(422, "El número de C.I. debe contener solamente dígitos.")

    values = {
        "company_code": company_code,
        "legal_name": legal_name,
        "trade_name": str(payload.get("trade_name", existing.trade_name if existing else "") or "").strip(),
        "owner_name": str(payload.get("owner_name", existing.owner_name if existing else "") or "").strip(),
        "legal_representative": str(payload.get("legal_representative", existing.legal_representative if existing else "") or "").strip(),
        "address": str(payload.get("address", existing.address if existing else "") or "").strip(),
        "city": city,
        "department": department,
        "work_sector": str(payload.get("work_sector", existing.work_sector if existing else "") or "").strip(),
        "work_location": str(payload.get("work_location", existing.work_location if existing else "") or "").strip(),
        "economic_activity": str(payload.get("economic_activity", profile.economic_activity if profile else "") or "").strip(),
        "phone": str(payload.get("phone", existing.phone if existing else "") or "").strip(),
        "contact_name": str(payload.get("contact_name", existing.contact_name if existing else "") or "").strip(),
        "email": str(payload.get("email", existing.email if existing else "") or "").strip(),
        "ips_employer_number": ips,
        "mtess_employer_number": mjt,
        "ruc": ruc,
        "legal_representative_document": ci,
        "responsible_name": str(payload.get("responsible_name", existing.responsible_name if existing else "Sin asignar") or "Sin asignar").strip(),
        "notes": str(payload.get("notes", existing.notes if existing else "") or "").strip(),
    }
    limits = {
        "trade_name": 160, "owner_name": 180, "legal_representative": 180, "address": 240,
        "work_sector": 160, "work_location": 180, "economic_activity": 220,
        "phone": 60, "contact_name": 180, "email": 180, "ips_employer_number": 80,
        "mtess_employer_number": 80, "legal_representative_document": 40, "responsible_name": 160,
    }
    for field, maximum in limits.items():
        if len(values[field]) > maximum:
            raise HTTPException(422, f"El campo {field.replace('_', ' ')} supera el máximo de {maximum} caracteres.")
    return values


def _check_company_uniqueness(db: Session, studio_id: int, values: dict, exclude_id: int | None = None) -> None:
    code_query = select(Company.id).where(
        Company.studio_id == studio_id, Company.company_code == values["company_code"]
    )
    if exclude_id is not None:
        code_query = code_query.where(Company.id != exclude_id)
    if db.scalar(code_query) is not None:
        raise HTTPException(409, "El Código Empresa ya existe dentro de este estudio.")

    new_ruc_digits = _ruc_digits(values["ruc"])
    existing_companies = db.scalars(select(Company).where(Company.studio_id == studio_id))
    for current in existing_companies:
        if exclude_id is not None and current.id == exclude_id:
            continue
        if _ruc_digits(current.ruc) == new_ruc_digits:
            raise HTTPException(409, "Ya existe una empresa con ese RUC dentro del estudio.")


def _apply_company_payload(db: Session, company: Company, values: dict) -> None:
    for field in (
        "company_code", "legal_name", "trade_name", "owner_name", "legal_representative", "address",
        "city", "work_sector", "work_location", "phone", "contact_name", "email",
        "ips_employer_number", "mtess_employer_number", "ruc", "responsible_name", "notes",
    ):
        setattr(company, field, values[field])
    company.updated_at = datetime.now(UTC)
    profile = _company_profile(db, company.id)
    if profile is None:
        profile = CompanyComplianceProfile(company_id=company.id)
        db.add(profile)
    profile.department = values["department"]
    profile.economic_activity = values["economic_activity"]
    profile.legal_representative_document = values["legal_representative_document"]


def _employee_profile(db: Session, employee_id: int) -> EmployeeComplianceProfile | None:
    return db.scalar(
        select(EmployeeComplianceProfile).where(EmployeeComplianceProfile.employee_id == employee_id)
    )


def _next_employee_code(db: Session, company_id: int) -> int:
    """Choose a readable legajo number scoped to one company; the DB constraint resolves races."""
    return int(db.scalar(
        select(func.max(Employee.employee_code)).where(Employee.company_id == company_id)
    ) or 0) + 1


def _employee_api_record(db: Session, employee: Employee) -> dict:
    profile = _employee_profile(db, employee.id)
    return {
        "id": employee.id,
        "employee_code": employee.employee_code,
        "company_id": employee.company_id,
        "company_name": employee.company.legal_name if employee.company else "",
        "branch_id": employee.branch_id,
        "branch_name": employee.branch.name if employee.branch else "",
        "section_id": employee.section_id,
        "section_name": employee.section.name if employee.section else "",
        "full_name": employee.full_name or "",
        "document_number": employee.document_number or "",
        "birth_date": employee.birth_date.isoformat() if employee.birth_date else None,
        "marital_status": profile.marital_status if profile else "",
        "nationality": profile.nationality if profile else "Paraguaya",
        "position": employee.position or "",
        "position_category": profile.position_category if profile else "",
        "admission_date": employee.admission_date.isoformat() if employee.admission_date else None,
        "termination_date": employee.termination_date.isoformat() if employee.termination_date else None,
        "contract_type": employee.contract_type or "Tiempo indefinido",
        "payment_frequency": employee.payment_frequency or "Mensual",
        "base_salary": int(employee.base_salary or 0),
        "ips_contributor": bool(employee.ips_contributor),
        "salary_type": profile.salary_type if profile else employee.payment_frequency or "Mensual",
        "work_schedule": profile.work_schedule if profile else "",
        "shift": profile.shift if profile else "Diurno",
        "weekly_hours": int(profile.weekly_hours if profile else 48),
        "daily_hours": int(profile.daily_hours if profile else 8),
        "ips_number": profile.ips_number if profile else "",
        "email": employee.email or "",
        "phone": employee.phone or "",
        "address": employee.address or "",
        "status": employee.status or "Activo",
        "notes": employee.notes or "",
        "created_at": employee.created_at.isoformat() if employee.created_at else None,
        "updated_at": employee.updated_at.isoformat() if employee.updated_at else None,
        "updated_by": employee.updated_by or "",
    }


def _validate_employee_payload(
    db: Session, payload: dict, existing: Employee | None = None
) -> dict:
    company_id = optional_int(payload.get("company_id"), field="empresa")
    if not company_id:
        raise HTTPException(422, "Seleccioná la empresa del funcionario.")
    company = db.get(Company, company_id)
    if not company or company.status == "Archivada":
        raise HTTPException(404, "La empresa seleccionada no está disponible.")

    raw_code = payload.get("employee_code", existing.employee_code if existing else None)
    if raw_code in (None, "") and existing:
        raw_code = existing.employee_code
    # Legacy fixtures/import paths may create an employee row without a legajo;
    # when editing that existing row, assign the next code instead of blocking
    # unrelated changes. New employee creation still requires a code in the API.
    if raw_code in (None, "") and existing:
        raw_code = _next_employee_code(db, company_id)
    if raw_code in (None, ""):
        raise HTTPException(422, "El Código Legajo es obligatorio.")
    try:
        employee_code = int(str(raw_code).strip())
    except (TypeError, ValueError):
        raise HTTPException(422, "El Código Legajo debe ser numérico.")
    if employee_code <= 0 or employee_code > 2_147_483_647:
        raise HTTPException(422, "El Código Legajo debe ser un entero positivo.")

    full_name = clean_text(payload.get("full_name", existing.full_name if existing else ""), max_length=180)
    if not full_name:
        raise HTTPException(422, "El nombre completo del funcionario es obligatorio.")
    if len(full_name) > 180:
        raise HTTPException(422, "El nombre completo no puede superar los 180 caracteres.")

    document_number = normalize_document_number(
        str(payload.get("document_number", existing.document_number if existing else "") or "")
    )
    if not document_number:
        raise HTTPException(422, "La cédula o documento del funcionario es obligatorio.")
    if len(document_number) > 40:
        raise HTTPException(422, "La cédula no puede superar los 40 caracteres.")

    position = clean_text(payload.get("position", existing.position if existing else ""), max_length=140)
    if not position:
        raise HTTPException(422, "El cargo es obligatorio.")

    admission_raw = payload.get("admission_date", existing.admission_date if existing else None)
    admission_date = optional_date(admission_raw, field="fecha de ingreso")
    if not admission_date:
        raise HTTPException(422, "La fecha de ingreso es obligatoria y debe ser válida.")

    birth_date = optional_date(
        payload.get("birth_date", existing.birth_date if existing else None),
        field="fecha de nacimiento",
    )
    if birth_date and (birth_date >= admission_date or birth_date > date.today()):
        raise HTTPException(422, "La fecha de nacimiento debe ser anterior al ingreso y no puede ser futura.")

    termination_date = optional_date(
        payload.get("termination_date", existing.termination_date if existing else None),
        field="fecha de egreso",
    )
    if termination_date and termination_date < admission_date:
        raise HTTPException(422, "La fecha de egreso no puede ser anterior a la fecha de ingreso.")

    status_value = clean_text(payload.get("status", existing.status if existing else "Activo"), max_length=30)
    if status_value not in {"Activo", "Inactivo", "Desvinculado"}:
        raise HTTPException(422, "El estado seleccionado no es válido. El archivo de legajos se realiza mediante la acción específica de archivo.")
    if status_value in {"Inactivo", "Desvinculado"} and not termination_date:
        raise HTTPException(422, "Indicá la fecha de egreso para un funcionario inactivo o desvinculado.")
    if status_value == "Activo":
        termination_date = None

    base_salary_raw = payload.get("base_salary", existing.base_salary if existing else None)
    if base_salary_raw in (None, ""):
        raise HTTPException(422, "El salario convenido es obligatorio.")
    try:
        base_salary = int(str(base_salary_raw).strip())
    except (TypeError, ValueError):
        raise HTTPException(422, "El salario convenido debe ser un número entero en guaraníes.")
    if base_salary < 0:
        raise HTTPException(422, "El salario convenido no puede ser negativo.")
    if existing and base_salary != int(existing.base_salary or 0):
        raise HTTPException(409, "El salario vigente solo puede modificarse mediante una solicitud salarial aprobada.")

    contract_type = clean_text(
        payload.get("contract_type", existing.contract_type if existing else "Tiempo indefinido"),
        max_length=80,
    ) or "Tiempo indefinido"
    payment_frequency = clean_text(
        payload.get("payment_frequency", existing.payment_frequency if existing else "Mensual"),
        max_length=40,
    ) or "Mensual"

    def parse_fk(name: str, old_value: int | None = None) -> int | None:
        raw = payload.get(name, old_value)
        value = optional_int(raw, field=name) if raw not in (None, "") else None
        if value is not None and value <= 0:
            raise HTTPException(422, f"El campo {name} debe ser positivo.")
        return value

    branch_id = parse_fk("branch_id", existing.branch_id if existing else None)
    if branch_id is not None:
        branch = db.get(Branch, branch_id)
        if (
            not branch
            or branch.company_id != company_id
            or (not branch.active and not (existing and existing.branch_id == branch_id))
        ):
            raise HTTPException(422, "La sucursal debe pertenecer a la empresa seleccionada y estar activa.")

    section_id = parse_fk("section_id", existing.section_id if existing else None)
    if section_id is not None:
        section = db.get(CompanySection, section_id)
        if (
            not section
            or section.company_id != company_id
            or (not section.active and not (existing and existing.section_id == section_id))
        ):
            raise HTTPException(422, "La sección debe pertenecer a la empresa seleccionada y estar activa.")

    email = clean_text(payload.get("email", existing.email if existing else ""), max_length=180)
    if email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise HTTPException(422, "El correo electrónico no tiene un formato válido.")

    def boolean_value(value, default=False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "on", "yes", "si", "sí"}

    profile = _employee_profile(db, existing.id) if existing else None
    weekly_hours_raw = payload.get("weekly_hours", profile.weekly_hours if profile else 48)
    try:
        weekly_hours = int(weekly_hours_raw or 48)
    except (TypeError, ValueError):
        raise HTTPException(422, "Las horas semanales deben ser un número entero.")
    if not 1 <= weekly_hours <= 96:
        raise HTTPException(422, "Las horas semanales deben estar entre 1 y 96.")
    daily_hours_raw = payload.get("daily_hours", profile.daily_hours if profile else 8)
    try:
        daily_hours = int(daily_hours_raw or 8)
    except (TypeError, ValueError):
        raise HTTPException(422, "Las horas diarias deben ser un número entero.")
    if not 1 <= daily_hours <= 24:
        raise HTTPException(422, "Las horas diarias deben estar entre 1 y 24.")
    ips_number = re.sub(
        r"[\s.-]+", "",
        str(payload.get("ips_number", profile.ips_number if profile else "") or "")
    )
    if ips_number and not ips_number.isdigit():
        raise HTTPException(422, "El número IPS del funcionario debe contener solamente dígitos.")

    values = {
        "employee_code": employee_code,
        "company_id": company_id,
        "branch_id": branch_id,
        "section_id": section_id,
        "full_name": full_name,
        "document_number": document_number,
        "birth_date": birth_date,
        "position": position,
        "admission_date": admission_date,
        "termination_date": termination_date,
        "contract_type": contract_type,
        "payment_frequency": payment_frequency,
        "base_salary": base_salary,
        "ips_contributor": boolean_value(
            payload.get("ips_contributor"), existing.ips_contributor if existing else True
        ),
        "email": email,
        "phone": clean_text(payload.get("phone", existing.phone if existing else ""), max_length=60),
        "address": clean_text(payload.get("address", existing.address if existing else ""), max_length=240),
        "status": status_value,
        "notes": clean_text(payload.get("notes", existing.notes if existing else ""), max_length=5000),
        "nationality": clean_text(
            payload.get("nationality", profile.nationality if profile else "Paraguaya"), max_length=80
        ) or "Paraguaya",
        "marital_status": clean_text(
            payload.get("marital_status", profile.marital_status if profile else ""), max_length=40
        ),
        "position_category": clean_text(
            payload.get("position_category", profile.position_category if profile else ""), max_length=100
        ),
        "work_schedule": clean_text(
            payload.get("work_schedule", profile.work_schedule if profile else ""), max_length=120
        ),
        "shift": clean_text(payload.get("shift", profile.shift if profile else "Diurno"), max_length=60) or "Diurno",
        "weekly_hours": weekly_hours,
        "daily_hours": daily_hours,
        "ips_number": ips_number,
        "salary_type": clean_text(
            payload.get("salary_type", profile.salary_type if profile else payment_frequency), max_length=40
        ) or payment_frequency,
    }
    if len(values["phone"]) > 60 or len(values["address"]) > 240:
        raise HTTPException(422, "Revisá el largo del teléfono o la dirección.")
    return values


def _check_employee_uniqueness(
    db: Session, values: dict, exclude_id: int | None = None
) -> None:
    code_query = select(Employee.id).where(
        Employee.company_id == values["company_id"],
        Employee.employee_code == values["employee_code"],
    )
    document_query = select(Employee).where(Employee.company_id == values["company_id"])
    if exclude_id is not None:
        code_query = code_query.where(Employee.id != exclude_id)
        document_query = document_query.where(Employee.id != exclude_id)
    if db.scalar(code_query) is not None:
        raise HTTPException(409, "Ese Código Legajo ya existe dentro de la empresa.")
    normalized_document = values["document_number"]
    for current in db.scalars(document_query):
        if normalize_document_number(current.document_number) == normalized_document:
            raise HTTPException(409, "Ya existe un funcionario con esa cédula dentro de la empresa.")


def _apply_employee_payload(
    db: Session, employee: Employee, values: dict, user: User
) -> None:
    for field in (
        "employee_code", "branch_id", "section_id", "full_name", "document_number",
        "birth_date", "position", "admission_date", "termination_date", "contract_type",
        "payment_frequency", "base_salary", "ips_contributor", "email", "phone", "address",
        "status", "notes",
    ):
        setattr(employee, field, values[field])
    employee.updated_at = datetime.now(UTC)
    employee.updated_by = user.email
    profile = _employee_profile(db, employee.id)
    if profile is None:
        profile = EmployeeComplianceProfile(employee_id=employee.id)
        db.add(profile)
    profile.nationality = values["nationality"]
    profile.marital_status = values["marital_status"]
    profile.position_category = values["position_category"]
    profile.work_schedule = values["work_schedule"]
    profile.shift = values["shift"]
    profile.weekly_hours = values["weekly_hours"]
    profile.daily_hours = values["daily_hours"]
    profile.ips_number = values["ips_number"]
    profile.salary_type = values["salary_type"]


async def _json_object(request: Request) -> dict:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(400, "El cuerpo de la solicitud debe ser JSON válido.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(422, "El cuerpo JSON debe ser un objeto.")
    return payload


def default_labor_context(
    request: Request,
    db: Session,
    user: User,
    allowed_company_ids: list[int],
    company_id: int | None,
    employee_id: int | None,
) -> tuple[int | None, int | None]:
    """Validate only the selectors submitted inside this module; do not carry them elsewhere."""
    if employee_id is not None:
        employee = db.get(Employee, employee_id)
        if not employee or employee.company_id not in allowed_company_ids:
            raise HTTPException(404, "Funcionario no encontrado en tu espacio de trabajo.")
        if company_id is not None and employee.company_id != company_id:
            raise HTTPException(400, "El funcionario no pertenece a la empresa seleccionada.")
        company_id = employee.company_id
    if company_id is not None and company_id not in allowed_company_ids:
        raise HTTPException(404, "Empresa no encontrada.")
    if user.role == "empresa":
        if user.company_id not in allowed_company_ids:
            raise HTTPException(403, "La cuenta no tiene una empresa asignada.")
        if company_id is not None and company_id != user.company_id:
            raise HTTPException(403, "No podés consultar otra empresa.")
        company_id = user.company_id
    return company_id, employee_id


def write_audit(db: Session, user: User, action: str, entity: str, entity_id: str = "", detail: str = "") -> None:
    db.add(
        AuditLog(
            studio_id=user.studio_id,
            user_email=user.email,
            action=action,
            entity=entity,
            entity_id=entity_id,
            detail=detail,
        )
    )


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return (forwarded or (request.client.host if request.client else ""))[:80]


def use_privileged_auth_context(db: Session) -> None:
    """Allow trusted pre-authentication/startup operations under PostgreSQL RLS."""
    db.info["user_id"] = None
    db.info["user_role"] = "superadmin"
    db.info["studio_id"] = None
    db.info["is_superadmin"] = True
    apply_session_tenant_context(db)


def security_rate_limited(
    db: Session, request: Request, *, event_types: tuple[str, ...], limit: int, minutes: int, failures_only: bool = False
) -> bool:
    cutoff = datetime.now(UTC) - timedelta(minutes=minutes)
    conditions = [
        SecurityEvent.ip_address == client_ip(request),
        SecurityEvent.event_type.in_(event_types),
        SecurityEvent.created_at >= cutoff,
    ]
    if failures_only:
        conditions.append(SecurityEvent.success.is_(False))
    count = db.scalar(select(func.count(SecurityEvent.id)).where(*conditions)) or 0
    return count >= limit


def write_security_event(
    db: Session, request: Request, event_type: str, success: bool,
    *, user: User | None = None, email: str = "", detail: str = "",
) -> None:
    db.add(
        SecurityEvent(
            studio_id=user.studio_id if user else None,
            user_id=user.id if user else None,
            email=(user.email if user else email).strip().lower()[:180],
            event_type=event_type[:80],
            success=success,
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent", "")[:300],
            detail=detail[:1000],
        )
    )


def establish_session(request: Request, user: User, security: UserSecurity) -> None:
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["security_version"] = security.session_version


def add_employee_event(
    db: Session, employee: Employee, user: User, event_type: str, title: str,
    detail: str = "", effective_date: date | None = None, amount: int | None = None,
) -> EmployeeEvent:
    event = EmployeeEvent(
        employee_id=employee.id,
        event_type=event_type,
        title=title,
        detail=detail,
        effective_date=effective_date or date.today(),
        amount=amount,
        created_by=user.email,
    )
    db.add(event)
    return event


def render(request: Request, template: str, db: Session, user: User | None = None, **context):
    csrf_token = request.session.get("csrf_token")
    if not csrf_token:
        csrf_token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = csrf_token
    data = {
        "request": request,
        "csrf_token": csrf_token,
        "user": user,
        "active_path": request.url.path,
        "today": date.today(),
        "environment": settings.environment,
        "notification_unread_count": 0,
        **context,
        "app_version": APP_VERSION,
        "app_build": APP_BUILD,
        "app_commit": APP_COMMIT,
        "app_branch": APP_BRANCH,
    }
    if user and user.role != "superadmin":
        data["notification_unread_count"] = db.scalar(
            select(func.count(Notification.id)).where(
                Notification.recipient_user_id == user.id,
                Notification.read_at.is_(None),
            )
        ) or 0
    if user and user.studio_id:
        data["studio"] = db.get(Studio, user.studio_id)
    return templates.TemplateResponse(request=request, name=template, context=data)


def format_gs(value: int | float | None) -> str:
    return f"{(value or 0):,.0f}".replace(",", ".")


def format_date(value: date | datetime | None) -> str:
    if not value:
        return "—"
    return value.strftime("%d/%m/%Y")


templates.env.filters["gs"] = format_gs
templates.env.filters["fecha"] = format_date

CERTIFICATE_TYPES = DOCUMENT_LABELS

templates.env.filters["fecha_larga"] = format_date_long_es


def build_certificate_body(
    document_type: str,
    company_name: str,
    employee_name: str,
    employee_document: str,
    position: str,
    admission_date: date | None,
    salary: int,
    observations: str,
) -> tuple[str, str]:
    """Compatibilidad con versiones anteriores y pruebas existentes."""
    return build_document_body(
        document_type,
        company_name=company_name,
        employee_name=employee_name,
        employee_document=employee_document,
        position=position,
        admission_date=admission_date,
        salary=salary,
        issue_date=date.today(),
        city="Ciudad del Este",
        metadata={"notes": observations},
    )

def get_parameter(db: Session, key: str, default: float = 0) -> float:
    parameter = db.scalar(select(LaborParameter).where(LaborParameter.key == key, LaborParameter.active.is_(True)))
    return float(parameter.value) if parameter else default


def safe_filename(name: str) -> str:
    base = Path(name).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    return cleaned[:180] or "archivo"


def recalculate_payroll(db: Session, payroll: Payroll) -> None:
    lines = list(db.scalars(select(PayrollLine).where(PayrollLine.payroll_id == payroll.id)))
    payroll.total_gross = sum(x.gross for x in lines)
    payroll.total_ips_employee = sum(x.ips_employee for x in lines)
    payroll.total_discounts = sum(x.total_discounts for x in lines)
    payroll.total_net = sum(x.net for x in lines)


def json_dict(raw: str | None) -> dict:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def get_or_create_branding(db: Session, company: Company) -> CompanyBranding:
    branding = db.scalar(select(CompanyBranding).where(CompanyBranding.company_id == company.id))
    if branding:
        return branding
    branding = CompanyBranding(
        company_id=company.id,
        signature_name=company.legal_representative or company.responsible_name or "",
        document_prefix=re.sub(r"[^A-Za-z0-9]", "", (company.trade_name or company.legal_name)[:3]).upper() or "DL",
    )
    db.add(branding)
    db.flush()
    return branding


def company_completeness(company: Company, branding: CompanyBranding | None) -> tuple[int, list[str]]:
    fields = {
        "RUC": company.ruc,
        "dirección": company.address,
        "teléfono": company.phone,
        "correo": company.email,
        "representante legal": company.legal_representative,
        "número patronal IPS": company.ips_employer_number,
        "registro MTESS": company.mtess_employer_number,
        "logo": bool(branding and branding.logo_bytes),
        "firma autorizada": bool(branding and branding.signature_name),
    }
    missing = [label for label, value in fields.items() if not value]
    score = round((len(fields) - len(missing)) * 100 / len(fields))
    return score, missing


def calculate_values(
    *,
    calculation_type: str,
    ips_rate: float,
    gross: int = 0,
    other_income: int = 0,
    other_discount: int = 0,
    ips_base: int | None = None,
    apply_ips: bool = True,
    salary: int = 0,
    monthly_hours: float = 240,
    hours_quantity: float = 0,
    multiplier: float = 1,
    total_remunerations: int = 0,
    days: float = 0,
) -> tuple[dict, dict, int]:
    inputs = {
        "gross": max(0, int(gross or 0)),
        "other_income": max(0, int(other_income or 0)),
        "other_discount": max(0, int(other_discount or 0)),
        "ips_base": max(0, int(ips_base)) if ips_base is not None else None,
        "apply_ips": bool(apply_ips),
        "salary": max(0, int(salary or 0)),
        "monthly_hours": max(1, float(monthly_hours or 240)),
        "hours_quantity": max(0, float(hours_quantity or 0)),
        "multiplier": max(0, float(multiplier or 1)),
        "total_remunerations": max(0, int(total_remunerations or 0)),
        "days": max(0, float(days or 0)),
    }
    if calculation_type == "salary":
        computable = inputs["gross"] + inputs["other_income"]
        effective_ips_base = inputs["ips_base"] if inputs["ips_base"] is not None else computable
        ips = round_gs(effective_ips_base * ips_rate / 100) if inputs["apply_ips"] else 0
        discounts = ips + inputs["other_discount"]
        amount = max(0, computable - discounts)
        results = {"gross_computable": computable, "ips_base": effective_ips_base, "ips_employee": ips, "discounts": discounts, "net": amount}
    elif calculation_type == "hours":
        base = inputs["salary"] / inputs["monthly_hours"]
        amount = round_gs(base * inputs["hours_quantity"] * inputs["multiplier"])
        results = {"hour_value": round_gs(base), "total": amount}
    elif calculation_type == "aguinaldo":
        amount = round_gs(inputs["total_remunerations"] / 12)
        results = {"total_remunerations": inputs["total_remunerations"], "aguinaldo": amount}
    elif calculation_type in {"vacation", "notice"}:
        daily = inputs["salary"] / 30
        amount = round_gs(daily * inputs["days"])
        results = {"daily_value": round_gs(daily), "days": inputs["days"], "total": amount}
    else:
        raise HTTPException(400, "Tipo de cálculo inválido.")
    return inputs, results, amount


def calculation_label(value: str) -> str:
    if value.startswith("suite_"):
        from .labor_calculator import TITLES
        return TITLES.get(value[6:], value)
    return {
        "salary": "Salario neto",
        "hours": "Horas",
        "aguinaldo": "Aguinaldo",
        "vacation": "Vacaciones",
        "notice": "Preaviso",
    }.get(value, value.capitalize())


def next_document_number(db: Session, company: Company, document_type: str, branding: CompanyBranding | None) -> str:
    year = date.today().year
    prefix = (branding.document_prefix if branding else "DL") or "DL"
    count = db.scalar(
        select(func.count(GeneratedCertificate.id)).where(
            GeneratedCertificate.company_id == company.id,
            GeneratedCertificate.document_type == document_type,
            func.extract("year", GeneratedCertificate.created_at) == year,
        )
    ) or 0
    code = re.sub(r"[^A-Za-z0-9]", "", document_type[:4]).upper()
    return f"{prefix}-{code}-{year}-{count + 1:05d}"


def build_ai_context(db: Session, company: Company | None, employee: Employee | None) -> dict:
    calculations: list[dict] = []
    if employee:
        items = list(
            db.scalars(
                select(CalculationRecord)
                .where(CalculationRecord.employee_id == employee.id)
                .order_by(CalculationRecord.created_at.desc())
                .limit(5)
            )
        )
        calculations = [
            {
                "id": item.id,
                "type": item.calculation_type,
                "period": item.reference_period,
                "amount": item.amount,
                "status": item.status,
                "results": json_dict(item.result_json),
            }
            for item in items
        ]
    return {
        "company": {
            "legal_name": company.legal_name if company else "",
            "ruc": company.ruc if company else "",
            "address": company.address if company else "",
            "legal_representative": company.legal_representative if company else "",
            "ips_employer_number": company.ips_employer_number if company else "",
            "mtess_employer_number": company.mtess_employer_number if company else "",
        },
        "employee": {
            "full_name": employee.full_name if employee else "",
            "document_number": employee.document_number if employee else "",
            "position": employee.position if employee else "",
            "admission_date": employee.admission_date.isoformat() if employee and employee.admission_date else "",
            "base_salary": employee.base_salary if employee else 0,
            "contract_type": employee.contract_type if employee else "",
            "ips_contributor": employee.ips_contributor if employee else False,
        },
        "calculations": calculations,
    }


@app.get("/", response_class=HTMLResponse)
def landing(request: Request, db: Session = Depends(get_db)):
    if current_user(request, db):
        return RedirectResponse("/app", status_code=303)
    return render(request, "landing.html", db)


@app.get("/activacion", response_class=HTMLResponse)
def activation_page(request: Request, db: Session = Depends(get_db)):
    return render(request, "activation.html", db, sent=request.query_params.get("sent") == "1")


@app.post("/activacion")
def activation_submit(
    request: Request,
    studio_name: Annotated[str, Form()],
    contact_name: Annotated[str, Form()],
    email: Annotated[str, Form()],
    phone: Annotated[str, Form()],
    estimated_companies: Annotated[int, Form()] = 1,
    message: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
):
    use_privileged_auth_context(db)
    if security_rate_limited(db, request, event_types=("solicitud_activacion",), limit=5, minutes=60):
        raise HTTPException(429, "Se alcanzó el límite temporal de solicitudes. Intentá nuevamente más tarde.")
    item = ActivationRequest(
        studio_name=studio_name.strip(),
        contact_name=contact_name.strip(),
        email=email.strip().lower(),
        phone=phone.strip(),
        estimated_companies=max(1, estimated_companies),
        message=message.strip(),
    )
    db.add(item)
    write_security_event(db, request, "solicitud_activacion", True, email=email.strip().lower(), detail=studio_name.strip())
    db.commit()
    return RedirectResponse("/activacion?sent=1", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    if current_user(request, db):
        return RedirectResponse("/app", status_code=303)
    return render(request, "login.html", db, error=None)


@app.post("/login")
def login_action(
    request: Request,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    db: Session = Depends(get_db),
):
    use_privileged_auth_context(db)
    if security_rate_limited(
        db, request, event_types=("inicio_sesion", "inicio_sesion_bloqueado"), limit=30, minutes=15, failures_only=True
    ):
        return render(request, "login.html", db, error="Demasiados intentos desde esta conexión. Esperá unos minutos.")
    normalized_email = email.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == normalized_email))
    security = get_or_create_security(db, user) if user else None
    if security and is_locked(security):
        write_security_event(db, request, "inicio_sesion_bloqueado", False, user=user, detail="Cuenta temporalmente bloqueada")
        db.commit()
        return render(request, "login.html", db, error="Demasiados intentos. La cuenta está bloqueada temporalmente.")
    if not user or not verify_password(password, user.password_hash) or not user.active:
        if security:
            record_failed_login(security)
        write_security_event(db, request, "inicio_sesion", False, user=user, email=normalized_email, detail="Credenciales inválidas o cuenta inactiva")
        db.commit()
        return render(request, "login.html", db, error="Correo o contraseña incorrectos.")
    if user.role != "superadmin" and user.studio and (not user.studio.active or user.studio.payment_status != "Activo"):
        write_security_event(db, request, "inicio_sesion", False, user=user, detail="Estudio suspendido o pago no activo")
        db.commit()
        return render(request, "login.html", db, error="La cuenta todavía no está habilitada o su plan se encuentra suspendido.")
    db.info["studio_id"] = user.studio_id
    db.info["is_superadmin"] = user.role == "superadmin"
    apply_session_tenant_context(db)
    reset_login_failures(security)
    if security.totp_enabled:
        request.session.clear()
        request.session["pending_2fa_user_id"] = user.id
        request.session["pending_2fa_at"] = datetime.now(UTC).isoformat()
        db.commit()
        return RedirectResponse("/login/2fa", status_code=303)
    establish_session(request, user, security)
    user.last_login_at = datetime.now(UTC)
    write_audit(db, user, "inicio_sesion", "usuario", str(user.id))
    write_security_event(db, request, "inicio_sesion", True, user=user)
    db.commit()
    return RedirectResponse("/admin" if user.role == "superadmin" else "/app", status_code=303)


@app.get("/login/2fa", response_class=HTMLResponse)
def login_2fa_page(request: Request, db: Session = Depends(get_db)):
    pending_id = request.session.get("pending_2fa_user_id")
    if not pending_id:
        return RedirectResponse("/login", status_code=303)
    user = db.get(User, int(pending_id))
    if not user:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)
    return render(request, "login_2fa.html", db, pending_email=user.email, error=None)


@app.post("/login/2fa")
def login_2fa_action(
    request: Request,
    code: Annotated[str, Form()],
    db: Session = Depends(get_db),
):
    use_privileged_auth_context(db)
    pending_id = request.session.get("pending_2fa_user_id")
    pending_at = request.session.get("pending_2fa_at", "")
    if not pending_id:
        return RedirectResponse("/login", status_code=303)
    try:
        requested_at = datetime.fromisoformat(pending_at)
        if requested_at.tzinfo is None:
            requested_at = requested_at.replace(tzinfo=UTC)
    except ValueError:
        requested_at = datetime.now(UTC) - timedelta(hours=1)
    if requested_at < datetime.now(UTC) - timedelta(minutes=10):
        request.session.clear()
        return RedirectResponse("/login?expired=1", status_code=303)
    user = db.get(User, int(pending_id))
    if not user:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)
    security = get_or_create_security(db, user)
    if is_locked(security):
        write_security_event(db, request, "segundo_factor_bloqueado", False, user=user, detail="Segundo factor intentado durante bloqueo temporal")
        db.commit()
        return render(
            request, "login_2fa.html", db, pending_email=user.email,
            error="La cuenta está bloqueada temporalmente por intentos fallidos. Volvé a iniciar sesión más tarde.",
        )
    if security_rate_limited(
        db, request, event_types=("segundo_factor",), limit=15, minutes=15, failures_only=True
    ):
        write_security_event(db, request, "segundo_factor_bloqueado", False, user=user, detail="Límite de intentos TOTP por conexión")
        db.commit()
        return render(
            request, "login_2fa.html", db, pending_email=user.email,
            error="Se alcanzó el límite de códigos de esta conexión. Esperá unos minutos antes de volver a intentar.",
        )
    if not verify_totp(security.totp_secret, code):
        record_failed_login(security)
        write_security_event(db, request, "segundo_factor", False, user=user, detail="Código TOTP inválido")
        db.commit()
        return render(request, "login_2fa.html", db, pending_email=user.email, error="El código no es válido.")
    reset_login_failures(security)
    db.info["studio_id"] = user.studio_id
    db.info["is_superadmin"] = user.role == "superadmin"
    apply_session_tenant_context(db)
    establish_session(request, user, security)
    user.last_login_at = datetime.now(UTC)
    write_audit(db, user, "inicio_sesion_2fa", "usuario", str(user.id))
    write_security_event(db, request, "segundo_factor", True, user=user)
    db.commit()
    return RedirectResponse("/admin" if user.role == "superadmin" else "/app", status_code=303)


@app.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request, db: Session = Depends(get_db)):
    return render(request, "forgot_password.html", db, sent=False, debug_url=None)


@app.post("/forgot-password", response_class=HTMLResponse)
def forgot_password_action(
    request: Request,
    email: Annotated[str, Form()],
    db: Session = Depends(get_db),
):
    use_privileged_auth_context(db)
    if security_rate_limited(db, request, event_types=("solicitud_restablecimiento",), limit=5, minutes=15):
        return render(request, "forgot_password.html", db, sent=True, debug_url=None)
    normalized = email.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == normalized, User.active.is_(True)))
    debug_url = None
    if user:
        _, raw_token = create_password_reset(db, user, client_ip(request))
        reset_url = f"{settings.public_url.rstrip('/')}/reset-password/{raw_token}"
        sent = False
        try:
            sent = send_password_reset_email(user.email, reset_url)
        except Exception:
            sent = False
        if settings.environment != "production" and not sent:
            debug_url = reset_url
        write_security_event(db, request, "solicitud_restablecimiento", True, user=user, detail="Correo enviado" if sent else "SMTP no configurado")
    else:
        write_security_event(db, request, "solicitud_restablecimiento", False, email=normalized, detail="Correo no registrado")
    db.commit()
    return render(request, "forgot_password.html", db, sent=True, debug_url=debug_url)


@app.get("/reset-password/{token}", response_class=HTMLResponse)
def reset_password_page(token: str, request: Request, db: Session = Depends(get_db)):
    item = validate_password_reset(db, token)
    return render(request, "reset_password.html", db, token=token, valid=bool(item), error=None)


@app.post("/reset-password/{token}", response_class=HTMLResponse)
def reset_password_action(
    token: str,
    request: Request,
    password: Annotated[str, Form()],
    password_confirm: Annotated[str, Form()],
    db: Session = Depends(get_db),
):
    use_privileged_auth_context(db)
    item = validate_password_reset(db, token)
    if not item:
        return render(request, "reset_password.html", db, token=token, valid=False, error="El enlace no es válido o ya venció.")
    if password != password_confirm:
        return render(request, "reset_password.html", db, token=token, valid=True, error="Las contraseñas no coinciden.")
    strength_error = password_strength_error(password)
    if strength_error:
        return render(request, "reset_password.html", db, token=token, valid=True, error=strength_error)
    user = db.get(User, item.user_id)
    if not user:
        return render(request, "reset_password.html", db, token=token, valid=False, error="Cuenta no encontrada.")
    user.password_hash = hash_password(password)
    user.must_change_password = False
    item.used_at = datetime.now(UTC)
    security = get_or_create_security(db, user)
    security.session_version += 1
    security.password_changed_at = datetime.now(UTC)
    reset_login_failures(security)
    write_security_event(db, request, "restablecimiento_contrasena", True, user=user)
    db.commit()
    return RedirectResponse("/login?reset=1", status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/app", response_class=HTMLResponse)
def dashboard(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    if user.role == "superadmin":
        return RedirectResponse("/admin", status_code=303)
    company_ids = company_ids_for_user(db, user)
    companies_count = len(company_ids)
    employee_count = db.scalar(select(func.count(Employee.id)).where(Employee.company_id.in_(company_ids), Employee.status == "Activo")) if company_ids else 0
    pending_count = db.scalar(select(func.count(CompanyRequest.id)).where(CompanyRequest.company_id.in_(company_ids), CompanyRequest.status.in_(["Pendiente", "En revisión", "Falta información", "Procesando", "Aprobada"]))) if company_ids else 0
    if user.role == "abogado" and company_ids:
        pending_count = db.scalar(
            select(func.count(CompanyRequest.id))
            .join(RequestWorkflow, RequestWorkflow.request_id == CompanyRequest.id)
            .where(
                CompanyRequest.company_id.in_(company_ids),
                RequestWorkflow.assigned_user_id == user.id,
                CompanyRequest.status.in_(["Pendiente", "En revisión", "Falta información", "Procesando", "Aprobada"]),
            )
        ) or 0
    payroll_count = db.scalar(select(func.count(Payroll.id)).where(Payroll.company_id.in_(company_ids), Payroll.status == "Borrador")) if company_ids else 0
    compliance_pending_count = db.scalar(
        select(func.count(ComplianceEvent.id)).where(
            ComplianceEvent.company_id.in_(company_ids),
            ComplianceEvent.status.in_(["Borrador", "Validado", "Exportado", "Observado"]),
        )
    ) if company_ids else 0
    compliance_overdue_count = db.scalar(
        select(func.count(ComplianceEvent.id)).where(
            ComplianceEvent.company_id.in_(company_ids),
            ComplianceEvent.due_date < date.today(),
            ComplianceEvent.status.notin_(["Presentado", "Aceptado", "Anulado"]),
        )
    ) if company_ids else 0
    companies = list(db.scalars(select(Company).where(Company.id.in_(company_ids)).order_by(Company.created_at.desc()).limit(5))) if company_ids else []
    if user.role == "abogado" and company_ids:
        recent_requests = list(
            db.scalars(
                select(CompanyRequest)
                .join(RequestWorkflow, RequestWorkflow.request_id == CompanyRequest.id)
                .where(
                    CompanyRequest.company_id.in_(company_ids),
                    RequestWorkflow.assigned_user_id == user.id,
                )
                .order_by(RequestWorkflow.due_date.asc().nullslast(), CompanyRequest.created_at.desc())
                .limit(5)
            )
        )
    else:
        recent_requests = list(
            db.scalars(
                select(CompanyRequest)
                .where(CompanyRequest.company_id.in_(company_ids))
                .order_by(CompanyRequest.created_at.desc())
                .limit(5)
            )
        ) if company_ids else []
    documents_count = db.scalar(select(func.count(Document.id)).where(Document.company_id.in_(company_ids))) if company_ids else 0
    certificates_count = db.scalar(select(func.count(GeneratedCertificate.id)).where(GeneratedCertificate.company_id.in_(company_ids))) if company_ids else 0
    minimum_salary = db.scalar(select(LaborParameter).where(LaborParameter.key == "minimum_monthly_salary_general", LaborParameter.active.is_(True)))
    low_salary_count = 0
    if company_ids and minimum_salary:
        low_salary_count = db.scalar(select(func.count(Employee.id)).where(Employee.company_id.in_(company_ids), Employee.status == "Activo", Employee.base_salary < int(minimum_salary.value))) or 0
    branding_items = list(db.scalars(select(CompanyBranding).where(CompanyBranding.company_id.in_(company_ids)))) if company_ids else []
    branded_ids = {item.company_id for item in branding_items if item.logo_bytes}
    missing_logo_count = len([company_id for company_id in company_ids if company_id not in branded_ids])
    incomplete_company_count = 0
    for company in list(db.scalars(select(Company).where(Company.id.in_(company_ids)))) if company_ids else []:
        branding = next((item for item in branding_items if item.company_id == company.id), None)
        score, _ = company_completeness(company, branding)
        if score < 80:
            incomplete_company_count += 1
    recent_calculations = list(
        db.scalars(
            select(CalculationRecord)
            .where(CalculationRecord.company_id.in_(company_ids))
            .order_by(CalculationRecord.created_at.desc())
            .limit(5)
        )
    ) if company_ids else []
    automation_alerts = []
    upcoming_deadlines = list(db.scalars(select(LaborDeadline).where(
        LaborDeadline.company_id.in_(company_ids), LaborDeadline.status == "Pendiente",
        LaborDeadline.due_date <= date.today() + timedelta(days=7),
    ).order_by(LaborDeadline.due_date))) if company_ids else []
    overdue_deadlines = [item for item in upcoming_deadlines if item.due_date < date.today()]
    if overdue_deadlines:
        automation_alerts.append({"level": "danger", "title": "Vencimientos atrasados", "detail": f"{len(overdue_deadlines)} tareas superaron su fecha límite.", "href": "/app/calendar"})
    elif upcoming_deadlines:
        automation_alerts.append({"level": "warning", "title": "Agenda de los próximos días", "detail": f"{len(upcoming_deadlines)} tareas vencen dentro de 7 días.", "href": "/app/calendar"})
    if pending_count:
        automation_alerts.append({"level": "warning", "title": "Solicitudes pendientes", "detail": f"{pending_count} solicitudes necesitan seguimiento.", "href": "/app/requests"})
    if missing_logo_count:
        automation_alerts.append({"level": "info", "title": "Identidad visual incompleta", "detail": f"{missing_logo_count} empresas todavía no cargaron su logo.", "href": "/app/companies"})
    if incomplete_company_count:
        automation_alerts.append({"level": "warning", "title": "Expedientes incompletos", "detail": f"{incomplete_company_count} empresas tienen menos del 80% de datos completos.", "href": "/app/companies"})
    if low_salary_count:
        automation_alerts.append({"level": "danger", "title": "Salarios para revisar", "detail": f"{low_salary_count} funcionarios están por debajo del parámetro general cargado.", "href": "/app/employees"})
    if compliance_overdue_count:
        automation_alerts.insert(0, {"level": "danger", "title": "Cumplimiento vencido", "detail": f"{compliance_overdue_count} comunicaciones REI/REOP superaron su fecha prevista.", "href": "/app/compliance"})
    elif compliance_pending_count:
        automation_alerts.append({"level": "warning", "title": "Presentaciones pendientes", "detail": f"{compliance_pending_count} registros REI/REOP requieren validación o presentación.", "href": "/app/compliance"})
    return render(
        request,
        "dashboard.html",
        db,
        user,
        companies_count=companies_count,
        employee_count=employee_count or 0,
        documents_count=documents_count or 0,
        certificates_count=certificates_count or 0,
        pending_count=pending_count or 0,
        payroll_count=payroll_count or 0,
        compliance_pending_count=compliance_pending_count or 0,
        compliance_overdue_count=compliance_overdue_count or 0,
        companies=companies,
        recent_requests=recent_requests,
        minimum_salary=minimum_salary,
        low_salary_count=low_salary_count,
        missing_logo_count=missing_logo_count,
        incomplete_company_count=incomplete_company_count,
        recent_calculations=recent_calculations,
        automation_alerts=automation_alerts,
    )


@app.get("/app/companies", response_class=HTMLResponse)
def companies_page(
    request: Request,
    q: str = "",
    city: str = "",
    department: str = "",
    show_archived: bool = False,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    if user.role == "empresa":
        return RedirectResponse(f"/app/companies/{user.company_id}", status_code=303)
    company_ids = company_ids_for_user(db, user)
    query = select(Company).where(Company.id.in_(company_ids)) if company_ids else select(Company).where(False)
    if not show_archived:
        query = query.where(Company.status != "Archivada")
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.where(or_(
            Company.legal_name.ilike(term),
            Company.ruc.ilike(term),
            Company.trade_name.ilike(term),
            func.cast(Company.company_code, String).ilike(term),
        ))
    if city.strip():
        query = query.where(Company.city == city.strip())
    if department.strip():
        query = query.where(Company.id.in_(
            select(CompanyComplianceProfile.company_id).where(CompanyComplianceProfile.department == department.strip())
        ))
    companies = list(db.scalars(query.order_by(Company.legal_name)))
    return render(
        request, "companies.html", db, user, companies=companies, q=q, selected_city=city,
        selected_department=department, show_archived=show_archived,
        departments=PARAGUAY_DEPARTMENTS, cities=PARAGUAY_CITIES,
    )


@app.post("/app/companies")
def add_company(
    legal_name: Annotated[str, Form()],
    ruc: Annotated[str, Form()],
    company_code: Annotated[str, Form()] = "",
    trade_name: Annotated[str, Form()] = "",
    owner_name: Annotated[str, Form()] = "",
    city: Annotated[str, Form()] = "Ciudad del Este",
    department: Annotated[str, Form()] = "",
    address: Annotated[str, Form()] = "",
    work_sector: Annotated[str, Form()] = "",
    work_location: Annotated[str, Form()] = "",
    economic_activity: Annotated[str, Form()] = "",
    phone: Annotated[str, Form()] = "",
    contact_name: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "",
    legal_representative: Annotated[str, Form()] = "",
    legal_representative_document: Annotated[str, Form()] = "",
    ips_employer_number: Annotated[str, Form()] = "",
    mtess_employer_number: Annotated[str, Form()] = "",
    responsible_name: Annotated[str, Form()] = "Sin asignar",
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    def form_error(message: str) -> RedirectResponse:
        return RedirectResponse(
            f"/app/companies?form_error={quote(message)}&open=companyModal",
            status_code=303,
        )

    name_value = legal_name.strip()
    if not name_value:
        return form_error("El nombre de la empresa es obligatorio.")
    if len(name_value) > 200:
        return form_error("El nombre de la empresa no puede superar los 200 caracteres.")
    if not ruc.strip():
        return form_error("El RUC es obligatorio.")
    normalized_ruc = normalize_company_ruc(ruc)
    if not normalized_ruc:
        return form_error("El RUC debe tener entre 3 y 8 dígitos base y un dígito verificador válido (módulo 11).")
    try:
        code_value = int(company_code.strip())
        if code_value <= 0 or code_value > 2_147_483_647:
            raise ValueError
    except ValueError:
        return form_error("El Código Empresa es obligatorio y debe ser numérico.")
    if department.strip() and department.strip() not in PARAGUAY_DEPARTMENTS:
        return form_error("Seleccioná un departamento válido de Paraguay.")
    if city.strip() and city.strip() not in PARAGUAY_CITY_NAMES:
        return form_error("Seleccioná una ciudad de la lista de localidades paraguayas.")
    if city.strip() and department.strip() and not any(
        item["name"] == city.strip() and item["department"] == department.strip() for item in PARAGUAY_CITIES
    ):
        return form_error("La ciudad seleccionada no corresponde al departamento indicado.")
    ips_clean = re.sub(r"[\s.-]+", "", ips_employer_number)
    mjt_clean = re.sub(r"[\s.-]+", "", mtess_employer_number)
    ci_clean = re.sub(r"[\s.-]+", "", legal_representative_document)
    if ips_clean and not ips_clean.isdigit():
        return form_error("El número patronal IPS debe contener solamente dígitos.")
    if mjt_clean and not mjt_clean.isdigit():
        return form_error("El número patronal MJT debe contener solamente dígitos.")
    if ci_clean and not ci_clean.isdigit():
        return form_error("El número de C.I. debe contener solamente dígitos.")

    code_exists = db.scalar(select(Company.id).where(
        Company.studio_id == user.studio_id, Company.company_code == code_value
    ))
    if code_exists:
        return RedirectResponse(
            f"/app/companies?code_duplicate=1&open=companyModal&company_code={code_value}",
            status_code=303,
        )
    duplicate_ruc = any(
        _ruc_digits(current.ruc) == _ruc_digits(normalized_ruc)
        for current in db.scalars(select(Company).where(Company.studio_id == user.studio_id))
    )
    if duplicate_ruc:
        return RedirectResponse("/app/companies?duplicate=1&open=companyModal", status_code=303)

    studio = db.get(Studio, user.studio_id)
    count = db.scalar(select(func.count(Company.id)).where(Company.studio_id == user.studio_id)) or 0
    if studio and count >= studio.company_limit:
        return RedirectResponse("/app/companies?limit=1", status_code=303)
    company = Company(
        studio_id=user.studio_id,
        company_code=code_value,
        legal_name=name_value,
        trade_name=trade_name.strip(),
        owner_name=owner_name.strip(),
        ruc=normalized_ruc,
        city=city.strip(),
        address=address.strip(),
        work_sector=work_sector.strip(),
        work_location=work_location.strip(),
        phone=phone.strip(),
        contact_name=contact_name.strip(),
        email=email.strip(),
        legal_representative=legal_representative.strip(),
        ips_employer_number=ips_clean,
        mtess_employer_number=mjt_clean,
        responsible_name=responsible_name.strip() or "Sin asignar",
        updated_at=datetime.now(UTC),
    )
    db.add(company)
    try:
        db.flush()
        db.add(CompanyComplianceProfile(
            company_id=company.id,
            department=department.strip(),
            economic_activity=economic_activity.strip(),
            legal_representative_document=ci_clean,
        ))
        db.add(Branch(company_id=company.id, name="Casa central", city=company.city, address=company.address))
        get_or_create_branding(db, company)
        write_audit(db, user, "crear", "empresa", str(company.id), f"Código {company.company_code} · {company.legal_name}")
        db.commit()
    except IntegrityError:
        db.rollback()
        return RedirectResponse("/app/companies?duplicate=1&open=companyModal", status_code=303)
    return RedirectResponse(f"/app/companies/{company.id}", status_code=303)


@app.get("/app/companies/{company_id}", response_class=HTMLResponse)
def company_detail(request: Request, company_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    company = company_allowed(db, user, company_id)
    employees = list(db.scalars(select(Employee).where(Employee.company_id == company_id).order_by(Employee.full_name)))
    requests_list = list(db.scalars(select(CompanyRequest).where(CompanyRequest.company_id == company_id).order_by(CompanyRequest.created_at.desc()).limit(10)))
    branches = list(db.scalars(select(Branch).where(Branch.company_id == company_id).order_by(Branch.name)))
    payrolls = list(db.scalars(select(Payroll).where(Payroll.company_id == company_id).order_by(Payroll.period.desc()).limit(6)))
    documents = list(db.scalars(select(Document).where(Document.company_id == company_id).order_by(Document.created_at.desc()).limit(8)))
    branding = get_or_create_branding(db, company)
    compliance_profile = _company_profile(db, company.id)
    completeness_score, missing_fields = company_completeness(company, branding)
    calculations = list(db.scalars(select(CalculationRecord).where(CalculationRecord.company_id == company_id).order_by(CalculationRecord.created_at.desc()).limit(6)))
    certificates_count = db.scalar(select(func.count(GeneratedCertificate.id)).where(GeneratedCertificate.company_id == company_id)) or 0
    db.commit()
    return render(
        request,
        "company_detail.html",
        db,
        user,
        company=company,
        employees=employees,
        requests_list=requests_list,
        branches=branches,
        payrolls=payrolls,
        documents=documents,
        branding=branding,
        completeness_score=completeness_score,
        missing_fields=missing_fields,
        calculations=calculations,
        certificates_count=certificates_count,
        compliance_profile=compliance_profile,
        departments=PARAGUAY_DEPARTMENTS,
        cities=PARAGUAY_CITIES,
    )


@app.get("/app/companies/{company_id}/logo")
def company_logo(company_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    company = company_allowed(db, user, company_id)
    branding = db.scalar(select(CompanyBranding).where(CompanyBranding.company_id == company.id))
    if not branding or not branding.logo_bytes:
        raise HTTPException(404, "Logo no encontrado.")
    return Response(
        content=branding.logo_bytes,
        media_type=branding.logo_content_type or "image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@app.post("/app/companies/{company_id}/logo")
async def upload_company_logo(
    company_id: int,
    logo: UploadFile = File(...),
    user: User = Depends(require_roles("administrador", "contador", "auxiliar", "empresa")),
    db: Session = Depends(get_db),
):
    company = company_allowed(db, user, company_id)
    target = f"/app/companies/{company.id}"

    def upload_error(message: str) -> RedirectResponse:
        return RedirectResponse(
            f"{target}?logo_error={quote(message)}&open=brandingModal",
            status_code=303,
        )

    if not logo.filename:
        return upload_error("Seleccioná una imagen antes de guardar.")

    upload_limit = max(settings.max_logo_size, 8 * 1024 * 1024)
    content = await logo.read(upload_limit + 1)
    if not content:
        return upload_error("El archivo seleccionado está vacío.")
    if len(content) > upload_limit:
        return upload_error(f"El logo supera el máximo permitido de {upload_limit / (1024 * 1024):g} MB.")
    if detect_logo_content_type(content) is None:
        return upload_error("El logo debe ser una imagen PNG, JPG/JPEG o WEBP válida.")

    try:
        optimized_bytes, optimized_type = smart_normalize_logo(content)
    except Exception as exc:
        logger.warning("Company logo processing failed for company_id=%s (%s)", company.id, type(exc).__name__)
        return upload_error("No se pudo procesar la imagen. Probá con un PNG, JPG o WEBP válido.")

    branding = get_or_create_branding(db, company)
    clean_name = safe_filename(logo.filename)
    base_name = clean_name.rsplit(".", 1)[0] if "." in clean_name else clean_name
    branding.logo_bytes = optimized_bytes
    branding.logo_content_type = optimized_type
    branding.logo_filename = f"{base_name or 'logo'}-normalizado.png"
    branding.updated_at = datetime.now(UTC)
    write_audit(db, user, "actualizar", "logo_empresa", str(company.id), company.legal_name)
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Could not save company logo for company_id=%s", company.id)
        return upload_error("No se pudo guardar el logo. Intentá nuevamente; si vuelve a fallar, avisá al administrador.")
    logger.info("Company logo saved (company_id=%s, size_bytes=%s)", company.id, len(optimized_bytes))
    return RedirectResponse(f"{target}?logo_saved=1", status_code=303)


@app.post("/app/companies/{company_id}/branding")
async def update_company_branding(
    company_id: int,
    primary_color: Annotated[str, Form()] = "#173B86",
    secondary_color: Annotated[str, Form()] = "#0B1F48",
    document_footer: Annotated[str, Form()] = "Generado por Digit Laboral",
    signature_name: Annotated[str, Form()] = "",
    signature_title: Annotated[str, Form()] = "Representante legal",
    document_prefix: Annotated[str, Form()] = "DL",
    show_ruc: Annotated[str | None, Form()] = None,
    show_contact: Annotated[str | None, Form()] = None,
    logo_fit: Annotated[str, Form()] = "contain",
    logo_scale: Annotated[int, Form()] = 100,
    logo_alignment: Annotated[str, Form()] = "center",
    logo_background: Annotated[str, Form()] = "white",
    logo: UploadFile | None = File(default=None),
    user: User = Depends(require_roles("administrador", "contador", "empresa")),
    db: Session = Depends(get_db),
):
    company = company_allowed(db, user, company_id)
    branding = get_or_create_branding(db, company)
    color_pattern = re.compile(r"^#[0-9A-Fa-f]{6}$")
    branding.logo_fit = logo_fit if logo_fit in {"contain", "cover"} else "contain"
    branding.logo_scale = max(60, min(140, logo_scale))
    branding.logo_alignment = logo_alignment if logo_alignment in {"left", "center", "right"} else "center"
    branding.logo_background = logo_background if logo_background in {"white", "transparent", "soft", "navy"} else "white"
    branding.primary_color = primary_color if color_pattern.fullmatch(primary_color) else "#173B86"
    branding.secondary_color = secondary_color if color_pattern.fullmatch(secondary_color) else "#0B1F48"
    branding.document_footer = document_footer.strip()[:240] or "Generado por Digit Laboral"
    branding.signature_name = signature_name.strip()[:180]
    branding.signature_title = signature_title.strip()[:140] or "Representante legal"
    branding.document_prefix = re.sub(r"[^A-Za-z0-9]", "", document_prefix.upper())[:12] or "DL"
    branding.show_ruc = show_ruc == "on"
    branding.show_contact = show_contact == "on"
    if logo and logo.filename:
        content = await logo.read(settings.max_logo_size + 1)
        if len(content) > settings.max_logo_size:
            raise HTTPException(413, f"El logo supera el máximo permitido de {settings.max_logo_size / (1024 * 1024):g} MB.")
        detected_type = detect_logo_content_type(content)
        if detected_type is None:
            raise HTTPException(415, "El logo debe ser una imagen PNG, JPG/JPEG o WEBP válida.")
        try:
            optimized_bytes, optimized_type = smart_normalize_logo(content)
        except Exception as exc:
            raise HTTPException(400, f"No se pudo procesar el logo: {exc}") from exc
        branding.logo_bytes = optimized_bytes
        branding.logo_content_type = optimized_type
        clean_name = safe_filename(logo.filename)
        base_name = clean_name.rsplit('.', 1)[0] if '.' in clean_name else clean_name
        branding.logo_filename = f"{base_name or 'logo'}-normalizado.png"
    branding.updated_at = datetime.now(UTC)
    write_audit(db, user, "actualizar", "identidad_visual", str(company.id), company.legal_name)
    db.commit()
    return RedirectResponse(f"/app/companies/{company.id}?branding=1", status_code=303)


@app.post("/app/companies/{company_id}/branding/delete-logo")
def delete_company_logo(
    company_id: int,
    user: User = Depends(require_roles("administrador", "contador", "empresa")),
    db: Session = Depends(get_db),
):
    company = company_allowed(db, user, company_id)
    branding = get_or_create_branding(db, company)
    branding.logo_bytes = None
    branding.logo_content_type = ""
    branding.logo_filename = ""
    write_audit(db, user, "eliminar", "logo_empresa", str(company.id), company.legal_name)
    db.commit()
    return RedirectResponse(f"/app/companies/{company.id}?logo_deleted=1", status_code=303)


@app.post("/app/companies/{company_id}/edit")
def edit_company(
    company_id: int,
    legal_name: Annotated[str, Form()],
    company_code: Annotated[str, Form()] = "",
    ruc: Annotated[str, Form()] = "",
    trade_name: Annotated[str, Form()] = "",
    owner_name: Annotated[str, Form()] = "",
    city: Annotated[str, Form()] = "",
    department: Annotated[str, Form()] = "",
    address: Annotated[str, Form()] = "",
    work_sector: Annotated[str, Form()] = "",
    work_location: Annotated[str, Form()] = "",
    economic_activity: Annotated[str, Form()] = "",
    phone: Annotated[str, Form()] = "",
    contact_name: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "",
    legal_representative: Annotated[str, Form()] = "",
    legal_representative_document: Annotated[str, Form()] = "",
    ips_employer_number: Annotated[str, Form()] = "",
    mtess_employer_number: Annotated[str, Form()] = "",
    responsible_name: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    company = company_allowed(db, user, company_id)
    submitted_code = company_code.strip() or str(company.company_code or "")
    if not submitted_code and company.company_code is None:
        current_max = db.scalar(select(func.max(Company.company_code)).where(Company.studio_id == company.studio_id)) or 0
        submitted_code = str(int(current_max) + 1)
    values = _validate_company_payload(db, {
        "company_code": submitted_code,
        "legal_name": legal_name,
        "ruc": ruc.strip() or company.ruc,
        "trade_name": trade_name,
        "owner_name": owner_name,
        "legal_representative": legal_representative,
        "legal_representative_document": legal_representative_document,
        "address": address,
        "city": city or company.city,
        "department": department,
        "work_sector": work_sector,
        "work_location": work_location,
        "economic_activity": economic_activity,
        "phone": phone,
        "contact_name": contact_name,
        "email": email,
        "ips_employer_number": ips_employer_number,
        "mtess_employer_number": mtess_employer_number,
        "responsible_name": responsible_name,
        "notes": notes,
    }, existing=company)
    _check_company_uniqueness(db, company.studio_id, values, exclude_id=company.id)
    _apply_company_payload(db, company, values)
    write_audit(db, user, "editar", "empresa", str(company.id), f"Código {company.company_code} · {company.legal_name}")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "El Código Empresa o el RUC ya está registrado.") from exc
    return RedirectResponse(f"/app/companies/{company_id}?company_saved=1", status_code=303)


@app.post("/app/companies/{company_id}/status")
def update_company_status(company_id: int, status_value: Annotated[str, Form(alias="status")], user: User = Depends(require_roles("administrador", "contador")), db: Session = Depends(get_db)):
    company = company_allowed(db, user, company_id)
    if status_value not in {"Activa", "Pendiente", "Suspendida", "Archivada"}:
        raise HTTPException(400, "El estado seleccionado para la empresa no es válido.")
    company.status = status_value
    company.updated_at = datetime.now(UTC)
    write_audit(db, user, "actualizar_estado", "empresa", str(company.id), status_value)
    db.commit()
    return RedirectResponse(f"/app/companies/{company_id}", status_code=303)


@app.post("/app/companies/{company_id}/delete")
def archive_company(
    company_id: int,
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    company = company_allowed(db, user, company_id)
    company.status = "Archivada"
    company.updated_at = datetime.now(UTC)
    write_audit(db, user, "archivar", "empresa", str(company.id), f"Código {company.company_code} · {company.legal_name}")
    db.commit()
    return RedirectResponse("/app/companies?archived=1", status_code=303)


@app.get("/api/companies")
def api_list_companies(
    q: str = "",
    city: str = "",
    department: str = "",
    include_archived: bool = False,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    company_ids = company_ids_for_user(db, user)
    query = select(Company).where(Company.id.in_(company_ids)) if company_ids else select(Company).where(False)
    if not include_archived:
        query = query.where(Company.status != "Archivada")
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.where(or_(
            Company.legal_name.ilike(term), Company.ruc.ilike(term), Company.trade_name.ilike(term),
            func.cast(Company.company_code, String).ilike(term),
        ))
    if city.strip():
        query = query.where(Company.city == city.strip())
    if department.strip():
        query = query.where(Company.id.in_(
            select(CompanyComplianceProfile.company_id).where(CompanyComplianceProfile.department == department.strip())
        ))
    records = list(db.scalars(query.order_by(Company.legal_name)))
    return {"count": len(records), "items": [_company_api_record(db, company) for company in records]}


@app.get("/api/companies/by-code/{company_code}")
def api_company_by_code(
    company_code: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    if company_code <= 0:
        raise HTTPException(422, "El Código Empresa debe ser positivo.")
    company = db.scalar(select(Company).where(
        Company.company_code == company_code,
        Company.id.in_(company_ids_for_user(db, user)),
    ))
    if not company or company.status == "Archivada":
        raise HTTPException(404, "No se encontró una empresa activa con ese código en tu espacio de trabajo.")
    return _company_api_record(db, company)


@app.get("/api/companies/{company_id}")
def api_company_by_id(
    company_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    company = company_allowed(db, user, company_id)
    return _company_api_record(db, company)


@app.post("/api/companies", status_code=201)
async def api_create_company(
    request: Request,
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    payload = await _json_object(request)
    values = _validate_company_payload(db, payload)
    _check_company_uniqueness(db, user.studio_id, values)
    studio = db.get(Studio, user.studio_id)
    count = db.scalar(select(func.count(Company.id)).where(Company.studio_id == user.studio_id)) or 0
    if studio and count >= studio.company_limit:
        raise HTTPException(409, "El estudio alcanzó el límite de empresas de su plan.")
    company = Company(
        studio_id=user.studio_id,
        company_code=values["company_code"],
        legal_name=values["legal_name"],
        ruc=values["ruc"],
        city=values["city"],
    )
    db.add(company)
    db.flush()
    _apply_company_payload(db, company, values)
    db.add(Branch(company_id=company.id, name="Casa central", city=company.city, address=company.address))
    get_or_create_branding(db, company)
    write_audit(db, user, "crear", "empresa", str(company.id), f"Código {company.company_code} · {company.legal_name}")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "El Código Empresa o el RUC ya está registrado.") from exc
    db.refresh(company)
    return _company_api_record(db, company)


@app.put("/api/companies/{company_id}")
async def api_update_company(
    company_id: int,
    request: Request,
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    company = company_allowed(db, user, company_id)
    payload = await _json_object(request)
    merged = _company_api_record(db, company)
    merged.update(payload)
    values = _validate_company_payload(db, merged, existing=company)
    _check_company_uniqueness(db, company.studio_id, values, exclude_id=company.id)
    _apply_company_payload(db, company, values)
    write_audit(db, user, "editar", "empresa", str(company.id), f"Código {company.company_code} · {company.legal_name}")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "El Código Empresa o el RUC ya está registrado.") from exc
    db.refresh(company)
    return _company_api_record(db, company)


@app.delete("/api/companies/{company_id}")
def api_archive_company(
    company_id: int,
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    # Logical deletion preserves payrolls, calculations, certificates, requests and audit history.
    company = company_allowed(db, user, company_id)
    company.status = "Archivada"
    company.updated_at = datetime.now(UTC)
    write_audit(db, user, "archivar", "empresa", str(company.id), f"Código {company.company_code} · {company.legal_name}")
    db.commit()
    return {"ok": True, "id": company.id, "company_code": company.company_code, "status": company.status}


@app.post("/app/companies/{company_id}/branches")
def add_branch(
    company_id: int,
    name: Annotated[str, Form()],
    city: Annotated[str, Form()] = "",
    address: Annotated[str, Form()] = "",
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    company = company_allowed(db, user, company_id)
    branch_name = name.strip()
    if not branch_name:
        raise HTTPException(400, "El nombre de la sucursal es obligatorio.")
    if len(branch_name) > 160:
        raise HTTPException(400, "El nombre de la sucursal no puede superar los 160 caracteres.")
    branch = Branch(company_id=company.id, name=branch_name, city=city.strip(), address=address.strip())
    db.add(branch)
    db.flush()
    write_audit(db, user, "crear", "sucursal", str(branch.id), branch.name)
    db.commit()
    return RedirectResponse(f"/app/companies/{company_id}", status_code=303)



@app.get("/app/sections", response_class=HTMLResponse)
def sections_page(
    request: Request,
    q: str = "",
    company_id: OptionalQueryId = None,
    include_inactive: bool = False,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Gestión de secciones dentro de Mantenimientos, limitada a las empresas autorizadas."""
    company_ids = company_ids_for_user(db, user)
    companies_query = (
        select(Company)
        .where(Company.id.in_(company_ids), Company.status != "Archivada")
        .order_by(Company.legal_name)
        if company_ids
        else select(Company).where(False)
    )
    companies = list(db.scalars(companies_query))
    active_company_ids = {company.id for company in companies}

    company_id, _ = default_labor_context(request, db, user, company_ids, company_id, None)
    if company_id is not None and company_id not in active_company_ids:
        raise HTTPException(404, "Empresa no encontrada o archivada.")
    if company_id is None and companies:
        company_id = companies[0].id
    selected_company = next((item for item in companies if item.id == company_id), None)

    sections = []
    all_sections_count = 0
    active_sections_count = 0
    employee_counts = {}
    if company_id is not None:
        all_sections_count = db.scalar(
            select(func.count(CompanySection.id)).where(CompanySection.company_id == company_id)
        ) or 0
        active_sections_count = db.scalar(
            select(func.count(CompanySection.id)).where(
                CompanySection.company_id == company_id,
                CompanySection.active.is_(True),
            )
        ) or 0

        section_query = select(CompanySection).where(CompanySection.company_id == company_id)
        if not include_inactive:
            section_query = section_query.where(CompanySection.active.is_(True))
        if q.strip():
            term = f"%{q.strip()}%"
            section_query = section_query.where(or_(
                func.cast(CompanySection.section_code, String).ilike(term),
                CompanySection.name.ilike(term),
            ))
        sections = list(db.scalars(section_query.order_by(CompanySection.section_code, CompanySection.name)))
        employee_counts = dict(db.execute(
            select(Employee.section_id, func.count(Employee.id))
            .where(Employee.company_id == company_id, Employee.section_id.is_not(None))
            .group_by(Employee.section_id)
        ).all())

    return render(
        request,
        "sections.html",
        db,
        user,
        companies=companies,
        selected_company=selected_company,
        selected_company_id=company_id,
        q=q,
        include_inactive=include_inactive,
        sections=sections,
        all_sections_count=all_sections_count,
        active_sections_count=active_sections_count,
        employee_counts=employee_counts,
        can_manage_sections=user.role in {"administrador", "contador"},
    )


@app.get("/api/sections")
def api_list_company_sections(
    company_id: int,
    include_inactive: bool = False,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    company = company_allowed(db, user, company_id)
    query = select(CompanySection).where(CompanySection.company_id == company.id)
    if not include_inactive:
        query = query.where(CompanySection.active.is_(True))
    sections = list(db.scalars(query.order_by(CompanySection.section_code, CompanySection.name)))
    return {
        "items": [
            {
                "id": item.id,
                "company_id": item.company_id,
                "section_code": item.section_code,
                "name": item.name,
                "active": item.active,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                "updated_by": item.updated_by or "",
            }
            for item in sections
        ]
    }


@app.post("/api/sections", status_code=201)
async def api_create_company_section(
    request: Request,
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    payload = await _json_object(request)
    company_id = optional_int(payload.get("company_id"), field="empresa")
    if not company_id:
        raise HTTPException(422, "Seleccioná una empresa para la sección.")
    company = company_allowed(db, user, company_id)
    if company.status == "Archivada":
        raise HTTPException(409, "No se pueden agregar secciones a una empresa archivada.")
    try:
        section_code = int(str(payload.get("section_code", "")).strip())
    except (TypeError, ValueError):
        raise HTTPException(422, "El código de sección es obligatorio y debe ser numérico.")
    if section_code <= 0:
        raise HTTPException(422, "El código de sección debe ser positivo.")
    name = clean_text(payload.get("name", ""), max_length=140)
    if not name:
        raise HTTPException(422, "El nombre de la sección es obligatorio.")
    existing = list(db.scalars(select(CompanySection).where(CompanySection.company_id == company.id)))
    if any(item.section_code == section_code for item in existing):
        raise HTTPException(409, "Ese código de sección ya existe en la empresa.")
    if any(item.name.casefold() == name.casefold() for item in existing):
        raise HTTPException(409, "Ya existe una sección con ese nombre en la empresa.")
    section = CompanySection(
        company_id=company.id,
        section_code=section_code,
        name=name,
        active=True,
        updated_by=user.email,
        updated_at=datetime.now(UTC),
    )
    db.add(section)
    try:
        db.flush()
        write_audit(db, user, "crear", "seccion", str(section.id), f"{section.section_code} · {section.name}")
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "El código o nombre de sección ya está registrado.") from exc
    return {
        "id": section.id, "company_id": section.company_id, "section_code": section.section_code,
        "name": section.name, "active": section.active,
        "updated_at": section.updated_at.isoformat() if section.updated_at else None,
        "updated_by": section.updated_by,
    }



@app.post("/api/sections/examples", status_code=201)
async def api_create_company_section_examples(
    request: Request,
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    """Carga un conjunto opcional de datos de prueba en una empresa vacía."""
    payload = await _json_object(request)
    company_id = optional_int(payload.get("company_id"), field="empresa")
    if not company_id:
        raise HTTPException(422, "Seleccioná una empresa para cargar los ejemplos.")
    company = company_allowed(db, user, company_id)
    if company.status == "Archivada":
        raise HTTPException(409, "No se pueden agregar secciones a una empresa archivada.")

    existing_count = db.scalar(
        select(func.count(CompanySection.id)).where(CompanySection.company_id == company.id)
    ) or 0
    if existing_count:
        raise HTTPException(409, "Los ejemplos solo se pueden cargar cuando la empresa no tiene secciones.")

    examples = [
        (1, "Administración"),
        (2, "Contabilidad"),
        (3, "Ventas"),
        (4, "Operaciones"),
    ]
    created = []
    try:
        for section_code, name in examples:
            section = CompanySection(
                company_id=company.id,
                section_code=section_code,
                name=name,
                active=True,
                updated_by=user.email,
                updated_at=datetime.now(UTC),
            )
            db.add(section)
            db.flush()
            write_audit(
                db,
                user,
                "crear",
                "seccion",
                str(section.id),
                f"Ejemplo inicial · {section.section_code} · {section.name}",
            )
            created.append(section)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "No se pudieron cargar los ejemplos por una duplicidad de código o nombre.") from exc

    return {
        "created": len(created),
        "items": [
            {
                "id": item.id,
                "company_id": item.company_id,
                "section_code": item.section_code,
                "name": item.name,
                "active": item.active,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                "updated_by": item.updated_by,
            }
            for item in created
        ],
    }


@app.put("/api/sections/{section_id}")
async def api_update_company_section(
    section_id: int,
    request: Request,
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    section = db.get(CompanySection, section_id)
    if not section:
        raise HTTPException(404, "Sección no encontrada.")
    company_allowed(db, user, section.company_id)
    payload = await _json_object(request)
    try:
        section_code = int(str(payload.get("section_code", section.section_code or "")).strip())
    except (TypeError, ValueError):
        raise HTTPException(422, "El código de sección debe ser numérico.")
    name = clean_text(payload.get("name", section.name), max_length=140)
    if section_code <= 0 or not name:
        raise HTTPException(422, "El código y nombre de la sección son obligatorios.")
    existing = list(db.scalars(select(CompanySection).where(
        CompanySection.company_id == section.company_id, CompanySection.id != section.id
    )))
    if any(item.section_code == section_code for item in existing):
        raise HTTPException(409, "Ese código de sección ya existe en la empresa.")
    if any(item.name.casefold() == name.casefold() for item in existing):
        raise HTTPException(409, "Ya existe una sección con ese nombre en la empresa.")
    section.section_code = section_code
    section.name = name
    if "active" in payload:
        section.active = str(payload["active"]).strip().lower() in {"true", "1", "yes", "on"}
    section.updated_by = user.email
    section.updated_at = datetime.now(UTC)
    write_audit(db, user, "editar", "seccion", str(section.id), f"{section.section_code} · {section.name}")
    db.commit()
    return {
        "id": section.id, "company_id": section.company_id, "section_code": section.section_code,
        "name": section.name, "active": section.active,
        "updated_at": section.updated_at.isoformat() if section.updated_at else None,
        "updated_by": section.updated_by,
    }


@app.delete("/api/sections/{section_id}")
def api_archive_company_section(
    section_id: int,
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    section = db.get(CompanySection, section_id)
    if not section:
        raise HTTPException(404, "Sección no encontrada.")
    company_allowed(db, user, section.company_id)
    section.active = False
    section.updated_by = user.email
    section.updated_at = datetime.now(UTC)
    write_audit(db, user, "archivar", "seccion", str(section.id), f"{section.section_code} · {section.name}")
    db.commit()
    return {"ok": True, "id": section.id, "active": False}


@app.get("/api/employees")
def api_list_employees(
    q: str = "",
    company_id: int | None = None,
    section_id: int | None = None,
    status_value: str = "",
    include_archived: bool = False,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    company_ids = company_ids_for_user(db, user)
    query = select(Employee).where(Employee.company_id.in_(company_ids)) if company_ids else select(Employee).where(False)
    query = query.join(Company, Company.id == Employee.company_id).where(Company.status != "Archivada")
    if company_id is not None:
        if company_id not in company_ids:
            raise HTTPException(404, "Empresa no encontrada.")
        query = query.where(Employee.company_id == company_id)
    if section_id is not None:
        query = query.where(Employee.section_id == section_id)
    if status_value:
        if status_value not in {"Activo", "Inactivo", "Desvinculado", "Archivado"}:
            raise HTTPException(422, "El estado seleccionado no es válido.")
        query = query.where(Employee.status == status_value)
    elif not include_archived:
        query = query.where(Employee.status != "Archivado")
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.where(or_(
            Employee.full_name.ilike(term),
            Employee.document_number.ilike(term),
            Employee.position.ilike(term),
            func.cast(Employee.employee_code, String).ilike(term),
        ))
    employees = list(db.scalars(query.order_by(Employee.full_name)))
    return {"items": [_employee_api_record(db, item) for item in employees], "count": len(employees)}


@app.get("/api/employees/by-code/{employee_code}")
def api_employee_by_code(
    employee_code: int,
    company_id: int | None = None,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    if employee_code <= 0:
        raise HTTPException(422, "El Código Legajo debe ser positivo.")
    if company_id is None:
        raise HTTPException(422, "Seleccioná la empresa para consultar el Código Legajo.")
    company = company_allowed(db, user, company_id)
    if company.status == "Archivada":
        raise HTTPException(404, "La empresa seleccionada está archivada.")
    employee = db.scalar(select(Employee).where(
        Employee.company_id == company.id,
        Employee.employee_code == employee_code,
        Employee.status != "Archivado",
    ))
    if not employee:
        raise HTTPException(404, "No se encontró un funcionario con ese código en la empresa seleccionada.")
    return _employee_api_record(db, employee)


@app.get("/api/employees/{employee_id}")
def api_employee_by_id(
    employee_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    employee = db.get(Employee, employee_id)
    if not employee or employee.company_id not in company_ids_for_user(db, user) or employee.status == "Archivado":
        raise HTTPException(404, "Funcionario no encontrado.")
    return _employee_api_record(db, employee)


@app.post("/api/employees", status_code=201)
async def api_create_employee(
    request: Request,
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    payload = await _json_object(request)
    company_id = optional_int(payload.get("company_id"), field="empresa")
    if not company_id:
        raise HTTPException(422, "Seleccioná la empresa del funcionario.")
    company = company_allowed(db, user, company_id)
    if company.status == "Archivada":
        raise HTTPException(409, "No se pueden agregar funcionarios a una empresa archivada.")
    values = _validate_employee_payload(db, payload)
    _check_employee_uniqueness(db, values)
    employee = Employee(
        company_id=company.id,
        employee_code=values["employee_code"],
        branch_id=values["branch_id"],
        section_id=values["section_id"],
        full_name=values["full_name"],
        document_number=values["document_number"],
        birth_date=values["birth_date"],
        position=values["position"],
        admission_date=values["admission_date"],
        termination_date=values["termination_date"],
        contract_type=values["contract_type"],
        payment_frequency=values["payment_frequency"],
        base_salary=values["base_salary"],
        ips_contributor=values["ips_contributor"],
        email=values["email"],
        phone=values["phone"],
        address=values["address"],
        status=values["status"],
        notes=values["notes"],
        updated_at=datetime.now(UTC),
        updated_by=user.email,
    )
    db.add(employee)
    try:
        db.flush()
        _apply_employee_payload(db, employee, values, user)
        add_employee_event(
            db, employee, user, "Alta", "Alta de funcionario",
            f"Cargo: {employee.position}", employee.admission_date, employee.base_salary,
        )
        db.add(SalaryHistory(
            employee_id=employee.id, previous_salary=0, new_salary=employee.base_salary,
            effective_from=employee.admission_date, reason="Salario inicial", created_by=user.email,
        ))
        ensure_compliance_event(
            db, company_id=employee.company_id, employee_id=employee.id, branch_id=employee.branch_id,
            authority="REOP", event_type="Entrada", event_date=employee.admission_date, due_date=None,
            payload={"employee_id": employee.id}, created_by=user.email,
            source_key=f"employee:{employee.id}:entry:reop",
        )
        if employee.ips_contributor:
            ensure_compliance_event(
                db, company_id=employee.company_id, employee_id=employee.id, branch_id=employee.branch_id,
                authority="REI", event_type="Entrada", event_date=employee.admission_date, due_date=None,
                payload={"employee_id": employee.id}, created_by=user.email,
                source_key=f"employee:{employee.id}:entry:rei",
            )
        write_audit(db, user, "crear", "funcionario", str(employee.id), f"Legajo {employee.employee_code} · {employee.full_name}")
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "El Código Legajo o la cédula ya está registrado en esa empresa.") from exc
    db.refresh(employee)
    return _employee_api_record(db, employee)


@app.put("/api/employees/{employee_id}")
async def api_update_employee(
    employee_id: int,
    request: Request,
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    employee = db.get(Employee, employee_id)
    if not employee or employee.company_id not in company_ids_for_user(db, user) or employee.status == "Archivado":
        raise HTTPException(404, "Funcionario no encontrado.")
    payload = await _json_object(request)
    if "company_id" in payload:
        try:
            requested_company_id = int(payload["company_id"])
        except (TypeError, ValueError):
            raise HTTPException(422, "El identificador de empresa no es válido.")
        if requested_company_id != employee.company_id:
            raise HTTPException(409, "La empresa de un legajo existente no se cambia desde la edición rápida.")
    merged = _employee_api_record(db, employee)
    merged.update(payload)
    merged["company_id"] = employee.company_id
    values = _validate_employee_payload(db, merged, existing=employee)
    _check_employee_uniqueness(db, values, exclude_id=employee.id)
    old_code = employee.employee_code
    _apply_employee_payload(db, employee, values, user)
    add_employee_event(db, employee, user, "Actualización", "Datos del funcionario actualizados")
    write_audit(
        db, user, "editar", "funcionario", str(employee.id),
        f"Legajo {old_code} → {employee.employee_code}; {employee.full_name}",
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "El código o la cédula ya está registrado en esa empresa.") from exc
    db.refresh(employee)
    return _employee_api_record(db, employee)


@app.delete("/api/employees/{employee_id}")
def api_archive_employee(
    employee_id: int,
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    employee = db.get(Employee, employee_id)
    if not employee or employee.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404, "Funcionario no encontrado.")
    if employee.status != "Archivado":
        employee.status = "Archivado"
        employee.updated_at = datetime.now(UTC)
        employee.updated_by = user.email
        add_employee_event(
            db, employee, user, "Archivo", "Legajo archivado",
            "Registro archivado de forma lógica; se conservaron cálculos, nóminas y documentos.",
        )
        write_audit(db, user, "archivar", "funcionario", str(employee.id), f"Legajo {employee.employee_code} · {employee.full_name}")
        db.commit()
    return {"ok": True, "id": employee.id, "employee_code": employee.employee_code, "status": employee.status}



# ---------------------------------------------------------------------------
# Mantenimientos · Exámenes médicos ocupacionales
# Solo administradores y contadores pueden consultar o administrar información
# médica. Todos los accesos se limitan a las empresas del estudio autenticado.
# ---------------------------------------------------------------------------

def _medical_exam_filtered_query(
    db: Session,
    user: User,
    *,
    q: str = "",
    employee_id: int | None = None,
    exam_type: str = "",
    result_filter: str = "",
):
    allowed_company_ids = company_ids_for_user(db, user)
    query = (
        select(MedicalExam)
        .join(Employee, Employee.id == MedicalExam.employee_id)
        .join(Company, Company.id == MedicalExam.company_id)
        .where(
            MedicalExam.company_id.in_(allowed_company_ids),
            Employee.company_id == MedicalExam.company_id,
        )
        .options(selectinload(MedicalExam.employee), selectinload(MedicalExam.company))
        if allowed_company_ids
        else select(MedicalExam).where(False)
    )
    if employee_id is not None:
        query = query.where(MedicalExam.employee_id == employee_id)
    if exam_type:
        if exam_type not in MEDICAL_EXAM_TYPES:
            raise HTTPException(422, "El tipo de examen seleccionado no es válido.")
        query = query.where(MedicalExam.exam_type == exam_type)
    if result_filter:
        if result_filter not in MEDICAL_EXAM_RESULTS:
            raise HTTPException(422, "El resultado seleccionado no es válido.")
        query = query.where(MedicalExam.result == result_filter)
    if q.strip():
        term = f"%{q.strip()[:100]}%"
        query = query.where(or_(
            MedicalExam.exam_code.ilike(term),
            Employee.full_name.ilike(term),
            Employee.document_number.ilike(term),
            func.cast(Employee.employee_code, String).ilike(term),
            Company.legal_name.ilike(term),
        ))
    return query


def _medical_exam_allowed(db: Session, user: User, exam_id: int) -> MedicalExam:
    exam = db.get(MedicalExam, exam_id)
    if not exam or exam.company_id not in company_ids_for_user(db, user):
        # No se revela si el ID existe en otra empresa/estudio.
        raise HTTPException(404, "Registro de examen médico no encontrado.")
    employee = db.get(Employee, exam.employee_id)
    if not employee or employee.company_id != exam.company_id:
        raise HTTPException(404, "Registro de examen médico no encontrado.")
    return exam


def _medical_exam_form_redirect(message: str, *, edit_id: int | None = None) -> RedirectResponse:
    query_string = f"form_error={quote(message)}"
    if edit_id is not None:
        query_string += f"&edit_id={edit_id}"
    query_string += "#medicalExamEditor"
    return RedirectResponse(f"/app/medical-exams?{query_string}", status_code=303)


@app.get("/app/medical-exams", response_class=HTMLResponse)
def medical_exams_page(
    request: Request,
    q: str = "",
    employee_id: OptionalQueryId = None,
    exam_type: str = "",
    result_filter: str = "",
    sort: str = "exam_date",
    direction: str = "desc",
    edit_id: OptionalQueryId = None,
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    allowed_company_ids = company_ids_for_user(db, user)
    employees = list(db.scalars(
        select(Employee)
        .join(Company, Company.id == Employee.company_id)
        .where(Employee.company_id.in_(allowed_company_ids), Company.status != "Archivada")
        .options(selectinload(Employee.company))
        .order_by(Company.legal_name, Employee.full_name)
    )) if allowed_company_ids else []

    sort_columns = {
        "exam_code": MedicalExam.exam_code,
        "employee": Employee.full_name,
        "exam_type": MedicalExam.exam_type,
        "exam_date": MedicalExam.exam_date,
        "result": MedicalExam.result,
        "expires_on": MedicalExam.expires_on,
    }
    if sort not in sort_columns:
        sort = "exam_date"
    if direction not in {"asc", "desc"}:
        direction = "desc"

    query = _medical_exam_filtered_query(
        db, user, q=q, employee_id=employee_id, exam_type=exam_type, result_filter=result_filter
    )
    sort_column = sort_columns[sort]
    rows = list(db.scalars(
        query.order_by(sort_column.asc() if direction == "asc" else sort_column.desc(), MedicalExam.id.desc())
    ))
    edit_record = _medical_exam_allowed(db, user, edit_id) if edit_id is not None else None
    today_value = date.today()
    expiry_states = {item.id: medical_exam_expiry_state(item.expires_on, today=today_value) for item in rows}

    if allowed_company_ids:
        total_count = db.scalar(select(func.count(MedicalExam.id)).where(
            MedicalExam.company_id.in_(allowed_company_ids)
        )) or 0
        expired_count = db.scalar(select(func.count(MedicalExam.id)).where(
            MedicalExam.company_id.in_(allowed_company_ids), MedicalExam.expires_on < today_value
        )) or 0
        expiring_count = db.scalar(select(func.count(MedicalExam.id)).where(
            MedicalExam.company_id.in_(allowed_company_ids),
            MedicalExam.expires_on >= today_value,
            MedicalExam.expires_on <= today_value + timedelta(days=MEDICAL_EXAM_WARNING_DAYS),
        )) or 0
    else:
        total_count = expired_count = expiring_count = 0

    return render(
        request, "medical_exams.html", db, user,
        exams=rows, employees=employees, q=q, employee_filter=employee_id,
        exam_type=exam_type, result_filter=result_filter, sort=sort, direction=direction,
        sort_options=[
            ("exam_date", "Fecha del examen"), ("expires_on", "Vencimiento"),
            ("employee", "Empleado"), ("exam_code", "Código"),
            ("exam_type", "Tipo"), ("result", "Resultado"),
        ],
        exam_types=MEDICAL_EXAM_TYPES, exam_results=MEDICAL_EXAM_RESULTS,
        expiry_states=expiry_states, today=today_value,
        total_count=total_count, expired_count=expired_count, expiring_count=expiring_count,
        edit_record=edit_record, form_error=request.query_params.get("form_error", ""),
        created=request.query_params.get("created") == "1",
        updated=request.query_params.get("updated") == "1",
        deleted=request.query_params.get("deleted") == "1",
    )


@app.post("/app/medical-exams/create")
def create_medical_exam(
    employee_id_raw: Annotated[str, Form(alias="employee_id")],
    exam_type: Annotated[str, Form()],
    exam_date_raw: Annotated[str, Form(alias="exam_date")],
    result: Annotated[str, Form()],
    expires_on_raw: Annotated[str, Form(alias="expires_on")],
    exam_code: Annotated[str, Form()] = "",
    observations: Annotated[str, Form()] = "",
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    try:
        employee_id_value = int(employee_id_raw)
        if employee_id_value <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return _medical_exam_form_redirect("Seleccioná un empleado válido.")

    employee = db.get(Employee, employee_id_value)
    allowed_company_ids = company_ids_for_user(db, user)
    if not employee or employee.company_id not in allowed_company_ids:
        raise HTTPException(404, "Funcionario no encontrado.")
    company = company_allowed(db, user, employee.company_id)
    if company.status == "Archivada":
        return _medical_exam_form_redirect("No se pueden crear registros para una empresa archivada.")

    try:
        values = validate_medical_exam_fields(
            company_id=employee.company_id, exam_code=exam_code, exam_type=exam_type,
            exam_date_raw=exam_date_raw, result=result, expires_on_raw=expires_on_raw,
            observations=observations,
        )
    except ValueError as exc:
        return _medical_exam_form_redirect(str(exc))

    duplicate = db.scalar(select(MedicalExam.id).where(
        MedicalExam.company_id == employee.company_id, MedicalExam.exam_code == values["exam_code"]
    ))
    if duplicate:
        return _medical_exam_form_redirect("Ese código de examen ya existe en la empresa.")
    record = MedicalExam(
        company_id=employee.company_id, employee_id=employee.id, **values,
        created_by=user.email, updated_by=user.email,
    )
    db.add(record)
    try:
        db.flush()
        write_audit(db, user, "crear", "examen_medico", str(record.id),
                    f"{record.exam_code} · legajo {employee.employee_code or employee.id}")
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        return _medical_exam_form_redirect("No se pudo guardar: el código de examen ya existe o los datos no son válidos.")
    return RedirectResponse("/app/medical-exams?created=1", status_code=303)


@app.post("/app/medical-exams/{exam_id}/edit")
def update_medical_exam(
    exam_id: int,
    employee_id_raw: Annotated[str, Form(alias="employee_id")],
    exam_type: Annotated[str, Form()],
    exam_date_raw: Annotated[str, Form(alias="exam_date")],
    result: Annotated[str, Form()],
    expires_on_raw: Annotated[str, Form(alias="expires_on")],
    exam_code: Annotated[str, Form()] = "",
    observations: Annotated[str, Form()] = "",
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    record = _medical_exam_allowed(db, user, exam_id)
    try:
        employee_id_value = int(employee_id_raw)
        if employee_id_value <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return _medical_exam_form_redirect("Seleccioná un empleado válido.", edit_id=exam_id)
    employee = db.get(Employee, employee_id_value)
    if not employee or employee.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404, "Funcionario no encontrado.")
    try:
        values = validate_medical_exam_fields(
            company_id=employee.company_id, exam_code=exam_code, exam_type=exam_type,
            exam_date_raw=exam_date_raw, result=result, expires_on_raw=expires_on_raw,
            observations=observations,
        )
    except ValueError as exc:
        return _medical_exam_form_redirect(str(exc), edit_id=exam_id)
    duplicate = db.scalar(select(MedicalExam.id).where(
        MedicalExam.company_id == employee.company_id,
        MedicalExam.exam_code == values["exam_code"],
        MedicalExam.id != record.id,
    ))
    if duplicate:
        return _medical_exam_form_redirect("Ese código de examen ya existe en la empresa.", edit_id=exam_id)

    old_code = record.exam_code
    record.company_id = employee.company_id
    record.employee_id = employee.id
    for key, value in values.items():
        setattr(record, key, value)
    record.updated_by = user.email
    record.updated_at = datetime.now(UTC)
    try:
        write_audit(db, user, "editar", "examen_medico", str(record.id),
                    f"{old_code} → {record.exam_code} · legajo {employee.employee_code or employee.id}")
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        return _medical_exam_form_redirect("No se pudo actualizar: verificá el código y las fechas.", edit_id=exam_id)
    return RedirectResponse("/app/medical-exams?updated=1", status_code=303)


@app.post("/app/medical-exams/{exam_id}/delete")
def delete_medical_exam(
    exam_id: int,
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    record = _medical_exam_allowed(db, user, exam_id)
    employee = db.get(Employee, record.employee_id)
    code = record.exam_code
    detail = f"{code} · legajo {(employee.employee_code or employee.id) if employee else record.employee_id}"
    write_audit(db, user, "eliminar", "examen_medico", str(record.id), detail)
    db.delete(record)
    db.commit()
    return RedirectResponse("/app/medical-exams?deleted=1", status_code=303)


@app.get("/app/medical-exams/export.csv")
def export_medical_exams_csv(
    q: str = "",
    employee_id: OptionalQueryId = None,
    exam_type: str = "",
    result_filter: str = "",
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    query = _medical_exam_filtered_query(
        db, user, q=q, employee_id=employee_id, exam_type=exam_type, result_filter=result_filter
    )
    rows = list(db.scalars(query.order_by(MedicalExam.exam_date.desc(), MedicalExam.id.desc())))
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Código", "Empresa", "Empleado", "Cédula", "Tipo de examen",
                     "Fecha del examen", "Resultado", "Vigencia / vencimiento", "Estado de vigencia", "Observaciones"])
    today_value = date.today()
    for item in rows:
        writer.writerow([
            item.exam_code, item.company.legal_name, item.employee.full_name, item.employee.document_number,
            item.exam_type, item.exam_date.isoformat(), item.result, item.expires_on.isoformat(),
            medical_exam_expiry_state(item.expires_on, today=today_value), item.observations or "",
        ])
    filename = safe_download_name("Informe de examenes medicos", date.today().isoformat(), "csv")
    payload = ("\ufeff" + output.getvalue()).encode("utf-8")
    write_audit(db, user, "exportar", "informe_examenes_medicos", "", f"{len(rows)} registros")
    db.commit()
    return StreamingResponse(
        io.BytesIO(payload), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@app.get("/app/medical-exams/{exam_id}/certificate.pdf")
def export_medical_exam_certificate(
    exam_id: int,
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    record = _medical_exam_allowed(db, user, exam_id)
    employee = db.get(Employee, record.employee_id)
    company = db.get(Company, record.company_id)
    if not employee or not company:
        raise HTTPException(404, "Registro de examen médico no encontrado.")
    branding = db.scalar(select(CompanyBranding).where(CompanyBranding.company_id == company.id))
    primary_color = getattr(branding, "primary_color", "#173B86") if branding else "#173B86"
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(primary_color or "")):
        primary_color = "#173B86"
    body = (
        f"Código del registro: {record.exam_code}\n"
        f"Empleado: {employee.full_name}\n"
        f"Cédula de identidad: {employee.document_number}\n"
        f"Cargo: {employee.position or 'No consignado'}\n"
        f"Tipo de examen: {record.exam_type}\n"
        f"Fecha del examen: {record.exam_date.strftime('%d/%m/%Y')}\n"
        f"Resultado registrado: {record.result}\n"
        f"Vigencia / vencimiento: {record.expires_on.strftime('%d/%m/%Y')}\n"
        f"Estado de vigencia al {date.today().strftime('%d/%m/%Y')}: "
        f"{medical_exam_expiry_state(record.expires_on)}\n\n"
        f"Observaciones registradas: {record.observations or 'Sin observaciones consignadas.'}\n\n"
        "AVISO: Documento administrativo generado a partir de los datos ingresados en Digit Laboral. "
        "No constituye diagnóstico, certificado médico profesional ni reemplaza el informe emitido "
        "por el profesional o centro médico competente."
    )
    payload = build_pdf_bytes(ExportData(
        document_type="registro_examen_medico",
        title="Constancia administrativa de registro de examen médico ocupacional",
        city=company.city or "Paraguay",
        issue_date=date.today(),
        company_name=company.legal_name,
        company_ruc=company.ruc or "",
        company_address=company.address or "",
        company_phone=company.phone or "",
        company_email=company.email or "",
        legal_representative=company.legal_representative or "",
        primary_color=primary_color,
        employee_name=employee.full_name,
        employee_document=employee.document_number,
        position=employee.position or "",
        admission_date=employee.admission_date,
        body=body,
        status=record.result,
        created_by=user.email,
        created_at=record.created_at,
        metadata={"document_number": record.exam_code},
        document_footer="Documento administrativo interno. No sustituye el certificado o informe médico original.",
    ))
    filename = safe_download_name("Constancia examen medico", employee.full_name, "pdf")
    write_audit(db, user, "exportar", "constancia_examen_medico", str(record.id), record.exam_code)
    db.commit()
    return StreamingResponse(
        io.BytesIO(payload), media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@app.get("/app/employees", response_class=HTMLResponse)
def employees_page(
    request: Request,
    q: str = "",
    company_id: OptionalQueryId = None,
    section_id: OptionalQueryId = None,
    status_filter: str = "",
    show_archived: bool = False,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    company_ids = company_ids_for_user(db, user)
    company_id, active_employee_id = default_labor_context(
        request, db, user, company_ids, company_id, None
    )
    query = select(Employee).where(Employee.company_id.in_(company_ids)) if company_ids else select(Employee).where(False)
    query = query.join(Company, Company.id == Employee.company_id).where(Company.status != "Archivada")
    if company_id and company_id in company_ids:
        query = query.where(Employee.company_id == company_id)
    if active_employee_id:
        query = query.where(Employee.id == active_employee_id)
    if not show_archived and status_filter != "Archivado":
        query = query.where(Employee.status != "Archivado")
    if status_filter:
        if status_filter not in {"Activo", "Inactivo", "Desvinculado", "Archivado"}:
            raise HTTPException(422, "El estado seleccionado no es válido.")
        query = query.where(Employee.status == status_filter)
    if section_id:
        query = query.where(Employee.section_id == section_id)
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.where(or_(
            Employee.full_name.ilike(term),
            Employee.document_number.ilike(term),
            Employee.position.ilike(term),
            func.cast(Employee.employee_code, String).ilike(term),
        ))
    employees = list(db.scalars(query.order_by(Employee.full_name)))
    companies_query = select(Company).where(Company.id.in_(company_ids), Company.status != "Archivada")
    companies = list(db.scalars(companies_query.order_by(Company.legal_name))) if company_ids else []
    branch_query = select(Branch).where(Branch.company_id.in_(company_ids)).order_by(Branch.name) if company_ids else select(Branch).where(False)
    branches = list(db.scalars(branch_query))
    section_query = select(CompanySection).where(CompanySection.company_id.in_(company_ids)).order_by(CompanySection.company_id, CompanySection.section_code, CompanySection.name) if company_ids else select(CompanySection).where(False)
    sections = list(db.scalars(section_query))
    employee_profiles = {item.id: _employee_profile(db, item.id) for item in employees}
    minimum_salary = db.scalar(select(LaborParameter).where(
        LaborParameter.key == "minimum_monthly_salary_general", LaborParameter.active.is_(True)
    ))
    return render(
        request, "employees.html", db, user,
        employees=employees, companies=companies, branches=branches, sections=sections,
        employee_profiles=employee_profiles, q=q, selected_company=company_id,
        selected_section=section_id, status_filter=status_filter, show_archived=show_archived,
        selected_employee=active_employee_id, minimum_salary=minimum_salary,
    )

@app.get("/app/employees/{employee_id}", response_class=HTMLResponse)
def employee_detail_page(
    employee_id: int,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    employee = db.get(Employee, employee_id)
    if not employee or employee.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404, "Funcionario no encontrado.")
    events = list(db.scalars(select(EmployeeEvent).where(EmployeeEvent.employee_id == employee.id).order_by(EmployeeEvent.effective_date.desc(), EmployeeEvent.created_at.desc())))
    salaries = list(db.scalars(select(SalaryHistory).where(SalaryHistory.employee_id == employee.id).order_by(SalaryHistory.effective_from.desc(), SalaryHistory.created_at.desc())))
    documents = list(db.scalars(select(Document).where(Document.employee_id == employee.id).order_by(Document.created_at.desc())))
    certificates = list(db.scalars(select(GeneratedCertificate).where(GeneratedCertificate.employee_id == employee.id).order_by(GeneratedCertificate.created_at.desc())))
    calculations = list(db.scalars(select(CalculationRecord).where(CalculationRecord.employee_id == employee.id).order_by(CalculationRecord.created_at.desc()).limit(30)))
    vacations = list(db.scalars(select(Vacation).where(Vacation.employee_id == employee.id).order_by(Vacation.period_year.desc())))
    payroll_lines = list(db.scalars(select(PayrollLine).where(PayrollLine.employee_id == employee.id).order_by(PayrollLine.id.desc()).limit(24)))
    deadlines = list(db.scalars(select(LaborDeadline).where(LaborDeadline.employee_id == employee.id).order_by(LaborDeadline.due_date)))
    return render(
        request, "employee_detail.html", db, user, employee=employee, events=events, salaries=salaries,
        documents=documents, certificates=certificates, calculations=calculations, vacations=vacations,
        payroll_lines=payroll_lines, deadlines=deadlines,
        employee_profile=_employee_profile(db, employee.id),
    )


@app.post("/app/employees/{employee_id}/events")
def add_employee_event_action(
    employee_id: int,
    event_type: Annotated[str, Form()],
    title: Annotated[str, Form()],
    effective_date: Annotated[date, Form()],
    detail: Annotated[str, Form()] = "",
    amount: Annotated[int | None, Form()] = None,
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    employee = db.get(Employee, employee_id)
    if not employee or employee.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    add_employee_event(db, employee, user, event_type.strip(), title.strip(), detail.strip(), effective_date, amount)
    write_audit(db, user, "crear", "evento_funcionario", str(employee.id), title.strip())
    db.commit()
    return RedirectResponse(f"/app/employees/{employee.id}#timeline", status_code=303)


@app.get("/app/import/employees/template.xlsx")
def employee_import_template(user: User = Depends(require_user)):
    data = build_employee_template()
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=plantilla_funcionarios_digit_laboral.xlsx"},
    )


@app.post("/app/import/employees/preview")
async def employee_import_preview(
    company_id: Annotated[int, Form()],
    file: UploadFile = File(),
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    company = company_allowed(db, user, company_id)
    content = await file.read(8 * 1024 * 1024 + 1)
    if len(content) > 8 * 1024 * 1024:
        raise HTTPException(413, "El archivo supera el máximo permitido de 8 MB.")
    try:
        rows = parse_employee_import(content, file.filename or "archivo.xlsx", settings.max_import_rows)
    except ValueError as exc:
        return RedirectResponse(f"/app/employees?import_error={quote(str(exc))}", status_code=303)
    token = uuid.uuid4().hex
    preview = ImportPreview(
        company_id=company.id, studio_id=user.studio_id or 0, user_id=user.id,
        created_at=datetime.now(UTC).isoformat(), filename=file.filename or "archivo", rows=rows,
    )
    save_preview(IMPORT_DIR, token, preview)
    write_audit(db, user, "previsualizar", "importacion_funcionarios", token, f"{company.legal_name}: {len(rows)} filas")
    db.commit()
    return RedirectResponse(f"/app/import/employees/{token}", status_code=303)


@app.get("/app/import/employees/{token}", response_class=HTMLResponse)
def employee_import_preview_page(
    token: str, request: Request, user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    try:
        preview = load_preview(IMPORT_DIR, token)
    except (ValueError, FileNotFoundError) as exc:
        return RedirectResponse(f"/app/employees?import_error={quote(str(exc))}", status_code=303)
    if preview.user_id != user.id or preview.studio_id != (user.studio_id or 0):
        raise HTTPException(403)
    company = company_allowed(db, user, preview.company_id)
    existing_employees = {}
    for item in db.scalars(select(Employee).where(Employee.company_id == company.id)):
        normalized_document = normalize_document_number(item.document_number)
        if normalized_document:
            existing_employees.setdefault(normalized_document, item)
    existing_documents = set(existing_employees)
    duplicate_count = sum(row.data.get("document_number") in existing_documents for row in preview.rows if row.valid)
    salary_change_count = sum(
        1 for row in preview.rows
        if row.valid
        and row.data.get("document_number") in existing_employees
        and int(row.data.get("base_salary") or 0) != existing_employees[row.data["document_number"]].base_salary
    )
    return render(
        request, "employee_import_preview.html", db, user, token=token, preview=preview, company=company,
        duplicate_count=duplicate_count, existing_documents=existing_documents,
        existing_employees=existing_employees, salary_change_count=salary_change_count,
    )


@app.post("/app/import/employees/{token}/confirm")
def employee_import_confirm(
    token: str,
    duplicate_action: Annotated[str, Form()] = "skip",
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    try:
        preview = load_preview(IMPORT_DIR, token)
    except (ValueError, FileNotFoundError) as exc:
        return RedirectResponse(f"/app/employees?import_error={quote(str(exc))}", status_code=303)
    if preview.user_id != user.id or preview.studio_id != (user.studio_id or 0):
        raise HTTPException(403)
    company = company_allowed(db, user, preview.company_id)
    existing_employees = {}
    for item in db.scalars(select(Employee).where(Employee.company_id == company.id)):
        normalized_document = normalize_document_number(item.document_number)
        if normalized_document:
            existing_employees.setdefault(normalized_document, item)
    created = updated = skipped = salary_changes_requires_request = 0
    for row in preview.rows:
        if not row.valid:
            skipped += 1
            continue
        data = row.data
        document_number = normalize_document_number(data.get("document_number"))
        if not document_number:
            skipped += 1
            continue
        employee = existing_employees.get(document_number)
        if employee and duplicate_action != "update":
            skipped += 1
            continue
        admission = date.fromisoformat(data["admission_date"])
        birth = date.fromisoformat(data["birth_date"]) if data.get("birth_date") else None
        if employee:
            # Los archivos pueden actualizar la ficha, pero no el salario vigente.
            # Cualquier diferencia debe tramitarse con una solicitud salarial aprobada.
            if int(data.get("base_salary") or 0) != employee.base_salary:
                salary_changes_requires_request += 1
            employee.full_name = data["full_name"]
            employee.position = data["position"]
            employee.admission_date = admission
            employee.birth_date = birth
            employee.contract_type = data["contract_type"]
            employee.payment_frequency = data["payment_frequency"]
            employee.ips_contributor = data["ips_contributor"]
            employee.email = data["email"]
            employee.phone = data["phone"]
            employee.address = data["address"]
            employee.notes = data["notes"]
            employee.updated_at = datetime.now(UTC)
            employee.updated_by = user.email
            add_employee_event(db, employee, user, "Importación", "Datos actualizados por importación", f"Archivo: {preview.filename}")
            updated += 1
        else:
            employee = Employee(
                company_id=company.id, employee_code=_next_employee_code(db, company.id),
                full_name=data["full_name"], document_number=data["document_number"],
                birth_date=birth, position=data["position"], admission_date=admission,
                contract_type=data["contract_type"], payment_frequency=data["payment_frequency"],
                base_salary=data["base_salary"], ips_contributor=data["ips_contributor"],
                email=data["email"], phone=data["phone"], address=data["address"], notes=data["notes"],
                updated_at=datetime.now(UTC), updated_by=user.email,
            )
            db.add(employee)
            db.flush()
            existing_employees[document_number] = employee
            add_employee_event(db, employee, user, "Alta", "Funcionario importado", f"Archivo: {preview.filename}", admission, employee.base_salary)
            db.add(SalaryHistory(
                employee_id=employee.id, previous_salary=0, new_salary=employee.base_salary,
                effective_from=admission, reason="Salario inicial importado", created_by=user.email,
            ))
            created += 1
    write_audit(
        db, user, "confirmar", "importacion_funcionarios", token,
        f"{company.legal_name}: {created} creados, {updated} actualizados, {skipped} omitidos, "
        f"{salary_changes_requires_request} cambios salariales derivados a solicitud",
    )
    db.commit()
    (IMPORT_DIR / f"{token}.json").unlink(missing_ok=True)
    return RedirectResponse(
        f"/app/employees?imported={created}&updated={updated}&skipped={skipped}"
        f"&salary_changes={salary_changes_requires_request}&company_id={company.id}",
        status_code=303,
    )


@app.post("/app/employees")
def add_employee(
    company_id: Annotated[int, Form()],
    full_name: Annotated[str, Form()],
    document_number: Annotated[str, Form()],
    position_name: Annotated[str, Form(alias="position")],
    admission_date: Annotated[date, Form()],
    base_salary: Annotated[int, Form()],
    employee_code: Annotated[str, Form()] = "",
    branch_id: Annotated[str, Form()] = "",
    section_id: Annotated[str, Form()] = "",
    birth_date: Annotated[str, Form()] = "",
    contract_type: Annotated[str, Form()] = "Tiempo indefinido",
    payment_frequency: Annotated[str, Form()] = "Mensual",
    nationality: Annotated[str, Form()] = "Paraguaya",
    marital_status: Annotated[str, Form()] = "",
    position_category: Annotated[str, Form()] = "",
    work_schedule: Annotated[str, Form()] = "",
    shift: Annotated[str, Form()] = "Diurno",
    weekly_hours: Annotated[int, Form()] = 48,
    daily_hours: Annotated[int, Form()] = 8,
    ips_number: Annotated[str, Form()] = "",
    salary_type: Annotated[str, Form()] = "Mensual",
    email: Annotated[str, Form()] = "",
    phone: Annotated[str, Form()] = "",
    address: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
    ips_contributor: Annotated[str | None, Form()] = None,
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    company = company_allowed(db, user, company_id)
    if company.status == "Archivada":
        raise HTTPException(409, "No se pueden agregar funcionarios a una empresa archivada.")
    full_name_value = full_name.strip()
    document_number_value = normalize_document_number(document_number)
    position_value = position_name.strip()
    if not full_name_value:
        raise HTTPException(400, "El nombre completo es obligatorio.")
    if len(full_name_value) > 180:
        raise HTTPException(400, "El nombre completo no puede superar los 180 caracteres.")
    if not document_number_value:
        raise HTTPException(400, "La cédula es obligatoria.")
    if len(document_number_value) > 40:
        raise HTTPException(400, "La cédula no puede superar los 40 caracteres.")
    if not position_value:
        raise HTTPException(400, "El cargo es obligatorio.")
    if len(position_value) > 140:
        raise HTTPException(400, "El cargo no puede superar los 140 caracteres.")
    if base_salary < 0:
        raise HTTPException(400, "El salario base no puede ser negativo.")
    try:
        employee_code_value = int(str(employee_code).strip()) if str(employee_code).strip() else _next_employee_code(db, company.id)
    except (TypeError, ValueError):
        raise HTTPException(400, "El Código Legajo debe ser numérico.")
    if employee_code_value <= 0:
        raise HTTPException(400, "El Código Legajo debe ser positivo.")
    code_exists = db.scalar(select(Employee.id).where(
        Employee.company_id == company.id, Employee.employee_code == employee_code_value
    ))
    if code_exists:
        raise HTTPException(409, "Ese Código Legajo ya existe dentro de la empresa.")

    branch_id_value = optional_int(branch_id, field="sucursal")
    section_id_value = optional_int(section_id, field="sección")
    birth_date_value = optional_date(birth_date, field="fecha de nacimiento")
    if birth_date_value and (birth_date_value >= admission_date or birth_date_value > date.today()):
        raise HTTPException(400, "La fecha de nacimiento debe ser anterior al ingreso y no puede ser futura.")
    if branch_id_value is not None:
        branch = db.scalar(select(Branch).where(
            Branch.id == branch_id_value, Branch.company_id == company.id
        ))
        if not branch or not branch.active:
            raise HTTPException(400, "La sucursal seleccionada no pertenece a la empresa o está inactiva.")
    if section_id_value is not None:
        section = db.scalar(select(CompanySection).where(
            CompanySection.id == section_id_value, CompanySection.company_id == company.id,
            CompanySection.active.is_(True),
        ))
        if not section:
            raise HTTPException(400, "La sección seleccionada no pertenece a la empresa o está inactiva.")
    if not 1 <= weekly_hours <= 96:
        raise HTTPException(400, "Las horas semanales deben estar entre 1 y 96.")
    if not 1 <= daily_hours <= 24:
        raise HTTPException(400, "Las horas diarias deben estar entre 1 y 24.")
    ips_number_value = re.sub(r"[\s.-]+", "", ips_number.strip())
    if ips_number_value and not ips_number_value.isdigit():
        raise HTTPException(400, "El número IPS del funcionario debe contener solamente dígitos.")
    if any(
        normalize_document_number(value) == document_number_value
        for value in db.scalars(select(Employee.document_number).where(Employee.company_id == company.id))
    ):
        return RedirectResponse("/app/employees?duplicate=1", status_code=303)

    employee = Employee(
        company_id=company.id,
        employee_code=employee_code_value,
        branch_id=branch_id_value,
        section_id=section_id_value,
        full_name=full_name_value,
        document_number=document_number_value,
        birth_date=birth_date_value,
        position=position_value,
        admission_date=admission_date,
        contract_type=contract_type.strip() or "Tiempo indefinido",
        payment_frequency=payment_frequency.strip() or "Mensual",
        base_salary=base_salary,
        ips_contributor=str(ips_contributor or "").strip().lower() in {"on", "true", "1", "yes"},
        email=email.strip(),
        phone=phone.strip(),
        address=address.strip(),
        notes=notes.strip(),
        status="Activo",
        updated_at=datetime.now(UTC),
        updated_by=user.email,
    )
    db.add(employee)
    try:
        db.flush()
        profile = EmployeeComplianceProfile(
            employee_id=employee.id,
            nationality=clean_text(nationality, max_length=80) or "Paraguaya",
            marital_status=clean_text(marital_status, max_length=40),
            position_category=clean_text(position_category, max_length=100),
            work_schedule=clean_text(work_schedule, max_length=120),
            shift=clean_text(shift, max_length=60) or "Diurno",
            weekly_hours=int(weekly_hours or 48),
            daily_hours=int(daily_hours or 8),
            ips_number=ips_number_value,
            salary_type=clean_text(salary_type, max_length=40) or payment_frequency.strip() or "Mensual",
        )
        db.add(profile)
    except IntegrityError:
        db.rollback()
        return RedirectResponse("/app/employees?form_error=El+código+o+la+cédula+ya+existe+en+esa+empresa", status_code=303)
    add_employee_event(db, employee, user, "Alta", "Alta de funcionario", f"Cargo: {employee.position}", employee.admission_date, employee.base_salary)
    db.add(SalaryHistory(
        employee_id=employee.id, previous_salary=0, new_salary=employee.base_salary,
        effective_from=employee.admission_date, reason="Salario inicial", created_by=user.email,
    ))
    ensure_compliance_event(
        db, company_id=company_id, employee_id=employee.id, branch_id=employee.branch_id, authority="REOP", event_type="Entrada",
        event_date=employee.admission_date, due_date=None, payload={"employee_id": employee.id},
        created_by=user.email, source_key=f"employee:{employee.id}:entry:reop",
    )
    if employee.ips_contributor:
        ensure_compliance_event(
            db, company_id=company_id, employee_id=employee.id, branch_id=employee.branch_id, authority="REI", event_type="Entrada",
            event_date=employee.admission_date, due_date=None, payload={"employee_id": employee.id},
            created_by=user.email, source_key=f"employee:{employee.id}:entry:rei",
        )
    write_audit(db, user, "crear", "funcionario", str(employee.id), f"Legajo {employee.employee_code} · {employee.full_name}")
    db.commit()
    return RedirectResponse(f"/app/employees/{employee.id}", status_code=303)


@app.post("/app/employees/{employee_id}/edit")
def edit_employee(
    employee_id: int,
    full_name: Annotated[str, Form()],
    position_name: Annotated[str, Form(alias="position")],
    employee_code: Annotated[str | None, Form()] = None,
    document_number: Annotated[str | None, Form()] = None,
    birth_date: Annotated[str | None, Form()] = None,
    branch_id: Annotated[str | None, Form()] = None,
    section_id: Annotated[str | None, Form()] = None,
    contract_type: Annotated[str | None, Form()] = None,
    payment_frequency: Annotated[str | None, Form()] = None,
    base_salary_raw: Annotated[str | None, Form(alias="base_salary")] = None,
    nationality: Annotated[str | None, Form()] = None,
    marital_status: Annotated[str | None, Form()] = None,
    position_category: Annotated[str | None, Form()] = None,
    work_schedule: Annotated[str | None, Form()] = None,
    shift: Annotated[str | None, Form()] = None,
    weekly_hours: Annotated[str | None, Form()] = None,
    daily_hours: Annotated[str | None, Form()] = None,
    ips_number: Annotated[str | None, Form()] = None,
    salary_type: Annotated[str | None, Form()] = None,
    ips_contributor: Annotated[str | None, Form()] = None,
    email: Annotated[str | None, Form()] = None,
    phone: Annotated[str | None, Form()] = None,
    address: Annotated[str | None, Form()] = None,
    notes: Annotated[str | None, Form()] = None,
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    employee = db.get(Employee, employee_id)
    if not employee or employee.company_id not in company_ids_for_user(db, user) or employee.status == "Archivado":
        raise HTTPException(404, "Funcionario no encontrado.")
    merged = _employee_api_record(db, employee)
    submitted = {
        "full_name": full_name,
        "position": position_name,
        "employee_code": employee_code,
        "document_number": document_number,
        "birth_date": birth_date,
        "branch_id": branch_id,
        "section_id": section_id,
        "contract_type": contract_type,
        "payment_frequency": payment_frequency,
        "base_salary": base_salary_raw,
        "nationality": nationality,
        "marital_status": marital_status,
        "position_category": position_category,
        "work_schedule": work_schedule,
        "shift": shift,
        "weekly_hours": weekly_hours,
        "daily_hours": daily_hours,
        "ips_number": ips_number,
        "salary_type": salary_type,
        "ips_contributor": ips_contributor,
        "email": email,
        "phone": phone,
        "address": address,
        "notes": notes,
    }
    merged.update({key: value for key, value in submitted.items() if value is not None})
    merged["company_id"] = employee.company_id
    values = _validate_employee_payload(db, merged, existing=employee)
    _check_employee_uniqueness(db, values, exclude_id=employee.id)
    old_code = employee.employee_code
    _apply_employee_payload(db, employee, values, user)
    add_employee_event(db, employee, user, "Actualización", "Datos del funcionario actualizados")
    write_audit(
        db, user, "editar", "funcionario", str(employee.id),
        f"Legajo {old_code} → {employee.employee_code}; {employee.full_name}",
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "El código o la cédula ya está registrado en esa empresa.")
    return RedirectResponse(f"/app/employees/{employee.id}", status_code=303)


@app.post("/app/employees/{employee_id}/status")
def employee_status(
    employee_id: int,
    status_value: Annotated[str, Form(alias="status")],
    termination_date: Annotated[str | date | None, Form()] = None,
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    employee = db.get(Employee, employee_id)
    if not employee or employee.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    if status_value not in {"Activo", "Inactivo", "Desvinculado"}:
        raise HTTPException(400, "El estado seleccionado no es válido.")
    termination_date = optional_date(termination_date, field="fecha efectiva de salida")
    if status_value != "Activo" and termination_date is None:
        raise HTTPException(400, "Indicá la fecha efectiva de salida para inactivar o desvincular al funcionario.")
    employee.status = status_value
    employee.termination_date = termination_date if status_value != "Activo" else None
    employee.updated_at = datetime.now(UTC)
    employee.updated_by = user.email
    effective = employee.termination_date or date.today()
    add_employee_event(db, employee, user, "Estado", f"Estado actualizado a {status_value}", "", effective)
    if status_value != "Activo":
        ensure_compliance_event(
            db, company_id=employee.company_id, employee_id=employee.id, branch_id=employee.branch_id, authority="REOP", event_type="Salida",
            event_date=effective, due_date=None, payload={"status": status_value}, created_by=user.email,
            source_key=f"employee:{employee.id}:exit:{effective.isoformat()}:reop",
        )
        if employee.ips_contributor:
            ensure_compliance_event(
                db, company_id=employee.company_id, employee_id=employee.id, branch_id=employee.branch_id, authority="REI", event_type="Salida",
                event_date=effective, due_date=None, payload={"status": status_value}, created_by=user.email,
                source_key=f"employee:{employee.id}:exit:{effective.isoformat()}:rei",
            )
    write_audit(db, user, "actualizar_estado", "funcionario", str(employee.id), status_value)
    db.commit()
    return RedirectResponse(f"/app/employees/{employee.id}", status_code=303)


@app.post("/app/employees/{employee_id}/delete")
def archive_employee_form(
    employee_id: int,
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    employee = db.get(Employee, employee_id)
    if not employee or employee.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404, "Funcionario no encontrado.")
    employee.status = "Archivado"
    employee.updated_at = datetime.now(UTC)
    employee.updated_by = user.email
    add_employee_event(
        db, employee, user, "Archivo", "Legajo archivado",
        "Registro archivado de forma lógica; se conservaron cálculos, nóminas y documentos.",
    )
    write_audit(db, user, "archivar", "funcionario", str(employee.id), f"Legajo {employee.employee_code} · {employee.full_name}")
    db.commit()
    return RedirectResponse("/app/employees?show_archived=true&archived=1", status_code=303)


@app.get("/app/calendar", response_class=HTMLResponse)
def calendar_page(
    request: Request, company_id: OptionalQueryId = None, employee_id: OptionalQueryId = None,
    status_filter: str = "", user: User = Depends(require_user), db: Session = Depends(get_db),
):
    company_ids = company_ids_for_user(db, user)
    companies = list(db.scalars(select(Company).where(Company.id.in_(company_ids)).order_by(Company.legal_name))) if company_ids else []
    employees_query = select(Employee).where(Employee.company_id.in_(company_ids)) if company_ids else select(Employee).where(False)
    if company_id and company_id in company_ids:
        employees_query = employees_query.where(Employee.company_id == company_id)
    employees = list(db.scalars(employees_query.order_by(Employee.full_name)))
    query = select(LaborDeadline).where(LaborDeadline.company_id.in_(company_ids)) if company_ids else select(LaborDeadline).where(False)
    if company_id and company_id in company_ids:
        query = query.where(LaborDeadline.company_id == company_id)
    if employee_id:
        query = query.where(LaborDeadline.employee_id == employee_id)
    if status_filter:
        query = query.where(LaborDeadline.status == status_filter)
    deadlines = list(db.scalars(query.order_by(LaborDeadline.due_date, LaborDeadline.priority)))
    today_value = date.today()
    horizon = today_value + timedelta(days=60)
    automatic_alerts: list[dict] = []
    for employee in employees:
        anniversary = labor_anniversary(employee.admission_date, today_value.year - employee.admission_date.year)
        if anniversary < today_value:
            anniversary = labor_anniversary(employee.admission_date, today_value.year + 1 - employee.admission_date.year)
        if anniversary <= horizon:
            automatic_alerts.append({
                "date": anniversary, "type": "Aniversario laboral", "title": employee.full_name,
                "detail": f"Ingreso: {format_date(employee.admission_date)} · {employee.company.legal_name}",
                "employee_id": employee.id,
            })
    vacation_query = select(Vacation).join(Employee).where(Employee.company_id.in_(company_ids), Vacation.start_date.is_not(None)) if company_ids else select(Vacation).where(False)
    for vacation in db.scalars(vacation_query):
        if vacation.start_date and today_value <= vacation.start_date <= horizon:
            automatic_alerts.append({
                "date": vacation.start_date, "type": "Vacaciones", "title": vacation.employee.full_name,
                "detail": f"Periodo {vacation.period_year} · {vacation.status}", "employee_id": vacation.employee_id,
            })
    automatic_alerts.sort(key=lambda item: item["date"])
    overdue_count = sum(item.status == "Pendiente" and item.due_date < today_value for item in deadlines)
    upcoming_count = sum(item.status == "Pendiente" and today_value <= item.due_date <= today_value + timedelta(days=7) for item in deadlines)
    return render(
        request, "calendar.html", db, user, companies=companies, employees=employees, deadlines=deadlines,
        automatic_alerts=automatic_alerts, selected_company=company_id, selected_employee=employee_id,
        status_filter=status_filter, overdue_count=overdue_count, upcoming_count=upcoming_count,
    )


@app.post("/app/calendar")
def create_deadline(
    company_id: Annotated[int, Form()], title: Annotated[str, Form()], due_date: Annotated[date, Form()],
    deadline_type: Annotated[str, Form()] = "General", priority: Annotated[str, Form()] = "Normal",
    employee_id: Annotated[int | None, Form()] = None, notes: Annotated[str, Form()] = "",
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")), db: Session = Depends(get_db),
):
    company = company_allowed(db, user, company_id)
    employee = db.get(Employee, employee_id) if employee_id else None
    if employee and employee.company_id != company.id:
        raise HTTPException(400, "El funcionario no pertenece a la empresa seleccionada.")
    item = LaborDeadline(
        company_id=company.id, employee_id=employee.id if employee else None, title=title.strip(),
        deadline_type=deadline_type.strip(), due_date=due_date, priority=priority, notes=notes.strip(),
        created_by=user.email,
    )
    db.add(item)
    db.flush()
    if employee:
        add_employee_event(db, employee, user, "Agenda", f"Vencimiento creado: {item.title}", item.notes, item.due_date)
    write_audit(db, user, "crear", "vencimiento", str(item.id), f"{company.legal_name}: {item.title}")
    db.commit()
    return RedirectResponse("/app/calendar", status_code=303)


@app.post("/app/calendar/{deadline_id}/status")
def deadline_status(
    deadline_id: int, status_value: Annotated[str, Form(alias="status")],
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")), db: Session = Depends(get_db),
):
    item = db.get(LaborDeadline, deadline_id)
    if not item or item.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    item.status = status_value
    write_audit(db, user, "actualizar_estado", "vencimiento", str(item.id), status_value)
    db.commit()
    return RedirectResponse("/app/calendar", status_code=303)


@app.post("/app/calendar/send-reminders")
def send_calendar_reminders(
    user: User = Depends(require_roles("administrador")), db: Session = Depends(get_db),
):
    studio = db.get(Studio, user.studio_id)
    company_ids = company_ids_for_user(db, user)
    horizon = date.today() + timedelta(days=7)
    deadlines = list(db.scalars(select(LaborDeadline).where(
        LaborDeadline.company_id.in_(company_ids), LaborDeadline.status == "Pendiente",
        LaborDeadline.due_date <= horizon,
    ).order_by(LaborDeadline.due_date))) if company_ids else []
    recipients = list(db.scalars(select(User).where(
        User.studio_id == user.studio_id, User.active.is_(True), User.role.in_(["administrador", "contador"]),
    )))
    payload = [{
        "date": format_date(item.due_date), "title": item.title, "company": item.company.legal_name,
        "status": "Vencido" if item.due_date < date.today() else "Próximo",
    } for item in deadlines]
    sent = 0
    for recipient in recipients:
        try:
            if send_deadline_summary(recipient.email, studio.name if studio else "el estudio", payload):
                sent += 1
        except Exception:
            continue
    write_audit(db, user, "enviar", "recordatorios_agenda", str(user.studio_id), f"{sent} correos; {len(deadlines)} vencimientos")
    db.commit()
    return RedirectResponse(f"/app/calendar?reminders={sent}", status_code=303)


@app.get("/app/calendar.ics")
def calendar_ics(user: User = Depends(require_user), db: Session = Depends(get_db)):
    company_ids = company_ids_for_user(db, user)
    items = list(db.scalars(select(LaborDeadline).where(LaborDeadline.company_id.in_(company_ids), LaborDeadline.status == "Pendiente").order_by(LaborDeadline.due_date))) if company_ids else []
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Digit Laboral//Agenda Laboral//ES"]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    for item in items:
        lines.extend([
            "BEGIN:VEVENT", f"UID:deadline-{item.id}@digitlaboral", f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{item.due_date.strftime('%Y%m%d')}",
            f"SUMMARY:{item.title.replace(',', '\\,')}",
            f"DESCRIPTION:{(item.notes or item.deadline_type).replace(chr(10), ' ').replace(',', '\\,')}",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    return Response("\r\n".join(lines) + "\r\n", media_type="text/calendar", headers={"Content-Disposition": "attachment; filename=agenda_digit_laboral.ics"})



def _parse_optional_form_date(value: str, label: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(400, f"La fecha de {label} no es válida.") from exc


def _parse_optional_form_int(value: str, label: str, minimum: int = 0) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, f"El campo {label} debe ser un número entero.") from exc
    if parsed < minimum:
        raise HTTPException(400, f"El campo {label} no puede ser menor que {minimum}.")
    if parsed > 2147483647:
        raise HTTPException(400, f"El campo {label} supera el máximo admitido.")
    return parsed


def _create_in_app_notification(
    db: Session,
    background_tasks: BackgroundTasks,
    recipient: User,
    *,
    event_type: str,
    title: str,
    body: str,
    target_url: str,
    request_id: int | None = None,
    dedupe_key: str | None = None,
) -> None:
    if not recipient.active:
        return
    _, delivery, created = create_notification(
        db,
        recipient=recipient,
        event_type=event_type,
        title=title,
        body=body,
        target_url=target_url,
        request_id=request_id,
        dedupe_key=dedupe_key,
    )
    if created and delivery is not None:
        background_tasks.add_task(send_notification_delivery, delivery.id, recipient.studio_id)


def _notify_studio_team(
    db: Session,
    background_tasks: BackgroundTasks,
    company: Company,
    actor: User | None,
    *,
    event_type: str,
    title: str,
    body: str,
    target_url: str,
    request_id: int | None = None,
    only_user_id: int | None = None,
) -> None:
    query = select(User).where(
        User.studio_id == company.studio_id,
        User.active.is_(True),
        User.role.in_(("administrador", "contador", "auxiliar")),
    )
    if only_user_id is not None:
        query = query.where(User.id == only_user_id)
    for recipient in db.scalars(query.order_by(User.id)):
        if actor is not None and recipient.id == actor.id:
            continue
        _create_in_app_notification(
            db, background_tasks, recipient,
            event_type=event_type, title=title, body=body,
            target_url=target_url, request_id=request_id,
        )


def _notify_company_contacts(
    db: Session,
    background_tasks: BackgroundTasks,
    item: CompanyRequest,
    actor: User | None,
    *,
    event_type: str,
    title: str,
    body: str,
    target_url: str,
) -> None:
    company = db.get(Company, item.company_id)
    recipients: dict[int, User] = {}
    if company:
        for recipient in db.scalars(select(User).where(
            User.company_id == item.company_id,
            User.studio_id == company.studio_id,
            User.role == "empresa",
            User.active.is_(True),
        )):
            recipients[recipient.id] = recipient
    if item.requested_by_user_id:
        requester = db.get(User, item.requested_by_user_id)
        if requester and requester.active and requester.role != "empresa":
            recipients[requester.id] = requester
    for recipient in recipients.values():
        if actor is not None and recipient.id == actor.id:
            continue
        _create_in_app_notification(
            db, background_tasks, recipient,
            event_type=event_type, title=title, body=body,
            target_url=target_url, request_id=item.id,
        )


def _notify_request_counterpart(
    db: Session,
    background_tasks: BackgroundTasks,
    item: CompanyRequest,
    actor: User,
    *,
    event_type: str,
    title: str,
    body: str,
    external_visible: bool = True,
) -> None:
    company = db.get(Company, item.company_id)
    if not company:
        return
    target_url = f"/app/requests/{item.id}"
    if actor.role == "empresa" or not external_visible:
        workflow = db.scalar(select(RequestWorkflow).where(RequestWorkflow.request_id == item.id))
        assigned_id = workflow.assigned_user_id if workflow else None
        _notify_studio_team(
            db, background_tasks, company, actor,
            event_type=event_type, title=title, body=body,
            target_url=target_url, request_id=item.id, only_user_id=assigned_id,
        ) if assigned_id else _notify_studio_team(
            db, background_tasks, company, actor,
            event_type=event_type, title=title, body=body,
            target_url=target_url, request_id=item.id,
        )
    else:
        _notify_company_contacts(
            db, background_tasks, item, actor,
            event_type=event_type, title=title, body=body, target_url=target_url,
        )


def _sync_due_notifications_for_user(
    db: Session, background_tasks: BackgroundTasks, user: User,
) -> None:
    if user.role not in {"administrador", "contador", "auxiliar"}:
        return
    today_value = date.today()
    horizon = today_value + timedelta(days=3)
    company_ids = company_ids_for_user(db, user)
    if not company_ids:
        return
    open_statuses = ("Pendiente", "En revisión", "Falta información", "Procesando", "Aprobada")
    due_rows = list(db.execute(
        select(CompanyRequest, RequestWorkflow, Company)
        .join(RequestWorkflow, RequestWorkflow.request_id == CompanyRequest.id)
        .join(Company, Company.id == CompanyRequest.company_id)
        .where(
            CompanyRequest.company_id.in_(company_ids),
            CompanyRequest.status.in_(open_statuses),
            RequestWorkflow.due_date.is_not(None),
            RequestWorkflow.due_date <= horizon,
        )
        .order_by(RequestWorkflow.due_date, CompanyRequest.id)
    ))
    for item, workflow, company in due_rows:
        if workflow.assigned_user_id and workflow.assigned_user_id != user.id:
            continue
        dedupe_key = f"request-deadline:{item.id}:{workflow.due_date.isoformat()}:{user.id}"
        due_text = workflow.due_date.strftime("%d/%m/%Y")
        is_overdue = workflow.due_date < today_value
        _create_in_app_notification(
            db, background_tasks, user,
            event_type="solicitud_vencimiento",
            title=f"{'Plazo vencido' if is_overdue else 'Solicitud próxima a vencer'} · #{item.id}",
            body=f"El trámite «{item.subject or item.request_type}» de {company.legal_name} "
                 f"{'venció' if is_overdue else 'vence'} el {due_text}.",
            target_url=f"/app/requests/{item.id}", request_id=item.id, dedupe_key=dedupe_key,
        )



@app.post("/internal/cron/notifications")
def run_notification_cron(request: Request):
    """Run periodic notices using the web service's existing database and SMTP settings."""
    expected = settings.notification_cron_token
    authorization = request.headers.get("authorization", "")
    supplied = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        raise HTTPException(401, "Autorización de trabajador inválida.")

    request_notices = create_due_request_notifications()
    certificate_notices = create_due_official_certificate_notifications()
    deliveries = dispatch_notification_outbox()
    return JSONResponse({
        "ok": True,
        "request_notices_created": request_notices,
        "certificate_notices_created": certificate_notices,
        "deliveries": deliveries,
    })


@app.get("/app/notifications", response_class=HTMLResponse)
def notifications_page(
    request: Request,
    background_tasks: BackgroundTasks,
    filter_value: str = "all",
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    if user.role == "superadmin":
        return RedirectResponse("/admin", status_code=303)
    # Materialize due-date notices when the recipient opens the inbox. A daily
    # worker can do the same sweep proactively; dedupe keys prevent repeats.
    _sync_due_notifications_for_user(db, background_tasks, user)
    db.commit()
    query = select(Notification).where(Notification.recipient_user_id == user.id)
    if filter_value == "unread":
        query = query.where(Notification.read_at.is_(None))
    elif filter_value == "read":
        query = query.where(Notification.read_at.is_not(None))
    elif filter_value != "all":
        filter_value = "all"
    items = list(db.scalars(query.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(100)))
    unread_count = db.scalar(select(func.count(Notification.id)).where(
        Notification.recipient_user_id == user.id, Notification.read_at.is_(None)
    )) or 0
    return render(
        request, "notifications.html", db, user,
        items=items, filter_value=filter_value, unread_count=unread_count,
    )


@app.get("/app/notifications/unread-count")
def notifications_unread_count(user: User = Depends(require_user), db: Session = Depends(get_db)):
    count = db.scalar(select(func.count(Notification.id)).where(
        Notification.recipient_user_id == user.id,
        Notification.read_at.is_(None),
    )) or 0
    return JSONResponse({"count": count})


@app.post("/app/notifications/read-all")
def notifications_read_all(user: User = Depends(require_user), db: Session = Depends(get_db)):
    items = list(db.scalars(select(Notification).where(
        Notification.recipient_user_id == user.id,
        Notification.read_at.is_(None),
    )))
    now = datetime.now(UTC)
    for item in items:
        item.read_at = now
    db.commit()
    return RedirectResponse("/app/notifications", status_code=303)


@app.post("/app/notifications/{notification_id}/open")
def notification_open(
    notification_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    item = db.scalar(select(Notification).where(
        Notification.id == notification_id,
        Notification.recipient_user_id == user.id,
    ))
    if not item:
        raise HTTPException(404, "Notificación no encontrada.")
    if item.read_at is None:
        item.read_at = datetime.now(UTC)
        db.commit()
    target = item.target_url or "/app/notifications"
    if not target.startswith("/") or target.startswith("//"):
        target = "/app/notifications"
    return RedirectResponse(target, status_code=303)


@app.post("/app/notifications/{notification_id}/read")
def notification_mark_read(
    notification_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    item = db.scalar(select(Notification).where(
        Notification.id == notification_id,
        Notification.recipient_user_id == user.id,
    ))
    if not item:
        raise HTTPException(404, "Notificación no encontrada.")
    if item.read_at is None:
        item.read_at = datetime.now(UTC)
        db.commit()
    return RedirectResponse("/app/notifications", status_code=303)


@app.get("/app/requests", response_class=HTMLResponse)
def requests_page(
    request: Request,
    status_filter: str = "",
    company_id: OptionalQueryId = None,
    request_type: str = "",
    assigned_filter: str = "",
    overdue_only: bool = False,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    company_ids = company_ids_for_user(db, user)
    companies = list(db.scalars(select(Company).where(Company.id.in_(company_ids)).order_by(Company.legal_name))) if company_ids else []
    employees = list(db.scalars(select(Employee).where(Employee.company_id.in_(company_ids)).order_by(Employee.full_name))) if company_ids else []

    allowed_statuses = {"Pendiente", "En revisión", "Falta información", "Procesando", "Aprobada", "Rechazada", "Resuelta", "Aplicada"}
    standard_types = {"Alta de funcionario", "Baja de funcionario", "Cambio salarial", "Vacaciones", "Permiso/licencia", "Documento laboral", "Otra consulta"}
    stored_types = set(db.scalars(
        select(CompanyRequest.request_type)
        .where(CompanyRequest.company_id.in_(company_ids))
        .distinct()
    )) if company_ids else set()
    allowed_types = standard_types | {str(value).strip() for value in stored_types if value and str(value).strip() and len(str(value)) <= 100}
    status_filter = status_filter if status_filter in allowed_statuses else ""
    request_type = request_type if request_type in allowed_types else ""
    if company_id not in company_ids:
        company_id = None
    # The lawyer workspace is assignment-based; query parameters cannot expose the full queue.
    if user.role == "abogado":
        assigned_filter = "mine"
    else:
        assigned_filter = "mine" if assigned_filter == "mine" and user.role != "empresa" else ""
    overdue_only = bool(overdue_only and user.role != "empresa")

    query = select(CompanyRequest).outerjoin(
        RequestWorkflow, RequestWorkflow.request_id == CompanyRequest.id
    ).where(CompanyRequest.company_id.in_(company_ids)) if company_ids else select(CompanyRequest).where(False)
    if company_id:
        query = query.where(CompanyRequest.company_id == company_id)
    if status_filter:
        query = query.where(CompanyRequest.status == status_filter)
    if request_type:
        query = query.where(CompanyRequest.request_type == request_type)
    if assigned_filter == "mine":
        query = query.where(RequestWorkflow.assigned_user_id == user.id)
    if overdue_only:
        query = query.where(
            RequestWorkflow.due_date.is_not(None),
            RequestWorkflow.due_date < date.today(),
            CompanyRequest.status.notin_({"Resuelta", "Rechazada", "Aplicada"}),
        )

    items = list(db.scalars(query.order_by(
        RequestWorkflow.due_date.asc().nullslast(),
        CompanyRequest.created_at.desc(),
    ))) if company_ids else []
    request_ids = [item.id for item in items]
    workflows = list(db.scalars(select(RequestWorkflow).where(RequestWorkflow.request_id.in_(request_ids)))) if request_ids else []
    workflow_by_request = {item.request_id: item for item in workflows}
    pending = sum(item.status not in {"Resuelta", "Rechazada", "Aplicada"} for item in items)
    overdue = sum(
        1 for workflow in workflows
        if workflow.due_date and workflow.due_date < date.today()
        and workflow.request_id in {item.id for item in items}
        and next((item.status for item in items if item.id == workflow.request_id), "") not in {"Resuelta", "Rechazada", "Aplicada"}
    )
    return render(
        request, "requests.html", db, user, items=items, companies=companies, employees=employees,
        workflow_by_request=workflow_by_request, pending=pending, overdue=overdue,
        selected_status=status_filter, selected_company=company_id, selected_type=request_type,
        assigned_filter=assigned_filter, overdue_only=overdue_only, request_types=sorted(allowed_types),
    )


def _vacation_balance(
    db: Session, employee_id: int, period_year: int, *, excluding_request_id: int | None = None,
) -> dict[str, int]:
    """Calculate annual entitlement minus used days and active approved reservations."""
    ledger_rows = list(db.scalars(
        select(Vacation).where(
            Vacation.employee_id == employee_id,
            Vacation.period_year == period_year,
            Vacation.status.notin_(("Rechazada", "Anulada", "Cancelada")),
        ).order_by(Vacation.created_at, Vacation.id)
    ))
    entitled = sum(max(0, int(row.entitled_days or 0)) for row in ledger_rows)
    used = sum(max(0, int(row.used_days or 0)) for row in ledger_rows)

    reservation_query = select(CompanyRequest).where(
        CompanyRequest.employee_id == employee_id,
        CompanyRequest.period_year == period_year,
        CompanyRequest.status == "Aprobada",
    )
    if excluding_request_id is not None:
        reservation_query = reservation_query.where(CompanyRequest.id != excluding_request_id)
    reservations = list(db.scalars(reservation_query))
    reserved = 0
    for request_item in reservations:
        if request_item.request_type.strip().casefold() != "vacaciones":
            continue
        workflow = db.scalar(select(RequestWorkflow).where(RequestWorkflow.request_id == request_item.id))
        if workflow and workflow.applied:
            continue
        reserved += max(0, int(request_item.requested_days or 0))

    return {
        "entitled_days": entitled,
        "used_days": used,
        "reserved_days": reserved,
        "available_days": entitled - used - reserved,
    }


def _validate_vacation_balance(db: Session, item: CompanyRequest) -> None:
    if (
        not item.employee_id or not item.period_year or not item.requested_days
        or not item.start_date or not item.end_date
    ):
        raise HTTPException(400, "La solicitud de vacaciones necesita funcionario, periodo, días y fechas válidas.")
    balance = _vacation_balance(db, item.employee_id, item.period_year, excluding_request_id=item.id)
    if balance["entitled_days"] <= 0:
        raise HTTPException(409, "No hay saldo anual cargado para ese funcionario y periodo. Registrá primero su derecho de vacaciones.")
    if item.requested_days > balance["available_days"]:
        raise HTTPException(
            409,
            f"Saldo insuficiente: hay {max(0, balance['available_days'])} días disponibles y la solicitud requiere {item.requested_days}.",
        )


@app.get("/app/requests/vacation-balance")
def request_vacation_balance(
    employee_id: int, period_year: int, user: User = Depends(require_user), db: Session = Depends(get_db),
):
    employee = db.get(Employee, employee_id)
    if not employee or employee.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404, "Funcionario no encontrado.")
    if not 1900 <= period_year <= date.today().year + 2:
        raise HTTPException(400, "El año del periodo no es válido.")
    return JSONResponse(_vacation_balance(db, employee_id, period_year))


@app.post("/app/requests")
def add_request(
    background_tasks: BackgroundTasks,
    company_id: Annotated[int, Form()],
    request_type: Annotated[str, Form()],
    detail: Annotated[str, Form()],
    subject: Annotated[str, Form()] = "",
    priority: Annotated[str, Form()] = "Normal",
    employee_id_raw: Annotated[str, Form(alias="employee_id")] = "",
    effective_date_raw: Annotated[str, Form(alias="effective_date")] = "",
    start_date_raw: Annotated[str, Form(alias="start_date")] = "",
    end_date_raw: Annotated[str, Form(alias="end_date")] = "",
    period_year_raw: Annotated[str, Form(alias="period_year")] = "",
    requested_days_raw: Annotated[str, Form(alias="requested_days")] = "",
    entitled_days_raw: Annotated[str, Form(alias="entitled_days")] = "",
    amount_raw: Annotated[str, Form(alias="amount")] = "",
    leave_type_raw: Annotated[str, Form(alias="leave_type")] = "",
    hours_requested_raw: Annotated[str, Form(alias="hours_requested")] = "",
    user: User = Depends(require_roles("administrador", "contador", "auxiliar", "empresa")),
    db: Session = Depends(get_db),
):
    company = company_allowed(db, user, company_id)
    request_type_value = request_type.strip()
    subject_value = subject.strip()
    detail_value = detail.strip()
    priority_value = priority.strip()
    if not request_type_value or len(request_type_value) > 100:
        raise HTTPException(400, "Seleccioná un tipo de solicitud válido.")
    if not detail_value:
        raise HTTPException(400, "La descripción de la solicitud es obligatoria.")
    if len(subject_value) > 180 or len(detail_value) > 10000:
        raise HTTPException(400, "El asunto o el detalle supera el tamaño permitido.")
    if priority_value not in {"Normal", "Alta", "Urgente"}:
        raise HTTPException(400, "La prioridad seleccionada no es válida.")

    employee_id = _parse_optional_form_int(employee_id_raw, "funcionario", 1)
    employee = db.get(Employee, employee_id) if employee_id else None
    if employee_id and (not employee or employee.company_id != company.id):
        raise HTTPException(400, "El funcionario no pertenece a la empresa seleccionada.")
    effective_date = _parse_optional_form_date(effective_date_raw, "fecha efectiva")
    start_date = _parse_optional_form_date(start_date_raw, "fecha inicial")
    end_date = _parse_optional_form_date(end_date_raw, "fecha final")
    period_year = _parse_optional_form_int(period_year_raw, "año del periodo", 1900)
    requested_days = _parse_optional_form_int(requested_days_raw or entitled_days_raw, "días solicitados", 1)
    amount = _parse_optional_form_int(amount_raw, "importe", 0)
    hours_raw = (hours_requested_raw or "").strip()
    hours_requested = None
    if hours_raw:
        try:
            hours_requested = Decimal(hours_raw)
        except Exception as exc:
            raise HTTPException(400, "La cantidad de horas no es válida.") from exc
        if not hours_requested.is_finite() or hours_requested <= 0 or hours_requested > Decimal("744"):
            raise HTTPException(400, "La cantidad de horas debe ser mayor que 0 y no superar 744.")
        rounded_hours = hours_requested.quantize(Decimal("0.01"))
        if hours_requested != rounded_hours:
            raise HTTPException(400, "La cantidad de horas admite como máximo dos decimales.")
        hours_requested = rounded_hours
    if period_year is not None and period_year > date.today().year + 2:
        raise HTTPException(400, "El año del periodo está demasiado lejos.")
    if start_date and end_date and end_date < start_date:
        raise HTTPException(400, "La fecha final no puede ser anterior a la fecha inicial.")

    request_kind = request_type_value.casefold()
    if request_kind == "cambio salarial":
        if not employee or amount is None or amount <= 0 or effective_date is None:
            raise HTTPException(400, "Un cambio salarial requiere funcionario, salario mensual positivo y fecha efectiva.")
    elif request_kind == "vacaciones":
        if not employee or period_year is None or requested_days is None or not start_date or not end_date:
            raise HTTPException(400, "Una solicitud de vacaciones requiere funcionario, periodo, días solicitados y fechas desde/hasta.")
        if requested_days > 365:
            raise HTTPException(400, "Los días solicitados de vacaciones no pueden superar 365.")
        balance = _vacation_balance(db, employee.id, period_year)
        if balance["entitled_days"] <= 0:
            raise HTTPException(409, "No hay saldo anual cargado para ese funcionario y periodo. Registrá primero su derecho de vacaciones.")
        if requested_days > balance["available_days"]:
            raise HTTPException(400, f"Saldo insuficiente: hay {max(0, balance['available_days'])} días disponibles para el periodo solicitado.")
    elif request_kind in {"permiso/licencia", "permiso", "licencia"}:
        if not employee or not leave_type_raw.strip() or not start_date or not end_date:
            raise HTTPException(400, "Un permiso o licencia requiere funcionario, tipo de permiso y fechas desde/hasta.")

    item = CompanyRequest(
        company_id=company.id,
        request_type=request_type_value,
        subject=subject_value,
        detail=detail_value,
        requested_by_user_id=user.id,
        employee_id=employee.id if employee else None,
        effective_date=effective_date,
        start_date=start_date,
        end_date=end_date,
        period_year=period_year,
        requested_days=requested_days,
        amount=amount,
        leave_type=leave_type_raw.strip()[:100],
        hours_requested=hours_requested,
        priority=priority_value,
        status="Pendiente",
    )
    db.add(item)
    db.flush()
    write_audit(db, user, "crear", "solicitud", str(item.id), request_type_value)
    title = f"Nueva solicitud #{item.id}"
    body = f"{company.legal_name} registró {item.request_type.lower()}: {item.subject or item.request_type}."
    if user.role == "empresa":
        _notify_studio_team(
            db, background_tasks, company, user,
            event_type="solicitud_creada", title=title, body=body,
            target_url=f"/app/requests/{item.id}", request_id=item.id,
        )
    else:
        _notify_company_contacts(
            db, background_tasks, item, user,
            event_type="solicitud_creada", title=title,
            body="El estudio registró una nueva gestión para tu empresa.",
            target_url=f"/app/requests/{item.id}",
        )
    db.commit()
    return RedirectResponse(f"/app/requests/{item.id}", status_code=303)


@app.get("/app/requests/{request_id}", response_class=HTMLResponse)
def request_detail_page(
    request_id: int, request: Request, user: User = Depends(require_user), db: Session = Depends(get_db),
):
    item = db.get(CompanyRequest, request_id)
    if not item or item.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404, "Solicitud no encontrada.")
    workflow = db.scalar(select(RequestWorkflow).where(RequestWorkflow.request_id == item.id))
    if user.role == "abogado" and (not workflow or workflow.assigned_user_id != user.id):
        raise HTTPException(404, "Solicitud no encontrada.")
    comments_query = select(RequestComment).where(RequestComment.request_id == item.id)
    if user.role == "empresa":
        comments_query = comments_query.where(RequestComment.visibility == "Empresa")
    comments = list(db.scalars(comments_query.order_by(RequestComment.created_at)))
    attachments = list(db.scalars(select(RequestAttachment).where(RequestAttachment.request_id == item.id).order_by(RequestAttachment.created_at.desc())))
    users = list(db.scalars(select(User).where(User.studio_id == user.studio_id, User.active.is_(True), User.role != "empresa").order_by(User.full_name))) if user.studio_id else []
    return render(request, "request_detail.html", db, user, item=item, workflow=workflow, comments=comments, attachments=attachments, users=users, today=date.today())


@app.post("/app/requests/{request_id}/comments")
def add_request_comment(
    request_id: int, background_tasks: BackgroundTasks,
    body: Annotated[str, Form()], visibility: Annotated[str, Form()] = "Empresa",
    user: User = Depends(require_user), db: Session = Depends(get_db),
):
    item = db.get(CompanyRequest, request_id)
    if not item or item.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    if user.role == "abogado":
        workflow = db.scalar(select(RequestWorkflow).where(RequestWorkflow.request_id == item.id))
        if not workflow or workflow.assigned_user_id != user.id:
            raise HTTPException(404)
    safe_visibility = "Empresa" if user.role == "empresa" else ("Interno" if visibility == "Interno" else "Empresa")
    body_value = body.strip()
    if not body_value:
        raise HTTPException(400, "El comentario no puede estar vacío.")
    if len(body_value) > 10000:
        raise HTTPException(400, "El comentario supera el máximo de 10.000 caracteres.")
    comment = RequestComment(
        request_id=item.id, user_id=user.id, author_name=user.full_name, visibility=safe_visibility, body=body_value,
    )
    db.add(comment)
    db.flush()
    write_audit(db, user, "comentar", "solicitud", str(item.id), safe_visibility)
    if safe_visibility == "Interno":
        company = db.get(Company, item.company_id)
        if company:
            _notify_studio_team(
                db, background_tasks, company, user,
                event_type="nota_interna", title=f"Nueva nota interna · Solicitud #{item.id}",
                body="Se agregó una nota interna al trámite.",
                target_url=f"/app/requests/{item.id}", request_id=item.id,
            )
    else:
        _notify_request_counterpart(
            db, background_tasks, item, user,
            event_type="comentario_solicitud", title=f"Nueva respuesta · Solicitud #{item.id}",
            body="Se agregó un comentario visible en el trámite.",
        )
    db.commit()
    return RedirectResponse(f"/app/requests/{item.id}#conversation", status_code=303)


@app.post("/app/requests/{request_id}/attachments")
async def add_request_attachment(
    request_id: int, background_tasks: BackgroundTasks,
    file: UploadFile = File(), user: User = Depends(require_user), db: Session = Depends(get_db),
):
    item = db.get(CompanyRequest, request_id)
    if not item or item.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    if user.role == "abogado":
        workflow = db.scalar(select(RequestWorkflow).where(RequestWorkflow.request_id == item.id))
        if not workflow or workflow.assigned_user_id != user.id:
            raise HTTPException(404)
    content = await file.read(MAX_UPLOAD_SIZE + 1)
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(413, "El archivo supera el máximo permitido de 10 MB.")
    if not content:
        raise HTTPException(400, "El archivo adjunto está vacío.")
    content_type = (file.content_type or "application/octet-stream").lower()
    if content_type not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(415, "Tipo de archivo no permitido.")
    if content_type == "application/pdf" and not content.startswith(b"%PDF-"):
        raise HTTPException(415, "El contenido no corresponde a un PDF válido.")
    if content_type == "image/png" and not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(415, "El contenido no corresponde a una imagen PNG válida.")
    if content_type == "image/jpeg" and not content.startswith(b"\xff\xd8\xff"):
        raise HTTPException(415, "El contenido no corresponde a una imagen JPEG válida.")
    if content_type in {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }:
        required_member = "word/document.xml" if content_type.endswith("wordprocessingml.document") else "xl/workbook.xml"
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                is_ooxml = required_member in archive.namelist()
        except (zipfile.BadZipFile, OSError):
            is_ooxml = False
        if not is_ooxml:
            raise HTTPException(415, "El contenido no corresponde a un documento Word o Excel válido.")
    stored_name = f"requests/{item.id}/{uuid.uuid4().hex}_{safe_filename(file.filename or 'archivo')}"
    storage.put(stored_name, content, content_type)
    attachment = RequestAttachment(
        request_id=item.id, stored_name=stored_name, original_name=safe_filename(file.filename or "archivo"),
        content_type=content_type,
        # Render's local filesystem may be ephemeral. PostgreSQL is the fallback for new uploads.
        content_bytes=content if settings.storage_backend == "local" else None,
        uploaded_by=user.email,
    )
    db.add(attachment)
    db.flush()
    write_audit(db, user, "adjuntar", "solicitud", str(item.id), attachment.original_name)
    _notify_request_counterpart(
        db, background_tasks, item, user,
        event_type="adjunto_solicitud", title=f"Nuevo archivo · Solicitud #{item.id}",
        body="Se adjuntó un archivo al trámite.",
    )
    db.commit()
    return RedirectResponse(f"/app/requests/{item.id}#attachments", status_code=303)


@app.get("/app/requests/{request_id}/attachments/{attachment_id}/download")
def download_request_attachment(
    request_id: int, attachment_id: int, user: User = Depends(require_user), db: Session = Depends(get_db),
):
    item = db.get(CompanyRequest, request_id)
    attachment = db.get(RequestAttachment, attachment_id)
    if not item or item.company_id not in company_ids_for_user(db, user) or not attachment or attachment.request_id != item.id:
        raise HTTPException(404)
    if user.role == "abogado":
        workflow = db.scalar(select(RequestWorkflow).where(RequestWorkflow.request_id == item.id))
        if not workflow or workflow.assigned_user_id != user.id:
            raise HTTPException(404)
    storage_key = attachment.stored_name
    if attachment.content_bytes is not None:
        content = bytes(attachment.content_bytes)
    elif storage.exists(storage_key):
        content = storage.get(storage_key)
    else:
        # Support both the current key layout and the older nested attachment directory.
        legacy_candidates = (
            UPLOAD_DIR / storage_key,
            UPLOAD_DIR / "requests" / str(item.id) / Path(storage_key).name,
        )
        root = UPLOAD_DIR.resolve()
        legacy = next(
            (
                candidate for candidate in legacy_candidates
                if candidate.resolve().is_file()
                and root in candidate.resolve().parents
            ),
            None,
        )
        if legacy is None:
            raise HTTPException(404, "Archivo no encontrado.")
        content = legacy.read_bytes()
    write_audit(db, user, "descargar", "adjunto_solicitud", str(attachment.id), attachment.original_name)
    db.commit()
    return StreamingResponse(io.BytesIO(content), media_type=attachment.content_type, headers={"Content-Disposition": f'attachment; filename="{attachment.original_name}"'})


@app.post("/app/requests/{request_id}/status")
def request_status(
    request_id: int,
    background_tasks: BackgroundTasks,
    status_value: Annotated[str, Form(alias="status")],
    response: Annotated[str, Form()] = "",
    assigned_user_id_raw: Annotated[str, Form(alias="assigned_user_id")] = "",
    due_date_raw: Annotated[str, Form(alias="due_date")] = "",
    internal_notes: Annotated[str, Form()] = "",
    user: User = Depends(require_roles("administrador", "contador", "auxiliar", "abogado")),
    db: Session = Depends(get_db),
):
    item = db.get(CompanyRequest, request_id)
    if not item or item.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    existing_workflow = db.scalar(select(RequestWorkflow).where(RequestWorkflow.request_id == item.id))
    if user.role == "abogado" and (not existing_workflow or existing_workflow.assigned_user_id != user.id):
        raise HTTPException(404, "Solicitud no encontrada.")
    if existing_workflow and existing_workflow.applied:
        raise HTTPException(409, "Este trámite ya fue aplicado y su historial no puede modificarse.")
    valid_statuses = {"Pendiente", "En revisión", "Falta información", "Procesando", "Aprobada", "Resuelta", "Rechazada"}
    if status_value not in valid_statuses:
        raise HTTPException(400, "Estado inválido.")
    if status_value in {"Aprobada", "Rechazada"} and user.role not in {"administrador", "contador"}:
        raise HTTPException(403, "Solo un administrador o contador puede aprobar o rechazar un trámite.")
    if status_value == "Aprobada" and item.request_type.strip().casefold() == "vacaciones":
        _validate_vacation_balance(db, item)
    if item.request_type.strip().casefold() == "cambio salarial" and status_value == "Resuelta":
        raise HTTPException(409, "Un cambio salarial debe aplicarse desde su acción específica o rechazarse; no se puede cerrar como resuelto sin actualizar el legajo.")
    due_date = _parse_optional_form_date(due_date_raw, "fecha límite")
    requested_assigned_user_id = _parse_optional_form_int(assigned_user_id_raw, "responsable", 1)
    # Lawyers can work assigned cases, not assign or unassign them.
    assigned_user_id = user.id if user.role == "abogado" else requested_assigned_user_id
    company = db.get(Company, item.company_id)
    previous_status = item.status
    previous_response = item.response
    workflow = db.scalar(select(RequestWorkflow).where(RequestWorkflow.request_id == item.id))
    if not workflow:
        workflow = RequestWorkflow(request_id=item.id)
        db.add(workflow)
        db.flush()
    old_assigned_id = workflow.assigned_user_id
    if assigned_user_id:
        assigned = db.get(User, assigned_user_id)
        if not assigned or not company or assigned.studio_id != company.studio_id or assigned.role == "empresa" or not assigned.active:
            raise HTTPException(400, "Responsable inválido.")
        workflow.assigned_user_id = assigned.id
    else:
        workflow.assigned_user_id = None
    workflow.due_date = due_date
    workflow.internal_notes = internal_notes.strip()
    workflow.decision_notes = response.strip()
    item.status = status_value
    item.response = response.strip()
    now = datetime.now(UTC)
    if status_value in {"Resuelta", "Rechazada", "Aplicada"}:
        item.resolved_at = now
    else:
        item.resolved_at = None
    if status_value == "Aprobada":
        workflow.approved_by_user_id = user.id
        workflow.approved_at = now
    elif previous_status == "Aprobada":
        workflow.approved_by_user_id = None
        workflow.approved_at = None
    if response.strip() and response.strip() != previous_response:
        db.add(RequestComment(
            request_id=item.id, user_id=user.id, author_name=user.full_name,
            visibility="Empresa", body=response.strip(),
        ))
    if company and old_assigned_id != workflow.assigned_user_id and workflow.assigned_user_id:
        assigned = db.get(User, workflow.assigned_user_id)
        if assigned and assigned.id != user.id:
            _create_in_app_notification(
                db, background_tasks, assigned,
                event_type="solicitud_asignada", title=f"Solicitud asignada · #{item.id}",
                body=f"Se te asignó el trámite «{item.subject or item.request_type}».",
                target_url=f"/app/requests/{item.id}", request_id=item.id,
            )
    if previous_status != status_value or (response.strip() and response.strip() != previous_response):
        _notify_request_counterpart(
            db, background_tasks, item, user,
            event_type="estado_solicitud", title=f"Actualización de solicitud #{item.id}",
            body=f"El estado del trámite cambió a «{status_value}».",
        )
    write_audit(db, user, "actualizar_estado", "solicitud", str(item.id), status_value)
    db.commit()
    return RedirectResponse(f"/app/requests/{item.id}", status_code=303)


@app.post("/app/requests/{request_id}/review")
def review_request(
    request_id: int,
    background_tasks: BackgroundTasks,
    status_value: Annotated[str, Form(alias="status")],
    response: Annotated[str, Form()] = "",
    assigned_to: Annotated[str, Form()] = "",
    assigned_user_id_raw: Annotated[str, Form(alias="assigned_user_id")] = "",
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    item = db.get(CompanyRequest, request_id)
    if not item or item.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404, "Solicitud no encontrada.")
    if status_value not in {"Aprobada", "Rechazada", "En revisión", "Falta información"}:
        raise HTTPException(400, "La decisión seleccionada no es válida.")
    if status_value == "Aprobada" and item.request_type.strip().casefold() == "vacaciones":
        _validate_vacation_balance(db, item)
    existing_workflow = db.scalar(select(RequestWorkflow).where(RequestWorkflow.request_id == item.id))
    if existing_workflow and existing_workflow.applied:
        raise HTTPException(409, "Este trámite ya fue aplicado y no admite nuevas decisiones.")
    company = db.get(Company, item.company_id)
    workflow = db.scalar(select(RequestWorkflow).where(RequestWorkflow.request_id == item.id))
    if not workflow:
        workflow = RequestWorkflow(request_id=item.id)
        db.add(workflow)
        db.flush()
    old_assigned_id = workflow.assigned_user_id
    assigned_id = _parse_optional_form_int(assigned_user_id_raw, "responsable", 1)
    if not assigned_id and assigned_to.strip():
        assigned = db.scalar(select(User).where(
            User.studio_id == user.studio_id,
            User.full_name == assigned_to.strip(),
            User.active.is_(True),
            User.role != "empresa",
        ))
        assigned_id = assigned.id if assigned else None
        if not assigned_id:
            raise HTTPException(400, "No se encontró el responsable indicado.")
    if assigned_id:
        assigned = db.get(User, assigned_id)
        if not company or not assigned or not assigned.active or assigned.studio_id != company.studio_id or assigned.role == "empresa":
            raise HTTPException(400, "Responsable inválido.")
        workflow.assigned_user_id = assigned.id
    if workflow.assigned_user_id and workflow.assigned_user_id != old_assigned_id:
        assigned_user = db.get(User, workflow.assigned_user_id)
        if assigned_user and assigned_user.id != user.id:
            _create_in_app_notification(
                db, background_tasks, assigned_user,
                event_type="solicitud_asignada",
                title=f"Solicitud asignada · #{item.id}",
                body=f"Se te asignó el trámite «{item.subject or item.request_type}».",
                target_url=f"/app/requests/{item.id}", request_id=item.id,
            )
    now = datetime.now(UTC)
    old_status = item.status
    item.status = status_value
    item.response = response.strip()
    workflow.decision_notes = response.strip()
    if status_value == "Aprobada":
        workflow.approved_by_user_id = user.id
        workflow.approved_at = now
    else:
        workflow.approved_by_user_id = None
        workflow.approved_at = None
    item.resolved_at = now if status_value == "Rechazada" else None
    if response.strip():
        db.add(RequestComment(
            request_id=item.id, user_id=user.id, author_name=user.full_name,
            visibility="Empresa", body=response.strip(),
        ))
    _notify_request_counterpart(
        db, background_tasks, item, user,
        event_type="decision_solicitud", title=f"Decisión sobre solicitud #{item.id}",
        body=f"El estudio actualizó la solicitud a «{status_value}».",
    )
    write_audit(db, user, "revisar_solicitud", "solicitud", str(item.id), f"{old_status} → {status_value}")
    db.commit()
    return RedirectResponse(f"/app/requests/{item.id}", status_code=303)


@app.post("/app/requests/{request_id}/apply")
def apply_request(
    request_id: int,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    item = db.get(CompanyRequest, request_id)
    if not item or item.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404, "Solicitud no encontrada.")
    workflow = db.scalar(select(RequestWorkflow).where(RequestWorkflow.request_id == item.id))
    # Idempotency check comes first: an already-applied operation remains a success
    # response even though its status is no longer "Aprobada".
    if workflow and workflow.applied:
        return RedirectResponse(f"/app/requests/{item.id}", status_code=303)
    if item.status != "Aprobada" or not workflow or not workflow.approved_at:
        raise HTTPException(409, "El trámite debe estar aprobado antes de aplicarse.")
    request_kind = item.request_type.strip().casefold()
    employee = db.get(Employee, item.employee_id) if item.employee_id else None
    if not employee or employee.company_id != item.company_id:
        raise HTTPException(400, "La solicitud requiere un funcionario válido de la misma empresa.")

    if request_kind == "cambio salarial":
        if (
            item.amount is None or item.amount <= 0 or item.amount > 2147483647
            or item.effective_date is None
        ):
            raise HTTPException(400, "La solicitud salarial necesita un salario mensual positivo y una fecha efectiva válida.")
        previous_salary = employee.base_salary
        effective_from = item.effective_date
        employee.base_salary = item.amount
        db.add(SalaryHistory(
            employee_id=employee.id,
            previous_salary=previous_salary,
            new_salary=item.amount,
            effective_from=effective_from,
            reason=f"Cambio salarial aprobado mediante solicitud #{item.id}",
            created_by=user.email,
        ))
        add_employee_event(
            db, employee, user, "Salario",
            f"Cambio salarial aplicado por solicitud #{item.id}",
            f"Salario anterior: {previous_salary}; nuevo salario: {item.amount}.",
            effective_from, item.amount,
        )
    elif request_kind == "vacaciones":
        if (
            item.period_year is None or item.requested_days is None or item.requested_days <= 0
            or item.start_date is None or item.end_date is None
        ):
            raise HTTPException(400, "La solicitud de vacaciones necesita periodo, días y fechas válidas.")
        if item.end_date > date.today():
            raise HTTPException(409, "Los días de vacaciones se registran como utilizados solo después de finalizar el periodo aprobado.")
        _validate_vacation_balance(db, item)
        ledger_rows = list(db.scalars(
            select(Vacation).where(
                Vacation.employee_id == employee.id,
                Vacation.period_year == item.period_year,
                Vacation.status.notin_(("Rechazada", "Anulada", "Cancelada")),
            ).order_by(Vacation.created_at, Vacation.id)
        ))
        remaining_to_allocate = item.requested_days
        for ledger in ledger_rows:
            capacity = max(0, int(ledger.entitled_days or 0) - int(ledger.used_days or 0))
            if capacity <= 0:
                continue
            used_now = min(capacity, remaining_to_allocate)
            ledger.used_days = int(ledger.used_days or 0) + used_now
            note = f"Uso confirmado mediante solicitud #{item.id}: {used_now} día(s), {item.start_date:%d/%m/%Y}–{item.end_date:%d/%m/%Y}."
            ledger.notes = f"{ledger.notes.rstrip()}\n{note}".strip()
            remaining_to_allocate -= used_now
            if remaining_to_allocate == 0:
                break
        if remaining_to_allocate:
            raise HTTPException(409, "No se pudo asignar el uso al saldo anual. Revisá los registros de vacaciones del periodo.")
        add_employee_event(
            db, employee, user, "Vacaciones",
            f"Vacaciones utilizadas mediante solicitud #{item.id}",
            f"Se confirmaron {item.requested_days} día(s) de vacaciones del periodo {item.period_year}, del {item.start_date:%d/%m/%Y} al {item.end_date:%d/%m/%Y}.",
            item.end_date, None,
        )
    elif request_kind in {"permiso/licencia", "permiso", "licencia"}:
        if not item.start_date or not item.end_date or not item.leave_type.strip():
            raise HTTPException(400, "El permiso o licencia necesita tipo y fechas válidas.")
        if item.end_date > date.today():
            raise HTTPException(409, "El permiso o licencia se registra en el expediente una vez finalizado el periodo aprobado.")
        hours_text = f" Duración declarada: {item.hours_requested} hora(s)." if item.hours_requested is not None else ""
        add_employee_event(
            db, employee, user, "Permiso",
            f"{item.leave_type} registrado mediante solicitud #{item.id}",
            f"Periodo: {item.start_date:%d/%m/%Y}–{item.end_date:%d/%m/%Y}.{hours_text} Motivo: {item.detail}",
            item.end_date, None,
        )
    else:
        raise HTTPException(400, "La aplicación de este tipo de trámite debe realizarse desde su módulo específico.")
    workflow.applied = True
    workflow.applied_at = datetime.now(UTC)
    item.status = "Aplicada"
    item.resolved_at = workflow.applied_at
    if request_kind == "cambio salarial":
        audit_detail = f"{previous_salary} → {item.amount}"
    elif request_kind == "vacaciones":
        audit_detail = f"{item.requested_days} días utilizados; periodo {item.period_year}"
    else:
        audit_detail = f"{item.leave_type}; {item.start_date:%d/%m/%Y}–{item.end_date:%d/%m/%Y}"
    write_audit(db, user, "aplicar_solicitud", "solicitud", str(item.id), audit_detail)
    applied_message = {
        "cambio salarial": "El cambio salarial aprobado fue aplicado al legajo del funcionario.",
        "vacaciones": f"Se confirmaron {item.requested_days} día(s) de vacaciones como utilizados y se actualizó el saldo del periodo {item.period_year}.",
        "permiso/licencia": "El permiso/licencia aprobado quedó registrado en la línea de tiempo del funcionario.",
        "permiso": "El permiso aprobado quedó registrado en la línea de tiempo del funcionario.",
        "licencia": "La licencia aprobada quedó registrada en la línea de tiempo del funcionario.",
    }.get(request_kind, "El trámite aprobado fue aplicado al expediente laboral.")
    _notify_request_counterpart(
        db, background_tasks, item, user,
        event_type="solicitud_aplicada", title=f"Trámite completado · Solicitud #{item.id}",
        body=applied_message,
    )
    db.commit()
    return RedirectResponse(f"/app/requests/{item.id}", status_code=303)


CALCULATION_MODULES = {
    "salary": {"title": "Salarios", "eyebrow": "CÁLCULO DE SALARIOS", "description": "Ingresá haberes, descuentos y base de IPS para revisar el bruto, el aporte y el neto estimado."},
    "hours": {"title": "Horas y recargos", "eyebrow": "CÁLCULO DE HORAS", "description": "Calculá el valor hora con una jornada y un multiplicador previamente revisados."},
    "aguinaldo": {"title": "Cálculo de aguinaldo", "eyebrow": "AGUINALDO · ARTS. 243/244", "description": "Estimá la doceava parte de las remuneraciones computables del periodo."},
    "vacation": {"title": "Cálculo de vacaciones", "eyebrow": "VACACIONES · ARTS. 218/220", "description": "Estimá la remuneración de vacaciones con base y días revisados."},
    "notice": {"title": "Cálculo de preaviso", "eyebrow": "PREAVISO · ARTS. 87/90/92", "description": "Estimá el importe a partir de la base promedio y los días que correspondan al caso."},
}


def _employee_annual_coverage(db: Session, company: Company, employee: Employee, year: int, today: date):
    """Build coverage from payroll rows and saved monthly salary calculations."""
    period_start, period_end = f"{year:04d}-01", f"{year:04d}-12"
    payroll_rows = db.execute(
        select(Payroll, PayrollLine)
        .join(PayrollLine, PayrollLine.payroll_id == Payroll.id)
        .where(
            Payroll.company_id == company.id,
            PayrollLine.employee_id == employee.id,
            Payroll.period >= period_start,
            Payroll.period <= period_end,
        )
        .order_by(Payroll.period)
    ).all()
    payroll_by_period = {}
    for payroll, line in payroll_rows:
        gross_components = (
            line.base_salary + line.overtime + line.commissions
            + line.bonuses + line.other_income
        )
        amounts_consistent = (
            min(line.base_salary, line.overtime, line.commissions, line.bonuses, line.other_income) >= 0
            and line.gross >= 0
            and line.gross == gross_components
        )
        payroll_by_period[payroll.period] = {
            "status": payroll.status,
            "gross": line.gross,
            "base_salary": line.base_salary,
            "amounts_consistent": amounts_consistent,
        }
    calc_periods = db.scalars(
        select(CalculationRecord.reference_period).where(
            CalculationRecord.company_id == company.id,
            CalculationRecord.employee_id == employee.id,
            CalculationRecord.calculation_type == "salary",
            CalculationRecord.reference_period.like(f"{year:04d}-%"),
            CalculationRecord.status != "Anulado",
        )
    )
    saved_salary_periods = {str(period) for period in calc_periods if period}
    return build_annual_coverage(
        year=year,
        admission_date=employee.admission_date,
        termination_date=employee.termination_date,
        payroll_by_period=payroll_by_period,
        saved_salary_periods=saved_salary_periods,
        today=today,
    )


@app.get("/app/calculations/periodos", response_class=HTMLResponse)
def calculation_period_coverage(
    request: Request,
    company_id: int | None = None,
    employee_id: int | None = None,
    year: int | None = None,
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    """Show monthly record coverage without treating missing data as zero."""
    today = current_paraguay_date()
    target_year = year or today.year
    if target_year < 1900 or target_year > today.year:
        raise HTTPException(422, "Seleccioná un año entre 1900 y el año actual.")
    company_ids = company_ids_for_user(db, user)
    company_id, employee_id = default_labor_context(
        request, db, user, company_ids, company_id, employee_id
    )
    companies = list(
        db.scalars(select(Company).where(Company.id.in_(company_ids)).order_by(Company.legal_name))
    ) if company_ids else []
    employees = list(
        db.scalars(
            select(Employee).where(Employee.company_id.in_(company_ids)).order_by(Employee.full_name)
        )
    ) if company_ids else []
    selected_company = None
    selected_employee = None
    coverage = None
    if employee_id:
        selected_employee = db.get(Employee, employee_id)
        if not selected_employee or selected_employee.company_id not in company_ids:
            raise HTTPException(404, "Funcionario no encontrado en tu espacio de trabajo.")
        if company_id and selected_employee.company_id != company_id:
            raise HTTPException(400, "El funcionario no pertenece a la empresa seleccionada.")
        company_id = selected_employee.company_id
    if company_id:
        selected_company = company_allowed(db, user, company_id)
    if selected_employee and selected_company:
        coverage = _employee_annual_coverage(db, selected_company, selected_employee, target_year, today)
    return render(
        request,
        "period_coverage.html",
        db,
        user,
        companies=companies,
        employees=employees,
        selected_company=company_id,
        selected_employee=employee_id,
        selected_company_name=selected_company.legal_name if selected_company else "",
        selected_employee_name=selected_employee.full_name if selected_employee else "",
        year=target_year,
        today=today,
        coverage=coverage,
        format_gs=format_gs,
    )


@app.get("/app/calculations", response_class=HTMLResponse)
def calculations_page(
    request: Request,
    company_id: OptionalQueryId = None,
    employee_id: OptionalQueryId = None,
    tipo: str | None = None,
    reuse_history: bool = False,
    year: int | None = None,
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    if tipo and tipo not in CALCULATION_MODULES:
        raise HTTPException(404, "Calculadora no encontrada.")
    company_ids = company_ids_for_user(db, user)
    company_id, employee_id = default_labor_context(
        request, db, user, company_ids, company_id, employee_id
    )
    companies = list(db.scalars(select(Company).where(Company.id.in_(company_ids)).order_by(Company.legal_name))) if company_ids else []
    employees_query = select(Employee).where(Employee.company_id.in_(company_ids), Employee.status == "Activo") if company_ids else select(Employee).where(False)
    employees = list(db.scalars(employees_query.order_by(Employee.full_name)))
    recent_query = select(CalculationRecord).where(CalculationRecord.company_id.in_(company_ids), CalculationRecord.source != "Centro laboral") if company_ids else select(CalculationRecord).where(False)
    if company_id and company_id in company_ids:
        recent_query = recent_query.where(CalculationRecord.company_id == company_id)
    if employee_id:
        recent_query = recent_query.where(CalculationRecord.employee_id == employee_id)
    if tipo:
        recent_query = recent_query.where(CalculationRecord.calculation_type == tipo)
    recent_calculations = list(db.scalars(recent_query.order_by(CalculationRecord.created_at.desc()).limit(30)))
    prefill_total_remunerations = 0
    prefill_notes = ""
    period_reuse_warning = ""
    prefill_year = year or current_paraguay_date().year
    if reuse_history and tipo == "aguinaldo" and company_id and employee_id:
        if prefill_year < 1900 or prefill_year > current_paraguay_date().year:
            raise HTTPException(422, "El año de reutilización debe estar entre 1900 y el año actual.")
        company = company_allowed(db, user, company_id)
        employee = db.get(Employee, employee_id)
        if not employee or employee.company_id != company.id:
            raise HTTPException(404, "Funcionario no encontrado en la empresa seleccionada.")
        coverage = _employee_annual_coverage(db, company, employee, prefill_year, current_paraguay_date())
        prefill_total_remunerations = coverage["suggested_total"]
        period_reuse_warning = coverage["coverage_note"] + " " + coverage["legal_note"]
        prefill_notes = (
            f"Propuesta desde historial de nóminas {prefill_year}: suma bruta de nóminas cerradas y consistentes "
            f"Gs. {format_gs(prefill_total_remunerations)}; cobertura {coverage['closed_count']}/"
            f"{coverage['expected_count']} periodos esperados. Revisar conceptos computables, ajustes y anticipos."
        )
    selected_employee_record = next((item for item in employees if item.id == employee_id), None)
    minimum_salary = get_parameter(db, "minimum_monthly_salary_general", 0)
    calculation_salary_default = (
        int(selected_employee_record.base_salary or 0) if selected_employee_record else int(minimum_salary or 0)
    )
    return render(
        request,
        "calculations.html",
        db,
        user,
        companies=companies,
        employees=employees,
        recent_calculations=recent_calculations,
        selected_company=company_id,
        selected_employee=employee_id,
        ips_rate=get_parameter(db, "ips_employee_rate_general", 9),
        minimum_salary=minimum_salary,
        calculation_salary_default=calculation_salary_default,
        hourly_reference=get_parameter(db, "minimum_hourly_wage_general", 0),
        calculation_labels={key: calculation_label(key) for key in ("salary", "hours", "aguinaldo", "vacation", "notice")},
        active_calculation_type=tipo or "",
        calculation_module=CALCULATION_MODULES.get(tipo),
        prefill_total_remunerations=prefill_total_remunerations,
        prefill_notes=prefill_notes,
        period_reuse_warning=period_reuse_warning,
        prefill_year=prefill_year,
    )


@app.post("/app/calculations")
def save_calculation(
    request: Request,
    calculation_type: Annotated[str, Form()],
    company_id: Annotated[int, Form()],
    employee_id: Annotated[int | None, Form()] = None,
    reference_period: Annotated[str, Form()] = "",
    gross: Annotated[int, Form()] = 0,
    other_income: Annotated[int, Form()] = 0,
    other_discount: Annotated[int, Form()] = 0,
    ips_base: Annotated[int | None, Form()] = None,
    apply_ips: Annotated[str | None, Form()] = None,
    salary: Annotated[int, Form()] = 0,
    monthly_hours: Annotated[float, Form()] = 240,
    hours_quantity: Annotated[float, Form()] = 0,
    multiplier: Annotated[float, Form()] = 1,
    total_remunerations: Annotated[int, Form()] = 0,
    days: Annotated[float, Form()] = 0,
    notes: Annotated[str, Form()] = "",
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    company = company_allowed(db, user, company_id)
    employee = db.get(Employee, employee_id) if employee_id else None
    if employee and employee.company_id != company.id:
        raise HTTPException(400, "El funcionario no pertenece a la empresa seleccionada.")
    if employee:
        salary = salary or employee.base_salary
        gross = gross or employee.base_salary
    inputs, results, amount = calculate_values(
        calculation_type=calculation_type,
        ips_rate=get_parameter(db, "ips_employee_rate_general", 9),
        gross=gross,
        other_income=other_income,
        other_discount=other_discount,
        ips_base=ips_base,
        apply_ips=apply_ips == "on",
        salary=salary,
        monthly_hours=monthly_hours,
        hours_quantity=hours_quantity,
        multiplier=multiplier,
        total_remunerations=total_remunerations,
        days=days,
    )
    item = CalculationRecord(
        company_id=company.id,
        employee_id=employee.id if employee else None,
        calculation_type=calculation_type,
        reference_period=reference_period.strip()[:20],
        input_json=json.dumps(inputs, ensure_ascii=False, separators=(",", ":")),
        result_json=json.dumps(results, ensure_ascii=False, separators=(",", ":")),
        amount=amount,
        status="Revisar",
        source="Cálculo automático",
        notes=notes.strip(),
        created_by=user.email,
    )
    db.add(item)
    db.flush()
    write_audit(db, user, "guardar", "calculo", str(item.id), f"{calculation_label(calculation_type)} · Gs. {format_gs(amount)}")
    db.commit()
    return RedirectResponse(f"/app/calculations?tipo={quote(calculation_type)}&saved={item.id}&company_id={company.id}" + (f"&employee_id={employee.id}" if employee else ""), status_code=303)


@app.post("/app/calculations/{calculation_id}/status")
def calculation_status(
    calculation_id: int,
    status_value: Annotated[str, Form(alias="status")],
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    item = db.get(CalculationRecord, calculation_id)
    if not item or item.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    if status_value not in {"Revisar", "Aprobado", "Anulado"}:
        raise HTTPException(400, "Estado inválido.")
    item.status = status_value
    write_audit(db, user, "actualizar_estado", "calculo", str(item.id), status_value)
    db.commit()
    target = f"/app/calculations?tipo={quote(item.calculation_type)}" if item.calculation_type in CALCULATION_MODULES else "/app/calculations"
    return RedirectResponse(target, status_code=303)


@app.get("/app/calculations/{calculation_id}/certificate")
def calculation_to_certificate(
    calculation_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    item = db.get(CalculationRecord, calculation_id)
    if not item or item.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    if item.source == "Centro laboral":
        return RedirectResponse(f"/app/liquidaciones/{item.id}", status_code=303)
    document_type = {
        "aguinaldo": "aguinaldo_anual",
        "vacation": "usufructo_vacaciones",
        "notice": "notificacion_preaviso",
        "salary": "certificado_trabajo_a",
        "hours": "constancia",
    }.get(item.calculation_type, "certificado_trabajo_a")
    query = f"calculation_id={item.id}&company_id={item.company_id}&document_type={document_type}"
    if item.employee_id:
        query += f"&employee_id={item.employee_id}"
    return RedirectResponse(f"/app/certificates?{query}", status_code=303)


@app.get("/app/certificates", response_class=HTMLResponse)
def certificates_page(
    request: Request,
    calculation_id: OptionalQueryId = None,
    company_id: OptionalQueryId = None,
    employee_id: OptionalQueryId = None,
    document_type: str = "",
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    company_ids = company_ids_for_user(db, user)
    if not calculation_id:
        company_id, employee_id = default_labor_context(
            request, db, user, company_ids, company_id, employee_id
        )
    companies = list(db.scalars(select(Company).where(Company.id.in_(company_ids)).order_by(Company.legal_name))) if company_ids else []
    employees = list(db.scalars(select(Employee).where(Employee.company_id.in_(company_ids)).order_by(Employee.full_name))) if company_ids else []
    generated = list(
        db.scalars(
            select(GeneratedCertificate)
            .where(GeneratedCertificate.company_id.in_(company_ids))
            .order_by(GeneratedCertificate.created_at.desc())
            .limit(30)
        )
    ) if company_ids else []
    selected_calculation = db.get(CalculationRecord, calculation_id) if calculation_id else None
    if calculation_id and (not selected_calculation or selected_calculation.company_id not in company_ids):
        raise HTTPException(404)
    if selected_calculation:
        company_id = selected_calculation.company_id
        employee_id = selected_calculation.employee_id
    selected_company = db.get(Company, company_id) if company_id in company_ids else None
    selected_employee = db.get(Employee, employee_id) if employee_id else None
    if company_id and not selected_company:
        raise HTTPException(404, "Empresa no encontrada.")
    if employee_id and (not selected_employee or selected_employee.company_id not in company_ids):
        raise HTTPException(404, "Funcionario no encontrado.")
    vacation_by_employee: dict[int, Vacation] = {}
    employee_ids = [employee.id for employee in employees]
    if employee_ids:
        latest_vacation_records = db.scalars(
            select(Vacation).where(Vacation.employee_id.in_(employee_ids))
            .order_by(Vacation.created_at.desc())
        )
        for vacation_record in latest_vacation_records:
            vacation_by_employee.setdefault(vacation_record.employee_id, vacation_record)
    selected_vacation = None
    if selected_employee:
        if selected_company and selected_employee.company_id != selected_company.id:
            raise HTTPException(404, "Funcionario no encontrado en la empresa seleccionada.")
        selected_company = selected_company or selected_employee.company
        selected_vacation = vacation_by_employee.get(selected_employee.id)
    calculation_inputs = json_dict(selected_calculation.input_json) if selected_calculation else {}
    calculation_results = json_dict(selected_calculation.result_json) if selected_calculation else {}
    branding = get_or_create_branding(db, selected_company) if selected_company else None
    if selected_company:
        db.commit()
    page = render(
        request,
        "certificates.html",
        db,
        user,
        companies=companies,
        employees=employees,
        generated=generated,
        certificate_types=CERTIFICATE_TYPES,
        signature_modes={key: document_signature_mode(key) for key in CERTIFICATE_TYPES},
        receipt_modes={key: document_receipt_mode(key) for key in CERTIFICATE_TYPES},
        selected_calculation=selected_calculation,
        selected_company=selected_company,
        selected_employee=selected_employee,
        selected_vacation=selected_vacation,
        vacation_by_employee=vacation_by_employee,
        selected_document_type=document_type if document_type in CERTIFICATE_TYPES else "",
        calculation_inputs=calculation_inputs,
        calculation_results=calculation_results,
        branding=branding,
        official_certificate_types=OFFICIAL_CERTIFICATE_TYPES,
    )
    # La pantalla del generador debe consultar HTML y JavaScript frescos tras cada despliegue.
    page.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    page.headers["Pragma"] = "no-cache"
    page.headers["Expires"] = "0"
    return page


@app.post("/app/certificates")
def create_certificate(
    request: Request,
    company_id: Annotated[int, Form()],
    employee_id: Annotated[int, Form()],
    document_type: Annotated[str, Form()],
    city: Annotated[str, Form()] = "Ciudad del Este",
    issue_date: Annotated[date, Form()] = date.today(),
    position: Annotated[str, Form()] = "",
    admission_date: Annotated[str, Form()] = "",
    salary: Annotated[int, Form()] = 0,
    observations: Annotated[str, Form()] = "",
    document_number: Annotated[str, Form()] = "",
    period_start: Annotated[str, Form()] = "",
    period_end: Annotated[str, Form()] = "",
    amount: Annotated[int, Form()] = 0,
    effective_date: Annotated[str, Form()] = "",
    leave_start: Annotated[str, Form()] = "",
    leave_end: Annotated[str, Form()] = "",
    nationality: Annotated[str, Form()] = "paraguaya",
    civil_status: Annotated[str, Form()] = "",
    recipient: Annotated[str, Form()] = "Encargado/a de Recursos Humanos",
    include_salary: Annotated[str, Form()] = "on",
    last_period_salary_amount: Annotated[str, Form()] = "",
    contract_modality: Annotated[str, Form()] = "",
    contract_end_date: Annotated[str, Form()] = "",
    contract_cause: Annotated[str, Form()] = "",
    previous_contract_number: Annotated[str, Form()] = "",
    workplace: Annotated[str, Form()] = "",
    job_functions: Annotated[str, Form()] = "",
    work_schedule: Annotated[str, Form()] = "",
    weekly_rest: Annotated[str, Form()] = "",
    payment_frequency: Annotated[str, Form()] = "",
    probation_period: Annotated[str, Form()] = "",
    payment_date: Annotated[str, Form()] = "",
    payment_method: Annotated[str, Form()] = "",
    days_worked: Annotated[str, Form()] = "",
    hours_worked: Annotated[str, Form()] = "",
    units_worked: Annotated[str, Form()] = "",
    salary_basic_amount: Annotated[str, Form()] = "",
    night_surcharge_amount: Annotated[str, Form()] = "0",
    overtime_day_amount: Annotated[str, Form()] = "0",
    overtime_night_amount: Annotated[str, Form()] = "0",
    holiday_amount: Annotated[str, Form()] = "0",
    vacation_pay_amount: Annotated[str, Form()] = "0",
    family_allowance_amount: Annotated[str, Form()] = "0",
    commission_amount: Annotated[str, Form()] = "0",
    gratification_amount: Annotated[str, Form()] = "0",
    prize_amount: Annotated[str, Form()] = "0",
    bonus_amount: Annotated[str, Form()] = "0",
    other_income_amount: Annotated[str, Form()] = "0",
    other_income_description: Annotated[str, Form()] = "",
    ips_deduction_amount: Annotated[str, Form()] = "0",
    advance_deduction_amount: Annotated[str, Form()] = "0",
    authorized_deduction_amount: Annotated[str, Form()] = "0",
    authority_deduction_amount: Annotated[str, Form()] = "0",
    other_deduction_amount: Annotated[str, Form()] = "0",
    other_deduction_description: Annotated[str, Form()] = "",
    vacation_period_year: Annotated[str, Form()] = "",
    vacation_request_date: Annotated[str, Form()] = "",
    vacation_notice_date: Annotated[str, Form()] = "",
    vacation_days: Annotated[str, Form()] = "",
    vacation_amount: Annotated[str, Form()] = "0",
    vacation_payment_date: Annotated[str, Form()] = "",
    leave_type: Annotated[str, Form()] = "",
    leave_quantity: Annotated[str, Form()] = "",
    leave_unit: Annotated[str, Form()] = "",
    paid_leave: Annotated[str, Form()] = "",
    compensation_method: Annotated[str, Form()] = "",
    birth_event_date: Annotated[str, Form()] = "",
    termination_reason: Annotated[str, Form()] = "",
    last_worked_date: Annotated[str, Form()] = "",
    notice_start_date: Annotated[str, Form()] = "",
    notice_days: Annotated[str, Form()] = "",
    incident_date: Annotated[str, Form()] = "",
    incident_details: Annotated[str, Form()] = "",
    disciplinary_action: Annotated[str, Form()] = "Amonestación escrita",
    sanction_start_date: Annotated[str, Form()] = "",
    sanction_end_date: Annotated[str, Form()] = "",
    previous_salary: Annotated[str, Form()] = "0",
    settlement_salary_due: Annotated[str, Form()] = "0",
    settlement_notice_amount: Annotated[str, Form()] = "0",
    settlement_indemnity_amount: Annotated[str, Form()] = "0",
    settlement_vacation_amount: Annotated[str, Form()] = "0",
    settlement_bonus_amount: Annotated[str, Form()] = "0",
    settlement_other_income_amount: Annotated[str, Form()] = "0",
    settlement_other_income_description: Annotated[str, Form()] = "",
    settlement_ips_deduction: Annotated[str, Form()] = "0",
    settlement_other_deduction: Annotated[str, Form()] = "0",
    settlement_other_deduction_description: Annotated[str, Form()] = "",
    calculation_id: Annotated[str, Form()] = "",
    intent: Annotated[str, Form()] = "save",
    user: User = Depends(require_roles("administrador", "contador", "auxiliar", "abogado")),
    db: Session = Depends(get_db),
):
    if document_type not in CERTIFICATE_TYPES:
        raise HTTPException(400, "Tipo de documento inválido.")

    # Los controles HTML de fecha envían "" cuando están vacíos. Normalizarlos
    # antes de cualquier validación evita rechazos Pydantic de campos opcionales.
    admission_date = optional_date(admission_date, field="fecha de ingreso")
    period_start = optional_date(period_start, field="inicio del período")
    period_end = optional_date(period_end, field="fin del período")
    effective_date = optional_date(effective_date, field="fecha efectiva")
    leave_start = optional_date(leave_start, field="inicio del permiso")
    leave_end = optional_date(leave_end, field="fin del permiso")
    contract_end_date = optional_date(contract_end_date, field="fin del contrato")
    payment_date = optional_date(payment_date, field="fecha de pago")
    vacation_request_date = optional_date(vacation_request_date, field="solicitud de vacaciones")
    vacation_notice_date = optional_date(vacation_notice_date, field="comunicación de vacaciones")
    vacation_payment_date = optional_date(vacation_payment_date, field="pago de vacaciones")
    birth_event_date = optional_date(birth_event_date, field="fecha del hecho generador")
    last_worked_date = optional_date(last_worked_date, field="último día trabajado")
    notice_start_date = optional_date(notice_start_date, field="inicio del preaviso")
    incident_date = optional_date(incident_date, field="fecha del hecho")
    sanction_start_date = optional_date(sanction_start_date, field="inicio de la medida")
    sanction_end_date = optional_date(sanction_end_date, field="fin de la medida")
    calculation_id = optional_int(calculation_id, field="identificador de cálculo")

    def nonnegative_amount(raw: str | int | None, label: str) -> int:
        value = str(raw if raw is not None else "").strip().replace(" ", "")
        if not value:
            return 0
        if not value.isdigit():
            raise HTTPException(400, f"El campo «{label}» debe contener un importe entero en guaraníes, sin separadores.")
        return int(value)

    field_amounts = {
        "salary_basic_amount": nonnegative_amount(salary_basic_amount, "Salario básico del período"),
        "last_period_salary_amount": nonnegative_amount(last_period_salary_amount, "Salario del último período de pago"),
        "night_surcharge_amount": nonnegative_amount(night_surcharge_amount, "Recargo nocturno"),
        "overtime_day_amount": nonnegative_amount(overtime_day_amount, "Horas extras diurnas"),
        "overtime_night_amount": nonnegative_amount(overtime_night_amount, "Horas extras nocturnas"),
        "holiday_amount": nonnegative_amount(holiday_amount, "Feriados trabajados"),
        "vacation_pay_amount": nonnegative_amount(vacation_pay_amount, "Vacaciones pagadas"),
        "family_allowance_amount": nonnegative_amount(family_allowance_amount, "Asignación familiar"),
        "commission_amount": nonnegative_amount(commission_amount, "Comisiones"),
        "gratification_amount": nonnegative_amount(gratification_amount, "Gratificaciones"),
        "prize_amount": nonnegative_amount(prize_amount, "Premios"),
        "bonus_amount": nonnegative_amount(bonus_amount, "Bonificaciones"),
        "other_income_amount": nonnegative_amount(other_income_amount, "Otros ingresos"),
        "ips_deduction_amount": nonnegative_amount(ips_deduction_amount, "Descuento IPS"),
        "advance_deduction_amount": nonnegative_amount(advance_deduction_amount, "Anticipo salarial"),
        "authorized_deduction_amount": nonnegative_amount(authorized_deduction_amount, "Descuento autorizado"),
        "authority_deduction_amount": nonnegative_amount(authority_deduction_amount, "Descuento por orden competente"),
        "other_deduction_amount": nonnegative_amount(other_deduction_amount, "Otros descuentos"),
        "vacation_amount": nonnegative_amount(vacation_amount, "Pago de vacaciones"),
        "previous_salary": nonnegative_amount(previous_salary, "Salario anterior"),
        "settlement_salary_due": nonnegative_amount(settlement_salary_due, "Salarios pendientes"),
        "settlement_notice_amount": nonnegative_amount(settlement_notice_amount, "Importe de preaviso"),
        "settlement_indemnity_amount": nonnegative_amount(settlement_indemnity_amount, "Indemnización"),
        "settlement_vacation_amount": nonnegative_amount(settlement_vacation_amount, "Vacaciones pendientes"),
        "settlement_bonus_amount": nonnegative_amount(settlement_bonus_amount, "Aguinaldo de liquidación"),
        "settlement_other_income_amount": nonnegative_amount(settlement_other_income_amount, "Otros haberes de liquidación"),
        "settlement_ips_deduction": nonnegative_amount(settlement_ips_deduction, "Descuento de liquidación"),
        "settlement_other_deduction": nonnegative_amount(settlement_other_deduction, "Otros descuentos de liquidación"),
    }

    contract_types = {
        "contrato_trabajo", "contrato_tiempo_parcial", "contrato_mipymes_plazo_determinado",
        "contrato_mipymes_80", "adenda_prorroga_contrato",
    }
    default_modality = {
        "contrato_trabajo": "indefinido",
        "contrato_tiempo_parcial": "tiempo_parcial",
        "contrato_mipymes_plazo_determinado": "mipyme_plazo_fijo",
        "contrato_mipymes_80": "mipyme_80",
        "adenda_prorroga_contrato": "prorroga",
    }.get(document_type, "")
    contract_modality_value = contract_modality.strip() or default_modality
    if document_type in contract_types:
        if not workplace.strip() or not job_functions.strip() or not work_schedule.strip():
            raise HTTPException(400, "Para emitir un contrato, completá el lugar de trabajo, las funciones y la jornada/horario.")
        if document_type in {"contrato_mipymes_plazo_determinado", "contrato_mipymes_80", "adenda_prorroga_contrato"}:
            if not contract_end_date or not contract_cause.strip():
                raise HTTPException(400, "Este modelo requiere fecha de finalización y una causa/condición específica documentada.")
        if document_type == "adenda_prorroga_contrato" and not previous_contract_number.strip():
            raise HTTPException(400, "La adenda requiere identificar el contrato anterior que se prorroga.")
        if document_type == "contrato_trabajo" and contract_modality_value in {"plazo_fijo", "mipyme_plazo_fijo", "mipyme_80", "prorroga"}:
            if not contract_end_date or not contract_cause.strip():
                raise HTTPException(400, "Para un contrato a plazo determinado, indicá fecha final y causa documentada.")

    if document_type == "recibo_salario" and (not period_start or not period_end):
        raise HTTPException(400, "El recibo de salario requiere el período de liquidación desde/hasta.")
    if document_type == "recibo_salario" and period_end < period_start:
        raise HTTPException(400, "El fin del período de liquidación no puede ser anterior al inicio.")
    company = company_allowed(db, user, company_id)
    employee = db.get(Employee, employee_id)
    if not employee or employee.company_id != company.id:
        raise HTTPException(400, "El funcionario no pertenece a la empresa seleccionada.")
    calculation = db.get(CalculationRecord, calculation_id) if calculation_id else None
    if calculation and (calculation.company_id != company.id or calculation.company_id not in company_ids_for_user(db, user)):
        raise HTTPException(400, "El cálculo vinculado no corresponde a la empresa seleccionada.")
    if calculation and calculation.employee_id and calculation.employee_id != employee.id:
        raise HTTPException(400, "El cálculo vinculado corresponde a otro funcionario.")
    calc_inputs = json_dict(calculation.input_json) if calculation else {}
    calc_results = json_dict(calculation.result_json) if calculation else {}
    position_value = position.strip() or employee.position
    admission_value = admission_date or employee.admission_date
    if document_type in {"certificado_trabajo_a", "certificado_trabajo_b", "constancia"} and not effective_date:
        if (employee.status or "").strip().lower() not in {"activo", "active"} and employee.termination_date:
            effective_date = employee.termination_date
    if document_type in {"certificado_trabajo_a", "constancia"} and effective_date and field_amounts["last_period_salary_amount"] <= 0 and intent != "preview":
        raise HTTPException(400, "Para un certificado al término de la relación, consigná el salario efectivamente devengado en el último período de pago, según nómina o recibo.")
    salary_value = max(0, salary or employee.base_salary)
    if calculation:
        if document_type in {"aguinaldo_anual", "aguinaldo_proporcional", "usufructo_vacaciones", "notificacion_preaviso"}:
            amount = amount or calculation.amount
        if document_type.startswith("aguinaldo") and not period_start:
            year = int(calculation.reference_period[:4]) if calculation.reference_period[:4].isdigit() else issue_date.year
            period_start, period_end = date(year, 1, 1), date(year, 12, 31)
        if document_type in {"solicitud_vacacion", "usufructo_vacaciones"} and not observations:
            observations = f"Cálculo vinculado N.º {calculation.id}: {calc_results.get('days', calc_inputs.get('days', 0))} días, total estimado Gs. {format_gs(calculation.amount)}."
        if document_type == "notificacion_preaviso" and not observations:
            observations = f"Cálculo vinculado N.º {calculation.id}: {calc_results.get('days', calc_inputs.get('days', 0))} días, total estimado Gs. {format_gs(calculation.amount)}."
    if not calculation and document_type in {"aguinaldo_anual", "aguinaldo_proporcional"}:
        latest_aguinaldo = db.scalar(
            select(Aguinaldo).where(Aguinaldo.employee_id == employee.id).order_by(Aguinaldo.year.desc(), Aguinaldo.created_at.desc())
        )
        if latest_aguinaldo:
            amount = amount or latest_aguinaldo.calculated_amount
            period_start = period_start or date(latest_aguinaldo.year, 1, 1)
            period_end = period_end or date(latest_aguinaldo.year, 12, 31)
            observations = observations or f"Importe tomado del registro de aguinaldo {latest_aguinaldo.year}, estado {latest_aguinaldo.status}."
    if not calculation and document_type in {"solicitud_vacacion", "notificacion_vacaciones", "usufructo_vacaciones", "recibo_vacaciones"}:
        latest_vacation = db.scalar(
            select(Vacation).where(Vacation.employee_id == employee.id).order_by(Vacation.created_at.desc())
        )
        if latest_vacation:
            leave_start = leave_start or latest_vacation.start_date
            leave_end = leave_end or latest_vacation.end_date
            vacation_period_year = vacation_period_year or str(latest_vacation.period_year)
            if not vacation_days and latest_vacation.used_days:
                vacation_days = str(latest_vacation.used_days)
            if not observations:
                observations = f"Periodo {latest_vacation.period_year}: {latest_vacation.used_days} de {latest_vacation.entitled_days} días registrados, estado {latest_vacation.status}."
    if document_type in {"solicitud_vacacion", "notificacion_vacaciones", "usufructo_vacaciones", "recibo_vacaciones"}:
        if not leave_start or not leave_end:
            raise HTTPException(400, "Completá las fechas de inicio y término del período de vacaciones.")
        if leave_end < leave_start:
            raise HTTPException(400, "La fecha final de vacaciones no puede ser anterior a la fecha inicial.")
    if document_type in {"aguinaldo_anual", "aguinaldo_proporcional"} and amount <= 0:
        raise HTTPException(400, "El recibo de aguinaldo requiere un cálculo o importe registrado.")
    # Evitar confundir un recibo con una cifra única: calcular subtotales a partir
    # de los conceptos detallados del modelo oficial y dejar visible cada componente.
    receipt_income_total = sum(field_amounts[key] for key in (
        "salary_basic_amount", "night_surcharge_amount", "overtime_day_amount", "overtime_night_amount",
        "holiday_amount", "vacation_pay_amount", "family_allowance_amount", "commission_amount",
        "gratification_amount", "prize_amount", "bonus_amount", "other_income_amount",
    ))
    receipt_deductions_total = sum(field_amounts[key] for key in (
        "ips_deduction_amount", "advance_deduction_amount", "authorized_deduction_amount",
        "authority_deduction_amount", "other_deduction_amount",
    ))
    if document_type == "recibo_salario" and not field_amounts["salary_basic_amount"]:
        field_amounts["salary_basic_amount"] = salary_value
        receipt_income_total += salary_value
    if document_type == "recibo_salario" and receipt_income_total - receipt_deductions_total < 0:
        raise HTTPException(400, "Los descuentos del recibo no pueden superar el total de haberes.")
    if document_type == "recibo_salario":
        amount = receipt_income_total - receipt_deductions_total

    contract_types = {
        "contrato_trabajo", "contrato_tiempo_parcial", "contrato_mipymes_plazo_determinado",
        "contrato_mipymes_80", "adenda_prorroga_contrato",
    }
    default_modality = {
        "contrato_trabajo": "indefinido",
        "contrato_tiempo_parcial": "tiempo_parcial",
        "contrato_mipymes_plazo_determinado": "mipyme_plazo_fijo",
        "contrato_mipymes_80": "mipyme_80",
        "adenda_prorroga_contrato": "prorroga",
    }.get(document_type, "")
    contract_modality_value = contract_modality.strip() or default_modality
    branding = get_or_create_branding(db, company) if intent != "preview" else None
    document_number_value = document_number.strip() or (
        "Vista previa" if intent == "preview" else next_document_number(db, company, document_type, branding)
    )
    metadata = {
        "notes": observations.strip(),
        "document_number": document_number_value,
        "period_start": period_start.isoformat() if period_start else "",
        "period_end": period_end.isoformat() if period_end else "",
        "amount": max(0, amount or salary_value),
        "effective_date": effective_date.isoformat() if effective_date else "",
        "leave_start": leave_start.isoformat() if leave_start else "",
        "leave_end": leave_end.isoformat() if leave_end else "",
        "nationality": nationality.strip(),
        "civil_status": civil_status.strip(),
        "recipient": recipient.strip(),
        "include_salary": include_salary.strip().lower() in {"on", "true", "1", "yes"},
        "last_period_salary_amount": field_amounts["last_period_salary_amount"],
        "contract_modality": contract_modality_value,
        "contract_end_date": contract_end_date.isoformat() if contract_end_date else "",
        "contract_cause": contract_cause.strip(),
        "previous_contract_number": previous_contract_number.strip(),
        "workplace": workplace.strip(),
        "job_functions": job_functions.strip(),
        "work_schedule": work_schedule.strip(),
        "weekly_rest": weekly_rest.strip(),
        "payment_frequency": (payment_frequency.strip() or employee.payment_frequency or "Mensual"),
        "probation_period": probation_period.strip(),
        "payment_date": (vacation_payment_date or payment_date).isoformat() if (vacation_payment_date or payment_date) else "",
        "payment_method": payment_method.strip(),
        "days_worked": str(days_worked).strip(),
        "hours_worked": str(hours_worked).strip(),
        "units_worked": units_worked.strip(),
        **field_amounts,
        "other_income_description": other_income_description.strip(),
        "other_deduction_description": other_deduction_description.strip(),
        "vacation_period_year": vacation_period_year.strip(),
        "vacation_request_date": vacation_request_date.isoformat() if vacation_request_date else "",
        "vacation_notice_date": vacation_notice_date.isoformat() if vacation_notice_date else "",
        "vacation_days": vacation_days.strip(),
        "vacation_amount": field_amounts["vacation_amount"],
        "leave_type": leave_type.strip(),
        "leave_quantity": leave_quantity.strip(),
        "leave_unit": leave_unit.strip(),
        "paid_leave": paid_leave.strip(),
        "compensation_method": compensation_method.strip(),
        "birth_event_date": birth_event_date.isoformat() if birth_event_date else "",
        "termination_reason": termination_reason.strip(),
        "last_worked_date": last_worked_date.isoformat() if last_worked_date else "",
        "notice_start_date": notice_start_date.isoformat() if notice_start_date else "",
        "notice_days": notice_days.strip(),
        "incident_date": incident_date.isoformat() if incident_date else "",
        "incident_details": incident_details.strip(),
        "disciplinary_action": disciplinary_action.strip(),
        "sanction_start_date": sanction_start_date.isoformat() if sanction_start_date else "",
        "sanction_end_date": sanction_end_date.isoformat() if sanction_end_date else "",
        "previous_salary": field_amounts["previous_salary"],
        "settlement_salary_due": field_amounts["settlement_salary_due"],
        "settlement_notice_amount": field_amounts["settlement_notice_amount"],
        "settlement_indemnity_amount": field_amounts["settlement_indemnity_amount"],
        "settlement_vacation_amount": field_amounts["settlement_vacation_amount"],
        "settlement_bonus_amount": field_amounts["settlement_bonus_amount"],
        "settlement_other_income_amount": field_amounts["settlement_other_income_amount"],
        "settlement_other_income_description": settlement_other_income_description.strip(),
        "settlement_ips_deduction": field_amounts["settlement_ips_deduction"],
        "settlement_other_deduction": field_amounts["settlement_other_deduction"],
        "settlement_other_deduction_description": settlement_other_deduction_description.strip(),
        "contract_type": employee.contract_type,
        "employee_address": employee.address or "",
        "employee_phone": employee.phone or "",
        "employee_email": employee.email or "",
        "employee_birth_date": employee.birth_date.isoformat() if employee.birth_date else "",
        "calculation_id": calculation.id if calculation else None,
        "calculation_type": calculation.calculation_type if calculation else "",
        "calculation_results": calc_results,
    }
    title, body = build_document_body(
        document_type,
        company_name=company.legal_name,
        employee_name=employee.full_name,
        employee_document=employee.document_number,
        position=position_value,
        admission_date=admission_value,
        salary=salary_value,
        issue_date=issue_date,
        city=city.strip() or company.city or "Ciudad del Este",
        metadata=metadata,
        company_ruc=company.ruc or "",
        company_address=company.address or "",
        company_phone=company.phone or "",
        company_email=company.email or "",
        legal_representative=company.legal_representative or "",
        employee_address=employee.address or "",
        employee_phone=employee.phone or "",
        employee_email=employee.email or "",
        employee_birth_date=employee.birth_date,
    )
    if intent == "preview":
        return JSONResponse(
            {"title": title, "body": body, "document_type": document_type},
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    item = GeneratedCertificate(
        company_id=company.id,
        employee_id=employee.id,
        document_type=document_type,
        title=title,
        city=city.strip() or company.city or "Ciudad del Este",
        issue_date=issue_date,
        company_name_snapshot=company.legal_name,
        employee_name_snapshot=employee.full_name,
        employee_document_snapshot=employee.document_number,
        position_snapshot=position_value,
        admission_date_snapshot=admission_value,
        salary_snapshot=salary_value,
        observations=encode_metadata(**metadata),
        body=body,
        status="Emitido" if intent in {"print", "docx", "pdf"} else "Borrador",
        created_by=user.email,
    )
    db.add(item)
    db.flush()
    write_audit(db, user, "generar", "documento_laboral", str(item.id), title)
    db.commit()

    if intent == "print":
        return RedirectResponse(f"/app/certificates/{item.id}/print", status_code=303)
    if intent == "docx":
        return RedirectResponse(f"/app/certificates/{item.id}/download.docx", status_code=303)
    if intent == "pdf":
        return RedirectResponse(f"/app/certificates/{item.id}/download.pdf", status_code=303)
    return RedirectResponse(f"/app/certificates?created={item.id}", status_code=303)


def get_allowed_certificate(certificate_id: int, user: User, db: Session) -> GeneratedCertificate:
    item = db.get(GeneratedCertificate, certificate_id)
    if not item or item.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404, "Documento no encontrado.")
    return item


@app.get("/app/certificates/{certificate_id}/print", response_class=HTMLResponse)
def print_certificate(certificate_id: int, request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    item = get_allowed_certificate(certificate_id, user, db)
    metadata = decode_metadata(item.observations)
    detail_table = document_detail_table_data(item.document_type, metadata, item.salary_snapshot)
    return render(
        request, "certificate_print.html", db, user,
        certificate=item, metadata=metadata, detail_table=detail_table,
        signature_mode=document_signature_mode(item.document_type),
        receipt_mode=document_receipt_mode(item.document_type),
    )


@app.get("/app/certificates/{certificate_id}/download.docx")
def download_certificate_docx(certificate_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    item = get_allowed_certificate(certificate_id, user, db)
    payload = build_docx_bytes(export_data_from_certificate(item))
    filename = safe_download_name(item.title, item.employee_name_snapshot, "docx")
    write_audit(db, user, "descargar", "documento_word", str(item.id), filename)
    db.commit()
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@app.get("/app/certificates/{certificate_id}/download.pdf")
def download_certificate_pdf(certificate_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    item = get_allowed_certificate(certificate_id, user, db)
    payload = build_pdf_bytes(export_data_from_certificate(item))
    filename = safe_download_name(item.title, item.employee_name_snapshot, "pdf")
    write_audit(db, user, "descargar", "documento_pdf", str(item.id), filename)
    db.commit()
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )



def get_allowed_official_certificate(record_id: int, user: User, db: Session) -> OfficialCertificateRecord:
    item = db.get(OfficialCertificateRecord, record_id)
    if not item or item.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404, "Registro de certificado oficial no encontrado.")
    return item


@app.get("/app/certificates/official")
def official_certificates_page():
    """Legacy path: keep users in the internal labor-document generator."""
    return RedirectResponse("/app/certificates", status_code=303)

@app.post("/app/certificates/official")
def create_official_certificate_record(
    background_tasks: BackgroundTasks,
    company_id: Annotated[int, Form()],
    certificate_type: Annotated[str, Form()],
    employee_id: Annotated[int | None, Form()] = None,
    request_date: Annotated[date | None, Form()] = None,
    notes: Annotated[str, Form()] = "",
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    info = OFFICIAL_CERTIFICATE_TYPES.get(certificate_type)
    if not info:
        raise HTTPException(400, "Tipo de certificado oficial inválido.")
    company = company_allowed(db, user, company_id)
    employee = None
    if employee_id:
        employee = db.get(Employee, employee_id)
        if not employee or employee.company_id != company.id:
            raise HTTPException(400, "El funcionario no pertenece a la empresa seleccionada.")
    if info.get("scope") == "persona" and not employee:
        raise HTTPException(400, "Seleccioná el funcionario relacionado con este certificado personal.")
    item = OfficialCertificateRecord(
        company_id=company.id,
        employee_id=employee.id if employee else None,
        institution=info["institution"],
        certificate_type=certificate_type,
        status="Pendiente",
        request_date=request_date or date.today(),
        notes=notes.strip()[:5000],
        created_by=user.email,
        updated_by=user.email,
    )
    db.add(item)
    db.flush()
    write_audit(
        db, user, "crear", "certificado_oficial", str(item.id),
        f"{info['institution']} / {info['label']} / {company.legal_name}",
    )
    _notify_studio_team(
        db, background_tasks, company, user,
        event_type="certificado_oficial_creado",
        title=f"Seguimiento de certificado oficial creado · {info['label']}",
        body=f"Se registró el seguimiento de {info['label']} para {company.legal_name}.",
        target_url="/app/certificates/official",
    )
    db.commit()
    return RedirectResponse(f"/app/certificates/official?created={item.id}", status_code=303)


@app.post("/app/certificates/official/{record_id}/update")
async def update_official_certificate_record(
    record_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    status_value: Annotated[str, Form(alias="status")],
    issue_date: Annotated[date | None, Form()] = None,
    expiry_date: Annotated[date | None, Form()] = None,
    official_number: Annotated[str, Form()] = "",
    result_status: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
    file: UploadFile | None = File(default=None),
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    if status_value not in OFFICIAL_CERTIFICATE_STATUSES:
        raise HTTPException(400, "Estado de certificado inválido.")
    item = get_allowed_official_certificate(record_id, user, db)
    company = company_allowed(db, user, item.company_id)
    info = OFFICIAL_CERTIFICATE_TYPES.get(item.certificate_type, {})
    if not info:
        raise HTTPException(400, "El tipo de certificado no existe en el catálogo.")
    if result_status not in OFFICIAL_CERTIFICATE_RESULTS:
        raise HTTPException(400, "Resultado del certificado inválido.")
    if info.get("has_result"):
        if result_status not in {"", "CUMPLE", "NO CUMPLE"}:
            raise HTTPException(400, "Resultado inválido para el Certificado Laboral del MTESS.")
        if status_value == "Emitido" and not result_status:
            raise HTTPException(400, "Registrá el resultado exacto indicado en el Certificado Laboral oficial.")
    elif result_status not in {"", "No aplica"}:
        raise HTTPException(400, "Este documento no utiliza un resultado CUMPLE/NO CUMPLE.")
    else:
        result_status = ""

    existing_document = db.get(Document, item.document_id) if item.document_id else None
    if existing_document and existing_document.company_id != item.company_id:
        raise HTTPException(409, "El archivo vinculado no corresponde a la empresa.")
    if (
        status_value == "Emitido"
        and item.certificate_type == "ips_certificado_cumplimiento"
        and not (expiry_date or item.expiry_date)
    ):
        raise HTTPException(400, "Para el Certificado de Cumplimiento IPS ingresá el vencimiento indicado por el IPS (próximo pago).")

    uploaded = file is not None and bool(file.filename)
    if uploaded:
        payload = await file.read(MAX_UPLOAD_SIZE + 1)
        if len(payload) > MAX_UPLOAD_SIZE:
            raise HTTPException(413, "El archivo supera el límite de tamaño permitido.")
        if not payload:
            raise HTTPException(400, "El archivo está vacío.")
        if payload.startswith(b"%PDF-"):
            content_type = "application/pdf"
            extension = ".pdf"
        elif payload.startswith(b"\x89PNG\r\n\x1a\n"):
            content_type = "image/png"
            extension = ".png"
        elif payload.startswith(b"\xff\xd8\xff"):
            content_type = "image/jpeg"
            extension = ".jpg"
        else:
            raise HTTPException(400, "Adjuntá un PDF o una imagen PNG/JPG válida del original oficial.")
        original_name = safe_filename(file.filename or f"certificado-oficial{extension}")
        if not original_name.lower().endswith(extension):
            original_name = f"{Path(original_name).stem}{extension}"
        stored_name = f"documents/{company.id}/{uuid.uuid4().hex}_{original_name}"
        storage.put(stored_name, payload, content_type)
        document = Document(
            company_id=company.id,
            employee_id=item.employee_id,
            category="Certificado oficial",
            title=f"{info.get('label', 'Certificado oficial')} · {company.legal_name}",
            stored_name=stored_name,
            original_name=original_name,
            content_type=content_type,
            content_bytes=payload if settings.storage_backend == "local" else None,
            uploaded_by=user.email,
        )
        db.add(document)
        db.flush()
        item.document_id = document.id

    if status_value == "Emitido":
        if not uploaded and not existing_document:
            raise HTTPException(400, "Adjuntá el original emitido por MTESS/IPS antes de marcarlo como Emitido.")
        if not uploaded and (not existing_document or existing_document.company_id != item.company_id):
            raise HTTPException(400, "El archivo original vinculado no está disponible para esta empresa.")
        if not uploaded and not storage.exists(existing_document.stored_name):
            raise HTTPException(400, "El archivo original no está disponible en el almacenamiento. Volvé a adjuntarlo antes de confirmar la emisión.")
        issue_date = issue_date or item.issue_date or date.today()
        fixed_expiry = default_expiry_date(item.certificate_type, issue_date)
        expiry_date = fixed_expiry if fixed_expiry else (expiry_date or item.expiry_date)
        if expiry_date and expiry_date < issue_date:
            raise HTTPException(400, "La fecha de vencimiento no puede ser anterior a la fecha de emisión.")
    else:
        issue_date = issue_date or item.issue_date
        expiry_date = expiry_date or item.expiry_date

    previous_status = item.status
    item.status = status_value
    item.issue_date = issue_date
    item.expiry_date = expiry_date
    item.official_number = official_number.strip()[:120]
    item.result_status = result_status
    item.notes = notes.strip()[:5000]
    item.updated_by = user.email
    item.updated_at = datetime.now(UTC)
    audit_detail = (
        f"{info.get('label', item.certificate_type)}; estado={previous_status} → {item.status}; "
        f"emisión={item.issue_date.isoformat() if item.issue_date else 'sin registrar'}; "
        f"vencimiento={item.expiry_date.isoformat() if item.expiry_date else 'sin registrar'}; "
        f"número={item.official_number or 'sin registrar'}; resultado={item.result_status or 'sin registrar'}; "
        f"original_document_id={item.document_id or 'sin adjuntar'}"
    )
    write_audit(db, user, "actualizar", "certificado_oficial", str(item.id), audit_detail)
    if previous_status != item.status:
        _notify_studio_team(
            db, background_tasks, company, user,
            event_type="certificado_oficial_estado",
            title=f"Estado de certificado actualizado · {info.get('label', item.certificate_type)}",
            body=f"El seguimiento de {info.get('label', item.certificate_type)} para {company.legal_name} cambió de {previous_status} a {item.status}.",
            target_url="/app/certificates/official",
        )
    db.commit()
    return RedirectResponse(f"/app/certificates/official?updated={item.id}", status_code=303)


def _csv_safe_cell(value):
    """Prevent spreadsheet formula execution when text exports are opened in Excel/LibreOffice."""
    if not isinstance(value, str):
        return value
    trimmed = value.lstrip(" \t\r\n")
    if value.startswith(("\t", "\r", "\n")) or (trimmed and trimmed[0] in {"=", "+", "-", "@"}):
        return "'" + value
    return value


@app.get("/app/reports", response_class=HTMLResponse)
def reports_page(
    request: Request,
    company_id: OptionalQueryId = None,
    employee_id: OptionalQueryId = None,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    company_ids = company_ids_for_user(db, user)
    company_id, employee_id = default_labor_context(
        request, db, user, company_ids, company_id, employee_id
    )
    companies = list(db.scalars(select(Company).where(Company.id.in_(company_ids)).order_by(Company.legal_name))) if company_ids else []
    if company_id not in company_ids:
        company_id = None
    employees = list(db.scalars(select(Employee).where(Employee.company_id.in_(company_ids)).order_by(Employee.full_name))) if company_ids else []
    if employee_id and employee_id not in {item.id for item in employees}:
        employee_id = None
    calculations_query = select(CalculationRecord).where(CalculationRecord.company_id == company_id) if company_id else select(CalculationRecord).where(False)
    certificates_query = select(GeneratedCertificate).where(GeneratedCertificate.company_id == company_id) if company_id else select(GeneratedCertificate).where(False)
    if employee_id:
        calculations_query = calculations_query.where(CalculationRecord.employee_id == employee_id)
        certificates_query = certificates_query.where(GeneratedCertificate.employee_id == employee_id)
    calculations = list(db.scalars(calculations_query.order_by(CalculationRecord.created_at.desc()).limit(50)))
    certificates = list(db.scalars(certificates_query.order_by(GeneratedCertificate.created_at.desc()).limit(50)))
    payrolls = list(db.scalars(select(Payroll).where(Payroll.company_id == company_id).order_by(Payroll.period.desc()).limit(24))) if company_id else []
    return render(
        request,
        "reports.html",
        db,
        user,
        companies=companies,
        employees=employees,
        selected_company=company_id,
        selected_employee=employee_id,
        calculations=calculations,
        certificates=certificates,
        payrolls=payrolls,
        calculation_labels={key: calculation_label(key) for key in ("salary", "hours", "aguinaldo", "vacation", "notice")},
        report_groups=[
            {
                "title": group["title"],
                "reports": [
                    spec for spec in group["reports"]
                    if spec.key not in _REPORT_SENSITIVE_KEYS or user.role in {"administrador", "contador", "auxiliar"}
                ],
            }
            for group in REPORT_GROUPS
            if any(spec.key not in _REPORT_SENSITIVE_KEYS or user.role in {"administrador", "contador", "auxiliar"} for spec in group["reports"])
        ],
        report_count=sum(
            1 for spec in REPORTS.values()
            if spec.key not in _REPORT_SENSITIVE_KEYS or user.role in {"administrador", "contador", "auxiliar"}
        ),
    )


@app.get("/app/reports/export.csv")
def reports_export_csv(
    company_id: int,
    employee_id: OptionalQueryId = None,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    company = company_allowed(db, user, company_id)
    query = select(CalculationRecord).where(CalculationRecord.company_id == company.id)
    if employee_id:
        employee = db.get(Employee, employee_id)
        if not employee or employee.company_id != company.id:
            raise HTTPException(404)
        query = query.where(CalculationRecord.employee_id == employee.id)
    items = list(db.scalars(query.order_by(CalculationRecord.created_at.desc())))
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Fecha", "Empresa", "Funcionario", "Tipo", "Periodo", "Monto", "Estado", "Origen", "Creado por"])
    for item in items:
        writer.writerow([_csv_safe_cell(value) for value in [
            item.created_at.strftime("%d/%m/%Y %H:%M"),
            company.legal_name,
            item.employee.full_name if item.employee else "",
            calculation_label(item.calculation_type),
            item.reference_period,
            item.amount,
            item.status,
            item.source,
            item.created_by,
        ]])
    filename = safe_download_name(f"Informe de cálculos {company.legal_name}", "", "csv")
    return StreamingResponse(
        iter(["\ufeff" + output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@app.get("/app/reports/employees/{employee_id}.pdf")
def employee_integral_report(
    employee_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    employee = db.get(Employee, employee_id)
    if not employee or employee.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    company = employee.company
    calculations = list(db.scalars(select(CalculationRecord).where(CalculationRecord.employee_id == employee.id).order_by(CalculationRecord.created_at.desc())))
    certificates = list(db.scalars(select(GeneratedCertificate).where(GeneratedCertificate.employee_id == employee.id).order_by(GeneratedCertificate.created_at.desc())))
    vacations = list(db.scalars(select(Vacation).where(Vacation.employee_id == employee.id).order_by(Vacation.period_year.desc())))
    aguinaldos = list(db.scalars(select(Aguinaldo).where(Aguinaldo.employee_id == employee.id).order_by(Aguinaldo.year.desc())))
    branding = get_or_create_branding(db, company)
    db.commit()
    payload = build_employee_report_pdf(
        company=company,
        employee=employee,
        calculations=calculations,
        certificates=certificates,
        vacations=vacations,
        aguinaldos=aguinaldos,
        branding=branding,
    )
    filename = safe_download_name("Informe integral", employee.full_name, "pdf")
    write_audit(db, user, "descargar", "informe_integral", str(employee.id), filename)
    db.commit()
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )




# Shared, tenant-scoped report catalog, query API and export endpoints.
_REPORT_SENSITIVE_KEYS = {"listado-examen-medico"}
_REPORT_EXPORT_LIMIT = 25000


def _validate_report_scope(report_key: str, company_id: int | None, employee_id: int | None, user: User, db: Session):
    spec = get_report(report_key)
    if spec is None:
        raise HTTPException(404, "El submódulo de informe no existe.")
    if spec.key in _REPORT_SENSITIVE_KEYS and user.role not in {"administrador", "contador", "auxiliar"}:
        raise HTTPException(403, "Tu perfil no está autorizado para consultar exámenes médicos.")
    allowed_company_ids = company_ids_for_user(db, user)
    if company_id is not None and company_id not in allowed_company_ids:
        raise HTTPException(404, "La empresa no está disponible para este usuario.")
    if employee_id is not None:
        employee = db.get(Employee, employee_id)
        if not employee or employee.company_id not in allowed_company_ids:
            raise HTTPException(404, "El funcionario no está disponible para este usuario.")
        if company_id is not None and employee.company_id != company_id:
            raise HTTPException(404, "El funcionario no pertenece a la empresa seleccionada.")
    return spec, allowed_company_ids


def _report_query_parameters(q, company_id, employee_id, status_filter, year, period, page, page_size, sort):
    params = {}
    for key, value in (
        ("q", q), ("company_id", company_id), ("employee_id", employee_id),
        ("status", status_filter), ("year", year), ("period", period),
        ("page_size", page_size), ("sort", sort),
    ):
        if value not in (None, ""):
            params[key] = value
    if page not in (None, 1):
        params["page"] = page
    return params


def _all_report_export_rows(db, spec, company_ids, company_id, employee_id, q, status_filter, year, period, sort):
    first_page = fetch_report(
        db, spec, company_ids, company_id, employee_id, q, status_filter, year, period, 1, 100, sort
    )
    rows = list(first_page["records"])
    target = min(int(first_page["total"]), _REPORT_EXPORT_LIMIT)
    for page_no in range(2, (target + 99) // 100 + 1):
        page_data = fetch_report(
            db, spec, company_ids, company_id, employee_id, q, status_filter, year, period, page_no, 100, sort
        )
        rows.extend(page_data["records"])
    return rows, int(first_page["total"])


def _report_export_response(report_key, output_format, company_id, employee_id, q, status_filter, year, period, sort, user, db):
    spec, allowed_company_ids = _validate_report_scope(report_key, company_id, employee_id, user, db)
    fmt = (output_format or "xlsx").strip().lower()
    if fmt not in {"xlsx", "pdf", "csv"}:
        raise HTTPException(400, "Formato no admitido. Usá xlsx, pdf o csv.")
    rows, total = _all_report_export_rows(
        db, spec, allowed_company_ids, company_id, employee_id, q, status_filter, year, period, sort
    )
    if fmt == "xlsx":
        payload = make_xlsx(spec, rows)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif fmt == "pdf":
        company_name = ""
        if company_id is not None:
            company = db.get(Company, company_id)
            company_name = company.legal_name if company else ""
        payload = make_pdf(spec, rows, company_name)
        media_type = "application/pdf"
    else:
        output = io.StringIO()
        writer = csv.writer(output)
        columns = fetch_report(db, spec, allowed_company_ids, company_id, employee_id, q, status_filter, year, period, 1, 1, sort)["columns"]
        writer.writerow(columns)
        for row in rows:
            writer.writerow([_csv_safe_cell(row.get(column, "")) for column in columns])
        payload = ("\ufeff" + output.getvalue()).encode("utf-8")
        media_type = "text/csv; charset=utf-8"
    filename = safe_download_name(f"Informe {spec.label}", "", fmt)
    write_audit(db, user, "descargar", "informe_laboral", spec.key, f"formato={fmt}; filas={len(rows)}; total={total}")
    db.commit()
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    if total > _REPORT_EXPORT_LIMIT:
        headers["X-Report-Result-Limit"] = str(_REPORT_EXPORT_LIMIT)
        headers["X-Report-Total-Available"] = str(total)
    return Response(content=payload, media_type=media_type, headers=headers)


@app.get("/api/reports/catalog")
def reports_catalog_api(user: User = Depends(require_user), db: Session = Depends(get_db)):
    groups = []
    for group in REPORT_GROUPS:
        visible = [
            {
                "key": spec.key,
                "label": spec.label,
                "group": spec.group,
                "description": spec.description,
                "note": spec.note,
                "endpoint": f"/api/reports/{spec.key}",
                "export_endpoint": f"/api/reports/{spec.key}/export",
            }
            for spec in group["reports"]
            if spec.key not in _REPORT_SENSITIVE_KEYS or user.role in {"administrador", "contador", "auxiliar"}
        ]
        if visible:
            groups.append({"title": group["title"], "reports": visible})
    return {"version": APP_VERSION, "total": sum(len(group["reports"]) for group in groups), "groups": groups}


@app.get("/api/reports/{report_key}")
def report_data_api(
    report_key: str,
    company_id: OptionalQueryId = None,
    employee_id: OptionalQueryId = None,
    q: str = "",
    status: str = "",
    year: int | None = None,
    period: str = "",
    page: int = 1,
    page_size: int = 25,
    sort: str = "",
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    spec, allowed_company_ids = _validate_report_scope(report_key, company_id, employee_id, user, db)
    if year is not None and (year < 1900 or year > 2100):
        raise HTTPException(400, "El año debe estar entre 1900 y 2100.")
    result = fetch_report(
        db, spec, allowed_company_ids, company_id, employee_id, q, status, year, period, page, page_size, sort
    )
    return {
        "report": {"key": spec.key, "label": spec.label, "group": spec.group, "description": spec.description, "note": spec.note},
        **result,
    }


@app.get("/api/reports/{report_key}/export")
def report_data_api_export(
    report_key: str,
    format: str = "xlsx",
    company_id: OptionalQueryId = None,
    employee_id: OptionalQueryId = None,
    q: str = "",
    status: str = "",
    year: int | None = None,
    period: str = "",
    sort: str = "",
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    if year is not None and (year < 1900 or year > 2100):
        raise HTTPException(400, "El año debe estar entre 1900 y 2100.")
    return _report_export_response(
        report_key, format, company_id, employee_id, q, status, year, period, sort, user, db
    )


@app.get("/app/reports/{report_key}/export")
def report_page_export(
    report_key: str,
    format: str = "xlsx",
    company_id: OptionalQueryId = None,
    employee_id: OptionalQueryId = None,
    q: str = "",
    status: str = "",
    year: int | None = None,
    period: str = "",
    sort: str = "",
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    if year is not None and (year < 1900 or year > 2100):
        raise HTTPException(400, "El año debe estar entre 1900 y 2100.")
    return _report_export_response(
        report_key, format, company_id, employee_id, q, status, year, period, sort, user, db
    )




# Submódulo dedicado de recibos internos de liquidación salarial.
_SALARY_REPORT_TYPES = ("salary", "suite_salary")


def _salary_report_record(db: Session, user: User, calculation_id: int):
    from .salary_report_service import SALARY_CALCULATION_TYPES

    item = db.get(CalculationRecord, calculation_id)
    if (
        not item
        or item.company_id not in company_ids_for_user(db, user)
        or item.calculation_type not in SALARY_CALCULATION_TYPES
        or not item.employee_id
    ):
        raise HTTPException(404, "Liquidación de salario no encontrada.")
    employee = db.get(Employee, item.employee_id)
    company = db.get(Company, item.company_id)
    if not employee or not company or employee.company_id != company.id:
        raise HTTPException(404, "La liquidación no tiene un funcionario válido asociado.")
    return item, company, employee


@app.get("/app/reports/liquidaciones-salarios", response_class=HTMLResponse)
def salary_settlements_report_page(
    request: Request,
    company_id: OptionalQueryId = None,
    employee_id: OptionalQueryId = None,
    period: str = "",
    status: str = "",
    q: str = "",
    page: int = 1,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    from .salary_report_service import SALARY_CALCULATION_TYPES

    allowed_ids = company_ids_for_user(db, user)
    company_id, employee_id = default_labor_context(request, db, user, allowed_ids, company_id, employee_id)
    period = clean_text(period, max_length=7)
    if period:
        if not re.fullmatch(r"\d{4}-\d{2}", period):
            raise HTTPException(422, "El período debe tener formato AAAA-MM.")
        try:
            date.fromisoformat(period + "-01")
        except ValueError as exc:
            raise HTTPException(422, "Seleccioná un mes válido.") from exc
    status = clean_text(status, max_length=30)
    q = clean_text(q, max_length=120)
    page_size = 30
    page = max(1, min(int(page or 1), 100000))

    companies = list(
        db.scalars(select(Company).where(Company.id.in_(allowed_ids)).order_by(Company.legal_name))
    ) if allowed_ids else []
    employees_query = (
        select(Employee).where(Employee.company_id.in_(allowed_ids)).order_by(Employee.full_name)
        if allowed_ids else select(Employee).where(False)
    )
    if company_id:
        employees_query = employees_query.where(Employee.company_id == company_id)
    employees = list(db.scalars(employees_query.limit(1500)))

    conditions = [
        CalculationRecord.company_id.in_(allowed_ids),
        CalculationRecord.calculation_type.in_(SALARY_CALCULATION_TYPES),
        CalculationRecord.employee_id.is_not(None),
    ]
    if company_id:
        conditions.append(CalculationRecord.company_id == company_id)
    if employee_id:
        conditions.append(CalculationRecord.employee_id == employee_id)
    if period:
        conditions.append(CalculationRecord.reference_period == period)
    if status:
        conditions.append(CalculationRecord.status == status)
    if q:
        term = f"%{q}%"
        conditions.append(or_(
            Company.legal_name.ilike(term), Company.ruc.ilike(term),
            Employee.full_name.ilike(term), Employee.document_number.ilike(term),
            CalculationRecord.notes.ilike(term), CalculationRecord.reference_period.ilike(term),
        ))

    query = (
        select(CalculationRecord)
        .join(Company, Company.id == CalculationRecord.company_id)
        .join(Employee, Employee.id == CalculationRecord.employee_id)
        .where(*conditions)
        .options(selectinload(CalculationRecord.company), selectinload(CalculationRecord.employee))
    )
    count_query = (
        select(func.count(CalculationRecord.id))
        .join(Company, Company.id == CalculationRecord.company_id)
        .join(Employee, Employee.id == CalculationRecord.employee_id)
        .where(*conditions)
    )
    total = int(db.scalar(count_query) or 0)
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, pages)
    items = list(db.scalars(
        query.order_by(
            CalculationRecord.reference_period.desc(),
            CalculationRecord.created_at.desc(),
            CalculationRecord.id.desc(),
        ).limit(page_size).offset((page - 1) * page_size)
    ))
    return render(
        request, "salary_settlement_index.html", db, user,
        companies=companies, employees=employees, items=items, total=total, page=page, pages=pages,
        page_size=page_size, selected_company=company_id, selected_employee=employee_id,
        filters={"period": period, "status": status, "q": q},
    )


@app.get("/app/reports/liquidaciones-salarios/{calculation_id}", response_class=HTMLResponse)
def salary_settlement_report_detail(
    request: Request,
    calculation_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    from .salary_report_service import build_salary_report_model, salary_report_history
    from .reop_salary_service import (
        REOP_COMMUNICATIONS_URL,
        REOP_FORMS_URL,
        build_reop_salary_payload,
    )

    item, company, employee = _salary_report_record(db, user, calculation_id)
    model = build_salary_report_model(db, item, company, employee)
    history = salary_report_history(db, item)
    audit_events = list(db.scalars(
        select(AuditLog).where(
            AuditLog.studio_id == user.studio_id,
            AuditLog.entity == "liquidacion_salario",
            AuditLog.entity_id == str(item.id),
        ).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(20)
    )) if user.studio_id else []
    reop_default_payload = build_reop_salary_payload(db, item, company, employee, model)
    reop_batches = list(db.scalars(
        select(IntegrationBatch)
        .where(
            IntegrationBatch.company_id == company.id,
            IntegrationBatch.calculation_record_id == item.id,
            IntegrationBatch.authority == "REOP",
        )
        .order_by(IntegrationBatch.created_at.desc(), IntegrationBatch.id.desc())
        .limit(20)
    ))
    reop_receipt_available = {}
    for batch in reop_batches:
        try:
            reop_receipt_available[batch.id] = bool(
                batch.receipt_bytes is not None
                or (batch.receipt_storage_key and storage.exists(batch.receipt_storage_key))
            )
        except Exception:
            reop_receipt_available[batch.id] = batch.receipt_bytes is not None
    return render(
        request, "salary_settlement_detail.html", db, user,
        item=item, model=model, history=history, audit_events=audit_events,
        reop_batches=reop_batches,
        reop_receipt_available=reop_receipt_available,
        reop_default_payload=reop_default_payload,
        reop_communications_url=REOP_COMMUNICATIONS_URL,
        reop_forms_url=REOP_FORMS_URL,
        reop_can_manage=user.role in {"administrador", "contador"},
        integration_batch_transitions={key: sorted(value) for key, value in INTEGRATION_BATCH_STATUS_TRANSITIONS.items()},
        reop_direct_enabled=settings.reop_direct_enabled,
        auto_print=request.query_params.get("imprimir") == "1",
    )


@app.post("/app/reports/liquidaciones-salarios/{calculation_id}/reop/prepare")
def prepare_reop_salary_submission(
    calculation_id: int,
    payment_date: Annotated[str, Form()] = "",
    payment_method: Annotated[str, Form()] = "",
    days_worked: Annotated[str, Form()] = "",
    hours_worked: Annotated[str, Form()] = "",
    pieces_or_tasks: Annotated[str, Form()] = "",
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    """Prepare a traceable handoff packet; this route does not transmit data to MTESS."""
    import hashlib
    from .salary_report_service import build_salary_report_model
    from .reop_salary_service import (
        XLSX_MIME,
        build_reop_salary_handoff_workbook,
        build_reop_salary_payload,
        validate_reop_profile_readiness,
        validate_reop_salary_payload,
    )

    item, company, employee = _salary_report_record(db, user, calculation_id)
    if (item.status or "").strip() not in {"Aprobado", "Validado"}:
        raise HTTPException(409, "Solo se puede preparar una comunicación REOP a partir de un cálculo aprobado o validado.")
    model = build_salary_report_model(db, item, company, employee)
    if not model.get("can_reprint"):
        raise HTTPException(409, "No se puede preparar una comunicación a partir de un cálculo anulado.")

    latest = db.scalar(
        select(IntegrationBatch)
        .where(
            IntegrationBatch.company_id == company.id,
            IntegrationBatch.calculation_record_id == item.id,
            IntegrationBatch.authority == "REOP",
        )
        .order_by(IntegrationBatch.created_at.desc(), IntegrationBatch.id.desc())
        .limit(1)
    )
    if latest and latest.status in {"Validado", "Presentado", "Aceptado"}:
        raise HTTPException(409, f"El intento REOP #{latest.id} está en estado {latest.status}. Continuá ese flujo antes de crear otro.")
    if latest and latest.status == "Generado" and not (latest.error_message or "").strip():
        raise HTTPException(409, f"Ya existe un intento REOP #{latest.id} listo para validar.")

    payload = build_reop_salary_payload(
        db, item, company, employee, model,
        payment_date=payment_date,
        payment_method=payment_method,
        days_worked=days_worked,
        hours_worked=hours_worked,
        pieces_or_tasks=pieces_or_tasks,
    )
    payload["profile_validation_errors"] = validate_reop_profile_readiness(db, company, employee)
    errors = validate_reop_salary_payload(payload)
    content = build_reop_salary_handoff_workbook(payload)
    batch = IntegrationBatch(
        studio_id=company.studio_id,
        company_id=company.id,
        calculation_record_id=item.id,
        payload_json=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        authority="REOP",
        batch_type="Liquidación salarial individual",
        period=str(payload.get("period") or item.reference_period or ""),
        status="Generado",
        file_sha256=hashlib.sha256(content).hexdigest(),
        item_count=1,
        error_message="\n".join(errors),
        created_by=user.email,
    )
    db.add(batch)
    db.flush()
    safe_ruc = re.sub(r"[^A-Za-z0-9_-]+", "-", company.ruc or str(company.id)).strip("-") or str(company.id)
    period_tag = re.sub(r"[^0-9-]", "", str(payload.get("period") or "sin-periodo")) or "sin-periodo"
    batch.file_name = safe_filename(
        f"reop_preparacion_salario_{safe_ruc}_{period_tag}_calc-{item.id}_lote-{batch.id}.xlsx"
    )
    if settings.storage_backend == "s3":
        key = f"integrations/{company.id}/reop-salary/batch-{batch.id}.xlsx"
        storage.put(key, content, XLSX_MIME)
        batch.storage_key = key
        batch.file_bytes = None
    else:
        # The database copy survives ephemeral local disks in hosted environments.
        batch.file_bytes = content
        batch.storage_key = ""
    write_audit(
        db, user, "preparar", "lote_integracion", str(batch.id),
        f"REOP · cálculo #{item.id} · período {payload.get('period') or ''} · SHA-256 {batch.file_sha256}",
    )
    db.commit()
    flag = "&reop_validation_error=1" if errors else ""
    return RedirectResponse(
        f"/app/reports/liquidaciones-salarios/{item.id}?reop_batch={batch.id}{flag}",
        status_code=303,
    )


@app.post("/app/reports/liquidaciones-salarios/{calculation_id}/reop/{batch_id}/validate")
def validate_reop_salary_submission(
    calculation_id: int,
    batch_id: int,
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    """Apply local preflight validation and approval; never claims MTESS acceptance."""
    from .reop_salary_service import validate_reop_profile_readiness, validate_reop_salary_payload

    item, company, employee = _salary_report_record(db, user, calculation_id)
    batch = db.get(IntegrationBatch, batch_id)
    if (
        not batch
        or batch.company_id != company.id
        or batch.calculation_record_id != item.id
        or batch.authority != "REOP"
    ):
        raise HTTPException(404, "No se encontró el intento REOP para este cálculo.")
    if batch.status != "Generado":
        raise HTTPException(409, f"Solo se puede validar un intento en estado Generado; estado actual: {batch.status}.")
    try:
        payload = json.loads(batch.payload_json or "{}")
    except (json.JSONDecodeError, TypeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    errors = list(dict.fromkeys([
        *validate_reop_salary_payload(payload),
        *validate_reop_profile_readiness(db, company, employee),
    ]))
    if errors:
        batch.error_message = "\n".join(errors)
        write_audit(
            db, user, "validacion_bloqueada", "lote_integracion", str(batch.id),
            f"REOP · cálculo #{item.id} · {len(errors)} validaciones pendientes",
        )
        db.commit()
        return RedirectResponse(
            f"/app/reports/liquidaciones-salarios/{item.id}?reop_batch={batch.id}&reop_validation_error=1",
            status_code=303,
        )
    if settings.compliance_dual_approval and batch.created_by == user.email:
        raise HTTPException(409, "La política de doble aprobación exige que valide otro usuario autorizado.")
    batch.status = "Validado"
    batch.approved_by = user.email
    batch.error_message = ""
    write_audit(
        db, user, "validar", "lote_integracion", str(batch.id),
        f"REOP · validación local aprobada para cálculo #{item.id}; pendiente de presentación en el portal oficial.",
    )
    db.commit()
    return RedirectResponse(
        f"/app/reports/liquidaciones-salarios/{item.id}?reop_batch={batch.id}",
        status_code=303,
    )


@app.post("/app/reports/liquidaciones-salarios/{calculation_id}/reimprimir")
def salary_settlement_reprint(
    calculation_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    from .salary_report_service import build_salary_report_model

    item, company, employee = _salary_report_record(db, user, calculation_id)
    model = build_salary_report_model(db, item, company, employee)
    if not model["can_reprint"]:
        raise HTTPException(409, "No se puede reimprimir un cálculo anulado.")
    write_audit(
        db, user, "reimpresion_liquidacion_salario", "liquidacion_salario", str(item.id),
        f"Impresión HTML · período {model['period']} · neto Gs. {format_gs(model['net'])}",
    )
    db.commit()
    return RedirectResponse(f"/app/reports/liquidaciones-salarios/{item.id}?imprimir=1", status_code=303)


@app.get("/app/reports/liquidaciones-salarios/{calculation_id}/pdf")
def salary_settlement_report_pdf(
    calculation_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    from .salary_report_service import build_salary_report_model, build_salary_report_pdf

    item, company, employee = _salary_report_record(db, user, calculation_id)
    model = build_salary_report_model(db, item, company, employee)
    if not model["can_reprint"]:
        raise HTTPException(409, "No se puede reimprimir un cálculo anulado.")
    write_audit(
        db, user, "reimpresion_pdf_liquidacion_salario", "liquidacion_salario", str(item.id),
        f"PDF · período {model['period']} · neto Gs. {format_gs(model['net'])}",
    )
    db.commit()
    payload = build_salary_report_pdf(model)
    filename = f"digit-laboral-liquidacion-salario-{item.id:06d}.pdf"
    return Response(
        content=payload, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )




@app.get("/app/reports/{report_key}", response_class=HTMLResponse)
def report_detail_page(
    request: Request,
    report_key: str,
    company_id: OptionalQueryId = None,
    employee_id: OptionalQueryId = None,
    q: str = "",
    status: str = "",
    year: int | None = None,
    period: str = "",
    page: int = 1,
    page_size: int = 25,
    sort: str = "",
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    if report_key == "liquidacion-salario":
        target = "/app/reports/liquidaciones-salarios"
        if request.url.query:
            target += f"?{request.url.query}"
        return RedirectResponse(target, status_code=303)

    spec, allowed_company_ids = _validate_report_scope(report_key, company_id, employee_id, user, db)
    if year is not None and (year < 1900 or year > 2100):
        raise HTTPException(400, "El año debe estar entre 1900 y 2100.")
    result = fetch_report(
        db, spec, allowed_company_ids, company_id, employee_id, q, status, year, period, page, page_size, sort
    )
    companies = list(db.scalars(select(Company).where(Company.id.in_(allowed_company_ids)).order_by(Company.legal_name))) if allowed_company_ids else []
    employee_query = select(Employee).where(Employee.company_id.in_(allowed_company_ids)).order_by(Employee.full_name) if allowed_company_ids else select(Employee).where(False)
    if company_id is not None:
        employee_query = employee_query.where(Employee.company_id == company_id)
    employees = list(db.scalars(employee_query.limit(1000)))
    params = _report_query_parameters(q, company_id, employee_id, status, year, period, 1, page_size, sort)
    export_base = f"/app/reports/{report_key}/export?{urlencode(params)}"
    pagination_base = f"/app/reports/{report_key}?{urlencode(params)}"
    return render(
        request, "report_detail.html", db, user,
        report=spec, companies=companies, employees=employees,
        selected_company=company_id, selected_employee=employee_id,
        filters={"q": q, "status": status, "year": year, "period": period, "sort": sort},
        sort_options=report_sort_options(spec),
        pagination=result, columns=result["columns"], rows=result["records"],
        export_base=export_base, pagination_base=pagination_base,
    )


@app.get("/app/ai", response_class=HTMLResponse)
def ai_page(
    request: Request,
    company_id: OptionalQueryId = None,
    employee_id: OptionalQueryId = None,
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    company_ids = company_ids_for_user(db, user)
    companies = list(db.scalars(select(Company).where(Company.id.in_(company_ids)).order_by(Company.legal_name))) if company_ids else []
    employees = list(db.scalars(select(Employee).where(Employee.company_id.in_(company_ids)).order_by(Employee.full_name))) if company_ids else []
    selected_company = db.get(Company, company_id) if company_id in company_ids else None
    selected_employee = db.get(Employee, employee_id) if employee_id else None
    if selected_employee and selected_employee.company_id not in company_ids:
        selected_employee = None
    interactions_query = select(AIInteraction).where(
        AIInteraction.studio_id == user.studio_id,
        or_(AIInteraction.company_id.is_(None), AIInteraction.company_id.in_(company_ids)),
    )
    if user.role == "empresa":
        interactions_query = interactions_query.where(AIInteraction.company_id.in_(company_ids))
    interactions = list(db.scalars(interactions_query.order_by(AIInteraction.created_at.desc()).limit(15)))
    result_id = request.query_params.get("result", "")
    latest = db.scalar(interactions_query.where(AIInteraction.id == int(result_id))) if result_id.isdigit() else None
    if result_id and not latest:
        raise HTTPException(404, "Consulta no encontrada.")
    return render(
        request,
        "ai_assistant.html",
        db,
        user,
        companies=companies,
        employees=employees,
        selected_company=selected_company,
        selected_employee=selected_employee,
        interactions=interactions,
        latest=latest,
        ai_external_available=bool(settings.openai_api_key and settings.ai_enabled),
        ai_model=settings.openai_model,
    )


@app.post("/app/ai")
def ai_assistance(
    purpose: Annotated[str, Form()] = "control",
    company_id: Annotated[int | None, Form()] = None,
    employee_id: Annotated[int | None, Form()] = None,
    instruction: Annotated[str, Form()] = "",
    external_consent: Annotated[str | None, Form()] = None,
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    company = company_allowed(db, user, company_id) if company_id else None
    employee = db.get(Employee, employee_id) if employee_id else None
    if employee and employee.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    if company and employee and employee.company_id != company.id:
        raise HTTPException(400, "El funcionario no corresponde a la empresa seleccionada.")
    if employee and not company:
        company = employee.company
    context = build_ai_context(db, company, employee)
    result = generate_assistance(
        purpose=purpose,
        context=context,
        instruction=instruction,
        allow_external=external_consent == "on",
    )
    item = AIInteraction(
        studio_id=user.studio_id,
        company_id=company.id if company else None,
        employee_id=employee.id if employee else None,
        purpose=purpose,
        user_instruction=instruction.strip(),
        context_summary=json.dumps(context, ensure_ascii=False, default=str)[:12000],
        response_text=result.text,
        provider=result.provider,
        model_name=result.model,
        status="Completado",
        created_by=user.email,
    )
    db.add(item)
    db.flush()
    write_audit(db, user, "consultar", "asistente_ia", str(item.id), purpose)
    db.commit()
    return RedirectResponse(f"/app/ai?result={item.id}", status_code=303)


@app.get("/app/payrolls", response_class=HTMLResponse)
def payrolls_page(
    request: Request,
    company_id: OptionalQueryId = None,
    employee_id: OptionalQueryId = None,
    user: User = Depends(require_roles("administrador", "contador", "auxiliar", "empresa")),
    db: Session = Depends(get_db),
):
    company_ids = company_ids_for_user(db, user)
    selected_company_id, selected_employee_id = default_labor_context(
        request, db, user, company_ids, company_id, employee_id
    )
    payroll_query = select(Payroll).where(Payroll.company_id.in_(company_ids)) if company_ids else select(Payroll).where(False)
    if selected_company_id:
        payroll_query = payroll_query.where(Payroll.company_id == selected_company_id)
    if selected_employee_id:
        payroll_query = payroll_query.join(PayrollLine).where(PayrollLine.employee_id == selected_employee_id)
    payrolls = list(db.scalars(payroll_query.order_by(Payroll.period.desc(), Payroll.created_at.desc()).distinct()))
    companies = list(db.scalars(select(Company).where(Company.id.in_(company_ids), Company.status == "Activa").order_by(Company.legal_name))) if company_ids else []
    filter_companies = list(db.scalars(select(Company).where(Company.id.in_(company_ids)).order_by(Company.legal_name))) if company_ids else []
    filter_employees = list(db.scalars(select(Employee).where(Employee.company_id.in_(company_ids)).order_by(Employee.full_name))) if company_ids else []
    return render(request, "payrolls.html", db, user, payrolls=payrolls, companies=companies,
                  filter_companies=filter_companies, filter_employees=filter_employees,
                  selected_company_id=selected_company_id, selected_employee_id=selected_employee_id)


@app.post("/app/payrolls")
def create_payroll(
    request: Request,
    company_id: Annotated[int, Form()],
    period: Annotated[str, Form()],
    notes: Annotated[str, Form()] = "",
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    company_allowed(db, user, company_id)
    try:
        if not re.fullmatch(r"\d{4}-\d{2}", period):
            raise ValueError
        date.fromisoformat(period + "-01")
    except ValueError:
        raise HTTPException(400, "Periodo inválido")
    period_year, period_month = (int(part) for part in period.split("-"))
    period_start = date(period_year, period_month, 1)
    period_end = date(period_year, period_month, calendar.monthrange(period_year, period_month)[1])
    payroll = Payroll(company_id=company_id, period=period, notes=notes.strip(), created_by=user.email)
    db.add(payroll)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(Payroll).where(Payroll.company_id == company_id, Payroll.period == period))
        return RedirectResponse(f"/app/payrolls/{existing.id}" if existing else "/app/payrolls", status_code=303)
    employees = list(db.scalars(
        select(Employee).where(
            Employee.company_id == company_id,
            Employee.status == "Activo",
            Employee.admission_date <= period_end,
        ).order_by(Employee.full_name)
    ))
    ips_rate = get_parameter(db, "ips_employee_rate_general", 9) / 100
    salary_review_warnings = []
    for employee in employees:
        gross, employee_warnings = salary_for_period(db, employee, period_start, period_end)
        salary_review_warnings.extend(employee_warnings)
        ips = round_gs(Decimal(gross) * Decimal(str(ips_rate))) if employee.ips_contributor else 0
        db.add(PayrollLine(
            payroll_id=payroll.id, employee_id=employee.id, base_salary=gross, gross=gross,
            ips_employee=ips, total_discounts=ips, net=gross - ips,
            ips_base=gross if employee.ips_contributor else 0,
            ips_rate=round(ips_rate * 100, 2) if employee.ips_contributor else 0,
        ))
    if salary_review_warnings:
        review_block = (
            "REVISIÓN MANUAL DE SALARIOS: revisá los casos indicados antes de cerrar la nómina.\n- "
            + "\n- ".join(salary_review_warnings)
        )
        payroll.notes = "\n\n".join(
            value for value in (payroll.notes.strip(), review_block) if value
        )
    db.flush()
    recalculate_payroll(db, payroll)
    payroll_lines = list(db.scalars(select(PayrollLine).where(PayrollLine.payroll_id == payroll.id)))
    for line in payroll_lines:
        ensure_compliance_event(
            db, company_id=company_id, employee_id=line.employee_id, branch_id=line.employee.branch_id, authority="REOP", event_type="Liquidación salarial",
            event_date=period_end, due_date=None,
            payload={"payroll_id": payroll.id, "period": period, "gross": line.gross, "net": line.net},
            created_by=user.email, source_key=f"payroll:{payroll.id}:employee:{line.employee_id}:reop",
        )
        if line.employee.ips_contributor:
            ensure_compliance_event(
                db, company_id=company_id, employee_id=line.employee_id, branch_id=line.employee.branch_id, authority="REI", event_type="Declaración salarial",
                event_date=period_end, due_date=None,
                payload={"payroll_id": payroll.id, "period": period, "gross": line.gross},
                created_by=user.email, source_key=f"payroll:{payroll.id}:employee:{line.employee_id}:rei",
            )
    write_audit(db, user, "crear", "liquidacion_mensual", str(payroll.id), f"{company_id} / {period}")
    db.commit()
    return RedirectResponse(f"/app/payrolls/{payroll.id}", status_code=303)


@app.get("/app/payrolls/{payroll_id}", response_class=HTMLResponse)
def payroll_detail(request: Request, payroll_id: int, user: User = Depends(require_roles("administrador", "contador", "auxiliar", "empresa")), db: Session = Depends(get_db)):
    payroll = db.get(Payroll, payroll_id)
    if not payroll or payroll.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    lines = list(db.scalars(select(PayrollLine).where(PayrollLine.payroll_id == payroll.id).order_by(PayrollLine.id)))
    details = {item.payroll_line_id: item for item in db.scalars(select(PayrollComplianceDetail).where(PayrollComplianceDetail.payroll_line_id.in_([line.id for line in lines])))}
    return render(request, "payroll_detail.html", db, user, payroll=payroll, lines=lines, detail_by_line=details, ips_rate=get_parameter(db, "ips_employee_rate_general", 9))


@app.post("/app/payrolls/{payroll_id}/lines/{line_id}")
def update_payroll_line(
    payroll_id: int,
    line_id: int,
    base_salary: Annotated[int, Form()],
    overtime: Annotated[int, Form()] = 0,
    commissions: Annotated[int, Form()] = 0,
    bonuses: Annotated[int, Form()] = 0,
    other_income: Annotated[int, Form()] = 0,
    absences_discount: Annotated[int, Form()] = 0,
    advances: Annotated[int, Form()] = 0,
    other_discount: Annotated[int, Form()] = 0,
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    payroll = db.get(Payroll, payroll_id)
    line = db.get(PayrollLine, line_id)
    if not payroll or not line or line.payroll_id != payroll.id or payroll.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    if payroll.status == "Cerrada":
        raise HTTPException(409, "La liquidación está cerrada.")
    for attr, value in {
        "base_salary": base_salary,
        "overtime": overtime,
        "commissions": commissions,
        "bonuses": bonuses,
        "other_income": other_income,
        "absences_discount": absences_discount,
        "advances": advances,
        "other_discount": other_discount,
    }.items():
        setattr(line, attr, max(0, value))
    line.gross = line.base_salary + line.overtime + line.commissions + line.bonuses + line.other_income
    rate = get_parameter(db, "ips_employee_rate_general", 9) / 100
    line.ips_employee = round_gs(line.gross * rate) if line.employee.ips_contributor else 0
    line.total_discounts = line.ips_employee + line.absences_discount + line.advances + line.other_discount
    line.net = max(0, line.gross - line.total_discounts)
    recalculate_payroll(db, payroll)
    write_audit(db, user, "editar", "linea_liquidacion", str(line.id), line.employee.full_name)
    db.commit()
    return RedirectResponse(f"/app/payrolls/{payroll_id}", status_code=303)


@app.post("/app/payrolls/{payroll_id}/status")
def payroll_status(
    payroll_id: int,
    status_value: Annotated[str, Form(alias="status")],
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    payroll = db.get(Payroll, payroll_id)
    if not payroll or payroll.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    if status_value not in {"Borrador", "En revisión", "Cerrada"}:
        raise HTTPException(422, "Estado de nómina inválido.")
    # El cierre fija los importes de la liquidación. No se puede reabrir cambiando
    # un selector de estado; cualquier ajuste debe seguir un procedimiento explícito.
    if payroll.status == "Cerrada":
        if status_value == "Cerrada":
            return RedirectResponse(f"/app/payrolls/{payroll_id}", status_code=303)
        raise HTTPException(409, "La nómina está cerrada y no puede reabrirse desde este flujo.")
    if status_value == "Cerrada":
        from .calculator_routes import payroll_result
        lines = list(db.scalars(select(PayrollLine).where(PayrollLine.payroll_id == payroll.id)))
        if not lines:
            raise HTTPException(409, "La nómina no contiene funcionarios.")
        for line in lines:
            payroll_result(payroll, line)
        recalculate_payroll(db, payroll)
    payroll.status = status_value
    if status_value == "Cerrada":
        payroll.closed_at = datetime.now(UTC)
        payroll.reviewed_by = user.email
    write_audit(db, user, "actualizar_estado", "liquidacion_mensual", str(payroll.id), status_value)
    db.commit()
    return RedirectResponse(f"/app/payrolls/{payroll_id}", status_code=303)


@app.get("/app/vacations", response_class=HTMLResponse)
def vacations_page(
    request: Request,
    company_id: OptionalQueryId = None,
    employee_id: OptionalQueryId = None,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    company_ids = company_ids_for_user(db, user)
    selected_company_id, selected_employee_id = default_labor_context(
        request, db, user, company_ids, company_id, employee_id
    )
    employee_query = select(Employee).where(Employee.company_id.in_(company_ids), Employee.status == "Activo") if company_ids else select(Employee).where(False)
    vacation_query = select(Vacation).join(Employee).where(Employee.company_id.in_(company_ids)) if company_ids else select(Vacation).where(False)
    if selected_company_id:
        employee_query = employee_query.where(Employee.company_id == selected_company_id)
        vacation_query = vacation_query.where(Employee.company_id == selected_company_id)
    if selected_employee_id:
        vacation_query = vacation_query.where(Vacation.employee_id == selected_employee_id)
    employees = list(db.scalars(employee_query.order_by(Employee.full_name)))
    items = list(db.scalars(vacation_query.order_by(Vacation.created_at.desc())))
    companies = list(db.scalars(select(Company).where(Company.id.in_(company_ids)).order_by(Company.legal_name))) if company_ids else []
    filter_employees = list(db.scalars(select(Employee).where(Employee.company_id.in_(company_ids)).order_by(Employee.full_name))) if company_ids else []
    return render(request, "vacations.html", db, user, employees=employees, filter_employees=filter_employees,
                  companies=companies, items=items, selected_company_id=selected_company_id,
                  selected_employee_id=selected_employee_id)


@app.post("/app/vacations")
def create_vacation(
    employee_id: Annotated[int, Form()],
    period_year: Annotated[int, Form()],
    entitled_days: Annotated[int, Form()],
    used_days: Annotated[int, Form()] = 0,
    start_date: Annotated[date | None, Form()] = None,
    end_date: Annotated[date | None, Form()] = None,
    status_value: Annotated[str, Form(alias="status")] = "Pendiente",
    notes: Annotated[str, Form()] = "",
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    employee = db.get(Employee, employee_id)
    if not employee or employee.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    item = Vacation(employee_id=employee_id, period_year=period_year, entitled_days=max(0, entitled_days), used_days=max(0, used_days), start_date=start_date, end_date=end_date, status=status_value, notes=notes.strip())
    db.add(item)
    db.flush()
    if item.start_date:
        ensure_compliance_event(
            db, company_id=employee.company_id, employee_id=employee.id, branch_id=employee.branch_id, authority="REOP", event_type="Vacaciones",
            event_date=item.start_date, due_date=None,
            payload={"vacation_id": item.id, "period_year": item.period_year, "end_date": item.end_date.isoformat() if item.end_date else ""},
            created_by=user.email, source_key=f"vacation:{item.id}:reop",
        )
    write_audit(db, user, "crear", "vacaciones", str(item.id), employee.full_name)
    db.commit()
    return RedirectResponse("/app/vacations", status_code=303)


@app.get("/app/aguinaldo", response_class=HTMLResponse)
def aguinaldo_page(
    request: Request,
    company_id: OptionalQueryId = None,
    employee_id: OptionalQueryId = None,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    company_ids = company_ids_for_user(db, user)
    selected_company_id, selected_employee_id = default_labor_context(
        request, db, user, company_ids, company_id, employee_id
    )
    employee_query = select(Employee).where(Employee.company_id.in_(company_ids)) if company_ids else select(Employee).where(False)
    aguinaldo_query = select(Aguinaldo).join(Employee).where(Employee.company_id.in_(company_ids)) if company_ids else select(Aguinaldo).where(False)
    if selected_company_id:
        employee_query = employee_query.where(Employee.company_id == selected_company_id)
        aguinaldo_query = aguinaldo_query.where(Employee.company_id == selected_company_id)
    if selected_employee_id:
        aguinaldo_query = aguinaldo_query.where(Aguinaldo.employee_id == selected_employee_id)
    employees = list(db.scalars(employee_query.order_by(Employee.full_name)))
    items = list(db.scalars(aguinaldo_query.order_by(Aguinaldo.year.desc(), Aguinaldo.created_at.desc())))
    suggested_total = None
    suggestion_note = ""
    suggested_year = current_paraguay_date().year
    selected_employee = db.get(Employee, selected_employee_id) if selected_employee_id else None
    if selected_employee and selected_company_id and selected_employee.company_id == selected_company_id:
        coverage = _employee_annual_coverage(
            db, db.get(Company, selected_company_id), selected_employee, suggested_year, current_paraguay_date()
        )
        suggested_total = coverage["suggested_total"] if coverage["closed_count"] else None
        suggestion_note = (
            f"Propuesta automática para el ejercicio {suggested_year}: Gs. {format_gs(coverage['suggested_total'])} "
            f"de nóminas cerradas y consistentes; {coverage['closed_count']} de {coverage['expected_count']} "
            "periodos esperados cubiertos. Si no hay nóminas cerradas, el importe queda vacío. "
            "Verificá conceptos computables, ajustes y anticipos antes de aprobar."
        )
    companies = list(db.scalars(select(Company).where(Company.id.in_(company_ids)).order_by(Company.legal_name))) if company_ids else []
    filter_employees = list(db.scalars(select(Employee).where(Employee.company_id.in_(company_ids)).order_by(Employee.full_name))) if company_ids else []
    return render(request, "aguinaldo.html", db, user, employees=employees, filter_employees=filter_employees,
                  companies=companies, items=items, selected_company_id=selected_company_id,
                  selected_employee_id=selected_employee_id, suggested_total=suggested_total,
                  suggested_year=suggested_year, suggestion_note=suggestion_note)


@app.post("/app/aguinaldo")
def create_aguinaldo(
    request: Request,
    employee_id: Annotated[int, Form()],
    year: Annotated[int, Form()],
    total_remunerations: Annotated[int, Form()],
    notes: Annotated[str, Form()] = "",
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    employee = db.get(Employee, employee_id)
    if not employee or employee.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    if not 1900 <= year <= 2100:
        raise HTTPException(400, "El año del aguinaldo debe estar entre 1900 y 2100.")
    if not 0 <= total_remunerations <= 2147483647:
        raise HTTPException(400, "Las remuneraciones computables deben estar entre 0 y 2.147.483.647 Gs.")
    amount = round_gs(total_remunerations / 12)
    item = Aguinaldo(employee_id=employee_id, year=year, total_remunerations=total_remunerations, calculated_amount=amount, notes=notes.strip())
    db.add(item)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return RedirectResponse("/app/aguinaldo?duplicate=1", status_code=303)
    ensure_compliance_event(
        db, company_id=employee.company_id, employee_id=employee.id, branch_id=employee.branch_id, authority="REOP", event_type="Aguinaldo",
        event_date=date(year, 12, 31), due_date=None,
        payload={"aguinaldo_id": item.id, "year": year, "amount": amount},
        created_by=user.email, source_key=f"aguinaldo:{item.id}:reop",
    )
    write_audit(db, user, "crear", "aguinaldo", str(item.id), employee.full_name)
    db.commit()
    return RedirectResponse("/app/aguinaldo", status_code=303)



# Supplementary calculation operations: time entries, advances, employee actions and telegram drafts.
def _visible_labor_operation(db: Session, user: User, operation_id: int) -> LaborOperation:
    item = db.get(LaborOperation, operation_id)
    if not item or item.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404, "Registro no encontrado.")
    return item


def _labor_operation_query(
    db: Session,
    user: User,
    operation_type: str | None = None,
    company_id: int | None = None,
    employee_id: int | None = None,
):
    company_ids = company_ids_for_user(db, user)
    query = select(LaborOperation).where(LaborOperation.company_id.in_(company_ids)) if company_ids else select(LaborOperation).where(False)
    if operation_type:
        query = query.where(LaborOperation.operation_type == operation_type)
    if company_id:
        if company_id not in company_ids:
            raise HTTPException(404, "Empresa no encontrada.")
        query = query.where(LaborOperation.company_id == company_id)
    if employee_id:
        employee = db.get(Employee, employee_id)
        if not employee or employee.company_id not in company_ids:
            raise HTTPException(404, "Funcionario no encontrado.")
        query = query.where(LaborOperation.employee_id == employee_id)
    return query


def _validated_operation_context(db: Session, user: User, payload: dict) -> tuple[Company, Employee, dict]:
    if not isinstance(payload, dict):
        raise HTTPException(422, "El cuerpo de la operación debe ser un objeto JSON.")
    try:
        company_id = int(payload.get("company_id") or 0)
        employee_id = int(payload.get("employee_id") or 0)
    except (TypeError, ValueError):
        raise HTTPException(422, "Empresa y funcionario son obligatorios.") from None
    company = company_allowed(db, user, company_id)
    employee = db.get(Employee, employee_id)
    if not employee or employee.company_id != company.id:
        raise HTTPException(422, "El funcionario debe pertenecer a la empresa seleccionada.")
    try:
        values = validate_labor_operation(payload, today=current_paraguay_date())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return company, employee, values


def _save_labor_operation(
    db: Session,
    user: User,
    company: Company,
    employee: Employee,
    values: dict,
    item: LaborOperation | None = None,
) -> LaborOperation:
    if item is None:
        item = LaborOperation(
            company_id=company.id,
            employee_id=employee.id,
            operation_type=values["operation_type"],
            created_by=user.email,
        )
        db.add(item)
    elif item.company_id != company.id:
        raise HTTPException(400, "No se puede mover un registro entre empresas.")
    item.employee_id = employee.id
    item.operation_type = values["operation_type"]
    item.reference_code = values["reference_code"]
    item.title = values["title"]
    item.effective_date = values["effective_date"]
    item.end_date = values["end_date"]
    item.quantity = values["quantity"]
    item.amount = values["amount"]
    item.status = values["status"]
    item.payload_json = values["payload_json"]
    item.notes = values["notes"]
    db.flush()
    return item


def _operation_payload_from_model(item: LaborOperation) -> dict:
    values = operation_to_dict(item)
    return {
        **values,
        **(values.get("payload") or {}),
        "operation_type": item.operation_type,
        "company_id": item.company_id,
        "employee_id": item.employee_id,
        "title": item.title,
        "effective_date": item.effective_date.isoformat(),
        "end_date": item.end_date.isoformat() if item.end_date else "",
        "reference_code": item.reference_code or "",
        "quantity": float(item.quantity) if item.quantity is not None else "",
        "amount": item.amount if item.amount is not None else "",
        "status": item.status,
        "notes": item.notes or "",
    }


@app.get("/app/calculation-operations", response_class=HTMLResponse)
def calculation_operations_page(
    request: Request,
    tipo: str = "hours",
    company_id: OptionalQueryId = None,
    employee_id: OptionalQueryId = None,
    q: str = "",
    edit: int | None = None,
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    if tipo not in OPERATION_TYPES:
        raise HTTPException(404, "Submódulo no encontrado.")
    company_ids = company_ids_for_user(db, user)
    selected_company, selected_employee = default_labor_context(
        request, db, user, company_ids, company_id, employee_id
    )
    companies = list(db.scalars(select(Company).where(Company.id.in_(company_ids)).order_by(Company.legal_name))) if company_ids else []
    employee_query = select(Employee).where(Employee.company_id.in_(company_ids)) if company_ids else select(Employee).where(False)
    if selected_company:
        employee_query = employee_query.where(Employee.company_id == selected_company)
    employees = list(db.scalars(employee_query.order_by(Employee.full_name)))
    query = _labor_operation_query(db, user, tipo, selected_company, selected_employee)
    term = q.strip()[:120]
    if term:
        query = query.join(Employee, Employee.id == LaborOperation.employee_id).where(
            or_(
                LaborOperation.title.ilike(f"%{term}%"),
                LaborOperation.reference_code.ilike(f"%{term}%"),
                LaborOperation.notes.ilike(f"%{term}%"),
                Employee.full_name.ilike(f"%{term}%"),
            )
        )
    items = list(db.scalars(query.order_by(LaborOperation.effective_date.desc(), LaborOperation.created_at.desc()).limit(300)))
    editing = _visible_labor_operation(db, user, edit) if edit else None
    if editing and editing.operation_type != tipo:
        raise HTTPException(400, "El registro no pertenece al submódulo seleccionado.")
    editing_payload = _operation_payload_from_model(editing) if editing else {}
    selected_employee_obj = next((employee for employee in employees if employee.id == selected_employee), None)
    selected_company_obj = next((company for company in companies if company.id == selected_company), None)
    return render(
        request, "calculation_operations.html", db, user,
        companies=companies, employees=employees, items=items,
        selected_employee_obj=selected_employee_obj, selected_company_obj=selected_company_obj,
        selected_company=selected_company, selected_employee=selected_employee,
        selected_type=tipo, type_label=OPERATION_LABELS[tipo], status_options=OPERATION_STATUSES[tipo],
        editing=editing, editing_payload=editing_payload, search_term=term,
        today=current_paraguay_date(), format_gs=format_gs,
    )


@app.post("/app/calculation-operations")
def save_calculation_operation(
    request: Request,
    operation_type: Annotated[str, Form()],
    company_id: Annotated[int, Form()],
    employee_id: Annotated[int, Form()],
    effective_date: Annotated[date, Form()],
    title: Annotated[str, Form()],
    operation_id: Annotated[int | None, Form()] = None,
    reference_code: Annotated[str, Form()] = "",
    end_date: Annotated[date | None, Form()] = None,
    status_value: Annotated[str, Form(alias="status")] = "",
    notes: Annotated[str, Form()] = "",
    regular_hours: Annotated[str, Form()] = "",
    overtime_hours: Annotated[str, Form()] = "",
    salary_reference: Annotated[str, Form()] = "",
    monthly_hours: Annotated[str, Form()] = "240",
    multiplier: Annotated[str, Form()] = "1.5",
    amount: Annotated[str, Form()] = "",
    deduction_period: Annotated[str, Form()] = "",
    payment_method: Annotated[str, Form()] = "",
    subtype: Annotated[str, Form()] = "",
    reason: Annotated[str, Form()] = "",
    authorized_by: Annotated[str, Form()] = "",
    quantity: Annotated[str, Form()] = "",
    recipient: Annotated[str, Form()] = "",
    recipient_document: Annotated[str, Form()] = "",
    recipient_address: Annotated[str, Form()] = "",
    sender: Annotated[str, Form()] = "",
    body: Annotated[str, Form()] = "",
    legal_review: Annotated[str, Form()] = "",
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    payload = {
        "operation_type": operation_type, "company_id": company_id, "employee_id": employee_id,
        "effective_date": effective_date, "end_date": end_date, "title": title,
        "reference_code": reference_code, "status": status_value or None, "notes": notes,
        "regular_hours": regular_hours, "overtime_hours": overtime_hours,
        "salary_reference": salary_reference, "monthly_hours": monthly_hours, "multiplier": multiplier,
        "amount": amount, "deduction_period": deduction_period, "payment_method": payment_method,
        "subtype": subtype, "reason": reason, "authorized_by": authorized_by, "quantity": quantity,
        "recipient": recipient, "recipient_document": recipient_document,
        "recipient_address": recipient_address, "sender": sender, "body": body, "legal_review": legal_review,
    }
    company, employee, values = _validated_operation_context(db, user, payload)
    item = _visible_labor_operation(db, user, operation_id) if operation_id else None
    if item and item.operation_type != operation_type:
        raise HTTPException(400, "No se puede cambiar el tipo de un registro existente.")
    item = _save_labor_operation(db, user, company, employee, values, item)
    write_audit(db, user, "actualizar" if operation_id else "crear", "operacion_laboral", str(item.id),
                f"{OPERATION_LABELS[operation_type]} · {employee.full_name}")
    db.commit()
    return RedirectResponse(f"/app/calculation-operations?tipo={quote(operation_type)}&{'updated' if operation_id else 'saved'}={item.id}&company_id={company.id}&employee_id={employee.id}", status_code=303)


@app.post("/app/calculation-operations/{operation_id}/status")
def update_calculation_operation_status(
    operation_id: int,
    status_value: Annotated[str, Form(alias="status")],
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    item = _visible_labor_operation(db, user, operation_id)
    if status_value not in OPERATION_STATUSES.get(item.operation_type, ()):
        raise HTTPException(422, "Estado no válido para este submódulo.")
    item.status = status_value
    write_audit(db, user, "actualizar_estado", "operacion_laboral", str(item.id), status_value)
    db.commit()
    return RedirectResponse(f"/app/calculation-operations?tipo={quote(item.operation_type)}&company_id={item.company_id}&employee_id={item.employee_id}", status_code=303)


@app.post("/app/calculation-operations/{operation_id}/delete")
def delete_calculation_operation(
    operation_id: int,
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    item = _visible_labor_operation(db, user, operation_id)
    if item.status in {"Aprobado", "Descontado", "Enviado"}:
        raise HTTPException(409, "El registro ya fue finalizado. Cambiá su estado a Anulado para conservar la trazabilidad.")
    item.status = "Anulado"
    write_audit(db, user, "anular", "operacion_laboral", str(item.id), item.title)
    db.commit()
    return RedirectResponse(f"/app/calculation-operations?tipo={quote(item.operation_type)}&company_id={item.company_id}&employee_id={item.employee_id}&deleted=1", status_code=303)


@app.get("/app/calculation-operations/export.csv")
def export_calculation_operations(
    tipo: str = "hours",
    company_id: OptionalQueryId = None,
    employee_id: OptionalQueryId = None,
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    if tipo not in OPERATION_TYPES:
        raise HTTPException(404, "Submódulo no encontrado.")
    query = _labor_operation_query(db, user, tipo, company_id, employee_id)
    items = list(db.scalars(query.order_by(LaborOperation.effective_date.desc()).limit(10000)))
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Código", "Empresa", "Funcionario", "Submódulo", "Concepto", "Fecha", "Fecha fin", "Cantidad", "Importe Gs.", "Estado", "Observaciones"])
    for item in items:
        writer.writerow([
            item.reference_code or item.id, item.company.legal_name, item.employee.full_name,
            OPERATION_LABELS[item.operation_type], item.title, item.effective_date.isoformat(),
            item.end_date.isoformat() if item.end_date else "", float(item.quantity) if item.quantity is not None else "",
            item.amount if item.amount is not None else "", item.status, item.notes,
        ])
    filename = f"digit-laboral-{tipo}-{current_paraguay_date().isoformat()}.csv"
    return Response(content="\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/app/calculation-operations/{operation_id}/print", response_class=HTMLResponse)
def print_labour_telegram(
    operation_id: int,
    request: Request,
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    item = _visible_labor_operation(db, user, operation_id)
    if item.operation_type != "telegram":
        raise HTTPException(404, "Solo los telegramas tienen vista imprimible.")
    operation = operation_to_dict(item)
    return render(request, "telegram_print.html", db, user, item=item, operation=operation,
                  company=item.company, employee=item.employee, payload=operation.get("payload") or {})


@app.get("/api/labor-operations")
def api_list_labor_operations(
    tipo: str | None = None,
    company_id: int | None = None,
    employee_id: int | None = None,
    limit: int = 100,
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    if tipo and tipo not in OPERATION_TYPES:
        raise HTTPException(422, "Tipo de operación no válido.")
    if limit < 1 or limit > 500:
        raise HTTPException(422, "El límite debe estar entre 1 y 500.")
    query = _labor_operation_query(db, user, tipo, company_id, employee_id)
    items = list(db.scalars(query.order_by(LaborOperation.created_at.desc()).limit(limit)))
    results = []
    for item in items:
        data = operation_to_dict(item)
        data["company_name"] = item.company.legal_name
        data["employee_name"] = item.employee.full_name
        results.append(data)
    return {"items": results, "count": len(results), "limit": limit}


@app.get("/api/labor-operations/{operation_id}")
def api_get_labor_operation(
    operation_id: int,
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    item = _visible_labor_operation(db, user, operation_id)
    data = operation_to_dict(item)
    data["company_name"] = item.company.legal_name
    data["employee_name"] = item.employee.full_name
    return data


@app.post("/api/labor-operations", status_code=201)
async def api_create_labor_operation(
    request: Request,
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Se esperaba un cuerpo JSON válido.") from None
    company, employee, values = _validated_operation_context(db, user, payload)
    item = _save_labor_operation(db, user, company, employee, values)
    write_audit(db, user, "crear_api", "operacion_laboral", str(item.id), item.title)
    db.commit()
    db.refresh(item)
    result = operation_to_dict(item)
    result["company_name"] = company.legal_name
    result["employee_name"] = employee.full_name
    return JSONResponse(result, status_code=201)


@app.patch("/api/labor-operations/{operation_id}")
async def api_update_labor_operation(
    operation_id: int,
    request: Request,
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    item = _visible_labor_operation(db, user, operation_id)
    try:
        incoming = await request.json()
    except Exception:
        raise HTTPException(400, "Se esperaba un cuerpo JSON válido.") from None
    if not isinstance(incoming, dict):
        raise HTTPException(422, "El cuerpo debe ser un objeto JSON.")
    payload = _operation_payload_from_model(item)
    payload.update(incoming)
    payload["operation_type"] = item.operation_type
    company, employee, values = _validated_operation_context(db, user, payload)
    item = _save_labor_operation(db, user, company, employee, values, item)
    write_audit(db, user, "actualizar_api", "operacion_laboral", str(item.id), item.title)
    db.commit()
    db.refresh(item)
    result = operation_to_dict(item)
    result["company_name"] = company.legal_name
    result["employee_name"] = employee.full_name
    return result


@app.delete("/api/labor-operations/{operation_id}", status_code=204)
def api_delete_labor_operation(
    operation_id: int,
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    item = _visible_labor_operation(db, user, operation_id)
    if item.status in {"Aprobado", "Descontado", "Enviado"}:
        raise HTTPException(409, "El registro ya fue finalizado; anulalo para conservar trazabilidad.")
    item.status = "Anulado"
    write_audit(db, user, "anular_api", "operacion_laboral", str(item.id), item.title)
    db.commit()
    return Response(status_code=204)


@app.get("/app/employee-history", response_class=HTMLResponse)
def employee_history_page(
    request: Request,
    company_id: OptionalQueryId = None,
    employee_id: OptionalQueryId = None,
    q: str = "",
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    company_ids = company_ids_for_user(db, user)
    selected_company, selected_employee = default_labor_context(
        request, db, user, company_ids, company_id, employee_id
    )
    companies = list(db.scalars(select(Company).where(Company.id.in_(company_ids)).order_by(Company.legal_name))) if company_ids else []
    query = select(Employee).where(Employee.company_id.in_(company_ids)) if company_ids else select(Employee).where(False)
    if selected_company:
        query = query.where(Employee.company_id == selected_company)
    term = q.strip()[:120]
    if term:
        query = query.where(or_(Employee.full_name.ilike(f"%{term}%"), Employee.document_number.ilike(f"%{term}%")))
    employees = list(db.scalars(query.order_by(Employee.full_name).limit(500)))
    selected = db.get(Employee, selected_employee) if selected_employee else None
    if selected and selected.company_id not in company_ids:
        raise HTTPException(404, "Funcionario no encontrado.")
    if selected and selected_company and selected.company_id != selected_company:
        raise HTTPException(400, "El funcionario no pertenece a la empresa seleccionada.")
    history = {}
    if selected:
        history = {
            "events": list(db.scalars(select(EmployeeEvent).where(EmployeeEvent.employee_id == selected.id).order_by(EmployeeEvent.effective_date.desc(), EmployeeEvent.created_at.desc()).limit(100))),
            "salary_history": list(db.scalars(select(SalaryHistory).where(SalaryHistory.employee_id == selected.id).order_by(SalaryHistory.effective_from.desc()).limit(100))),
            "calculations": list(db.scalars(select(CalculationRecord).where(CalculationRecord.employee_id == selected.id).order_by(CalculationRecord.created_at.desc()).limit(100))),
            "operations": list(db.scalars(select(LaborOperation).where(LaborOperation.employee_id == selected.id).order_by(LaborOperation.effective_date.desc()).limit(100))),
            "vacations": list(db.scalars(select(Vacation).where(Vacation.employee_id == selected.id).order_by(Vacation.period_year.desc()).limit(100))),
            "aguinaldos": list(db.scalars(select(Aguinaldo).where(Aguinaldo.employee_id == selected.id).order_by(Aguinaldo.year.desc()).limit(100))),
            "medical_exams": (
                list(db.scalars(select(MedicalExam).where(MedicalExam.employee_id == selected.id).order_by(MedicalExam.exam_date.desc()).limit(100)))
                if user.role in {"administrador", "contador"} else []
            ),
            "payroll_lines": list(db.scalars(select(PayrollLine).where(PayrollLine.employee_id == selected.id).order_by(PayrollLine.id.desc()).limit(100))),
        }
    return render(request, "employee_history.html", db, user, companies=companies, employees=employees,
                  selected_company=selected_company, selected_employee=selected.id if selected else None,
                  selected=selected, history=history, search_term=term, format_gs=format_gs)


@app.get("/app/documents", response_class=HTMLResponse)
def documents_page(
    request: Request,
    company_id: OptionalQueryId = None,
    employee_id: OptionalQueryId = None,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    company_ids = company_ids_for_user(db, user)
    selected_company_id, selected_employee_id = default_labor_context(
        request, db, user, company_ids, company_id, employee_id
    )
    company_query = select(Company).where(Company.id.in_(company_ids)) if company_ids else select(Company).where(False)
    employee_query = select(Employee).where(Employee.company_id.in_(company_ids)) if company_ids else select(Employee).where(False)
    document_query = select(Document).where(Document.company_id.in_(company_ids)) if company_ids else select(Document).where(False)
    if selected_company_id:
        company_query = company_query.where(Company.id == selected_company_id)
        employee_query = employee_query.where(Employee.company_id == selected_company_id)
        document_query = document_query.where(Document.company_id == selected_company_id)
    if selected_employee_id:
        document_query = document_query.where(
            or_(Document.employee_id == selected_employee_id, Document.employee_id.is_(None))
        )
    companies = list(db.scalars(company_query.order_by(Company.legal_name)))
    employees = list(db.scalars(employee_query.order_by(Employee.full_name)))
    documents = list(db.scalars(document_query.order_by(Document.created_at.desc())))
    filter_employees = list(db.scalars(select(Employee).where(Employee.company_id.in_(company_ids)).order_by(Employee.full_name))) if company_ids else []
    all_companies = list(db.scalars(select(Company).where(Company.id.in_(company_ids)).order_by(Company.legal_name))) if company_ids else []
    return render(request, "documents.html", db, user, companies=all_companies, employees=employees,
                  filter_employees=filter_employees, documents=documents,
                  selected_company_id=selected_company_id, selected_employee_id=selected_employee_id)


@app.post("/app/documents")
async def upload_document(
    request: Request,
    company_id: Annotated[int, Form()],
    title: Annotated[str, Form()],
    category: Annotated[str, Form()] = "General",
    employee_id: Annotated[int | None, Form()] = None,
    file: UploadFile = File(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    company_allowed(db, user, company_id)
    if file.content_type not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(400, "Formato no permitido.")
    content = await file.read(MAX_UPLOAD_SIZE + 1)
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(413, "El archivo supera 10 MB.")
    if employee_id:
        employee = db.get(Employee, employee_id)
        if not employee or employee.company_id != company_id:
            raise HTTPException(400, "Funcionario inválido.")
    original = safe_filename(file.filename or "archivo")
    stored = f"documents/{company_id}/{uuid.uuid4().hex}_{original}"
    storage.put(stored, content, file.content_type or "application/octet-stream")
    document = Document(
        company_id=company_id,
        employee_id=employee_id or None,
        category=category.strip(),
        title=title.strip(),
        stored_name=stored,
        original_name=original,
        content_type=file.content_type or "application/octet-stream",
        # Keep new local uploads recoverable if the deployment filesystem is replaced.
        content_bytes=content if settings.storage_backend == "local" else None,
        uploaded_by=user.email,
    )
    db.add(document)
    db.flush()
    write_audit(db, user, "subir", "documento", str(document.id), original)
    db.commit()
    return RedirectResponse("/app/documents", status_code=303)


@app.get("/app/documents/{document_id}/download")
def download_document(document_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document or document.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    if document.content_bytes is not None:
        # Official certificate originals use PostgreSQL as a durable fallback when
        # the deployment's local filesystem is ephemeral.
        content = bytes(document.content_bytes)
    elif storage.exists(document.stored_name):
        content = storage.get(document.stored_name)
    else:
        legacy = UPLOAD_DIR / document.stored_name
        if not legacy.exists():
            raise HTTPException(404, "Archivo no disponible.")
        content = legacy.read_bytes()
    write_audit(db, user, "descargar", "documento", str(document.id), document.original_name)
    db.commit()
    return StreamingResponse(io.BytesIO(content), media_type=document.content_type, headers={"Content-Disposition": f'attachment; filename="{document.original_name}"'})


@app.get("/app/security", response_class=HTMLResponse)
def security_page(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    security = get_or_create_security(db, user)
    pending_secret = request.session.get("pending_totp_secret", "")
    recent_events = list(db.scalars(select(SecurityEvent).where(SecurityEvent.user_id == user.id).order_by(SecurityEvent.created_at.desc()).limit(25)))
    db.commit()
    return render(request, "security.html", db, user, security=security, pending_secret=pending_secret, recent_events=recent_events)


@app.post("/app/security/2fa/start")
def security_2fa_start(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    security = get_or_create_security(db, user)
    if security.totp_enabled:
        return RedirectResponse("/app/security?already=1", status_code=303)
    request.session["pending_totp_secret"] = build_totp_secret()
    return RedirectResponse("/app/security?setup=1", status_code=303)


@app.get("/app/security/2fa/qr")
def security_2fa_qr(request: Request, user: User = Depends(require_user)):
    secret = request.session.get("pending_totp_secret", "")
    if not secret:
        raise HTTPException(404)
    return Response(build_totp_qr_svg(user, secret), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


@app.post("/app/security/2fa/confirm")
def security_2fa_confirm(
    request: Request, code: Annotated[str, Form()], user: User = Depends(require_user), db: Session = Depends(get_db),
):
    secret = request.session.get("pending_totp_secret", "")
    if security_rate_limited(
        db, request, event_types=("activar_2fa",), limit=10, minutes=15, failures_only=True
    ):
        return RedirectResponse("/app/security?invalid_code=1", status_code=303)
    if not secret or not verify_totp(secret, code):
        write_security_event(db, request, "activar_2fa", False, user=user, detail="Código de activación TOTP inválido")
        db.commit()
        return RedirectResponse("/app/security?invalid_code=1", status_code=303)
    security = get_or_create_security(db, user)
    security.totp_secret = secret
    security.totp_enabled = True
    security.session_version += 1
    request.session["security_version"] = security.session_version
    request.session.pop("pending_totp_secret", None)
    write_audit(db, user, "activar", "doble_factor", str(user.id))
    write_security_event(db, request, "activar_2fa", True, user=user)
    db.commit()
    return RedirectResponse("/app/security?enabled=1", status_code=303)


@app.post("/app/security/2fa/disable")
def security_2fa_disable(
    request: Request, password: Annotated[str, Form()], code: Annotated[str, Form()],
    user: User = Depends(require_user), db: Session = Depends(get_db),
):
    if security_rate_limited(
        db, request, event_types=("desactivar_2fa",), limit=10, minutes=15, failures_only=True
    ):
        return RedirectResponse("/app/security?disable_error=1", status_code=303)
    security = get_or_create_security(db, user)
    if not verify_password(password, user.password_hash) or not verify_totp(security.totp_secret, code):
        write_security_event(db, request, "desactivar_2fa", False, user=user, detail="Contraseña o código TOTP incorrecto")
        db.commit()
        return RedirectResponse("/app/security?disable_error=1", status_code=303)
    security.totp_enabled = False
    security.totp_secret = ""
    security.session_version += 1
    request.session["security_version"] = security.session_version
    write_audit(db, user, "desactivar", "doble_factor", str(user.id))
    write_security_event(db, request, "desactivar_2fa", True, user=user)
    db.commit()
    return RedirectResponse("/app/security?disabled=1", status_code=303)


@app.post("/app/security/password")
def security_change_password(
    request: Request, current_password: Annotated[str, Form()], new_password: Annotated[str, Form()],
    new_password_confirm: Annotated[str, Form()], user: User = Depends(require_user), db: Session = Depends(get_db),
):
    if security_rate_limited(
        db, request, event_types=("cambio_contrasena",), limit=10, minutes=15, failures_only=True
    ):
        return RedirectResponse("/app/security?password_error=current", status_code=303)
    if not verify_password(current_password, user.password_hash):
        write_security_event(db, request, "cambio_contrasena", False, user=user, detail="Contraseña actual incorrecta")
        db.commit()
        return RedirectResponse("/app/security?password_error=current", status_code=303)
    if new_password != new_password_confirm:
        return RedirectResponse("/app/security?password_error=match", status_code=303)
    error = password_strength_error(new_password)
    if error:
        return RedirectResponse(f"/app/security?password_error={quote(error)}", status_code=303)
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    security = get_or_create_security(db, user)
    security.password_changed_at = datetime.now(UTC)
    security.session_version += 1
    request.session["security_version"] = security.session_version
    write_audit(db, user, "cambiar", "contrasena", str(user.id))
    write_security_event(db, request, "cambio_contrasena", True, user=user)
    db.commit()
    return RedirectResponse("/app/security?password_changed=1", status_code=303)


@app.post("/app/security/logout-all")
def security_logout_all(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    security = get_or_create_security(db, user)
    security.session_version += 1
    write_audit(db, user, "cerrar", "todas_sesiones", str(user.id))
    write_security_event(db, request, "cerrar_todas_sesiones", True, user=user)
    db.commit()
    request.session.clear()
    return RedirectResponse("/login?logged_out_all=1", status_code=303)


@app.get("/app/users", response_class=HTMLResponse)
def users_page(request: Request, user: User = Depends(require_roles("administrador")), db: Session = Depends(get_db)):
    users = list(db.scalars(select(User).where(User.studio_id == user.studio_id).order_by(User.full_name)))
    companies = list(db.scalars(select(Company).where(Company.studio_id == user.studio_id).order_by(Company.legal_name)))
    securities = list(db.scalars(select(UserSecurity).where(UserSecurity.user_id.in_([item.id for item in users])))) if users else []
    security_by_user = {item.user_id: item for item in securities}
    return render(request, "users.html", db, user, users=users, companies=companies, security_by_user=security_by_user)


@app.post("/app/users")
def create_user(
    full_name: Annotated[str, Form()],
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    role: Annotated[str, Form()],
    company_id: Annotated[str, Form()] = "",
    user: User = Depends(require_roles("administrador")),
    db: Session = Depends(get_db),
):
    parsed_company_id = optional_int(company_id, field="empresa vinculada")
    full_name = clean_text(full_name, max_length=160, required=True, field="nombre completo")
    email = clean_text(email, max_length=180, required=True, field="correo").lower()
    strength_error = password_strength_error(password)
    if strength_error:
        return RedirectResponse(f"/app/users?password_error={quote(strength_error)}", status_code=303)
    if role not in {"administrador", "contador", "auxiliar", "empresa", "abogado"}:
        return RedirectResponse("/app/users?role_error=1", status_code=303)
    if role == "empresa" and not parsed_company_id:
        return RedirectResponse("/app/users?company_required=1", status_code=303)
    if parsed_company_id:
        company_allowed(db, user, parsed_company_id)
    item = User(studio_id=user.studio_id, company_id=parsed_company_id if role == "empresa" else None, full_name=full_name, email=email, password_hash=hash_password(password), role=role, must_change_password=True)
    db.add(item)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return RedirectResponse("/app/users?duplicate=1", status_code=303)
    get_or_create_security(db, item)
    write_audit(db, user, "crear", "usuario", str(item.id), item.email)
    db.commit()
    return RedirectResponse("/app/users", status_code=303)


@app.post("/app/users/{user_id}/toggle")
def toggle_user(user_id: int, user: User = Depends(require_roles("administrador")), db: Session = Depends(get_db)):
    item = db.get(User, user_id)
    if not item or item.studio_id != user.studio_id or item.id == user.id:
        raise HTTPException(400)
    item.active = not item.active
    write_audit(db, user, "activar" if item.active else "desactivar", "usuario", str(item.id), item.email)
    security = get_or_create_security(db, item)
    security.session_version += 1
    db.commit()
    return RedirectResponse("/app/users", status_code=303)


@app.post("/app/users/{user_id}/logout-all")
def admin_logout_user_sessions(user_id: int, user: User = Depends(require_roles("administrador")), db: Session = Depends(get_db)):
    item = db.get(User, user_id)
    if not item or item.studio_id != user.studio_id:
        raise HTTPException(404)
    security = get_or_create_security(db, item)
    security.session_version += 1
    write_audit(db, user, "cerrar", "sesiones_usuario", str(item.id), item.email)
    db.commit()
    return RedirectResponse("/app/users?logout_all=1", status_code=303)


@app.post("/app/users/{user_id}/reset-2fa")
def admin_reset_user_2fa(user_id: int, user: User = Depends(require_roles("administrador")), db: Session = Depends(get_db)):
    item = db.get(User, user_id)
    if not item or item.studio_id != user.studio_id:
        raise HTTPException(404)
    security = get_or_create_security(db, item)
    security.totp_enabled = False
    security.totp_secret = ""
    security.session_version += 1
    write_audit(db, user, "restablecer", "doble_factor", str(item.id), item.email)
    db.commit()
    return RedirectResponse("/app/users?reset_2fa=1", status_code=303)


def _labor_hierarchy(article: LaborArticle) -> dict[str, str]:
    codes = (article.category or "").split("|")
    names = (article.heading or "").split("|")
    codes += [""] * (3 - len(codes))
    names += [""] * (3 - len(names))
    return {
        "book_code": codes[0], "title_code": codes[1], "chapter_code": codes[2],
        "book_name": names[0], "title_name": names[1], "chapter_name": names[2],
    }


def _labor_article_view(article: LaborArticle) -> dict:
    hierarchy = _labor_hierarchy(article)
    status_norm = normalize_search(article.content_status)
    return {
        "id": article.id, "number": article.article_number, "body": article.body,
        "law_number": article.law_number, "content_status": article.content_status,
        "amendment_note": article.amendment_note, "source_name": article.source_name,
        "source_url": article.source_url, "reviewed_at": article.reviewed_at,
        "is_repealed": "derogad" in status_norm,
        "is_modified": "modific" in status_norm or "derogacion parcial" in status_norm,
        "heading": hierarchy["chapter_name"] or hierarchy["title_name"] or hierarchy["book_name"],
        **hierarchy,
    }


def _labor_outline(items: list[dict]) -> list[dict]:
    books: OrderedDict[str, dict] = OrderedDict()
    for item in items:
        number = item["number"]
        book = books.setdefault(item["book_code"] or "SIN LIBRO", {
            "code": item["book_code"], "name": item["book_name"] or "Disposiciones sin clasificación",
            "count": 0, "titles": OrderedDict(), "start_number": number, "end_number": number,
        })
        book["count"] += 1
        book["end_number"] = number
        title = book["titles"].setdefault(item["title_code"] or "SIN TITULO", {
            "code": item["title_code"], "name": item["title_name"] or "Sin título",
            "count": 0, "chapters": OrderedDict(), "start_number": number, "end_number": number,
        })
        title["count"] += 1
        title["end_number"] = number
        chapter = title["chapters"].setdefault(item["chapter_code"] or "SIN CAPITULO", {
            "code": item["chapter_code"], "name": item["chapter_name"] or "Sin capítulo", "count": 0,
            "start_number": number, "end_number": number,
        })
        chapter["count"] += 1
        chapter["end_number"] = number
    result = []
    for book in books.values():
        book["titles"] = [{**title, "chapters": list(title["chapters"].values())} for title in book["titles"].values()]
        result.append(book)
    return result



@app.get("/app/compliance", response_class=HTMLResponse)
def compliance_page(
    request: Request,
    company_id: OptionalQueryId = None,
    authority: str = "",
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    company_ids = company_ids_for_user(db, user)
    companies = list(db.scalars(select(Company).where(Company.id.in_(company_ids)).order_by(Company.legal_name))) if company_ids else []
    selected_company = None
    if company_id:
        selected_company = company_allowed(db, user, company_id)
    elif companies:
        selected_company = companies[0]
    employees: list[Employee] = []
    branches: list[Branch] = []
    company_profile = None
    branch_profiles: dict[int, BranchComplianceProfile] = {}
    employee_profiles: dict[int, EmployeeComplianceProfile] = {}
    events: list[ComplianceEvent] = []
    batches: list[IntegrationBatch] = []
    batch_receipt_available: dict[int, bool] = {}
    rei_errors: list[str] = []
    reop_errors: list[str] = []
    if selected_company:
        employees = list(db.scalars(select(Employee).where(Employee.company_id == selected_company.id).order_by(Employee.full_name)))
        branches = list(db.scalars(select(Branch).where(Branch.company_id == selected_company.id).order_by(Branch.name)))
        company_profile = db.scalar(select(CompanyComplianceProfile).where(CompanyComplianceProfile.company_id == selected_company.id))
        branch_profile_rows = list(
            db.scalars(
                select(BranchComplianceProfile)
                .join(Branch, Branch.id == BranchComplianceProfile.branch_id)
                .where(Branch.company_id == selected_company.id)
            )
        )
        branch_profiles = {item.branch_id: item for item in branch_profile_rows}
        profiles = list(
            db.scalars(
                select(EmployeeComplianceProfile)
                .join(Employee, Employee.id == EmployeeComplianceProfile.employee_id)
                .where(Employee.company_id == selected_company.id)
            )
        )
        employee_profiles = {item.employee_id: item for item in profiles}
        event_query = select(ComplianceEvent).where(ComplianceEvent.company_id == selected_company.id)
        if authority.upper() in {"REI", "REOP"}:
            event_query = event_query.where(ComplianceEvent.authority == authority.upper())
        events = list(db.scalars(event_query.order_by(ComplianceEvent.created_at.desc()).limit(100)))
        batches = list(
            db.scalars(
                select(IntegrationBatch)
                .where(IntegrationBatch.company_id == selected_company.id)
                .order_by(IntegrationBatch.created_at.desc())
                .limit(40)
            )
        )
        if batches:
            batch_ids = [item.id for item in batches]
            linked_receipts: dict[int, list[str]] = {}
            for event in db.scalars(
                select(ComplianceEvent).where(
                    ComplianceEvent.batch_id.in_(batch_ids),
                    ComplianceEvent.receipt_storage_key != "",
                )
            ):
                linked_receipts.setdefault(event.batch_id, []).append(event.receipt_storage_key)
            receipt_extensions = ("pdf", "png", "jpg")
            for batch in batches:
                deterministic_keys = [
                    f"integrations/{batch.company_id}/receipts/batch-{batch.id}.{extension}"
                    for extension in receipt_extensions
                ]
                legacy_keys = linked_receipts.get(batch.id, [])
                candidate_keys = (batch.receipt_storage_key, *deterministic_keys, *legacy_keys)
                batch_receipt_available[batch.id] = (
                    batch.receipt_bytes is not None
                    or any(storage.exists(key) for key in candidate_keys if key)
                )
        rei_errors = validate_company_for_authority(db, selected_company, "REI")
        reop_errors = validate_company_for_authority(db, selected_company, "REOP")
    pending = sum(item.status in {"Borrador", "Validado", "Exportado", "Observado"} for item in events)
    overdue = sum(bool(item.due_date and item.due_date < date.today() and item.status not in {"Presentado", "Aceptado", "Anulado"}) for item in events)
    return render(
        request,
        "compliance.html",
        db,
        user,
        companies=companies,
        selected_company=selected_company,
        company_profile=company_profile,
        branches=branches,
        branch_profiles=branch_profiles,
        employees=employees,
        employee_profiles=employee_profiles,
        events=events,
        batches=batches,
        batch_receipt_available=batch_receipt_available,
        authority_filter=authority.upper(),
        rei_errors=rei_errors,
        reop_errors=reop_errors,
        pending=pending,
        overdue=overdue,
        rei_event_types=sorted(REI_EVENT_TYPES),
        reop_event_types=sorted(REOP_EVENT_TYPES),
        official_sources=OFFICIAL_SOURCES,
        direct_rei=settings.rei_direct_enabled,
        direct_reop=settings.reop_direct_enabled,
        storage_backend=settings.storage_backend,
        compliance_status_transitions={key: sorted(value) for key, value in COMPLIANCE_STATUS_TRANSITIONS.items()},
        integration_batch_transitions={key: sorted(value) for key, value in INTEGRATION_BATCH_STATUS_TRANSITIONS.items()},
        compliance_dual_approval=settings.compliance_dual_approval,
    )


@app.post("/app/compliance/company-profile")
def update_company_compliance_profile(
    company_id: Annotated[int, Form()],
    department: Annotated[str, Form()] = "",
    district: Annotated[str, Form()] = "",
    locality: Annotated[str, Form()] = "",
    economic_activity: Annotated[str, Form()] = "",
    activity_code: Annotated[str, Form()] = "",
    establishment_type: Annotated[str, Form()] = "Matriz",
    legal_representative_document: Annotated[str, Form()] = "",
    rei_status: Annotated[str, Form()] = "Pendiente",
    reop_status: Annotated[str, Form()] = "Pendiente",
    notes: Annotated[str, Form()] = "",
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    company = company_allowed(db, user, company_id)
    profile = db.scalar(select(CompanyComplianceProfile).where(CompanyComplianceProfile.company_id == company.id))
    if not profile:
        profile = CompanyComplianceProfile(company_id=company.id)
        db.add(profile)
    profile.department = clean_text(department, max_length=100)
    profile.district = clean_text(district, max_length=100)
    profile.locality = clean_text(locality, max_length=120)
    profile.economic_activity = clean_text(economic_activity, max_length=220)
    profile.activity_code = clean_text(activity_code, max_length=60)
    profile.establishment_type = establishment_type if establishment_type in {"Matriz", "Sucursal"} else "Matriz"
    profile.legal_representative_document = clean_text(legal_representative_document, max_length=40)
    profile.rei_status = rei_status if rei_status in {"Pendiente", "Verificado", "Observado"} else "Pendiente"
    profile.reop_status = reop_status if reop_status in {"Pendiente", "Verificado", "Observado"} else "Pendiente"
    profile.notes = clean_text(notes, max_length=2000)
    if profile.rei_status == "Verificado":
        profile.rei_last_verified_at = datetime.now(UTC)
    if profile.reop_status == "Verificado":
        profile.reop_last_verified_at = datetime.now(UTC)
    write_audit(db, user, "actualizar", "perfil_cumplimiento_empresa", str(company.id))
    db.commit()
    return RedirectResponse(f"/app/compliance?company_id={company.id}&saved=company", status_code=303)


@app.post("/app/compliance/branch-profile")
def update_branch_compliance_profile(
    company_id: Annotated[int, Form()],
    branch_id: Annotated[int, Form()],
    ips_employer_number: Annotated[str, Form()] = "",
    mtess_employer_number: Annotated[str, Form()] = "",
    department: Annotated[str, Form()] = "",
    district: Annotated[str, Form()] = "",
    locality: Annotated[str, Form()] = "",
    economic_activity: Annotated[str, Form()] = "",
    activity_code: Annotated[str, Form()] = "",
    establishment_type: Annotated[str, Form()] = "Sucursal",
    rei_status: Annotated[str, Form()] = "Pendiente",
    reop_status: Annotated[str, Form()] = "Pendiente",
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    company = company_allowed(db, user, company_id)
    branch = db.get(Branch, branch_id)
    if not branch or branch.company_id != company.id:
        raise HTTPException(404, "Sucursal no encontrada.")
    profile = db.scalar(select(BranchComplianceProfile).where(BranchComplianceProfile.branch_id == branch.id))
    if not profile:
        profile = BranchComplianceProfile(branch_id=branch.id)
        db.add(profile)
    profile.ips_employer_number = clean_text(ips_employer_number, max_length=80)
    profile.mtess_employer_number = clean_text(mtess_employer_number, max_length=80)
    profile.department = clean_text(department, max_length=100)
    profile.district = clean_text(district, max_length=100)
    profile.locality = clean_text(locality, max_length=120)
    profile.economic_activity = clean_text(economic_activity, max_length=220)
    profile.activity_code = clean_text(activity_code, max_length=60)
    profile.establishment_type = establishment_type if establishment_type in {"Sucursal", "Agencia", "Depósito", "Obra", "Otro"} else "Sucursal"
    profile.rei_status = rei_status if rei_status in {"Pendiente", "Verificado", "Observado"} else "Pendiente"
    profile.reop_status = reop_status if reop_status in {"Pendiente", "Verificado", "Observado"} else "Pendiente"
    write_audit(db, user, "actualizar", "perfil_cumplimiento_sucursal", str(branch.id), branch.name)
    db.commit()
    return RedirectResponse(f"/app/compliance?company_id={company.id}&saved=branch", status_code=303)


@app.post("/app/compliance/employee-profile")
def update_employee_compliance_profile(
    company_id: Annotated[int, Form()],
    employee_id: Annotated[int, Form()],
    document_type: Annotated[str, Form()] = "CI",
    sex: Annotated[str, Form()] = "",
    nationality: Annotated[str, Form()] = "Paraguaya",
    marital_status: Annotated[str, Form()] = "",
    birth_place: Annotated[str, Form()] = "",
    department: Annotated[str, Form()] = "",
    district: Annotated[str, Form()] = "",
    profession: Annotated[str, Form()] = "",
    occupation_code: Annotated[str, Form()] = "",
    position_category: Annotated[str, Form()] = "",
    work_schedule: Annotated[str, Form()] = "",
    shift: Annotated[str, Form()] = "Diurno",
    weekly_hours: Annotated[int, Form()] = 48,
    salary_type: Annotated[str, Form()] = "Mensual",
    dependent_children: Annotated[int, Form()] = 0,
    indigenous: Annotated[str | None, Form()] = None,
    disability: Annotated[str | None, Form()] = None,
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    company = company_allowed(db, user, company_id)
    employee = db.get(Employee, employee_id)
    if not employee or employee.company_id != company.id:
        raise HTTPException(404, "Funcionario no encontrado.")
    profile = db.scalar(select(EmployeeComplianceProfile).where(EmployeeComplianceProfile.employee_id == employee.id))
    if not profile:
        profile = EmployeeComplianceProfile(employee_id=employee.id)
        db.add(profile)
    profile.document_type = clean_text(document_type, max_length=30) or "CI"
    profile.sex = clean_text(sex, max_length=30)
    profile.nationality = clean_text(nationality, max_length=80) or "Paraguaya"
    profile.marital_status = clean_text(marital_status, max_length=40)
    profile.birth_place = clean_text(birth_place, max_length=120)
    profile.department = clean_text(department, max_length=100)
    profile.district = clean_text(district, max_length=100)
    profile.profession = clean_text(profession, max_length=160)
    profile.occupation_code = clean_text(occupation_code, max_length=60)
    profile.position_category = clean_text(position_category, max_length=100)
    profile.work_schedule = clean_text(work_schedule, max_length=120)
    profile.shift = clean_text(shift, max_length=60) or "Diurno"
    profile.weekly_hours = max(1, min(int(weekly_hours or 48), 96))
    profile.salary_type = clean_text(salary_type, max_length=40) or "Mensual"
    profile.dependent_children = max(0, min(int(dependent_children or 0), 30))
    profile.indigenous = (indigenous or "").strip().lower() in {"on", "true", "1", "yes"}
    profile.disability = (disability or "").strip().lower() in {"on", "true", "1", "yes"}
    employee.updated_at = datetime.now(UTC)
    employee.updated_by = user.email
    write_audit(db, user, "actualizar", "perfil_cumplimiento_funcionario", str(employee.id))
    db.commit()
    return RedirectResponse(f"/app/compliance?company_id={company.id}&saved=employee", status_code=303)


@app.post("/app/compliance/events")
def add_compliance_event(
    company_id: Annotated[int, Form()],
    employee_id: Annotated[str, Form()] = "",
    authority: Annotated[str, Form()] = "REOP",
    event_type: Annotated[str, Form()] = "Entrada",
    event_date: Annotated[date, Form()] = date.today(),
    due_date: Annotated[str, Form()] = "",
    detail: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    company = company_allowed(db, user, company_id)
    parsed_employee_id = optional_int(employee_id, field="funcionario")
    selected_employee = None
    if parsed_employee_id:
        selected_employee = db.get(Employee, parsed_employee_id)
        if not selected_employee or selected_employee.company_id != company.id:
            raise HTTPException(400, "Funcionario inválido.")
    authority_value = authority.strip().upper()
    if authority_value not in {"REI", "REOP"}:
        raise HTTPException(400, "Seleccioná una autoridad válida: REI o REOP.")
    event_type_value = event_type.strip()
    allowed_event_types = REI_EVENT_TYPES if authority_value == "REI" else REOP_EVENT_TYPES
    if event_type_value not in allowed_event_types:
        raise HTTPException(400, "El tipo de comunicación no corresponde a la autoridad seleccionada.")
    parsed_due = _parse_optional_form_date(due_date, "fecha límite")
    if parsed_due and parsed_due < event_date:
        raise HTTPException(400, "La fecha límite no puede ser anterior a la fecha del evento.")
    event = create_compliance_event(
        db,
        company_id=company.id,
        employee_id=parsed_employee_id,
        branch_id=selected_employee.branch_id if selected_employee else None,
        authority=authority_value,
        event_type=event_type_value,
        event_date=event_date,
        due_date=parsed_due,
        payload={"detail": clean_text(detail, max_length=4000), "notes": clean_text(notes, max_length=2000)},
        created_by=user.email,
    )
    db.flush()
    write_audit(db, user, "crear", "comunicacion_oficial", str(event.id), f"{event.authority} · {event.event_type}")
    db.commit()
    return RedirectResponse(f"/app/compliance?company_id={company.id}&created=1", status_code=303)


@app.post("/app/compliance/events/{event_id}/status")
def update_compliance_event_status(
    event_id: int,
    status_value: Annotated[str, Form(alias="status")],
    external_reference: Annotated[str, Form()] = "",
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    event = db.get(ComplianceEvent, event_id)
    if not event or event.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    allowed = {"Borrador", "Validado", "Exportado", "Presentado", "Aceptado", "Observado", "Rechazado", "Anulado"}
    if status_value not in allowed:
        raise HTTPException(400, "Estado inválido.")
    if event.batch_id:
        raise HTTPException(409, "Esta comunicación pertenece a un lote. Actualizá su presentación y comprobante desde «Lotes y comprobantes».")
    if status_value == "Exportado":
        raise HTTPException(409, "El estado Exportado se asigna únicamente al generar el archivo del lote.")
    if not can_transition_compliance_status(event.status, status_value):
        raise HTTPException(409, f"No se puede cambiar una comunicación de {event.status} a {status_value}.")
    if status_value == "Validado" and settings.compliance_dual_approval and event.created_by == user.email:
        raise HTTPException(409, "La validación debe realizarla un segundo usuario autorizado.")
    reference_value = clean_text(external_reference, max_length=160) or event.external_reference
    if status_value in {"Presentado", "Aceptado", "Observado", "Rechazado"} and not reference_value:
        raise HTTPException(400, "Registrá la referencia del portal o el comprobante en el lote antes de actualizar el resultado.")
    previous_status = event.status
    event.status = status_value
    event.external_reference = reference_value
    if status_value == "Validado":
        event.approved_by = user.email
    if status_value == "Presentado" and previous_status != "Presentado":
        event.submitted_at = datetime.now(UTC)
    if status_value == "Aceptado" and previous_status != "Aceptado":
        event.approved_by = user.email
    write_audit(db, user, "cambiar_estado", "comunicacion_oficial", str(event.id), status_value)
    db.commit()
    return RedirectResponse(f"/app/compliance?company_id={event.company_id}&status_updated=1", status_code=303)


@app.get("/app/compliance/export/events.xlsx")
def export_compliance_events(
    company_id: int,
    authority: str,
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    company = company_allowed(db, user, company_id)
    authority = authority.upper()
    if authority not in {"REI", "REOP"}:
        raise HTTPException(400, "Sistema inválido.")
    validation_errors = validate_company_for_authority(db, company, authority)
    if validation_errors:
        return RedirectResponse(f"/app/compliance?company_id={company.id}&validation_block={authority}", status_code=303)
    events = list(
        db.scalars(
            select(ComplianceEvent)
            .where(
                ComplianceEvent.company_id == company.id,
                ComplianceEvent.authority == authority,
                ComplianceEvent.status == "Validado",
            )
            .order_by(ComplianceEvent.event_date, ComplianceEvent.id)
        )
    )
    if not events:
        return RedirectResponse(f"/app/compliance?company_id={company.id}&empty_export=1", status_code=303)
    content = build_event_workbook(db, company, authority, events)
    batch = register_batch(
        db,
        company=company,
        authority=authority,
        batch_type="Comunicaciones",
        period=date.today().isoformat(),
        content=content,
        created_by=user.email,
        events=events,
    )
    key = f"integrations/{company.id}/{batch.file_name}"
    storage.put(key, content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    batch.storage_key = key
    # The configured local backend is not a durable file store on Render free.
    batch.file_bytes = content if settings.storage_backend == "local" else None
    write_audit(db, user, "exportar", "lote_integracion", str(batch.id), f"{authority} · {len(events)} registros")
    db.commit()
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{batch.file_name}"'},
    )


@app.get("/app/compliance/export/reop-annual.xlsx")
def export_reop_annual(
    company_id: int,
    year: int = date.today().year,
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    company = company_allowed(db, user, company_id)
    validation_errors = validate_company_for_authority(db, company, "REOP")
    if validation_errors:
        return RedirectResponse(f"/app/compliance?company_id={company.id}&validation_block=REOP", status_code=303)
    year = max(2000, min(year, date.today().year + 1))
    content = build_reop_annual_workbook(db, company, year)
    batch = register_batch(
        db,
        company=company,
        authority="REOP",
        batch_type="Planillas anuales",
        period=str(year),
        content=content,
        created_by=user.email,
    )
    batch.file_name = f"reop_planillas_{company.ruc}_{year}.xlsx".replace("/", "-")
    key = f"integrations/{company.id}/{batch.file_name}"
    storage.put(key, content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    batch.storage_key = key
    # The configured local backend is not a durable file store on Render free.
    batch.file_bytes = content if settings.storage_backend == "local" else None
    write_audit(db, user, "exportar", "planillas_reop", str(batch.id), str(year))
    db.commit()
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{batch.file_name}"'},
    )


@app.get("/app/compliance/batches/{batch_id}/download")
def download_integration_batch(
    batch_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    batch = db.get(IntegrationBatch, batch_id)
    if not batch or batch.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    if batch.file_bytes is not None:
        content = bytes(batch.file_bytes)
    elif batch.storage_key and storage.exists(batch.storage_key):
        content = storage.get(batch.storage_key)
    else:
        root = UPLOAD_DIR.resolve()
        candidate = (UPLOAD_DIR / batch.storage_key).resolve() if batch.storage_key else root
        if not batch.storage_key or root not in candidate.parents or not candidate.is_file():
            raise HTTPException(404, "El archivo del lote no está disponible.")
        content = candidate.read_bytes()
    write_audit(db, user, "descargar", "lote_integracion", str(batch.id), batch.file_name)
    db.commit()
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{batch.file_name}"'},
    )


@app.post("/app/compliance/batches/{batch_id}/receipt")
async def upload_integration_receipt(
    batch_id: int,
    status_value: Annotated[str, Form(alias="status")] = "Presentado",
    external_reference: Annotated[str, Form()] = "",
    result_detail: Annotated[str, Form()] = "",
    receipt: UploadFile | None = File(None),
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    batch = db.get(IntegrationBatch, batch_id)
    if not batch or batch.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    if status_value not in {"Presentado", "Aceptado", "Observado", "Rechazado"}:
        raise HTTPException(400, "Estado inválido.")
    if status_value not in INTEGRATION_BATCH_STATUS_TRANSITIONS.get(batch.status, set()):
        raise HTTPException(409, f"No se puede cambiar el lote de {batch.status} a {status_value}.")
    reference_value = clean_text(external_reference, max_length=160) or batch.external_reference
    content: bytes | None = None
    content_type = ""
    extension = ""
    if receipt and receipt.filename:
        content = await receipt.read(MAX_UPLOAD_SIZE + 1)
        if len(content) > MAX_UPLOAD_SIZE:
            raise HTTPException(413, "El comprobante supera el máximo permitido.")
        if not content:
            raise HTTPException(400, "El archivo de comprobante está vacío.")
        content_type = (receipt.content_type or "application/octet-stream").lower()
        signatures = {
            "application/pdf": (b"%PDF-", "pdf"),
            "image/png": (b"\x89PNG\r\n\x1a\n", "png"),
            "image/jpeg": (b"\xff\xd8\xff", "jpg"),
        }
        if content_type not in signatures:
            raise HTTPException(415, "El comprobante debe ser PDF, PNG o JPG.")
        signature, extension = signatures[content_type]
        if not content.startswith(signature):
            raise HTTPException(415, "El contenido no corresponde al tipo de comprobante declarado.")
    if not reference_value and content is None:
        raise HTTPException(400, "Registrá la referencia del portal o adjuntá el comprobante.")
    linked_events = list(db.scalars(select(ComplianceEvent).where(ComplianceEvent.batch_id == batch.id)))
    for event in linked_events:
        if not can_transition_compliance_status(event.status, status_value):
            raise HTTPException(409, f"La comunicación #{event.id} no admite el cambio de estado solicitado.")

    receipt_key = ""
    if content is not None:
        receipt_key = f"integrations/{batch.company_id}/receipts/batch-{batch.id}.{extension}"
        # Store first; only remove previous formats after the new upload succeeds.
        storage.put(receipt_key, content, content_type)
        batch.receipt_storage_key = receipt_key
        batch.receipt_bytes = content if settings.storage_backend == "local" else None
        batch.receipt_content_type = content_type
        batch.receipt_file_name = safe_filename(receipt.filename or f"comprobante-lote-{batch.id}.{extension}")
        for old_extension in ("pdf", "png", "jpg"):
            old_key = f"integrations/{batch.company_id}/receipts/batch-{batch.id}.{old_extension}"
            if old_key != receipt_key and storage.exists(old_key):
                storage.delete(old_key)

    previous_batch_status = batch.status
    now = datetime.now(UTC)
    batch.status = status_value
    batch.external_reference = reference_value
    clean_result_detail = clean_text(result_detail, max_length=3000)
    if status_value in {"Observado", "Rechazado"}:
        batch.error_message = clean_result_detail or "El resultado de REOP requiere revisión; registrá el detalle y corregí el siguiente intento."
    elif status_value in {"Presentado", "Aceptado"}:
        batch.error_message = ""
    if status_value == "Presentado" and previous_batch_status != "Presentado":
        batch.submitted_at = now
    if status_value == "Aceptado" and previous_batch_status != "Aceptado":
        batch.approved_by = user.email
    for event in linked_events:
        previous_event_status = event.status
        event.status = status_value
        event.external_reference = reference_value
        if receipt_key:
            event.receipt_storage_key = receipt_key
        if status_value == "Presentado" and previous_event_status != "Presentado":
            event.submitted_at = now
        if status_value == "Aceptado" and previous_event_status != "Aceptado":
            event.approved_by = user.email
    audit_detail = status_value
    if clean_result_detail:
        audit_detail += f" · {clean_result_detail[:500]}"
    write_audit(db, user, "registrar", "comprobante_integracion", str(batch.id), audit_detail)
    db.commit()
    if batch.calculation_record_id:
        return RedirectResponse(
            f"/app/reports/liquidaciones-salarios/{batch.calculation_record_id}?reop_batch={batch.id}&receipt=1",
            status_code=303,
        )
    return RedirectResponse(f"/app/compliance?company_id={batch.company_id}&receipt=1", status_code=303)


@app.get("/app/compliance/batches/{batch_id}/receipt")
def download_integration_batch_receipt(
    batch_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    batch = db.get(IntegrationBatch, batch_id)
    if not batch or batch.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)

    receipt_key = batch.receipt_storage_key or ""
    download_name = batch.receipt_file_name or ""
    if batch.receipt_bytes is not None:
        content = bytes(batch.receipt_bytes)
        content_type = batch.receipt_content_type or "application/octet-stream"
        extension = Path(download_name).suffix.lower().lstrip(".")
    else:
        linked_key = db.scalar(
            select(ComplianceEvent.receipt_storage_key)
            .where(ComplianceEvent.batch_id == batch.id, ComplianceEvent.receipt_storage_key != "")
            .order_by(ComplianceEvent.id.desc())
            .limit(1)
        )
        candidates = [
            receipt_key,
            linked_key or "",
            *(f"integrations/{batch.company_id}/receipts/batch-{batch.id}.{ext}" for ext in ("pdf", "png", "jpg")),
        ]
        selected_key = ""
        content = b""
        root = UPLOAD_DIR.resolve()
        for key in candidates:
            if not key:
                continue
            if storage.exists(key):
                selected_key = key
                content = storage.get(key)
                break
            local_candidate = (UPLOAD_DIR / key).resolve()
            if root in local_candidate.parents and local_candidate.is_file():
                selected_key = key
                content = local_candidate.read_bytes()
                break
        if not selected_key:
            raise HTTPException(404, "El comprobante del lote no está disponible.")
        receipt_key = selected_key
        extension = Path(download_name or receipt_key).suffix.lower().lstrip(".")
        content_type = batch.receipt_content_type if batch.receipt_storage_key else ""
        if not content_type:
            content_type = {
                "pdf": "application/pdf",
                "png": "image/png",
                "jpg": "image/jpeg",
                "jpeg": "image/jpeg",
            }.get(extension, "application/octet-stream")
    if not download_name:
        extension = extension or receipt_key.lower().rsplit(".", 1)[-1]
        download_name = f"comprobante-lote-{batch.id}.{extension or 'bin'}"
    write_audit(db, user, "descargar", "comprobante_integracion", str(batch.id), batch.file_name)
    db.commit()
    return StreamingResponse(
        io.BytesIO(content),
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{safe_filename(download_name)}"'},
    )

@app.get("/app/labor-code", response_class=HTMLResponse)
def labor_code_page(
    request: Request, q: str = "", book: str = "", title: str = "", chapter: str = "",
    status_filter: str = "", article: str = "", page: int = 1,
    user: User = Depends(require_user), db: Session = Depends(get_db),
):
    sync_error = request.query_params.get("sync_error", "")
    count = db.scalar(select(func.count(LaborArticle.id))) or 0
    if count < 400:
        try:
            sync_labor_code(db, force=True)
        except Exception:
            db.rollback()
            sync_error = "No se pudo sincronizar ahora. Se conservó la biblioteca anterior."

    records = list(db.scalars(select(LaborArticle)))
    records.sort(key=lambda item: article_sort_key(item.article_number))
    all_items = [_labor_article_view(item) for item in records]
    outline = _labor_outline(all_items)
    books = list(OrderedDict((item["book_code"], item["book_name"]) for item in all_items if item["book_code"]).items())
    titles = list(OrderedDict((item["title_code"], item["title_name"]) for item in all_items if item["title_code"] and (not book or item["book_code"] == book)).items())
    chapters = list(OrderedDict((item["chapter_code"], item["chapter_name"]) for item in all_items if item["chapter_code"] and (not book or item["book_code"] == book) and (not title or item["title_code"] == title)).items())
    query_norm = normalize_search(q)
    article_norm = normalize_search(article).replace("articulo", "").replace("art.", "").strip()
    filtered = []
    for item in all_items:
        if book and item["book_code"] != book: continue
        if title and item["title_code"] != title: continue
        if chapter and item["chapter_code"] != chapter: continue
        if status_filter == "vigente" and item["is_repealed"]: continue
        if status_filter == "modificado" and not item["is_modified"]: continue
        if status_filter == "derogado" and not item["is_repealed"]: continue
        searchable = " ".join(str(item.get(key, "")) for key in ("number","body","heading","book_name","title_name","chapter_name","content_status","amendment_note","law_number"))
        if query_norm and query_norm not in normalize_search(searchable): continue
        if article_norm and article_norm != normalize_search(item["number"]): continue
        filtered.append(item)
    per_page = 20
    total = len(filtered)
    pages = max(1, math.ceil(total / per_page))
    page = min(max(1, page), pages)
    visible = filtered[(page-1)*per_page:page*per_page]
    stats = {
        "total": len(all_items), "modified": sum(item["is_modified"] for item in all_items),
        "repealed": sum(item["is_repealed"] for item in all_items), "books": len(outline),
        "reviewed_at": max((item["reviewed_at"] for item in all_items if item["reviewed_at"]), default=None),
    }
    current_scope = (visible or filtered or all_items)
    current_context = None
    if current_scope:
        first_item = current_scope[0]
        current_context = {
            "book_code": first_item.get("book_code", ""),
            "book_name": first_item.get("book_name", ""),
            "title_code": first_item.get("title_code", ""),
            "title_name": first_item.get("title_name", ""),
            "chapter_code": first_item.get("chapter_code", ""),
            "chapter_name": first_item.get("chapter_name", ""),
            "start_number": current_scope[0].get("number", ""),
            "end_number": current_scope[-1].get("number", ""),
        }
    return render(request, "labor_code_v17.html", db, user, articles=visible, outline=outline, books=books, titles=titles, chapters=chapters, q=q, selected_book=book, selected_title=title, selected_chapter=chapter, status_filter=status_filter, article_query=article, page=page, pages=pages, total=total, stats=stats, source_registry=SOURCE_REGISTRY, sync_error=sync_error, synced=request.query_params.get("synced") == "1", version="1.6.0-preview", current_context=current_context)


@app.post("/app/labor-code/sync")
def labor_code_sync_action(
    confirm: Annotated[str, Form()] = "",
    user: User = Depends(require_user), db: Session = Depends(get_db),
):
    if user.role not in {"administrador", "contador", "superadmin"}:
        raise HTTPException(403, "No tiene permiso para actualizar la biblioteca jurídica.")
    if confirm != "sync":
        raise HTTPException(400, "Confirmación inválida.")
    try:
        result = sync_labor_code(db, force=True)
        write_audit(db, user, "sincronizar", "codigo_laboral", "Ley 213/1993", f"{result.article_count} artículos; {result.modified_count} modificados; {result.repealed_count} derogados")
        db.commit()
        return RedirectResponse("/app/labor-code?synced=1", status_code=303)
    except Exception:
        db.rollback()
        return RedirectResponse("/app/labor-code?sync_error=1", status_code=303)


@app.get("/app/parameters", response_class=HTMLResponse)
def parameters_page(request: Request, user: User = Depends(require_roles("administrador")), db: Session = Depends(get_db)):
    parameters = list(db.scalars(select(LaborParameter).where(LaborParameter.active.is_(True)).order_by(LaborParameter.label)))
    return render(request, "parameters.html", db, user, parameters=parameters)


def _audit_filtered_query(
    studio_id: int | None,
    *,
    q: str = "",
    user_email: str = "",
    action: str = "",
    entity: str = "",
    date_from: str = "",
    date_to: str = "",
):
    query = select(AuditLog).where(AuditLog.studio_id == studio_id) if studio_id else select(AuditLog).where(False)
    search = clean_text(q, max_length=160)
    if search:
        pattern = f"%{search}%"
        query = query.where(or_(
            AuditLog.user_email.ilike(pattern),
            AuditLog.action.ilike(pattern),
            AuditLog.entity.ilike(pattern),
            AuditLog.entity_id.ilike(pattern),
            AuditLog.detail.ilike(pattern),
        ))
    for column, raw in (
        (AuditLog.user_email, user_email),
        (AuditLog.action, action),
        (AuditLog.entity, entity),
    ):
        value = clean_text(raw, max_length=180)
        if value:
            query = query.where(column.ilike(f"%{value}%"))
    start_date = _parse_optional_form_date(date_from, "fecha inicial")
    end_date = _parse_optional_form_date(date_to, "fecha final")
    if start_date and end_date and end_date < start_date:
        raise HTTPException(400, "La fecha final no puede ser anterior a la fecha inicial.")
    if start_date:
        query = query.where(AuditLog.created_at >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        query = query.where(AuditLog.created_at <= datetime.combine(end_date, datetime.max.time()))
    return query


@app.get("/app/audit", response_class=HTMLResponse)
def audit_page(
    request: Request,
    q: str = "",
    user_email: str = "",
    action: str = "",
    entity: str = "",
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
    user: User = Depends(require_roles("administrador")),
    db: Session = Depends(get_db),
):
    query = _audit_filtered_query(
        user.studio_id, q=q, user_email=user_email, action=action, entity=entity,
        date_from=date_from, date_to=date_to,
    )
    total_count = db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    page_size = 50
    total_pages = max(1, (total_count + page_size - 1) // page_size)
    current_page = max(1, min(page, total_pages))
    logs = list(db.scalars(
        query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(page_size).offset((current_page - 1) * page_size)
    ))
    filters = {
        "q": clean_text(q, max_length=160),
        "user_email": clean_text(user_email, max_length=180),
        "action": clean_text(action, max_length=120),
        "entity": clean_text(entity, max_length=80),
        "date_from": date_from,
        "date_to": date_to,
    }
    return render(
        request, "audit.html", db, user, logs=logs, filters=filters,
        total_count=total_count, current_page=current_page, total_pages=total_pages,
        page_size=page_size,
    )


@app.get("/app/audit/export.csv")
def export_audit_csv(
    q: str = "",
    user_email: str = "",
    action: str = "",
    entity: str = "",
    date_from: str = "",
    date_to: str = "",
    user: User = Depends(require_roles("administrador")),
    db: Session = Depends(get_db),
):
    query = _audit_filtered_query(
        user.studio_id, q=q, user_email=user_email, action=action, entity=entity,
        date_from=date_from, date_to=date_to,
    )
    items = list(db.scalars(query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())))
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Fecha", "Usuario", "Acción", "Entidad", "ID", "Detalle"])
    for item in items:
        writer.writerow([_csv_safe_cell(value) for value in [
            item.created_at.strftime("%d/%m/%Y %H:%M"),
            item.user_email,
            item.action,
            item.entity,
            item.entity_id or "",
            item.detail or "",
        ]])
    write_audit(db, user, "exportar", "auditoria", str(user.studio_id or ""), f"{len(items)} movimientos")
    db.commit()
    output_name = safe_download_name("Auditoria Digit Laboral", date.today().isoformat(), "csv")
    return StreamingResponse(
        iter(["\ufeff" + output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(output_name)}"},
    )


@app.get("/app/export/studio.zip")
def export_studio_backup(
    user: User = Depends(require_roles("administrador")), db: Session = Depends(get_db),
):
    studio = db.get(Studio, user.studio_id)
    if not studio:
        raise HTTPException(404)
    payload = build_studio_export(db, studio, UPLOAD_DIR)
    filename = safe_download_name(f"Respaldo completo {studio.name} {date.today().isoformat()}", "", "zip")
    write_audit(db, user, "exportar", "respaldo_estudio", str(studio.id), filename)
    db.commit()
    return StreamingResponse(
        io.BytesIO(payload), media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@app.get("/app/export/employees.csv")
def export_employees(user: User = Depends(require_user), db: Session = Depends(get_db)):
    company_ids = company_ids_for_user(db, user)
    employees = list(db.scalars(select(Employee).where(Employee.company_id.in_(company_ids)).order_by(Employee.full_name))) if company_ids else []
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Empresa", "RUC", "Funcionario", "Documento", "Cargo", "Ingreso", "Salario", "IPS", "Estado"])
    for item in employees:
        writer.writerow([_csv_safe_cell(value) for value in [item.company.legal_name, item.company.ruc, item.full_name, item.document_number, item.position, item.admission_date.isoformat(), item.base_salary, "Sí" if item.ips_contributor else "No", item.status]])
    data = output.getvalue().encode("utf-8-sig")
    return StreamingResponse(io.BytesIO(data), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=funcionarios_digit_laboral.csv"})


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, user: User = Depends(require_roles("superadmin")), db: Session = Depends(get_db)):
    studios = list(db.scalars(select(Studio).order_by(Studio.created_at.desc())))
    requests_list = list(db.scalars(select(ActivationRequest).order_by(ActivationRequest.created_at.desc())))
    total_companies = db.scalar(select(func.count(Company.id))) or 0
    total_users = db.scalar(select(func.count(User.id))) or 0
    payments = list(db.scalars(select(StudioPayment).order_by(StudioPayment.payment_date.desc(), StudioPayment.id.desc()).limit(100)))
    monthly_revenue = sum(item.amount for item in payments if item.payment_date.year == date.today().year and item.payment_date.month == date.today().month and item.status == "Confirmado")
    return render(request, "admin.html", db, user, studios=studios, requests_list=requests_list, total_companies=total_companies, total_users=total_users, payments=payments, monthly_revenue=monthly_revenue)


@app.post("/admin/studios")
def admin_create_studio(
    name: Annotated[str, Form()],
    owner_name: Annotated[str, Form()],
    owner_email: Annotated[str, Form()],
    temporary_password: Annotated[str, Form()],
    plan_name: Annotated[str, Form()] = "Inicial",
    company_limit: Annotated[int, Form()] = 5,
    phone: Annotated[str, Form()] = "",
    user: User = Depends(require_roles("superadmin")),
    db: Session = Depends(get_db),
):
    strength_error = password_strength_error(temporary_password)
    if strength_error:
        return RedirectResponse(f"/admin?password_error={quote(strength_error)}", status_code=303)
    studio = Studio(name=name.strip(), phone=phone.strip(), plan_name=plan_name, company_limit=max(1, company_limit), payment_status="Activo")
    db.add(studio)
    try:
        db.flush()
        owner = User(studio_id=studio.id, full_name=owner_name.strip(), email=owner_email.strip().lower(), password_hash=hash_password(temporary_password), role="administrador", must_change_password=True)
        db.add(owner)
        db.flush()
        get_or_create_security(db, owner)
    except IntegrityError:
        db.rollback()
        return RedirectResponse("/admin?duplicate=1", status_code=303)
    write_audit(db, user, "crear", "estudio", str(studio.id), studio.name)
    db.commit()
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/studios/{studio_id}/status")
def admin_studio_status(
    studio_id: int,
    active: Annotated[str, Form()],
    payment_status: Annotated[str, Form()],
    company_limit: Annotated[int, Form()],
    user: User = Depends(require_roles("superadmin")),
    db: Session = Depends(get_db),
):
    studio = db.get(Studio, studio_id)
    if not studio:
        raise HTTPException(404)
    studio.active = active == "true"
    studio.payment_status = payment_status
    studio.company_limit = max(1, company_limit)
    write_audit(db, user, "actualizar", "estudio", str(studio.id), f"{payment_status} / {company_limit}")
    db.commit()
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/studios/{studio_id}/payments")
def admin_add_payment(
    studio_id: int, amount: Annotated[int, Form()], period: Annotated[str, Form()],
    payment_date: Annotated[date, Form()], method: Annotated[str, Form()] = "Transferencia",
    reference: Annotated[str, Form()] = "", status_value: Annotated[str, Form(alias="status")] = "Confirmado",
    notes: Annotated[str, Form()] = "", user: User = Depends(require_roles("superadmin")),
    db: Session = Depends(get_db),
):
    studio = db.get(Studio, studio_id)
    if not studio:
        raise HTTPException(404)
    item = StudioPayment(
        studio_id=studio.id, amount=max(0, amount), period=period.strip(), payment_date=payment_date,
        method=method.strip(), reference=reference.strip(), status=status_value, notes=notes.strip(),
    )
    db.add(item)
    if status_value == "Confirmado":
        studio.payment_status = "Activo"
        studio.active = True
    write_audit(db, user, "registrar", "pago_estudio", str(studio.id), f"Gs. {format_gs(item.amount)} · {item.period}")
    db.commit()
    return RedirectResponse("/admin?payment=1", status_code=303)


@app.post("/admin/activation/{request_id}/status")
def admin_activation_status(
    request_id: int,
    status_value: Annotated[str, Form(alias="status")],
    user: User = Depends(require_roles("superadmin")),
    db: Session = Depends(get_db),
):
    item = db.get(ActivationRequest, request_id)
    if not item:
        raise HTTPException(404)
    item.status = status_value
    write_audit(db, user, "actualizar", "solicitud_activacion", str(item.id), status_value)
    db.commit()
    return RedirectResponse("/admin", status_code=303)


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment, "version": APP_VERSION}


@app.get("/health/live")
def health_live():
    return {"status": "alive", "version": APP_VERSION}


@app.get("/health/ready")
def health_ready(db: Session = Depends(get_db)):
    checks = {"database": "ok", "migrations": "ok", "storage": settings.storage_backend}
    try:
        db.execute(select(func.count(User.id)))
        migration_revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
        if not migration_revision:
            checks["migrations"] = "missing"
    except Exception as exc:
        logger.exception("Readiness check failed")
        return JSONResponse(
            {"status": "not_ready", "checks": {**checks, "database": "error"}, "detail": str(exc)[:180]},
            status_code=503,
        )
    warnings = [*settings.production_issues(), *postgres_rls_role_issues()]
    return {"status": "ready" if not warnings else "degraded", "checks": checks, "warnings": warnings, "version": APP_VERSION}



# REST resources for annual vacation balances and aguinaldo records already exposed in the UI.
VACATION_API_STATUSES = {"Pendiente", "Aprobada", "Completada", "Cancelada"}
AGUINALDO_API_STATUSES = {"Borrador", "Revisar", "Aprobado", "Pagado", "Anulado"}


def _employee_in_user_scope(db: Session, user: User, employee_id: int) -> Employee:
    employee = db.get(Employee, employee_id)
    if not employee or employee.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404, "Funcionario no encontrado.")
    return employee


def _vacation_api_record(item: Vacation) -> dict:
    return {
        "id": item.id,
        "company_id": item.employee.company_id,
        "employee_id": item.employee_id,
        "employee_name": item.employee.full_name,
        "period_year": item.period_year,
        "entitled_days": item.entitled_days,
        "used_days": item.used_days,
        "balance_days": item.entitled_days - item.used_days,
        "start_date": item.start_date.isoformat() if item.start_date else None,
        "end_date": item.end_date.isoformat() if item.end_date else None,
        "status": item.status,
        "notes": item.notes or "",
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def _aguinaldo_api_record(item: Aguinaldo) -> dict:
    return {
        "id": item.id,
        "company_id": item.employee.company_id,
        "employee_id": item.employee_id,
        "employee_name": item.employee.full_name,
        "year": item.year,
        "total_remunerations": item.total_remunerations,
        "calculated_amount": item.calculated_amount,
        "status": item.status,
        "notes": item.notes or "",
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def _api_date(value, label: str) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise HTTPException(422, f"{label} debe ser una fecha válida en formato AAAA-MM-DD.") from None


def _api_int(value, label: str, *, minimum: int = 0, maximum: int = 2147483647) -> int:
    if isinstance(value, bool):
        raise HTTPException(422, f"{label} debe ser un número entero.")
    try:
        result = int(str(value))
    except (TypeError, ValueError):
        raise HTTPException(422, f"{label} debe ser un número entero.") from None
    if str(value).strip() not in {str(result), f"+{result}"} or not minimum <= result <= maximum:
        raise HTTPException(422, f"{label} debe estar entre {minimum} y {maximum}.")
    return result


@app.get("/api/vacations")
def api_list_vacations(
    company_id: int | None = None,
    employee_id: int | None = None,
    year: int | None = None,
    limit: int = 100,
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    company_ids = company_ids_for_user(db, user)
    if not 1 <= limit <= 500:
        raise HTTPException(422, "El límite debe estar entre 1 y 500.")
    query = select(Vacation).join(Employee).where(Employee.company_id.in_(company_ids)) if company_ids else select(Vacation).where(False)
    if company_id:
        if company_id not in company_ids:
            raise HTTPException(404, "Empresa no encontrada.")
        query = query.where(Employee.company_id == company_id)
    if employee_id:
        employee = _employee_in_user_scope(db, user, employee_id)
        if company_id and employee.company_id != company_id:
            raise HTTPException(422, "El funcionario no pertenece a la empresa indicada.")
        query = query.where(Vacation.employee_id == employee_id)
    if year is not None:
        query = query.where(Vacation.period_year == year)
    items = list(db.scalars(query.order_by(Vacation.period_year.desc(), Vacation.created_at.desc()).limit(limit)))
    return {"items": [_vacation_api_record(item) for item in items], "count": len(items), "limit": limit}


@app.post("/api/vacations", status_code=201)
async def api_create_vacation(
    request: Request,
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Se esperaba un cuerpo JSON válido.") from None
    if not isinstance(payload, dict):
        raise HTTPException(422, "El cuerpo debe ser un objeto JSON.")
    employee = _employee_in_user_scope(db, user, _api_int(payload.get("employee_id"), "employee_id", minimum=1))
    today = current_paraguay_date()
    year = _api_int(payload.get("period_year", today.year), "period_year", minimum=1990, maximum=today.year + 2)
    entitled = _api_int(payload.get("entitled_days", 0), "entitled_days", maximum=365)
    used = _api_int(payload.get("used_days", 0), "used_days", maximum=365)
    if used > entitled:
        raise HTTPException(422, "Los días utilizados no pueden superar los días concedidos.")
    start = _api_date(payload.get("start_date"), "start_date")
    end = _api_date(payload.get("end_date"), "end_date")
    if bool(start) != bool(end):
        raise HTTPException(422, "Ingresá ambas fechas del periodo de vacaciones.")
    if start and end and end < start:
        raise HTTPException(422, "La fecha de fin no puede ser anterior a la fecha de inicio.")
    status_value = str(payload.get("status") or "Pendiente").strip()
    if status_value not in VACATION_API_STATUSES - {"Cancelada"}:
        raise HTTPException(422, "El estado de vacaciones no es válido para un nuevo registro.")
    notes = str(payload.get("notes") or "").strip()
    if len(notes) > 3000:
        raise HTTPException(422, "Las observaciones superan el máximo de 3.000 caracteres.")
    item = Vacation(employee_id=employee.id, period_year=year, entitled_days=entitled, used_days=used,
                    start_date=start, end_date=end, status=status_value, notes=notes)
    db.add(item)
    db.flush()
    if start:
        ensure_compliance_event(
            db, company_id=employee.company_id, employee_id=employee.id, branch_id=employee.branch_id,
            authority="REOP", event_type="Vacaciones", event_date=start, due_date=None,
            payload={"vacation_id": item.id, "period_year": year, "end_date": end.isoformat() if end else ""},
            created_by=user.email, source_key=f"vacation:{item.id}:reop",
        )
    write_audit(db, user, "crear_api", "vacaciones", str(item.id), employee.full_name)
    db.commit()
    db.refresh(item)
    return JSONResponse(_vacation_api_record(item), status_code=201)


@app.patch("/api/vacations/{vacation_id}")
async def api_update_vacation(
    vacation_id: int,
    request: Request,
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    item = db.get(Vacation, vacation_id)
    if not item or item.employee.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404, "Registro de vacaciones no encontrado.")
    if item.status == "Cancelada":
        raise HTTPException(409, "El registro está cancelado.")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Se esperaba un cuerpo JSON válido.") from None
    if not isinstance(payload, dict):
        raise HTTPException(422, "El cuerpo debe ser un objeto JSON.")
    year = _api_int(payload.get("period_year", item.period_year), "period_year", minimum=1990, maximum=current_paraguay_date().year + 2)
    entitled = _api_int(payload.get("entitled_days", item.entitled_days), "entitled_days", maximum=365)
    used = _api_int(payload.get("used_days", item.used_days), "used_days", maximum=365)
    if used > entitled:
        raise HTTPException(422, "Los días utilizados no pueden superar los días concedidos.")
    start = _api_date(payload.get("start_date", item.start_date), "start_date")
    end = _api_date(payload.get("end_date", item.end_date), "end_date")
    if bool(start) != bool(end) or (start and end and end < start):
        raise HTTPException(422, "Revisá el rango de fechas del periodo de vacaciones.")
    status_value = str(payload.get("status", item.status)).strip()
    if status_value not in VACATION_API_STATUSES:
        raise HTTPException(422, "El estado de vacaciones no es válido.")
    notes = str(payload.get("notes", item.notes or "")).strip()
    if len(notes) > 3000:
        raise HTTPException(422, "Las observaciones superan el máximo de 3.000 caracteres.")
    item.period_year, item.entitled_days, item.used_days = year, entitled, used
    item.start_date, item.end_date, item.status, item.notes = start, end, status_value, notes
    write_audit(db, user, "actualizar_api", "vacaciones", str(item.id), f"{item.employee.full_name} · {status_value}")
    db.commit()
    db.refresh(item)
    return _vacation_api_record(item)


@app.delete("/api/vacations/{vacation_id}", status_code=204)
def api_cancel_vacation(
    vacation_id: int,
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    item = db.get(Vacation, vacation_id)
    if not item or item.employee.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404, "Registro de vacaciones no encontrado.")
    if item.status == "Completada":
        raise HTTPException(409, "No se puede cancelar un periodo completado; conservá la trazabilidad.")
    item.status = "Cancelada"
    write_audit(db, user, "cancelar_api", "vacaciones", str(item.id), item.employee.full_name)
    db.commit()
    return Response(status_code=204)


@app.get("/api/aguinaldos")
def api_list_aguinaldos(
    company_id: int | None = None,
    employee_id: int | None = None,
    year: int | None = None,
    limit: int = 100,
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    company_ids = company_ids_for_user(db, user)
    if not 1 <= limit <= 500:
        raise HTTPException(422, "El límite debe estar entre 1 y 500.")
    query = select(Aguinaldo).join(Employee).where(Employee.company_id.in_(company_ids)) if company_ids else select(Aguinaldo).where(False)
    if company_id:
        if company_id not in company_ids:
            raise HTTPException(404, "Empresa no encontrada.")
        query = query.where(Employee.company_id == company_id)
    if employee_id:
        employee = _employee_in_user_scope(db, user, employee_id)
        if company_id and employee.company_id != company_id:
            raise HTTPException(422, "El funcionario no pertenece a la empresa indicada.")
        query = query.where(Aguinaldo.employee_id == employee_id)
    if year is not None:
        query = query.where(Aguinaldo.year == year)
    items = list(db.scalars(query.order_by(Aguinaldo.year.desc(), Aguinaldo.created_at.desc()).limit(limit)))
    return {"items": [_aguinaldo_api_record(item) for item in items], "count": len(items), "limit": limit}


@app.post("/api/aguinaldos", status_code=201)
async def api_create_aguinaldo(
    request: Request,
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Se esperaba un cuerpo JSON válido.") from None
    if not isinstance(payload, dict):
        raise HTTPException(422, "El cuerpo debe ser un objeto JSON.")
    employee = _employee_in_user_scope(db, user, _api_int(payload.get("employee_id"), "employee_id", minimum=1))
    today = current_paraguay_date()
    year = _api_int(payload.get("year", today.year), "year", minimum=1900, maximum=2100)
    total = _api_int(payload.get("total_remunerations"), "total_remunerations", maximum=2147483647)
    notes = str(payload.get("notes") or "").strip()
    if len(notes) > 3000:
        raise HTTPException(422, "Las observaciones superan el máximo de 3.000 caracteres.")
    item = Aguinaldo(employee_id=employee.id, year=year, total_remunerations=total,
                     calculated_amount=round_gs(total / 12), notes=notes, status="Borrador")
    db.add(item)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Ya existe un cálculo de aguinaldo para ese funcionario y año.") from None
    ensure_compliance_event(
        db, company_id=employee.company_id, employee_id=employee.id, branch_id=employee.branch_id,
        authority="REOP", event_type="Aguinaldo", event_date=date(year, 12, 31), due_date=None,
        payload={"aguinaldo_id": item.id, "year": year, "amount": item.calculated_amount},
        created_by=user.email, source_key=f"aguinaldo:{item.id}:reop",
    )
    write_audit(db, user, "crear_api", "aguinaldo", str(item.id), employee.full_name)
    db.commit()
    db.refresh(item)
    return JSONResponse(_aguinaldo_api_record(item), status_code=201)


@app.patch("/api/aguinaldos/{aguinaldo_id}")
async def api_update_aguinaldo(
    aguinaldo_id: int,
    request: Request,
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    item = db.get(Aguinaldo, aguinaldo_id)
    if not item or item.employee.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404, "Registro de aguinaldo no encontrado.")
    if item.status in {"Pagado", "Anulado"}:
        raise HTTPException(409, "El registro fue cerrado; no se puede modificar.")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Se esperaba un cuerpo JSON válido.") from None
    if not isinstance(payload, dict):
        raise HTTPException(422, "El cuerpo debe ser un objeto JSON.")
    year = _api_int(payload.get("year", item.year), "year", minimum=1900, maximum=2100)
    total = _api_int(payload.get("total_remunerations", item.total_remunerations), "total_remunerations", maximum=2147483647)
    status_value = str(payload.get("status", item.status)).strip()
    if status_value not in AGUINALDO_API_STATUSES:
        raise HTTPException(422, "El estado del aguinaldo no es válido.")
    notes = str(payload.get("notes", item.notes or "")).strip()
    if len(notes) > 3000:
        raise HTTPException(422, "Las observaciones superan el máximo de 3.000 caracteres.")
    duplicate = db.scalar(select(Aguinaldo.id).where(
        Aguinaldo.employee_id == item.employee_id, Aguinaldo.year == year, Aguinaldo.id != item.id
    ))
    if duplicate:
        raise HTTPException(409, "Ya existe un cálculo de aguinaldo para ese funcionario y año.")
    item.year, item.total_remunerations = year, total
    item.calculated_amount = round_gs(total / 12)
    item.status, item.notes = status_value, notes
    write_audit(db, user, "actualizar_api", "aguinaldo", str(item.id), f"{item.employee.full_name} · {status_value}")
    db.commit()
    db.refresh(item)
    return _aguinaldo_api_record(item)


@app.delete("/api/aguinaldos/{aguinaldo_id}", status_code=204)
def api_cancel_aguinaldo(
    aguinaldo_id: int,
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    item = db.get(Aguinaldo, aguinaldo_id)
    if not item or item.employee.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404, "Registro de aguinaldo no encontrado.")
    if item.status == "Pagado":
        raise HTTPException(409, "No se puede anular un aguinaldo marcado como pagado.")
    item.status = "Anulado"
    write_audit(db, user, "anular_api", "aguinaldo", str(item.id), item.employee.full_name)
    db.commit()
    return Response(status_code=204)



# Register the existing professional calculation engine only after core helpers are defined.
from .calculator_routes import router as calculator_router
app.include_router(calculator_router)
