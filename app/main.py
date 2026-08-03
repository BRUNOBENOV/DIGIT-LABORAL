from __future__ import annotations

import csv
import hmac
import io
import json
import math
import os
import re
import secrets
import uuid
import zipfile
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated
from urllib.parse import parse_qs, quote

from PIL import Image, ImageChops, ImageOps

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .ai_service import generate_assistance
from .auth import hash_password, verify_password
from .config import settings
from .database import Base, SessionLocal, apply_session_tenant_context, engine
from .document_export import (
    DOCUMENT_LABELS,
    build_document_body,
    build_docx_bytes,
    build_pdf_bytes,
    decode_metadata,
    encode_metadata,
    export_data_from_certificate,
    format_date_long_es,
    safe_download_name,
)
from .models import (
    ActivationRequest,
    AIInteraction,
    Aguinaldo,
    AuditLog,
    Branch,
    Company,
    CompanyBranding,
    CompanyRequest,
    CalculationRecord,
    Document,
    Employee,
    EmployeeEvent,
    GeneratedCertificate,
    LaborArticle,
    LaborDeadline,
    LaborParameter,
    Payroll,
    PayrollLine,
    PasswordResetToken,
    RequestAttachment,
    RequestComment,
    RequestWorkflow,
    SalaryHistory,
    SecurityEvent,
    Studio,
    StudioPayment,
    User,
    UserSecurity,
    Vacation,
)
from .report_export import build_employee_report_pdf
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
    parse_employee_import,
    save_preview,
)
from .tenant_security import apply_postgres_rls
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
MAX_UPLOAD_SIZE = 10 * 1024 * 1024


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


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    seed_database()
    if settings.rls_enabled:
        apply_postgres_rls(engine)
    yield


if settings.environment == "production" and settings.secret_key == "cambiar-esta-clave-en-produccion":
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
        protected = method in {"POST", "PUT", "PATCH", "DELETE"} and (
            path.startswith("/app") or path.startswith("/admin")
        )
        session = scope.get("session") or {}
        expected = session.get("csrf_token", "")
        if not protected:
            await self.app(scope, receive, send)
            return

        body_parts: list[bytes] = []
        more = True
        while more:
            message = await receive()
            if message.get("type") != "http.request":
                continue
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
            match = re.search(
                rb'name="csrf_token"\r?\n(?:[^\r\n]*\r?\n)*\r?\n([^\r\n]+)',
                body,
            )
            if match:
                supplied = match.group(1).decode("utf-8", errors="replace")
        if not expected or not supplied or not hmac.compare_digest(str(expected), str(supplied)):
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


app = FastAPI(title="Digit Laboral", version="1.9.0-preview", lifespan=lifespan)
app.add_middleware(CSRFMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    same_site="lax",
    https_only=settings.secure_cookies,
    max_age=60 * 60 * 12,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))

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


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_user(request: Request, db: Session) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.get(User, int(user_id))
    if not user:
        request.session.clear()
        return None
    security = get_or_create_security(db, user)
    session_version = int(request.session.get("security_version", 0) or 0)
    if session_version != security.session_version:
        request.session.clear()
        return None
    db.info["studio_id"] = user.studio_id
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
    if user.role == "empresa" and user.company_id:
        return [user.company_id]
    if user.studio_id:
        return list(db.scalars(select(Company.id).where(Company.studio_id == user.studio_id)))
    return []


def company_allowed(db: Session, user: User, company_id: int) -> Company:
    company = db.get(Company, company_id)
    if not company or company_id not in company_ids_for_user(db, user):
        raise HTTPException(404, "Empresa no encontrada.")
    return company


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
        **context,
    }
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
        ips = round(computable * ips_rate / 100) if inputs["apply_ips"] else 0
        discounts = ips + inputs["other_discount"]
        amount = max(0, computable - discounts)
        results = {"gross_computable": computable, "ips_employee": ips, "discounts": discounts, "net": amount}
    elif calculation_type == "hours":
        base = inputs["salary"] / inputs["monthly_hours"]
        amount = round(base * inputs["hours_quantity"] * inputs["multiplier"])
        results = {"hour_value": round(base), "total": amount}
    elif calculation_type == "aguinaldo":
        amount = round(inputs["total_remunerations"] / 12)
        results = {"total_remunerations": inputs["total_remunerations"], "aguinaldo": amount}
    elif calculation_type in {"vacation", "notice"}:
        daily = inputs["salary"] / 30
        amount = round(daily * inputs["days"])
        results = {"daily_value": round(daily), "days": inputs["days"], "total": amount}
    else:
        raise HTTPException(400, "Tipo de cálculo inválido.")
    return inputs, results, amount


