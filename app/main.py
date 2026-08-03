from __future__ import annotations

import csv
import io
import json
import os
import re
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

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
from .database import Base, SessionLocal, engine
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
    GeneratedCertificate,
    LaborArticle,
    LaborParameter,
    Payroll,
    PayrollLine,
    Studio,
    User,
    Vacation,
)
from .report_export import build_employee_report_pdf
from .seed import seed_database

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_UPLOAD_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
MAX_UPLOAD_SIZE = 10 * 1024 * 1024


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    seed_database()
    yield


if settings.environment == "production" and settings.secret_key == "cambiar-esta-clave-en-produccion":
    raise RuntimeError("DIGIT_SECRET_KEY debe configurarse con una clave segura en producción.")

app = FastAPI(title="Digit Laboral", version="1.4.0-preview", lifespan=lifespan)
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
    return db.get(User, int(user_id))


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


def render(request: Request, template: str, db: Session, user: User | None = None, **context):
    data = {
        "request": request,
        "user": user,
        "active_path": request.url.path,
        "today": date.today(),
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
    user = db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
    if not user or not verify_password(password, user.password_hash) or not user.active:
        return render(request, "login.html", db, error="Correo o contraseña incorrectos.")
    if user.role != "superadmin" and user.studio and (not user.studio.active or user.studio.payment_status != "Activo"):
        return render(request, "login.html", db, error="La cuenta todavía no está habilitada o su plan se encuentra suspendido.")
    request.session.clear()
    request.session["user_id"] = user.id
    user.last_login_at = datetime.now(UTC)
    write_audit(db, user, "inicio_sesion", "usuario", str(user.id))
    db.commit()
    return RedirectResponse("/admin" if user.role == "superadmin" else "/app", status_code=303)


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
    pending_count = db.scalar(select(func.count(CompanyRequest.id)).where(CompanyRequest.company_id.in_(company_ids), CompanyRequest.status.in_(["Pendiente", "En revisión"]))) if company_ids else 0
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
        branding.logo_bytes = content
        branding.logo_content_type = "image/png" if is_png else "image/jpeg"
        branding.logo_filename = safe_filename(logo.filename)
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
    write_audit(db, user, "crear", "funcionario", str(employee.id), employee.full_name)
    db.commit()
    return RedirectResponse("/app/employees", status_code=303)


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
    employee.full_name = full_name.strip()
    employee.position = position_name.strip()
    employee.base_salary = max(0, base_salary)
    employee.email = email.strip()
    employee.phone = phone.strip()
    employee.address = address.strip()
    employee.notes = notes.strip()
    write_audit(db, user, "editar", "funcionario", str(employee.id), employee.full_name)
    db.commit()
    return RedirectResponse("/app/employees", status_code=303)


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
    write_audit(db, user, "actualizar_estado", "funcionario", str(employee.id), status_value)
    db.commit()
    return RedirectResponse("/app/employees", status_code=303)


@app.get("/app/requests", response_class=HTMLResponse)
def requests_page(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    company_ids = company_ids_for_user(db, user)
    items = list(db.scalars(select(CompanyRequest).where(CompanyRequest.company_id.in_(company_ids)).order_by(CompanyRequest.created_at.desc()))) if company_ids else []
    companies = list(db.scalars(select(Company).where(Company.id.in_(company_ids)).order_by(Company.legal_name))) if company_ids else []
    return render(request, "requests.html", db, user, items=items, companies=companies)


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


@app.post("/app/requests/{request_id}/status")
def request_status(
    request_id: int,
    status_value: Annotated[str, Form(alias="status")],
    response: Annotated[str, Form()] = "",
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    item = db.get(CompanyRequest, request_id)
    if not item or item.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    item.status = status_value
    item.response = response.strip()
    if status_value in {"Resuelta", "Rechazada"}:
        item.resolved_at = datetime.now(UTC)
    write_audit(db, user, "actualizar_estado", "solicitud", str(item.id), status_value)
    db.commit()
    return RedirectResponse("/app/requests", status_code=303)


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


@app.get("/app/users", response_class=HTMLResponse)
def users_page(request: Request, user: User = Depends(require_roles("administrador")), db: Session = Depends(get_db)):
    users = list(db.scalars(select(User).where(User.studio_id == user.studio_id).order_by(User.full_name)))
    companies = list(db.scalars(select(Company).where(Company.studio_id == user.studio_id).order_by(Company.legal_name)))
    return render(request, "users.html", db, user, users=users, companies=companies)


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
    db.commit()
    return RedirectResponse("/app/users", status_code=303)


@app.get("/app/labor-code", response_class=HTMLResponse)
def labor_code_page(request: Request, q: str = "", category: str = "", user: User = Depends(require_user), db: Session = Depends(get_db)):
    query = select(LaborArticle)
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.where(or_(LaborArticle.article_number.ilike(term), LaborArticle.heading.ilike(term), LaborArticle.body.ilike(term)))
    if category.strip():
        query = query.where(LaborArticle.category == category)
    articles = list(db.scalars(query.order_by(LaborArticle.category, LaborArticle.article_number)))
    categories = list(db.scalars(select(LaborArticle.category).distinct().order_by(LaborArticle.category)))
    return render(request, "labor_code.html", db, user, articles=articles, categories=categories, q=q, category=category)


@app.get("/app/parameters", response_class=HTMLResponse)
def parameters_page(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    parameters = list(db.scalars(select(LaborParameter).where(LaborParameter.active.is_(True)).order_by(LaborParameter.label)))
    return render(request, "parameters.html", db, user, parameters=parameters)


@app.get("/app/audit", response_class=HTMLResponse)
def audit_page(request: Request, user: User = Depends(require_roles("administrador")), db: Session = Depends(get_db)):
    logs = list(db.scalars(select(AuditLog).where(AuditLog.studio_id == user.studio_id).order_by(AuditLog.created_at.desc()).limit(300)))
    return render(request, "audit.html", db, user, logs=logs)


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
    return render(request, "admin.html", db, user, studios=studios, requests_list=requests_list, total_companies=total_companies, total_users=total_users)


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
    studio = Studio(name=name.strip(), phone=phone.strip(), plan_name=plan_name, company_limit=max(1, company_limit), payment_status="Activo")
    db.add(studio)
    try:
        db.flush()
        owner = User(studio_id=studio.id, full_name=owner_name.strip(), email=owner_email.strip().lower(), password_hash=hash_password(temporary_password), role="administrador", must_change_password=True)
        db.add(owner)
        db.flush()
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
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment, "version": "1.4.0-preview"}
