from __future__ import annotations

import csv
import io
import json
import os
import re
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime
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
    EmployeeHistory,
    LaborArticle,
    LaborParameter,
    Payroll,
    PayrollLine,
    PayrollNovelty,
    RequestAttachment,
    RequestEvent,
    RequestWorkflow,
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


app = FastAPI(title="Digit Laboral", version="0.13.0", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    same_site="lax",
    https_only=settings.secure_cookies,
    max_age=60 * 60 * 12,
)
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


def employee_allowed(db: Session, user: User, employee_id: int) -> Employee:
    employee = db.get(Employee, employee_id)
    if not employee or employee.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404, "Funcionario no encontrado.")
    return employee


def branch_allowed(db: Session, user: User, branch_id: int) -> Branch:
    branch = db.get(Branch, branch_id)
    if not branch or branch.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404, "Sucursal no encontrada.")
    return branch


def add_employee_history(
    db: Session,
    user: User,
    employee: Employee,
    event_type: str,
    effective_date: date | None = None,
    previous_value: str = "",
    new_value: str = "",
    detail: str = "",
) -> None:
    db.add(
        EmployeeHistory(
            employee_id=employee.id,
            event_type=event_type,
            effective_date=effective_date or date.today(),
            previous_value=previous_value,
            new_value=new_value,
            detail=detail,
            created_by=user.email,
        )
    )


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


def request_payload(item: CompanyRequest) -> dict:
    if not item.workflow or not item.workflow.payload_json:
        return {}
    try:
        value = json.loads(item.workflow.payload_json)
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def optional_int(value: str | int | None) -> int:
    if value is None or value == "":
        return 0
    try:
        return max(0, int(str(value).replace(".", "").replace(",", "")))
    except ValueError:
        return 0


def optional_float(value: str | float | None) -> float:
    if value is None or value == "":
        return 0
    try:
        return max(0, float(str(value).replace(",", ".")))
    except ValueError:
        return 0


