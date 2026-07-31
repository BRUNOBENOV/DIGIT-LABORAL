from __future__ import annotations

import csv
import io
import os
import re
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .auth import hash_password, verify_password
from .config import settings
from .database import Base, SessionLocal, engine
from .models import (
    ActivationRequest,
    Aguinaldo,
    AuditLog,
    Branch,
    Company,
    CompanyRequest,
    Document,
    Employee,
    LaborArticle,
    LaborParameter,
    Payroll,
    PayrollLine,
    Studio,
    User,
    Vacation,
)
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

app = FastAPI(title="Digit Laboral", version="1.0.0-preview", lifespan=lifespan)
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
    return render(request, "company_detail.html", db, user, company=company, employees=employees, requests_list=requests_list, branches=branches, payrolls=payrolls, documents=documents)


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
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment, "version": "1.0.0-preview"}
