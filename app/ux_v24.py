from __future__ import annotations

import inspect
import json
from datetime import date
from urllib.parse import quote

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import main as core
from .labor_rules import (
    aguinaldo_amount,
    preaviso_days,
    validate_date_range,
    validate_vacation_usage,
    vacation_amount,
    vacation_entitlement_days,
)
from .models import Branch, CalculationRecord, Employee, Payroll, PayrollLine, User

app = core.app


def _take_route(path: str, method: str):
    method = method.upper()
    endpoint = None
    kept = []
    for route in app.router.routes:
        methods = getattr(route, "methods", set()) or set()
        if getattr(route, "path", None) == path and method in methods:
            endpoint = getattr(route, "endpoint", None)
            continue
        kept.append(route)
    app.router.routes[:] = kept
    if endpoint is None:
        raise RuntimeError(f"No se encontró la ruta que v2.4 necesita reforzar: {method} {path}")
    return endpoint


async def _invoke(endpoint, **kwargs):
    result = endpoint(**kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


def _clean(value, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _int(value, default: int = 0) -> int:
    try:
        return int(str(value or "").strip())
    except (TypeError, ValueError):
        return default


def _float(value, default: float = 0.0) -> float:
    try:
        return float(str(value or "").strip().replace(",", "."))
    except (TypeError, ValueError):
        return default


def _date(value) -> date | None:
    text = _clean(value, 20)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _error(path: str, message: str, modal: str = "") -> RedirectResponse:
    separator = "&" if "?" in path else "?"
    target = f"{path}{separator}form_error={quote(message)}"
    if modal:
        target += f"&open={quote(modal)}"
    return RedirectResponse(target, status_code=303)


def _valid_email(value: str) -> bool:
    if not value:
        return True
    if len(value) > 180 or value.count("@") != 1:
        return False
    local, domain = value.rsplit("@", 1)
    return bool(local and "." in domain and not domain.startswith(".") and not domain.endswith("."))


_original_create_company = _take_route("/app/companies", "POST")
_original_create_employee = _take_route("/app/employees", "POST")
_original_employee_status = _take_route("/app/employees/{employee_id}/status", "POST")
_original_create_vacation = _take_route("/app/vacations", "POST")
_take_route("/app/calculations", "POST")
_take_route("/app/payrolls/{payroll_id}/lines/{line_id}", "POST")


@app.post("/app/companies")
async def create_company_v24(
    request: Request,
    user: User = Depends(core.require_roles("administrador", "contador")),
    db: Session = Depends(core.get_db),
):
    form = await request.form()
    legal_name = _clean(form.get("legal_name"), 200)
    ruc = _clean(form.get("ruc"), 40)
    email = _clean(form.get("email"), 180).lower()
    if len(legal_name) < 2:
        return _error("/app/companies", "Ingresá una razón social válida.", "companyModal")
    if len(ruc) < 5 or not any(char.isdigit() for char in ruc):
        return _error("/app/companies", "Revisá el RUC. Debe contener una identificación válida.", "companyModal")
    if email and not _valid_email(email):
        return _error("/app/companies", "El correo de la empresa no tiene un formato válido.", "companyModal")
    return await _invoke(
        _original_create_company,
        legal_name=legal_name,
        trade_name=_clean(form.get("trade_name"), 160),
        ruc=ruc,
        city=_clean(form.get("city"), 100),
        address=_clean(form.get("address"), 240),
        phone=_clean(form.get("phone"), 60),
        email=email,
        legal_representative=_clean(form.get("legal_representative"), 180),
        ips_employer_number=_clean(form.get("ips_employer_number"), 80),
        mtess_employer_number=_clean(form.get("mtess_employer_number"), 80),
        responsible_name=_clean(form.get("responsible_name"), 160),
        user=user,
        db=db,
    )


@app.post("/app/employees")
async def create_employee_v24(
    request: Request,
    user: User = Depends(core.require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(core.get_db),
):
    form = await request.form()
    company_id = _int(form.get("company_id"))
    company = core.company_allowed(db, user, company_id)
    full_name = _clean(form.get("full_name"), 180)
    document_number = _clean(form.get("document_number"), 40)
    position = _clean(form.get("position"), 140)
    birth_date = _date(form.get("birth_date"))
    admission_date = _date(form.get("admission_date"))
    branch_id = _int(form.get("branch_id")) or None
    base_salary = _int(form.get("base_salary"), -1)
    email = _clean(form.get("email"), 180).lower()

    if len(full_name) < 3:
        return _error(f"/app/employees?company_id={company.id}", "Ingresá el nombre completo del funcionario.", "employeeModal")
    if len(document_number) < 3:
        return _error(f"/app/employees?company_id={company.id}", "Ingresá una cédula o documento válido.", "employeeModal")
    if not position:
        return _error(f"/app/employees?company_id={company.id}", "Indicá el cargo del funcionario.", "employeeModal")
    if admission_date is None:
        return _error(f"/app/employees?company_id={company.id}", "Indicá una fecha de ingreso válida.", "employeeModal")
    if birth_date and birth_date >= admission_date:
        return _error(f"/app/employees?company_id={company.id}", "La fecha de nacimiento debe ser anterior al ingreso.", "employeeModal")
    if base_salary < 0:
        return _error(f"/app/employees?company_id={company.id}", "El salario base no puede ser negativo.", "employeeModal")
    if email and not _valid_email(email):
        return _error(f"/app/employees?company_id={company.id}", "El correo del funcionario no tiene un formato válido.", "employeeModal")
    if branch_id:
        branch = db.get(Branch, branch_id)
        if not branch or branch.company_id != company.id:
            return _error(f"/app/employees?company_id={company.id}", "La sucursal seleccionada no pertenece a la empresa.", "employeeModal")

    return await _invoke(
        _original_create_employee,
        company_id=company.id,
        full_name=full_name,
        document_number=document_number,
        birth_date=birth_date,
        position_name=position,
        admission_date=admission_date,
        contract_type=_clean(form.get("contract_type"), 80) or "Tiempo indefinido",
        payment_frequency=_clean(form.get("payment_frequency"), 40) or "Mensual",
        base_salary=base_salary,
        email=email,
        phone=_clean(form.get("phone"), 60),
        address=_clean(form.get("address"), 240),
        notes=_clean(form.get("notes"), 3000),
        branch_id=branch_id,
        ips_contributor=form.get("ips_contributor"),
        user=user,
        db=db,
    )


@app.post("/app/employees/{employee_id}/status")
async def employee_status_v24(
    employee_id: int,
    request: Request,
    user: User = Depends(core.require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(core.get_db),
):
    employee = db.get(Employee, employee_id)
    if not employee or employee.company_id not in core.company_ids_for_user(db, user):
        raise HTTPException(404, "Funcionario no encontrado.")
    form = await request.form()
    status_value = _clean(form.get("status"), 30) or "Activo"
    termination_date = _date(form.get("termination_date"))
    if status_value != "Activo" and termination_date is None:
        return _error(f"/app/employees?company_id={employee.company_id}", "Indicá la fecha efectiva de salida para cambiar el estado.")
    if termination_date and termination_date < employee.admission_date:
        return _error(f"/app/employees?company_id={employee.company_id}", "La fecha de salida no puede ser anterior al ingreso.")
    return await _invoke(
        _original_employee_status,
        employee_id=employee_id,
        status_value=status_value,
        termination_date=termination_date,
        user=user,
        db=db,
    )


@app.post("/app/vacations")
async def create_vacation_v24(
    request: Request,
    user: User = Depends(core.require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(core.get_db),
):
    form = await request.form()
    employee_id = _int(form.get("employee_id"))
    employee = db.get(Employee, employee_id)
    if not employee or employee.company_id not in core.company_ids_for_user(db, user):
        raise HTTPException(404, "Funcionario no encontrado.")
    period_year = _int(form.get("period_year"), date.today().year)
    if period_year < 1990 or period_year > date.today().year + 2:
        return _error("/app/vacations", "Revisá el año del periodo.", "vacationModal")
    reference_date = date(period_year, 12, 31)
    suggestion = vacation_entitlement_days(employee.admission_date, reference_date)
    entitled_raw = _clean(form.get("entitled_days"), 10)
    entitled_days = _int(entitled_raw, int(suggestion.value)) if entitled_raw else int(suggestion.value)
    used_days = _int(form.get("used_days"), 0)
    usage_error = validate_vacation_usage(entitled_days, used_days)
    if usage_error:
        return _error("/app/vacations", usage_error, "vacationModal")
    start_date = _date(form.get("start_date"))
    end_date = _date(form.get("end_date"))
    range_error = validate_date_range(start_date, end_date)
    if range_error:
        return _error("/app/vacations", range_error, "vacationModal")
    status_value = _clean(form.get("status"), 30) or "Pendiente"
    if status_value in {"Aprobada", "Completada"} and (not start_date or not end_date):
        return _error("/app/vacations", "Para vacaciones aprobadas o completadas indicá las fechas de inicio y fin.", "vacationModal")
    notes = _clean(form.get("notes"), 3000)
    if suggestion.value and entitled_days != int(suggestion.value):
        control = f"Referencia automática art. 218: {int(suggestion.value)} días; registro manual: {entitled_days} días."
        notes = f"{notes}\n{control}".strip()
    return await _invoke(
        _original_create_vacation,
        employee_id=employee.id,
        period_year=period_year,
        entitled_days=entitled_days,
        used_days=used_days,
        start_date=start_date,
        end_date=end_date,
        status_value=status_value,
        notes=notes,
        user=user,
        db=db,
    )


@app.post("/app/calculations")
async def save_calculation_v24(
    request: Request,
    user: User = Depends(core.require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(core.get_db),
):
    form = await request.form()
    calculation_type = _clean(form.get("calculation_type"), 60)
    if calculation_type not in {"salary", "hours", "aguinaldo", "vacation", "notice"}:
        raise HTTPException(400, "Tipo de cálculo inválido.")
    company_id = _int(form.get("company_id"))
    company = core.company_allowed(db, user, company_id)
    employee_id = _int(form.get("employee_id")) or None
    employee = db.get(Employee, employee_id) if employee_id else None
    if employee and employee.company_id != company.id:
        raise HTTPException(400, "El funcionario no pertenece a la empresa seleccionada.")

    gross = max(0, _int(form.get("gross")))
    other_income = max(0, _int(form.get("other_income")))
    other_discount = max(0, _int(form.get("other_discount")))
    salary = max(0, _int(form.get("salary")))
    monthly_hours = max(1.0, _float(form.get("monthly_hours"), 240))
    hours_quantity = max(0.0, _float(form.get("hours_quantity"), 0))
    multiplier = max(0.0, _float(form.get("multiplier"), 1))
    total_remunerations = max(0, _int(form.get("total_remunerations")))
    days = max(0.0, _float(form.get("days"), 0))
    if employee:
        salary = salary or employee.base_salary
        gross = gross or employee.base_salary

    inputs: dict = {"calculation_type": calculation_type}
    results: dict = {}
    amount = 0
    if calculation_type == "salary":
        computable = gross + other_income
        apply_ips = form.get("apply_ips") == "on" and (not employee or employee.ips_contributor)
        ips_base_raw = _clean(form.get("ips_base"), 30)
        ips_base = _int(ips_base_raw, computable) if ips_base_raw else computable
        ips_base = min(max(0, ips_base), computable)
        rate = core.get_parameter(db, "ips_employee_rate_general", 9)
        ips = round(ips_base * rate / 100) if apply_ips else 0
        discounts = ips + other_discount
        amount = max(0, computable - discounts)
        inputs.update({"gross": gross, "other_income": other_income, "other_discount": other_discount, "apply_ips": apply_ips, "ips_base": ips_base, "ips_rate": rate})
        results.update({"gross_computable": computable, "ips_base": ips_base, "ips_employee": ips, "discounts": discounts, "net": amount})
    elif calculation_type == "hours":
        base = salary / monthly_hours
        amount = round(base * hours_quantity * multiplier)
        inputs.update({"salary": salary, "monthly_hours": monthly_hours, "hours_quantity": hours_quantity, "multiplier": multiplier})
        results.update({"hour_value": round(base), "total": amount})
    elif calculation_type == "aguinaldo":
        rule = aguinaldo_amount(total_remunerations)
        amount = int(rule.value)
        inputs.update({"total_remunerations": total_remunerations})
        results.update({"total_remunerations": total_remunerations, "aguinaldo": amount, "legal_basis": rule.legal_basis})
    elif calculation_type == "vacation":
        minimum = core.get_parameter(db, "minimum_monthly_salary_general", 0)
        rule = vacation_amount(salary, minimum, days)
        amount = int(rule.value)
        inputs.update({"salary": salary, "minimum_salary_reference": minimum, "days": days})
        results.update({"base_monthly": max(salary, int(minimum)), "daily_value": round(max(salary, int(minimum)) / 30), "days": days, "total": amount, "legal_basis": rule.legal_basis})
    else:
        if employee and not _clean(form.get("days")):
            days = float(preaviso_days(employee.admission_date, date.today()).value)
        amount = round(salary / 30 * days)
        inputs.update({"monthly_average_base": salary, "days": days})
        results.update({"daily_value": round(salary / 30), "days": days, "total": amount, "legal_basis": "Código del Trabajo, arts. 87, 90 y 92"})

    item = CalculationRecord(
        company_id=company.id,
        employee_id=employee.id if employee else None,
        calculation_type=calculation_type,
        reference_period=_clean(form.get("reference_period"), 20),
        input_json=json.dumps(inputs, ensure_ascii=False, separators=(",", ":")),
        result_json=json.dumps(results, ensure_ascii=False, separators=(",", ":")),
        amount=amount,
        status="Revisar",
        source="Calculadora v2.4",
        notes=_clean(form.get("notes"), 3000),
        created_by=user.email,
    )
    db.add(item)
    db.flush()
    core.write_audit(db, user, "crear", "calculo", str(item.id), f"{calculation_type}: {amount}")
    db.commit()
    return RedirectResponse(f"/app/calculations?saved=1&company_id={company.id}", status_code=303)


@app.post("/app/payrolls/{payroll_id}/lines/{line_id}")
async def update_payroll_line_v24(
    payroll_id: int,
    line_id: int,
    request: Request,
    user: User = Depends(core.require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(core.get_db),
):
    payroll = db.get(Payroll, payroll_id)
    line = db.get(PayrollLine, line_id)
    if not payroll or not line or line.payroll_id != payroll.id or payroll.company_id not in core.company_ids_for_user(db, user):
        raise HTTPException(404, "Línea de liquidación no encontrada.")
    if payroll.status == "Cerrada":
        raise HTTPException(409, "La liquidación está cerrada.")
    form = await request.form()
    for attr in ("base_salary", "overtime", "commissions", "bonuses", "other_income", "absences_discount", "advances", "other_discount"):
        setattr(line, attr, max(0, _int(form.get(attr))))
    line.gross = line.base_salary + line.overtime + line.commissions + line.bonuses + line.other_income
    rate = core.get_parameter(db, "ips_employee_rate_general", 9)
    ips_base_raw = _clean(form.get("ips_base"), 30)
    ips_base = _int(ips_base_raw, line.gross) if ips_base_raw else line.gross
    ips_base = min(max(0, ips_base), line.gross)
    line.ips_employee = round(ips_base * rate / 100) if line.employee.ips_contributor else 0
    line.total_discounts = line.ips_employee + line.absences_discount + line.advances + line.other_discount
    line.net = max(0, line.gross - line.total_discounts)
    core.recalculate_payroll(db, payroll)
    core.write_audit(db, user, "editar", "linea_liquidacion", str(line.id), f"{line.employee.full_name} · base IPS Gs. {ips_base}")
    db.commit()
    return RedirectResponse(f"/app/payrolls/{payroll.id}?saved=1", status_code=303)