def optional_date(value: str | date | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        return None


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
    user.last_login_at = datetime.utcnow()
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
    company_users = list(db.scalars(select(User).where(User.company_id == company_id).order_by(User.full_name)))
    active_employees = sum(1 for item in employees if item.status == "Activo")
    return render(
        request,
        "company_detail.html",
        db,
        user,
        company=company,
        employees=employees,
        active_employees=active_employees,
        requests_list=requests_list,
        branches=branches,
        payrolls=payrolls,
        documents=documents,
        company_users=company_users,
    )


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


@app.post("/app/branches/{branch_id}/edit")
def edit_branch(
    branch_id: int,
    name: Annotated[str, Form()],
    city: Annotated[str, Form()] = "",
    address: Annotated[str, Form()] = "",
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    branch = branch_allowed(db, user, branch_id)
    branch.name = name.strip()
    branch.city = city.strip()
    branch.address = address.strip()
    write_audit(db, user, "editar", "sucursal", str(branch.id), branch.name)
    db.commit()
    return RedirectResponse(f"/app/companies/{branch.company_id}", status_code=303)


@app.post("/app/branches/{branch_id}/toggle")
def toggle_branch(
    branch_id: int,
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    branch = branch_allowed(db, user, branch_id)
    branch.active = not branch.active
    write_audit(db, user, "actualizar_estado", "sucursal", str(branch.id), "Activa" if branch.active else "Inactiva")
    db.commit()
    return RedirectResponse(f"/app/companies/{branch.company_id}", status_code=303)


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
    add_employee_history(
        db, user, employee, "Alta", employee.admission_date, "", "Activo",
        f"Ingreso a {employee.company.legal_name if employee.company else 'la empresa'} como {employee.position}.",
    )
    add_employee_history(db, user, employee, "Salario inicial", employee.admission_date, "", str(employee.base_salary), "Remuneración base registrada al alta.")
    write_audit(db, user, "crear", "funcionario", str(employee.id), employee.full_name)
    db.commit()
    return RedirectResponse(f"/app/employees/{employee.id}", status_code=303)


@app.get("/app/employees/{employee_id}", response_class=HTMLResponse)
def employee_detail(
    request: Request,
    employee_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    employee = employee_allowed(db, user, employee_id)
    branches = list(db.scalars(select(Branch).where(Branch.company_id == employee.company_id).order_by(Branch.name)))
    history = list(db.scalars(select(EmployeeHistory).where(EmployeeHistory.employee_id == employee_id).order_by(EmployeeHistory.effective_date.desc(), EmployeeHistory.created_at.desc())))
    payroll_lines = list(db.scalars(select(PayrollLine).where(PayrollLine.employee_id == employee_id).order_by(PayrollLine.id.desc()).limit(8)))
    vacations = list(db.scalars(select(Vacation).where(Vacation.employee_id == employee_id).order_by(Vacation.period_year.desc()).limit(6)))
    documents = list(db.scalars(select(Document).where(Document.employee_id == employee_id).order_by(Document.created_at.desc()).limit(8)))
    minimum_salary = db.scalar(select(LaborParameter).where(LaborParameter.key == "minimum_monthly_salary_general", LaborParameter.active.is_(True)))
    return render(
        request,
        "employee_detail.html",
        db,
        user,
        employee=employee,
        branches=branches,
        history=history,
        payroll_lines=payroll_lines,
        vacations=vacations,
        documents=documents,
        minimum_salary=minimum_salary,
    )


@app.post("/app/employees/{employee_id}/edit")
def edit_employee(
    employee_id: int,
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
    employee = employee_allowed(db, user, employee_id)
    previous_salary = employee.base_salary
    previous_position = employee.position
    if branch_id:
        branch = branch_allowed(db, user, branch_id)
        if branch.company_id != employee.company_id:
            raise HTTPException(400, "La sucursal no pertenece a la empresa del funcionario.")
    employee.full_name = full_name.strip()
    employee.document_number = document_number.strip()
    employee.birth_date = birth_date
    employee.position = position_name.strip()
    employee.admission_date = admission_date
    employee.contract_type = contract_type.strip()
    employee.payment_frequency = payment_frequency.strip()
    employee.branch_id = branch_id or None
    employee.base_salary = max(0, base_salary)
    employee.ips_contributor = ips_contributor == "on"
    employee.email = email.strip()
    employee.phone = phone.strip()
    employee.address = address.strip()
    employee.notes = notes.strip()
    if previous_salary != employee.base_salary:
        add_employee_history(db, user, employee, "Cambio salarial", date.today(), str(previous_salary), str(employee.base_salary), "Actualización desde el expediente del funcionario.")
    if previous_position != employee.position:
        add_employee_history(db, user, employee, "Cambio de cargo", date.today(), previous_position, employee.position, "Actualización de datos laborales.")
    write_audit(db, user, "editar", "funcionario", str(employee.id), employee.full_name)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return RedirectResponse(f"/app/employees/{employee_id}?duplicate=1", status_code=303)
    return RedirectResponse(f"/app/employees/{employee_id}?saved=1", status_code=303)


@app.post("/app/employees/{employee_id}/salary")
def update_employee_salary(
    employee_id: int,
    new_salary: Annotated[int, Form()],
    effective_date: Annotated[date, Form()],
    reason: Annotated[str, Form()] = "",
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    employee = employee_allowed(db, user, employee_id)
    previous_salary = employee.base_salary
    employee.base_salary = max(0, new_salary)
    add_employee_history(
        db, user, employee, "Cambio salarial", effective_date, str(previous_salary), str(employee.base_salary),
        reason.strip() or "Actualización de salario base.",
    )
    write_audit(db, user, "cambiar_salario", "funcionario", str(employee.id), f"{previous_salary} → {employee.base_salary}")
    db.commit()
    return RedirectResponse(f"/app/employees/{employee_id}?salary=1", status_code=303)


@app.post("/app/employees/{employee_id}/status")
def employee_status(
    employee_id: int,
    status_value: Annotated[str, Form(alias="status")],
    termination_date: Annotated[date | None, Form()] = None,
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    employee = employee_allowed(db, user, employee_id)
    previous_status = employee.status
    employee.status = status_value
    employee.termination_date = termination_date if status_value != "Activo" else None
    add_employee_history(
        db, user, employee, "Cambio de estado", termination_date or date.today(), previous_status, status_value,
        "Actualización del vínculo laboral.",
    )
    write_audit(db, user, "actualizar_estado", "funcionario", str(employee.id), status_value)
    db.commit()
    return RedirectResponse(f"/app/employees/{employee_id}?status=1", status_code=303)


@app.get("/app/requests", response_class=HTMLResponse)
def requests_page(
    request: Request,
    q: str = "",
    status_filter: str = "",
    type_filter: str = "",
    company_filter: int | None = None,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    company_ids = company_ids_for_user(db, user)
    query = select(CompanyRequest).where(CompanyRequest.company_id.in_(company_ids)) if company_ids else select(CompanyRequest).where(CompanyRequest.id == -1)
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.where(or_(CompanyRequest.subject.ilike(term), CompanyRequest.detail.ilike(term), CompanyRequest.request_type.ilike(term)))
    if status_filter.strip():
        query = query.where(CompanyRequest.status == status_filter)
    if type_filter.strip():
        query = query.where(CompanyRequest.request_type == type_filter)
    if company_filter and company_filter in company_ids:
        query = query.where(CompanyRequest.company_id == company_filter)
    items = list(db.scalars(query.order_by(CompanyRequest.created_at.desc())))
    companies = list(db.scalars(select(Company).where(Company.id.in_(company_ids)).order_by(Company.legal_name))) if company_ids else []
    employees = list(db.scalars(select(Employee).where(Employee.company_id.in_(company_ids), Employee.status == "Activo").order_by(Employee.full_name))) if company_ids else []
    studio_users = list(db.scalars(select(User).where(User.studio_id == user.studio_id, User.role.in_(["administrador", "contador", "auxiliar"]), User.active.is_(True)).order_by(User.full_name))) if user.studio_id else []
    statuses = ["Pendiente", "En revisión", "Requiere corrección", "Aprobada", "Rechazada", "Aplicada"]
    request_types = [
        "Alta de funcionario", "Baja de funcionario", "Cambio salarial", "Cambio de cargo",
        "Vacaciones", "Ausencia o reposo", "Horas extra", "Bonificación o descuento",
        "Documento laboral", "Otra consulta",
    ]
    counts = {name: 0 for name in statuses}
    for value, total in db.execute(select(CompanyRequest.status, func.count(CompanyRequest.id)).where(CompanyRequest.company_id.in_(company_ids)).group_by(CompanyRequest.status)) if company_ids else []:
        counts[value] = total
    return render(
        request, "requests.html", db, user, items=items, companies=companies, employees=employees,
        studio_users=studio_users, statuses=statuses, request_types=request_types, counts=counts,
        q=q, status_filter=status_filter, type_filter=type_filter, company_filter=company_filter,
        files_enabled=settings.files_enabled,
    )


@app.post("/app/requests")
async def add_request(
    request_type: Annotated[str, Form()],
    detail: Annotated[str, Form()],
    company_id: Annotated[str, Form()] = "",
    subject: Annotated[str, Form()] = "",
    priority: Annotated[str, Form()] = "Normal",
    employee_id: Annotated[str, Form()] = "",
    effective_date: Annotated[str, Form()] = "",
    period: Annotated[str, Form()] = "",
    full_name: Annotated[str, Form()] = "",
    document_number: Annotated[str, Form()] = "",
    position: Annotated[str, Form()] = "",
    new_position: Annotated[str, Form()] = "",
    base_salary: Annotated[str, Form()] = "",
    amount: Annotated[str, Form()] = "",
    quantity: Annotated[str, Form()] = "",
    movement_kind: Annotated[str, Form()] = "Bonificación",
    start_date: Annotated[str, Form()] = "",
    end_date: Annotated[str, Form()] = "",
    period_year: Annotated[str, Form()] = "",
    entitled_days: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "",
    phone: Annotated[str, Form()] = "",
    ips_contributor: Annotated[str | None, Form()] = None,
    attachment: UploadFile | None = File(None),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    company_id_value = optional_int(company_id) or None
    employee_id_value = optional_int(employee_id) or None
    effective_date_value = optional_date(effective_date)
    start_date_value = optional_date(start_date)
    end_date_value = optional_date(end_date)
    period_year_value = optional_int(period_year) or None
    entitled_days_value = optional_int(entitled_days) or None

    if user.role == "empresa":
        company_id_value = user.company_id
    if not company_id_value:
        raise HTTPException(400, "Debe seleccionar una empresa.")
    company = company_allowed(db, user, company_id_value)
    if employee_id_value:
        employee = db.get(Employee, employee_id_value)
        if not employee or employee.company_id != company.id:
            raise HTTPException(400, "Funcionario inválido para la empresa seleccionada.")
    payload = {
        "employee_id": employee_id_value,
        "effective_date": effective_date_value.isoformat() if effective_date_value else "",
        "period": period.strip(),
        "full_name": full_name.strip(),
        "document_number": document_number.strip(),
        "position": position.strip(),
        "new_position": new_position.strip(),
        "base_salary": optional_int(base_salary),
        "amount": optional_int(amount),
        "quantity": optional_float(quantity),
        "movement_kind": movement_kind.strip(),
        "start_date": start_date_value.isoformat() if start_date_value else "",
        "end_date": end_date_value.isoformat() if end_date_value else "",
        "period_year": period_year_value,
        "entitled_days": entitled_days_value,
        "email": email.strip().lower(),
        "phone": phone.strip(),
        "ips_contributor": ips_contributor == "on",
    }
    item = CompanyRequest(
        company_id=company.id,
        request_type=request_type.strip(),
        subject=subject.strip() or request_type.strip(),
        detail=detail.strip(),
        priority=priority,
        status="Pendiente",
    )
    db.add(item)
    db.flush()
    workflow = RequestWorkflow(
        request_id=item.id,
        employee_id=employee_id_value,
        period=period.strip(),
        effective_date=effective_date_value,
        requested_by=user.email,
        payload_json=json.dumps(payload, ensure_ascii=False),
    )
    db.add(workflow)
    db.add(RequestEvent(request_id=item.id, event_type="Creación", status="Pendiente", note="Solicitud enviada al estudio contable.", user_email=user.email))
    if attachment and attachment.filename:
        if not settings.files_enabled:
            raise HTTPException(409, "La carga de archivos no está habilitada en este entorno.")
        if attachment.content_type not in ALLOWED_UPLOAD_TYPES:
            raise HTTPException(400, "Formato no permitido.")
        content = await attachment.read(MAX_UPLOAD_SIZE + 1)
        if len(content) > MAX_UPLOAD_SIZE:
            raise HTTPException(413, "El archivo supera 10 MB.")
        original = safe_filename(attachment.filename)
        stored = f"request_{item.id}_{uuid.uuid4().hex}_{original}"
        (UPLOAD_DIR / stored).write_bytes(content)
        db.add(RequestAttachment(request_id=item.id, stored_name=stored, original_name=original, content_type=attachment.content_type or "application/octet-stream", uploaded_by=user.email))
    write_audit(db, user, "crear", "solicitud", str(item.id), request_type)
    db.commit()
    return RedirectResponse(f"/app/requests/{item.id}?created=1", status_code=303)


@app.get("/app/requests/{request_id}", response_class=HTMLResponse)
def request_detail(request: Request, request_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    item = db.get(CompanyRequest, request_id)
    if not item or item.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    workflow = item.workflow
    payload = request_payload(item)
    employees = list(db.scalars(select(Employee).where(Employee.company_id == item.company_id).order_by(Employee.full_name)))
    studio_users = list(db.scalars(select(User).where(User.studio_id == user.studio_id, User.role.in_(["administrador", "contador", "auxiliar"]), User.active.is_(True)).order_by(User.full_name))) if user.studio_id else []
    return render(
        request, "request_detail.html", db, user, item=item, workflow=workflow, payload=payload,
        employees=employees, studio_users=studio_users, files_enabled=settings.files_enabled,
        created=request.query_params.get("created") == "1", applied=request.query_params.get("applied") == "1",
        error=request.query_params.get("error", ""),
    )


@app.post("/app/requests/{request_id}/review")
def request_review(
    request_id: int,
    status_value: Annotated[str, Form(alias="status")],
    response: Annotated[str, Form()] = "",
    assigned_to: Annotated[str, Form()] = "",
    correction_note: Annotated[str, Form()] = "",
    user: User = Depends(require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(get_db),
):
    item = db.get(CompanyRequest, request_id)
    if not item or item.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    allowed_statuses = {"Pendiente", "En revisión", "Requiere corrección", "Aprobada", "Rechazada", "Aplicada"}
    if status_value not in allowed_statuses:
        raise HTTPException(400, "Estado inválido.")
    workflow = item.workflow or RequestWorkflow(request_id=item.id, requested_by="")
    if workflow.id is None:
        db.add(workflow)
    workflow.assigned_to = assigned_to.strip()
    workflow.correction_note = correction_note.strip()
    item.status = status_value
    item.response = response.strip()
    if status_value in {"Rechazada", "Aplicada"}:
        item.resolved_at = datetime.utcnow()
    elif status_value not in {"Rechazada", "Aplicada"}:
        item.resolved_at = None
    note = response.strip() or correction_note.strip() or f"Estado actualizado a {status_value}."
    db.add(RequestEvent(request_id=item.id, event_type="Revisión", status=status_value, note=note, user_email=user.email))
    write_audit(db, user, "actualizar_estado", "solicitud", str(item.id), status_value)
    db.commit()
    return RedirectResponse(f"/app/requests/{item.id}", status_code=303)


@app.post("/app/requests/{request_id}/attachment")
async def request_add_attachment(
    request_id: int,
    attachment: UploadFile = File(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    item = db.get(CompanyRequest, request_id)
    if not item or item.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    if not settings.files_enabled:
        return RedirectResponse(f"/app/requests/{request_id}?error=files", status_code=303)
    if attachment.content_type not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(400, "Formato no permitido.")
    content = await attachment.read(MAX_UPLOAD_SIZE + 1)
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(413, "El archivo supera 10 MB.")
    original = safe_filename(attachment.filename or "archivo")
    stored = f"request_{item.id}_{uuid.uuid4().hex}_{original}"
    (UPLOAD_DIR / stored).write_bytes(content)
    db.add(RequestAttachment(request_id=item.id, stored_name=stored, original_name=original, content_type=attachment.content_type or "application/octet-stream", uploaded_by=user.email))
    db.add(RequestEvent(request_id=item.id, event_type="Documento", status=item.status, note=f"Archivo adjunto: {original}", user_email=user.email))
    write_audit(db, user, "subir", "adjunto_solicitud", str(item.id), original)
    db.commit()
    return RedirectResponse(f"/app/requests/{request_id}", status_code=303)


@app.get("/app/requests/{request_id}/attachments/{attachment_id}")
def request_download_attachment(request_id: int, attachment_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    item = db.get(CompanyRequest, request_id)
    attachment = db.get(RequestAttachment, attachment_id)
    if not item or not attachment or attachment.request_id != item.id or item.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    path = UPLOAD_DIR / attachment.stored_name
    if not path.exists():
        raise HTTPException(404, "Archivo no disponible.")
    write_audit(db, user, "descargar", "adjunto_solicitud", str(attachment.id), attachment.original_name)
    db.commit()
    return FileResponse(path, media_type=attachment.content_type, filename=attachment.original_name)


@app.post("/app/requests/{request_id}/apply")
def request_apply(
    request_id: int,
    user: User = Depends(require_roles("administrador", "contador")),
    db: Session = Depends(get_db),
):
    item = db.get(CompanyRequest, request_id)
    if not item or item.company_id not in company_ids_for_user(db, user):
        raise HTTPException(404)
    if item.status != "Aprobada":
        return RedirectResponse(f"/app/requests/{item.id}?error=approval", status_code=303)
    workflow = item.workflow
    if not workflow or workflow.applied:
        return RedirectResponse(f"/app/requests/{item.id}?error=applied", status_code=303)
    payload = request_payload(item)
    effective = workflow.effective_date or date.today()
    employee = db.get(Employee, workflow.employee_id) if workflow.employee_id else None
    if employee and employee.company_id != item.company_id:
        raise HTTPException(400, "Funcionario inválido.")

    if item.request_type == "Alta de funcionario":
        if not payload.get("full_name") or not payload.get("document_number"):
            return RedirectResponse(f"/app/requests/{item.id}?error=data", status_code=303)
        employee = Employee(
            company_id=item.company_id,
            full_name=payload.get("full_name", "").strip(),
            document_number=payload.get("document_number", "").strip(),
            position=payload.get("position", "").strip(),
            admission_date=effective,
            base_salary=optional_int(payload.get("base_salary")),
            ips_contributor=bool(payload.get("ips_contributor", True)),
            email=payload.get("email", "").strip(),
            phone=payload.get("phone", "").strip(),
            status="Activo",
        )
        db.add(employee)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return RedirectResponse(f"/app/requests/{item.id}?error=duplicate", status_code=303)
        workflow.employee_id = employee.id
        add_employee_history(db, user, employee, "Alta", effective, "", "Activo", f"Creado desde la solicitud #{item.id}.")
    elif item.request_type == "Baja de funcionario":
        if not employee:
            return RedirectResponse(f"/app/requests/{item.id}?error=employee", status_code=303)
        previous = employee.status
        employee.status = "Inactivo"
        employee.termination_date = effective
        add_employee_history(db, user, employee, "Baja", effective, previous, "Inactivo", f"Aplicada desde la solicitud #{item.id}.")
    elif item.request_type == "Cambio salarial":
        if not employee or optional_int(payload.get("amount")) <= 0:
            return RedirectResponse(f"/app/requests/{item.id}?error=data", status_code=303)
        previous = employee.base_salary
        employee.base_salary = optional_int(payload.get("amount"))
        add_employee_history(db, user, employee, "Cambio salarial", effective, str(previous), str(employee.base_salary), f"Aplicado desde la solicitud #{item.id}.")
    elif item.request_type == "Cambio de cargo":
        if not employee or not payload.get("new_position"):
            return RedirectResponse(f"/app/requests/{item.id}?error=data", status_code=303)
        previous = employee.position
        employee.position = payload.get("new_position", "").strip()
        add_employee_history(db, user, employee, "Cambio de cargo", effective, previous, employee.position, f"Aplicado desde la solicitud #{item.id}.")
    elif item.request_type == "Vacaciones":
        if not employee:
            return RedirectResponse(f"/app/requests/{item.id}?error=employee", status_code=303)
        start = date.fromisoformat(payload["start_date"]) if payload.get("start_date") else None
        end = date.fromisoformat(payload["end_date"]) if payload.get("end_date") else None
        year = int(payload.get("period_year") or (start.year if start else effective.year))
        days = int(payload.get("entitled_days") or payload.get("quantity") or 0)
        db.add(Vacation(employee_id=employee.id, period_year=year, entitled_days=max(0, days), used_days=max(0, days), start_date=start, end_date=end, status="Aprobada", notes=f"Generado desde solicitud #{item.id}. {item.detail}"))
    elif item.request_type in {"Ausencia o reposo", "Horas extra", "Bonificación o descuento"}:
        if not employee:
            return RedirectResponse(f"/app/requests/{item.id}?error=employee", status_code=303)
        period = workflow.period or effective.strftime("%Y-%m")
        amount = optional_int(payload.get("amount"))
        movement = payload.get("movement_kind", "Bonificación")
        income = amount if item.request_type == "Horas extra" or movement == "Bonificación" else 0
        discount = amount if item.request_type == "Bonificación o descuento" and movement == "Descuento" else 0
        start = date.fromisoformat(payload["start_date"]) if payload.get("start_date") else None
        end = date.fromisoformat(payload["end_date"]) if payload.get("end_date") else None
        db.add(PayrollNovelty(
            company_id=item.company_id,
            employee_id=employee.id,
            request_id=item.id,
            period=period,
            novelty_type=item.request_type,
            concept=item.subject,
            quantity=optional_float(payload.get("quantity")),
            income_amount=income,
            discount_amount=discount,
            date_from=start,
            date_to=end,
            status="Pendiente",
            notes=item.detail,
            created_by=user.email,
        ))

    workflow.applied = True
    workflow.applied_at = datetime.utcnow()
    workflow.applied_by = user.email
    item.status = "Aplicada"
    item.resolved_at = datetime.utcnow()
    if not item.response:
        item.response = "Solicitud aprobada y aplicada al registro laboral."
    db.add(RequestEvent(request_id=item.id, event_type="Aplicación", status="Aplicada", note="La solicitud fue incorporada a los registros del sistema.", user_email=user.email))
    write_audit(db, user, "aplicar", "solicitud", str(item.id), item.request_type)
    db.commit()
    return RedirectResponse(f"/app/requests/{item.id}?applied=1", status_code=303)


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
        payroll.closed_at = datetime.utcnow()
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
    return render(request, "documents.html", db, user, companies=companies, employees=employees, documents=documents, files_enabled=settings.files_enabled, disabled=request.query_params.get("disabled") == "1")


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
    if not settings.files_enabled:
        return RedirectResponse("/app/documents?disabled=1", status_code=303)
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
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment, "version": "0.11.0"}