def calculation_label(value: str) -> str:
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
    studio_name: Annotated[str, Form()],
    contact_name: Annotated[str, Form()],
    email: Annotated[str, Form()],
    phone: Annotated[str, Form()],
    estimated_companies: Annotated[int, Form()] = 1,
    message: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
):
    item = ActivationRequest(
        studio_name=studio_name.strip(),
        contact_name=contact_name.strip(),
        email=email.strip().lower(),
        phone=phone.strip(),
        estimated_companies=max(1, estimated_companies),
        message=message.strip(),
    )
    db.add(item)
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
    if not verify_totp(security.totp_secret, code):
        write_security_event(db, request, "segundo_factor", False, user=user, detail="Código TOTP inválido")
        db.commit()
        return render(request, "login_2fa.html", db, pending_email=user.email, error="El código no es válido.")
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
    pending_count = db.scalar(select(func.count(CompanyRequest.id)).where(CompanyRequest.company_id.in_(company_ids), CompanyRequest.status.in_(["Pendiente", "En revisión", "Falta información", "Procesando"]))) if company_ids else 0
    payroll_count = db.scalar(select(func.count(Payroll.id)).where(Payroll.company_id.in_(company_ids), Payroll.status == "Borrador")) if company_ids else 0
    companies = list(db.scalars(select(Company).where(Company.id.in_(company_ids)).order_by(Company.created_at.desc()).limit(5))) if company_ids else []
    recent_requests = list(db.scalars(select(CompanyRequest).where(CompanyRequest.company_id.in_(company_ids)).order_by(CompanyRequest.created_at.desc()).limit(5))) if company_ids else []
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
    return render(
        request,
        "dashboard.html",
        db,
        user,
        companies_count=companies_count,
        employee_count=employee_count or 0,
        pending_count=pending_count or 0,
        payroll_count=payroll_count or 0,
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
def companies_page(request: Request, q: str = "", user: User = Depends(require_user), db: Session = Depends(get_db)):
    if user.role == "empresa":
        return RedirectResponse(f"/app/companies/{user.company_id}", status_code=303)
    query = select(Company).where(Company.studio_id == user.studio_id)
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.where(or_(Company.legal_name.ilike(term), Company.ruc.ilike(term), Company.trade_name.ilike(term)))
    companies = list(db.scalars(query.order_by(Company.legal_name)))
    return render(request, "companies.html", db, user, companies=companies, q=q)


@app.post("/app/companies")
def add_company(
    legal_name: Annotated[str, Form()],
    ruc: Annotated[str, Form()],
    trade_name: Annotated[str, Form()] = "",
    city: Annotated[str, Form()] = "Ciudad del Este",
    address: Annotated[str, Form()] = "",
    phone: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "",
    legal_representative: Annotated[str, Form()] = "",
    ips_employer_number: Annotated[str, Form()] = "",
    mtess_employer_number: Annotated[str, Form()] = "",
    responsible_name: Annotated[str, Form()] = "Sin asignar",
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    studio = db.get(Studio, user.studio_id)
    count = db.scalar(select(func.count(Company.id)).where(Company.studio_id == user.studio_id)) or 0
    if studio and count >= studio.company_limit:
        return RedirectResponse("/app/companies?limit=1", status_code=303)
    company = Company(
        studio_id=user.studio_id,
        legal_name=legal_name.strip(),
        trade_name=trade_name.strip(),
        ruc=ruc.strip(),
        city=city.strip(),
        address=address.strip(),
        phone=phone.strip(),
        email=email.strip(),
        legal_representative=legal_representative.strip(),
        ips_employer_number=ips_employer_number.strip(),
        mtess_employer_number=mtess_employer_number.strip(),
        responsible_name=responsible_name.strip() or "Sin asignar",
    )
    db.add(company)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return RedirectResponse("/app/companies?duplicate=1", status_code=303)
    db.add(Branch(company_id=company.id, name="Casa central", city=company.city, address=company.address))
    get_or_create_branding(db, company)
    write_audit(db, user, "crear", "empresa", str(company.id), company.legal_name)
    db.commit()
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
    logo: UploadFile | None = File(default=None),
    user: User = Depends(require_roles("administrador", "contador", "empresa")),
    db: Session = Depends(get_db),
):
    company = company_allowed(db, user, company_id)
    branding = get_or_create_branding(db, company)
    color_pattern = re.compile(r"^#[0-9A-Fa-f]{6}$")
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
            raise HTTPException(413, "El logo supera el máximo permitido de 2 MB.")
        content_type = (logo.content_type or "").lower()
        is_png = content.startswith(b"\x89PNG\r\n\x1a\n")
        is_jpeg = content.startswith(b"\xff\xd8\xff")
        if content_type not in {"image/png", "image/jpeg"} or not (is_png or is_jpeg):
            raise HTTPException(415, "El logo debe ser PNG o JPG válido.")
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
    trade_name: Annotated[str, Form()] = "",
    city: Annotated[str, Form()] = "",
    address: Annotated[str, Form()] = "",
    phone: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "",
    legal_representative: Annotated[str, Form()] = "",
    ips_employer_number: Annotated[str, Form()] = "",
    mtess_employer_number: Annotated[str, Form()] = "",
    responsible_name: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    company = company_allowed(db, user, company_id)
    for attr, value in {
        "legal_name": legal_name,
        "trade_name": trade_name,
        "city": city,
        "address": address,
        "phone": phone,
        "email": email,
        "legal_representative": legal_representative,
        "ips_employer_number": ips_employer_number,
        "mtess_employer_number": mtess_employer_number,
        "responsible_name": responsible_name,
        "notes": notes,
    }.items():
        setattr(company, attr, value.strip())
    write_audit(db, user, "editar", "empresa", str(company.id), company.legal_name)
    db.commit()
    return RedirectResponse(f"/app/companies/{company_id}", status_code=303)


@app.post("/app/companies/{company_id}/status")
def update_company_status(company_id: int, status_value: Annotated[str, Form(alias="status")], user: User = Depends(require_roles("administrador", "contador")), db: Session = Depends(get_db)):
    company = company_allowed(db, user, company_id)
    company.status = status_value
    write_audit(db, user, "actualizar_estado", "empresa", str(company.id), status_value)
    db.commit()
    return RedirectResponse(f"/app/companies/{company_id}", status_code=303)


@app.post("/app/companies/{company_id}/branches")
def add_branch(
    company_id: int,
    name: Annotated[str, Form()],
    city: Annotated[str, Form()] = "",
    address: Annotated[str, Form()] = "",
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    company_allowed(db, user, company_id)
    branch = Branch(company_id=company_id, name=name.strip(), city=city.strip(), address=address.strip())
    db.add(branch)
    db.flush()
    write_audit(db, user, "crear", "sucursal", str(branch.id), branch.name)
    db.commit()
    return RedirectResponse(f"/app/companies/{company_id}", status_code=303)


@app.get("/app/employees", response_class=HTMLResponse)
def employees_page(request: Request, q: str = "", company_id: int | None = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    company_ids = company_ids_for_user(db, user)
    query = select(Employee).where(Employee.company_id.in_(company_ids)) if company_ids else select(Employee).where(False)
    if company_id and company_id in company_ids:
        query = query.where(Employee.company_id == company_id)
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.where(or_(Employee.full_name.ilike(term), Employee.document_number.ilike(term), Employee.position.ilike(term)))
    employees = list(db.scalars(query.order_by(Employee.full_name)))
    companies = list(db.scalars(select(Company).where(Company.id.in_(company_ids)).order_by(Company.legal_name))) if company_ids else []
    branches = list(db.scalars(select(Branch).where(Branch.company_id.in_(company_ids)).order_by(Branch.name))) if company_ids else []
    minimum_salary = db.scalar(select(LaborParameter).where(LaborParameter.key == "minimum_monthly_salary_general", LaborParameter.active.is_(True)))
    return render(request, "employees.html", db, user, employees=employees, companies=companies, branches=branches, q=q, selected_company=company_id, minimum_salary=minimum_salary)


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
    existing_documents = set(db.scalars(select(Employee.document_number).where(Employee.company_id == company.id)))
    duplicate_count = sum(row.data.get("document_number") in existing_documents for row in preview.rows if row.valid)
    return render(
        request, "employee_import_preview.html", db, user, token=token, preview=preview, company=company,
        duplicate_count=duplicate_count, existing_documents=existing_documents,
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
    created = updated = skipped = 0
    for row in preview.rows:
        if not row.valid:
            skipped += 1
            continue
        data = row.data
        employee = db.scalar(
            select(Employee).where(
                Employee.company_id == company.id,
                Employee.document_number == data["document_number"],
            )
        )
        if employee and duplicate_action != "update":
            skipped += 1
            continue
        admission = date.fromisoformat(data["admission_date"])
        birth = date.fromisoformat(data["birth_date"]) if data.get("birth_date") else None
        if employee:
            old_salary = employee.base_salary
            employee.full_name = data["full_name"]
            employee.position = data["position"]
            employee.admission_date = admission
            employee.birth_date = birth
            employee.contract_type = data["contract_type"]
            employee.payment_frequency = data["payment_frequency"]
            employee.base_salary = data["base_salary"]
            employee.ips_contributor = data["ips_contributor"]
            employee.email = data["email"]
            employee.phone = data["phone"]
            employee.address = data["address"]
            employee.notes = data["notes"]
            if old_salary != employee.base_salary:
                db.add(SalaryHistory(
                    employee_id=employee.id, previous_salary=old_salary, new_salary=employee.base_salary,
                    effective_from=date.today(), reason="Actualización por importación", created_by=user.email,
                ))
            add_employee_event(db, employee, user, "Importación", "Datos actualizados por importación", f"Archivo: {preview.filename}")
            updated += 1
        else:
            employee = Employee(
                company_id=company.id, full_name=data["full_name"], document_number=data["document_number"],
                birth_date=birth, position=data["position"], admission_date=admission,
                contract_type=data["contract_type"], payment_frequency=data["payment_frequency"],
                base_salary=data["base_salary"], ips_contributor=data["ips_contributor"],
                email=data["email"], phone=data["phone"], address=data["address"], notes=data["notes"],
            )
            db.add(employee)
            db.flush()
            add_employee_event(db, employee, user, "Alta", "Funcionario importado", f"Archivo: {preview.filename}", admission, employee.base_salary)
            db.add(SalaryHistory(
                employee_id=employee.id, previous_salary=0, new_salary=employee.base_salary,
                effective_from=admission, reason="Salario inicial importado", created_by=user.email,
            ))
            created += 1
    write_audit(db, user, "confirmar", "importacion_funcionarios", token, f"{company.legal_name}: {created} creados, {updated} actualizados, {skipped} omitidos")
    db.commit()
    (IMPORT_DIR / f"{token}.json").unlink(missing_ok=True)
    return RedirectResponse(f"/app/employees?imported={created}&updated={updated}&skipped={skipped}&company_id={company.id}", status_code=303)


@app.post("/app/employees")
def add_employee(
    company_id: Annotated[int, Form()],
    full_name: Annotated[str, Form()],
    document_number: Annotated[str, Form()],
    position_name: Annotated[str, Form(alias="position")],
    admission_date: Annotated[date, Form()],
    base_salary: Annotated[int, Form()],
    branch_id: Annotated[int | None, Form()] = None,
    birth_date: Annotated[date | None, Form()] = None,
    contract_type: Annotated[str, Form()] = "Tiempo indefinido",
    payment_frequency: Annotated[str, Form()] = "Mensual",
    email: Annotated[str, Form()] = "",
    phone: Annotated[str, Form()] = "",
    address: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
    ips_contributor: Annotated[str | None, Form()] = None,
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    company_allowed(db, user, company_id)
    employee = Employee(
        company_id=company_id,
        branch_id=branch_id or None,
        full_name=full_name.strip(),
        document_number=document_number.strip(),
        birth_date=birth_date,
        position=position_name.strip(),
        admission_date=admission_date,
        contract_type=contract_type.strip(),
        payment_frequency=payment_frequency.strip(),
        base_salary=max(0, base_salary),
        ips_contributor=ips_contributor == "on",
        email=email.strip(),
        phone=phone.strip(),
        address=address.strip(),
        notes=notes.strip(),
    )
    db.add(employee)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return RedirectResponse("/app/employees?duplicate=1", status_code=303)
    add_employee_event(db, employee, user, "Alta", "Alta de funcionario", f"Cargo: {employee.position}", employee.admission_date, employee.base_salary)
    db.add(SalaryHistory(
        employee_id=employee.id, previous_salary=0, new_salary=employee.base_salary,
        effective_from=employee.admission_date, reason="Salario inicial", created_by=user.email,
    ))
    write_audit(db, user, "crear", "funcionario", str(employee.id), employee.full_name)
    db.commit()
    return RedirectResponse(f"/app/employees/{employee.id}", status_code=303)


@app.post("/app/employees/{employee_id}/edit")
def edit_employee(
    employee_id: int,
    full_name: Annotated[str, Form()],
    position_name: Annotated[str, Form(alias="position")],
    base_salary: Annotated[int, Form()],
    email: Annotated[str, Form()] = "",
    phone: Annotated[str, Form()] = "",
    address: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    employee = db.get(Employee, employee_id)
    if not employee or employee.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    previous_salary = employee.base_salary
    employee.full_name = full_name.strip()
    employee.position = position_name.strip()
    employee.base_salary = max(0, base_salary)
    employee.email = email.strip()
    employee.phone = phone.strip()
    employee.address = address.strip()
    employee.notes = notes.strip()
    if previous_salary != employee.base_salary:
        db.add(SalaryHistory(
            employee_id=employee.id, previous_salary=previous_salary, new_salary=employee.base_salary,
            effective_from=date.today(), reason="Actualización desde expediente", created_by=user.email,
        ))
        add_employee_event(
            db, employee, user, "Cambio salarial", "Actualización salarial",
            f"De Gs. {format_gs(previous_salary)} a Gs. {format_gs(employee.base_salary)}",
            date.today(), employee.base_salary,
        )
    else:
        add_employee_event(db, employee, user, "Actualización", "Datos del funcionario actualizados")
    write_audit(db, user, "editar", "funcionario", str(employee.id), employee.full_name)
    db.commit()
    return RedirectResponse(f"/app/employees/{employee.id}", status_code=303)


@app.post("/app/employees/{employee_id}/status")
def employee_status(
    employee_id: int,
    status_value: Annotated[str, Form(alias="status")],
    termination_date: Annotated[date | None, Form()] = None,
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    employee = db.get(Employee, employee_id)
    if not employee or employee.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    employee.status = status_value
    employee.termination_date = termination_date if status_value != "Activo" else None
    effective = employee.termination_date or date.today()
    add_employee_event(db, employee, user, "Estado", f"Estado actualizado a {status_value}", "", effective)
    write_audit(db, user, "actualizar_estado", "funcionario", str(employee.id), status_value)
    db.commit()
    return RedirectResponse(f"/app/employees/{employee.id}", status_code=303)


@app.get("/app/calendar", response_class=HTMLResponse)
def calendar_page(
    request: Request, company_id: int | None = None, employee_id: int | None = None,
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
        anniversary = employee.admission_date.replace(year=today_value.year)
        if anniversary < today_value:
            anniversary = anniversary.replace(year=today_value.year + 1)
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


@app.get("/app/requests", response_class=HTMLResponse)
def requests_page(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    company_ids = company_ids_for_user(db, user)
    items = list(db.scalars(select(CompanyRequest).where(CompanyRequest.company_id.in_(company_ids)).order_by(CompanyRequest.created_at.desc()))) if company_ids else []
    companies = list(db.scalars(select(Company).where(Company.id.in_(company_ids)).order_by(Company.legal_name))) if company_ids else []
    request_ids = [item.id for item in items]
    workflows = list(db.scalars(select(RequestWorkflow).where(RequestWorkflow.request_id.in_(request_ids)))) if request_ids else []
    workflow_by_request = {item.request_id: item for item in workflows}
    pending = sum(item.status not in {"Resuelta", "Rechazada"} for item in items)
    overdue = sum(
        workflow.due_date and workflow.due_date < date.today() and next((item.status for item in items if item.id == workflow.request_id), "") not in {"Resuelta", "Rechazada"}
        for workflow in workflows
    )
    return render(request, "requests.html", db, user, items=items, companies=companies, workflow_by_request=workflow_by_request, pending=pending, overdue=overdue)


@app.post("/app/requests")
def add_request(
    company_id: Annotated[int, Form()],
    request_type: Annotated[str, Form()],
    detail: Annotated[str, Form()],
    subject: Annotated[str, Form()] = "",
    priority: Annotated[str, Form()] = "Normal",
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    company_allowed(db, user, company_id)
    item = CompanyRequest(company_id=company_id, request_type=request_type.strip(), subject=subject.strip(), detail=detail.strip(), priority=priority, status="Pendiente")
    db.add(item)
    db.flush()
    write_audit(db, user, "crear", "solicitud", str(item.id), request_type)
    db.commit()
    return RedirectResponse("/app/requests", status_code=303)


@app.get("/app/requests/{request_id}", response_class=HTMLResponse)
def request_detail_page(
    request_id: int, request: Request, user: User = Depends(require_user), db: Session = Depends(get_db),
):
    item = db.get(CompanyRequest, request_id)
    if not item or item.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404, "Solicitud no encontrada.")
    workflow = db.scalar(select(RequestWorkflow).where(RequestWorkflow.request_id == item.id))
    comments_query = select(RequestComment).where(RequestComment.request_id == item.id)
    if user.role == "empresa":
        comments_query = comments_query.where(RequestComment.visibility == "Empresa")
    comments = list(db.scalars(comments_query.order_by(RequestComment.created_at)))
    attachments = list(db.scalars(select(RequestAttachment).where(RequestAttachment.request_id == item.id).order_by(RequestAttachment.created_at.desc())))
    users = list(db.scalars(select(User).where(User.studio_id == user.studio_id, User.active.is_(True), User.role != "empresa").order_by(User.full_name))) if user.studio_id else []
    return render(request, "request_detail.html", db, user, item=item, workflow=workflow, comments=comments, attachments=attachments, users=users)


@app.post("/app/requests/{request_id}/comments")
def add_request_comment(
    request_id: int, body: Annotated[str, Form()], visibility: Annotated[str, Form()] = "Empresa",
    user: User = Depends(require_user), db: Session = Depends(get_db),
):
    item = db.get(CompanyRequest, request_id)
    if not item or item.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    safe_visibility = "Empresa" if user.role == "empresa" else ("Interno" if visibility == "Interno" else "Empresa")
    comment = RequestComment(
        request_id=item.id, user_id=user.id, author_name=user.full_name, visibility=safe_visibility, body=body.strip(),
    )
    db.add(comment)
    write_audit(db, user, "comentar", "solicitud", str(item.id), safe_visibility)
    db.commit()
    return RedirectResponse(f"/app/requests/{item.id}#conversation", status_code=303)


@app.post("/app/requests/{request_id}/attachments")
async def add_request_attachment(
    request_id: int, file: UploadFile = File(), user: User = Depends(require_user), db: Session = Depends(get_db),
):
    item = db.get(CompanyRequest, request_id)
    if not item or item.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    content = await file.read(MAX_UPLOAD_SIZE + 1)
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(413, "El archivo supera el máximo permitido de 10 MB.")
    content_type = (file.content_type or "application/octet-stream").lower()
    if content_type not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(415, "Tipo de archivo no permitido.")
    folder = UPLOAD_DIR / "requests" / str(item.id)
    folder.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}_{safe_filename(file.filename or 'archivo')}"
    (folder / stored_name).write_bytes(content)
    attachment = RequestAttachment(
        request_id=item.id, stored_name=stored_name, original_name=safe_filename(file.filename or "archivo"),
        content_type=content_type, uploaded_by=user.email,
    )
    db.add(attachment)
    write_audit(db, user, "adjuntar", "solicitud", str(item.id), attachment.original_name)
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
    path = UPLOAD_DIR / "requests" / str(item.id) / attachment.stored_name
    if not path.exists():
        raise HTTPException(404, "Archivo no encontrado.")
    write_audit(db, user, "descargar", "adjunto_solicitud", str(attachment.id), attachment.original_name)
    db.commit()
    return FileResponse(path, media_type=attachment.content_type, filename=attachment.original_name)


@app.post("/app/requests/{request_id}/status")
def request_status(
    request_id: int,
    status_value: Annotated[str, Form(alias="status")],
    response: Annotated[str, Form()] = "",
    assigned_user_id: Annotated[int | None, Form()] = None,
    due_date: Annotated[date | None, Form()] = None,
    internal_notes: Annotated[str, Form()] = "",
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    item = db.get(CompanyRequest, request_id)
    if not item or item.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    valid_statuses = {"Pendiente", "En revisión", "Falta información", "Procesando", "Resuelta", "Rechazada"}
    if status_value not in valid_statuses:
        raise HTTPException(400, "Estado inválido.")
    item.status = status_value
    item.response = response.strip()
    if status_value in {"Resuelta", "Rechazada"}:
        item.resolved_at = datetime.now(UTC)
    else:
        item.resolved_at = None
    workflow = db.scalar(select(RequestWorkflow).where(RequestWorkflow.request_id == item.id))
    if not workflow:
        workflow = RequestWorkflow(request_id=item.id)
        db.add(workflow)
    if assigned_user_id:
        assigned = db.get(User, assigned_user_id)
        if not assigned or assigned.studio_id != user.studio_id or assigned.role == "empresa":
            raise HTTPException(400, "Responsable inválido.")
        workflow.assigned_user_id = assigned.id
    else:
        workflow.assigned_user_id = None
    workflow.due_date = due_date
    workflow.internal_notes = internal_notes.strip()
    if response.strip():
        db.add(RequestComment(
            request_id=item.id, user_id=user.id, author_name=user.full_name, visibility="Empresa", body=response.strip(),
        ))
    write_audit(db, user, "actualizar_estado", "solicitud", str(item.id), status_value)
    db.commit()
    return RedirectResponse(f"/app/requests/{item.id}", status_code=303)


@app.get("/app/calculations", response_class=HTMLResponse)
def calculations_page(
    request: Request,
    company_id: int | None = None,
    employee_id: int | None = None,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    company_ids = company_ids_for_user(db, user)
    companies = list(db.scalars(select(Company).where(Company.id.in_(company_ids)).order_by(Company.legal_name))) if company_ids else []
    employees_query = select(Employee).where(Employee.company_id.in_(company_ids), Employee.status == "Activo") if company_ids else select(Employee).where(False)
    if company_id and company_id in company_ids:
        employees_query = employees_query.where(Employee.company_id == company_id)
    employees = list(db.scalars(employees_query.order_by(Employee.full_name)))
    recent_query = select(CalculationRecord).where(CalculationRecord.company_id.in_(company_ids)) if company_ids else select(CalculationRecord).where(False)
    if company_id and company_id in company_ids:
        recent_query = recent_query.where(CalculationRecord.company_id == company_id)
    if employee_id:
        recent_query = recent_query.where(CalculationRecord.employee_id == employee_id)
    recent_calculations = list(db.scalars(recent_query.order_by(CalculationRecord.created_at.desc()).limit(30)))
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
        minimum_salary=get_parameter(db, "minimum_monthly_salary_general", 0),
        hourly_reference=get_parameter(db, "minimum_hourly_wage_general", 0),
        calculation_labels={key: calculation_label(key) for key in ("salary", "hours", "aguinaldo", "vacation", "notice")},
    )


@app.post("/app/calculations")
def save_calculation(
    calculation_type: Annotated[str, Form()],
    company_id: Annotated[int, Form()],
    employee_id: Annotated[int | None, Form()] = None,
    reference_period: Annotated[str, Form()] = "",
    gross: Annotated[int, Form()] = 0,
    other_income: Annotated[int, Form()] = 0,
    other_discount: Annotated[int, Form()] = 0,
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
    return RedirectResponse(f"/app/calculations?saved={item.id}&company_id={company.id}" + (f"&employee_id={employee.id}" if employee else ""), status_code=303)


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
    return RedirectResponse("/app/calculations", status_code=303)


@app.get("/app/calculations/{calculation_id}/certificate")
def calculation_to_certificate(
    calculation_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    item = db.get(CalculationRecord, calculation_id)
    if not item or item.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
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
    calculation_id: int | None = None,
    company_id: int | None = None,
    employee_id: int | None = None,
    document_type: str = "",
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    company_ids = company_ids_for_user(db, user)
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
    if selected_calculation and selected_calculation.company_id not in company_ids:
        raise HTTPException(404)
    if selected_calculation:
        company_id = selected_calculation.company_id
        employee_id = selected_calculation.employee_id
    selected_company = db.get(Company, company_id) if company_id in company_ids else None
    selected_employee = db.get(Employee, employee_id) if employee_id else None
    if selected_employee and selected_company and selected_employee.company_id != selected_company.id:
        selected_employee = None
    calculation_inputs = json_dict(selected_calculation.input_json) if selected_calculation else {}
    calculation_results = json_dict(selected_calculation.result_json) if selected_calculation else {}
    branding = get_or_create_branding(db, selected_company) if selected_company else None
    if selected_company:
        db.commit()
    return render(
        request,
        "certificates.html",
        db,
        user,
        companies=companies,
        employees=employees,
        generated=generated,
        certificate_types=CERTIFICATE_TYPES,
        selected_calculation=selected_calculation,
        selected_company=selected_company,
        selected_employee=selected_employee,
        selected_document_type=document_type if document_type in CERTIFICATE_TYPES else "",
        calculation_inputs=calculation_inputs,
        calculation_results=calculation_results,
        branding=branding,
    )


@app.post("/app/certificates")
def create_certificate(
    company_id: Annotated[int, Form()],
    employee_id: Annotated[int, Form()],
    document_type: Annotated[str, Form()],
    city: Annotated[str, Form()] = "Ciudad del Este",
    issue_date: Annotated[date, Form()] = date.today(),
    position: Annotated[str, Form()] = "",
    admission_date: Annotated[date | None, Form()] = None,
    salary: Annotated[int, Form()] = 0,
    observations: Annotated[str, Form()] = "",
    document_number: Annotated[str, Form()] = "",
    period_start: Annotated[date | None, Form()] = None,
    period_end: Annotated[date | None, Form()] = None,
    amount: Annotated[int, Form()] = 0,
    effective_date: Annotated[date | None, Form()] = None,
    leave_start: Annotated[date | None, Form()] = None,
    leave_end: Annotated[date | None, Form()] = None,
    nationality: Annotated[str, Form()] = "paraguaya",
    civil_status: Annotated[str, Form()] = "",
    recipient: Annotated[str, Form()] = "Encargado/a de Recursos Humanos",
    calculation_id: Annotated[int | None, Form()] = None,
    intent: Annotated[str, Form()] = "save",
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    if document_type not in CERTIFICATE_TYPES:
        raise HTTPException(400, "Tipo de documento inválido.")
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
    if not calculation and document_type in {"solicitud_vacacion", "usufructo_vacaciones"}:
        latest_vacation = db.scalar(
            select(Vacation).where(Vacation.employee_id == employee.id).order_by(Vacation.created_at.desc())
        )
        if latest_vacation:
            leave_start = leave_start or latest_vacation.start_date
            leave_end = leave_end or latest_vacation.end_date
            if not observations:
                observations = f"Periodo {latest_vacation.period_year}: {latest_vacation.used_days} de {latest_vacation.entitled_days} días registrados, estado {latest_vacation.status}."
    if document_type in {"aguinaldo_anual", "aguinaldo_proporcional"} and amount <= 0:
        raise HTTPException(400, "El recibo de aguinaldo requiere un cálculo o importe registrado.")
    branding = get_or_create_branding(db, company)
    document_number_value = document_number.strip() or next_document_number(db, company, document_type, branding)
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
    return render(request, "certificate_print.html", db, user, certificate=item, metadata=decode_metadata(item.observations))


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


@app.get("/app/reports", response_class=HTMLResponse)
def reports_page(
    request: Request,
    company_id: int | None = None,
    employee_id: int | None = None,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    company_ids = company_ids_for_user(db, user)
    companies = list(db.scalars(select(Company).where(Company.id.in_(company_ids)).order_by(Company.legal_name))) if company_ids else []
    if company_id not in company_ids:
        company_id = company_ids[0] if company_ids else None
    employees = list(db.scalars(select(Employee).where(Employee.company_id == company_id).order_by(Employee.full_name))) if company_id else []
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
    )


@app.get("/app/reports/export.csv")
def reports_export_csv(
    company_id: int,
    employee_id: int | None = None,
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
        writer.writerow([
            item.created_at.strftime("%d/%m/%Y %H:%M"),
            company.legal_name,
            item.employee.full_name if item.employee else "",
            calculation_label(item.calculation_type),
            item.reference_period,
            item.amount,
            item.status,
            item.source,
            item.created_by,
        ])
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


@app.get("/app/ai", response_class=HTMLResponse)
def ai_page(
    request: Request,
    company_id: int | None = None,
    employee_id: int | None = None,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    company_ids = company_ids_for_user(db, user)
    companies = list(db.scalars(select(Company).where(Company.id.in_(company_ids)).order_by(Company.legal_name))) if company_ids else []
    employees = list(db.scalars(select(Employee).where(Employee.company_id.in_(company_ids)).order_by(Employee.full_name))) if company_ids else []
    selected_company = db.get(Company, company_id) if company_id in company_ids else None
    selected_employee = db.get(Employee, employee_id) if employee_id else None
    if selected_employee and selected_employee.company_id not in company_ids:
        selected_employee = None
    interactions = list(
        db.scalars(
            select(AIInteraction)
            .where(AIInteraction.studio_id == user.studio_id)
            .order_by(AIInteraction.created_at.desc())
            .limit(15)
        )
    )
    latest = db.get(AIInteraction, int(request.query_params["result"])) if request.query_params.get("result", "").isdigit() else None
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
def payrolls_page(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    company_ids = company_ids_for_user(db, user)
    payrolls = list(db.scalars(select(Payroll).where(Payroll.company_id.in_(company_ids)).order_by(Payroll.period.desc(), Payroll.created_at.desc()))) if company_ids else []
    companies = list(db.scalars(select(Company).where(Company.id.in_(company_ids), Company.status == "Activa").order_by(Company.legal_name))) if company_ids else []
    return render(request, "payrolls.html", db, user, payrolls=payrolls, companies=companies)


@app.post("/app/payrolls")
def create_payroll(
    company_id: Annotated[int, Form()],
    period: Annotated[str, Form()],
    notes: Annotated[str, Form()] = "",
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    company_allowed(db, user, company_id)
    if not re.fullmatch(r"\d{4}-\d{2}", period):
        raise HTTPException(400, "Periodo inválido")
    payroll = Payroll(company_id=company_id, period=period, notes=notes.strip(), created_by=user.email)
    db.add(payroll)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(Payroll).where(Payroll.company_id == company_id, Payroll.period == period))
        return RedirectResponse(f"/app/payrolls/{existing.id}" if existing else "/app/payrolls", status_code=303)
    employees = list(db.scalars(select(Employee).where(Employee.company_id == company_id, Employee.status == "Activo").order_by(Employee.full_name)))
    ips_rate = get_parameter(db, "ips_employee_rate_general", 9) / 100
    for employee in employees:
        gross = employee.base_salary
        ips = round(gross * ips_rate) if employee.ips_contributor else 0
        db.add(PayrollLine(payroll_id=payroll.id, employee_id=employee.id, base_salary=employee.base_salary, gross=gross, ips_employee=ips, total_discounts=ips, net=gross - ips))
    db.flush()
    recalculate_payroll(db, payroll)
    write_audit(db, user, "crear", "liquidacion_mensual", str(payroll.id), f"{company_id} / {period}")
    db.commit()
    return RedirectResponse(f"/app/payrolls/{payroll.id}", status_code=303)


@app.get("/app/payrolls/{payroll_id}", response_class=HTMLResponse)
def payroll_detail(request: Request, payroll_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    payroll = db.get(Payroll, payroll_id)
    if not payroll or payroll.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    lines = list(db.scalars(select(PayrollLine).where(PayrollLine.payroll_id == payroll.id).order_by(PayrollLine.id)))
    return render(request, "payroll_detail.html", db, user, payroll=payroll, lines=lines, ips_rate=get_parameter(db, "ips_employee_rate_general", 9))


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
    line.ips_employee = round(line.gross * rate) if line.employee.ips_contributor else 0
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
    payroll.status = status_value
    if status_value == "Cerrada":
        payroll.closed_at = datetime.now(UTC)
        payroll.reviewed_by = user.email
    write_audit(db, user, "actualizar_estado", "liquidacion_mensual", str(payroll.id), status_value)
    db.commit()
    return RedirectResponse(f"/app/payrolls/{payroll_id}", status_code=303)


@app.get("/app/vacations", response_class=HTMLResponse)
def vacations_page(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    company_ids = company_ids_for_user(db, user)
    employees = list(db.scalars(select(Employee).where(Employee.company_id.in_(company_ids), Employee.status == "Activo").order_by(Employee.full_name))) if company_ids else []
    items = list(db.scalars(select(Vacation).join(Employee).where(Employee.company_id.in_(company_ids)).order_by(Vacation.created_at.desc()))) if company_ids else []
    return render(request, "vacations.html", db, user, employees=employees, items=items)


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
    write_audit(db, user, "crear", "vacaciones", str(item.id), employee.full_name)
    db.commit()
    return RedirectResponse("/app/vacations", status_code=303)


@app.get("/app/aguinaldo", response_class=HTMLResponse)
def aguinaldo_page(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    company_ids = company_ids_for_user(db, user)
    employees = list(db.scalars(select(Employee).where(Employee.company_id.in_(company_ids), Employee.status == "Activo").order_by(Employee.full_name))) if company_ids else []
    items = list(db.scalars(select(Aguinaldo).join(Employee).where(Employee.company_id.in_(company_ids)).order_by(Aguinaldo.year.desc(), Aguinaldo.created_at.desc()))) if company_ids else []
    return render(request, "aguinaldo.html", db, user, employees=employees, items=items)


@app.post("/app/aguinaldo")
def create_aguinaldo(
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
    amount = round(max(0, total_remunerations) / 12)
    item = Aguinaldo(employee_id=employee_id, year=year, total_remunerations=max(0, total_remunerations), calculated_amount=amount, notes=notes.strip())
    db.add(item)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return RedirectResponse("/app/aguinaldo?duplicate=1", status_code=303)
    write_audit(db, user, "crear", "aguinaldo", str(item.id), employee.full_name)
    db.commit()
    return RedirectResponse("/app/aguinaldo", status_code=303)


@app.get("/app/documents", response_class=HTMLResponse)
def documents_page(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    company_ids = company_ids_for_user(db, user)
    companies = list(db.scalars(select(Company).where(Company.id.in_(company_ids)).order_by(Company.legal_name))) if company_ids else []
    employees = list(db.scalars(select(Employee).where(Employee.company_id.in_(company_ids)).order_by(Employee.full_name))) if company_ids else []
    documents = list(db.scalars(select(Document).where(Document.company_id.in_(company_ids)).order_by(Document.created_at.desc()))) if company_ids else []
    return render(request, "documents.html", db, user, companies=companies, employees=employees, documents=documents)


@app.post("/app/documents")
async def upload_document(
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
    stored = f"{uuid.uuid4().hex}_{original}"
    (UPLOAD_DIR / stored).write_bytes(content)
    document = Document(company_id=company_id, employee_id=employee_id or None, category=category.strip(), title=title.strip(), stored_name=stored, original_name=original, content_type=file.content_type or "application/octet-stream", uploaded_by=user.email)
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
    path = UPLOAD_DIR / document.stored_name
    if not path.exists():
        raise HTTPException(404, "Archivo no disponible.")
    write_audit(db, user, "descargar", "documento", str(document.id), document.original_name)
    db.commit()
    return FileResponse(path, media_type=document.content_type, filename=document.original_name)


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
    if not secret or not verify_totp(secret, code):
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
    security = get_or_create_security(db, user)
    if not verify_password(password, user.password_hash) or not verify_totp(security.totp_secret, code):
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
    if not verify_password(current_password, user.password_hash):
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
    company_id: Annotated[int | None, Form()] = None,
    user: User = Depends(require_roles("administrador")),
    db: Session = Depends(get_db),
):
    strength_error = password_strength_error(password)
    if strength_error:
        return RedirectResponse(f"/app/users?password_error={quote(strength_error)}", status_code=303)
    if role not in {"administrador", "contador", "auxiliar", "empresa"}:
        raise HTTPException(400)
    if role == "empresa" and not company_id:
        raise HTTPException(400, "Debe seleccionar una empresa.")
    if company_id:
        company_allowed(db, user, company_id)
    item = User(studio_id=user.studio_id, company_id=company_id if role == "empresa" else None, full_name=full_name.strip(), email=email.strip().lower(), password_hash=hash_password(password), role=role, must_change_password=True)
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
def parameters_page(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    parameters = list(db.scalars(select(LaborParameter).where(LaborParameter.active.is_(True)).order_by(LaborParameter.label)))
    return render(request, "parameters.html", db, user, parameters=parameters)


@app.get("/app/audit", response_class=HTMLResponse)
def audit_page(request: Request, user: User = Depends(require_roles("administrador")), db: Session = Depends(get_db)):
    logs = list(db.scalars(select(AuditLog).where(AuditLog.studio_id == user.studio_id).order_by(AuditLog.created_at.desc()).limit(300)))
    return render(request, "audit.html", db, user, logs=logs)


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
        writer.writerow([item.company.legal_name, item.company.ruc, item.full_name, item.document_number, item.position, item.admission_date.isoformat(), item.base_salary, "Sí" if item.ips_contributor else "No", item.status])
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
def health(db: Session = Depends(get_db)):
    db.scalar(select(func.count(User.id)))
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment, "version": "1.9.0-preview"}
