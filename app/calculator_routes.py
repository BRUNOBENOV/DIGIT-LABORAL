from __future__ import annotations

import io
import json
import re
import unicodedata
from copy import deepcopy
from calendar import monthrange
import zipfile
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from . import main as core
from .entity_selects import seed_choices
from .unified_labor_history import calculation_history_page
from .calculator_fields import GROUPS
from .calculator_presentation import calculation_summary, quick_steps
from .form_utils import OptionalQueryId
from .labor_calculator import CalculationError, SOURCE, TITLES, VERSION, amount as round_gs, calculate, clean, settlement_projection
from .liquidation_export import build_liquidation_pdf, build_liquidation_csv
from .labor_examples import example_values
from .models import CalculationRecord, Company, Employee, EmployeeExit, FinalSettlement, Payroll, PayrollLine, PayrollComplianceDetail, User
from .salary_history import employee_salary_history, salary_from_history, salary_for_period
from .payroll_average import annotate_average, propose_monthly_average, verify_average_selection
from .payroll_annual import annotate_annual, propose_annual_remuneration, verify_annual_selection
from .settlement_presets import settlement_defaults
from .settlement_evidence import annotate_judicial_document, judicial_document_choices, verify_judicial_document
from .salary_data import attendance_proposal, apply_attendance_proposal, verify_attendance_inheritance, SALARY_TYPES, official_salary_period_submitted
from .salary_novelties import salary_novelties

router = APIRouter()
HEADERS = {"Cache-Control": "no-store", "X-Digit-Laboral-Version": VERSION}


def context(kind, values=None):
    if kind not in TITLES:
        raise HTTPException(404, "Calculadora no encontrada.")
    today = datetime.now(ZoneInfo("America/Asuncion")).date()
    defaults = {f["name"]: f["value"] for g in GROUPS[kind] for f in g["fields"]}
    defaults.update(issued_date=today.isoformat(), month=today.strftime("%Y-%m"),
                    year=str(today.year), end_date=today.isoformat())
    if kind == "settlement":
        defaults.update(kind=kind, settlement_preset_version="2", severance_regime="ordinary")
    if values is not None:
        defaults.update(values)
    defaults = settlement_defaults(defaults)
    return dict(kind=kind, titles=TITLES, groups=GROUPS[kind], quick_steps=quick_steps(kind), values=defaults, result=None,
                error="", error_field="", private=False, companies=[], employees=[], history=[])


async def form_values(request):
    body = await request.body()
    if len(body) > 64000:
        raise HTTPException(413, "Formulario demasiado grande.")
    form = await request.form(max_files=0, max_fields=100)
    data = {k: str(v) for k, v in form.items() if k != "csrf_token"}
    if data.get("kind") not in TITLES:
        raise HTTPException(422, "Tipo de cálculo inválido.")
    for group in GROUPS[data["kind"]]:
        for field in group["fields"]:
            if field["type"] == "checkbox":
                data.setdefault(field["name"], "")
    return settlement_defaults(data)


def private_context(db, user, data):
    company_ids = core.company_ids_for_user(db, user)
    companies = seed_choices(db, select(Company).where(Company.id.in_(company_ids)).order_by(Company.legal_name), Company, selected_ids=[data.get("company_id")])
    try:
        company_id = int(data.get("company_id") or 0)
        employee_id = int(data.get("employee_id") or 0)
    except (ValueError, TypeError):
        raise HTTPException(422, "Selección inválida de empresa o funcionario.")
    company = core.company_allowed(db, user, company_id) if company_id else None
    employee = db.get(Employee, employee_id) if employee_id else None
    if employee_id and (not employee or not company or employee.company_id != company.id):
        raise HTTPException(404, "Funcionario no encontrado en la empresa seleccionada.")
    employee_choices = select(Employee).where(Employee.company_id.in_(company_ids))
    if company_id:
        employee_choices = employee_choices.where(Employee.company_id == company_id)
    employees = seed_choices(db, employee_choices.order_by(Employee.full_name), Employee, selected_ids=[employee_id])
    query = select(CalculationRecord).where(CalculationRecord.company_id.in_(company_ids), CalculationRecord.source == SOURCE)
    if company:
        query = query.where(CalculationRecord.company_id == company.id)
    if employee:
        query = query.where(CalculationRecord.employee_id == employee.id)
    history = list(db.scalars(query.order_by(CalculationRecord.id.desc()).limit(30)))
    if company:
        data.update(employer=company.legal_name, ruc=company.ruc)
    salary_history = employee_salary_history(db, employee.id) if employee else []
    if employee:
        data.update(employee=employee.full_name, ci=employee.document_number, position=employee.position)
    judicial_documents = judicial_document_choices(db, employee, data.get("judicial_document_id")) if employee and data.get("kind") == "settlement" else []
    return dict(private=True, companies=companies, employees=employees, company=company,
                employee=employee, company_id=company_id, employee_id=employee_id, history=history,
                salary_history=salary_history, judicial_documents=judicial_documents)


def add_salary_period_warnings(result, db, scoped, data):
    """Attach review warnings for hires and salary changes within a monthly period.

    Never prorates a salary change automatically: a monthly salary snapshot can
    represent only one base amount, so the result must remain subject to review.
    """
    if result.get("kind") != "salary" or not scoped.get("employee"):
        return result
    try:
        period_start = date.fromisoformat(str(result.get("period", "")) + "-01")
    except ValueError:
        return result
    period_end = date(
        period_start.year, period_start.month,
        monthrange(period_start.year, period_start.month)[1],
    )
    _, period_warnings = salary_for_period(
        db, scoped["employee"], period_start, period_end
    )
    # Imported legajos can carry a current salary without dated SalaryHistory
    # entries. Allow a documented verification for *this calculation/period*
    # without manufacturing historical events or mutating the worker's salary.
    no_history = not employee_salary_history(db, scoped["employee"].id)
    evidence = clean(data.get("salary_base_verification_note"), 300)
    acknowledged = (
        no_history and str(data.get("salary_base_verified") or "") == "on"
        and len(evidence) >= 12
        and str(data.get("salary_base_verification_period") or "") == result["period"]
        and str(data.get("salary_base_verification_amount") or "") == str(data.get("salary") or "")
    )
    existing = result.setdefault("warnings", [])
    for warning in period_warnings:
        if acknowledged and "no hay historial salarial registrado" in warning:
            continue
        if warning not in existing:
            existing.append(warning)
    if acknowledged:
        result.setdefault("notes", []).append(
            "Salario de Gs. " + str(data.get("salary") or "") +
            " del período " + result["period"] +
            " verificado manualmente por el liquidador. Respaldo: " + evidence +
            ". La confirmación no crea historial salarial ni altera el legajo."
        )
    return result


def page(request, kind, data=None, result=None, error=None, db=None, user=None, copied_from=None):
    values = dict(data) if data is not None else None
    private = private_context(db, user, values if values is not None else {}) if user else {}
    ctx = context(kind, values)
    if kind == "settlement" and private:
        ctx["groups"], ctx["quick_steps"] = deepcopy(ctx["groups"]), deepcopy(ctx["quick_steps"])
        options = [("", "Seleccioná un documento del funcionario"), *[(str(item["id"]),item["label"]) for item in private["judicial_documents"]]]
        for group in ctx["groups"] + [group for step in ctx["quick_steps"] for group in step["groups"]]:
            for field in group["fields"]:
                if field["name"] == "judicial_document_id":
                    field["attrs"]["options"] = options
    salary_history_data = [
        {"id": item.id, "effective_from": item.effective_from.isoformat(), "new_salary": int(item.new_salary or 0)}
        for item in private.get("salary_history", [])
    ]
    suggestion_label = "Sugerido del salario ingresado. Modificar si es necesario"
    if employee := private.get("employee"):
        try:
            target = date.fromisoformat(str(ctx["values"].get("end_date", "")))
            recorded_salary = salary_from_history(employee, private["salary_history"], target)
            if str(ctx["values"].get("salary", "")) == str(recorded_salary):
                suggestion_label = "Sugerido del legajo. Modificar si es necesario"
        except ValueError:
            pass
    # El histórico DOS informa, pero no modifica los conceptos de liquidación.
    historic_vacations, historic_notices = None, None
    if kind == "settlement" and db is not None and private.get("employee"):
        from .historical_labor_context import historical_vacation_summary
        from .historical_notice_context import notice_history_summary
        historic_vacations = historical_vacation_summary(db, private["employee"].id)
        historic_notices = notice_history_summary(db, private["employee"].id)
    ctx.update(historical_vacation_overview=historic_vacations,
               historical_notice_overview=historic_notices)
    # Same traceability stream as the calculation module, including old and
    # current records; no historical source is promoted to an approved calculation.
    labor_history = None
    labor_prev_query, labor_next_query, labor_toggle_query = "", "", ""
    show_superseded_salary = False
    show_deleted_calculations = False
    if private and db is not None and user is not None:
        try:
            requested_page = int(request.query_params.get("history_page", "1"))
        except (ValueError, TypeError):
            requested_page = 1
        show_superseded_salary = request.query_params.get("history_all") == "1"
        show_deleted_calculations = request.query_params.get("deleted_all") == "1"
        labor_history = calculation_history_page(
            db, core.company_ids_for_user(db, user),
            company_id=private.get("company_id") or None,
            employee_id=private.get("employee_id") or None,
            page=requested_page, page_size=30,
            include_center_calculations=True,
            include_superseded_salary=show_superseded_salary,
            include_deleted=show_deleted_calculations,
            include_mov_salary=(kind == "salary"),
            include_liq_settlement=(kind == "settlement"),
        )
        filters = {
            key: val for key, val in {
                "tipo": kind,
                "company_id": private.get("company_id") or None,
                "employee_id": private.get("employee_id") or None,
                "history_all": "1" if show_superseded_salary else None,
                "deleted_all": "1" if show_deleted_calculations else None,
            }.items() if val is not None
        }
        labor_toggle_query = urlencode({
            **{key: value for key, value in filters.items() if key != "history_all"},
            **({} if show_superseded_salary else {"history_all": "1"}),
            "history_page": 1,
        })
        labor_deleted_toggle_query = urlencode({
            **{key: value for key, value in filters.items() if key != "deleted_all"},
            **({} if show_deleted_calculations else {"deleted_all": "1"}),
            "history_page": 1,
        })
        labor_prev_query = urlencode({**filters, "history_page": labor_history["page"] - 1})
        labor_next_query = urlencode({**filters, "history_page": labor_history["page"] + 1})
    if labor_history:
        for row in labor_history["rows"]:
            if row["origin"] == "current" and row["record"].source == SOURCE:
                try:
                    source_id = json.loads(row["record"].input_json or "{}").get("rectifies_record_id")
                    row["rectifies"] = int(source_id) if source_id else None
                except (ValueError, TypeError, AttributeError):
                    row["rectifies"] = None
    ctx.update(labor_history=labor_history,
               labor_prev_query=labor_prev_query, labor_next_query=labor_next_query,
               labor_toggle_query=labor_toggle_query,
               labor_deleted_toggle_query=locals().get("labor_deleted_toggle_query", ""),
               show_deleted_calculations=show_deleted_calculations,
               show_superseded_salary=show_superseded_salary)
    ctx.update(private, salary_history_data=salary_history_data, result=result,
               average_suggestion_label=suggestion_label,
               live_summary=calculation_summary(result) if result else None, error=str(error or ""),
               error_field=getattr(error, "field", ""), copied_from=copied_from)
    response = core.render(request, "labor_workbench.html", db, user, **ctx)
    response.headers.update(HEADERS)
    if error:
        response.status_code = 422
    return response


def calculate_scoped(data, db, scoped):
    data.update(settlement_defaults(data))
    novelties = None
    if data.get("kind") == "salary" and scoped.get("employee"):
        try:
            novelties = salary_novelties(
                db, scoped["employee"].company_id, scoped["employee"].id,
                str(data.get("month") or ""), str(data.get("pay_basis") or "monthly"),
            )
        except ValueError as exc:
            raise CalculationError(str(exc), "month") from None
        applied = data.get("novelties_applied") == "on"
        complete = data.get("novelties_attendance_confirmed") == "on"
        if applied or complete:
            if str(data.get("novelties_fingerprint") or "") != novelties["fingerprint"]:
                raise CalculationError(
                    "Las novedades del mes cambiaron. Actualizá la conciliación antes de calcular o guardar.", "days_paid"
                )
        if applied and (not novelties["can_apply_paid_days"]
                        or str(data.get("days_paid") or "") != str(novelties["suggested_paid_days"])):
            raise CalculationError(
                "La propuesta de días remunerados ya no coincide con el cálculo. Volvé a revisar las novedades.", "days_paid"
            )
        if complete:
            if data.get("attendance_source_id") and data.get("attendance_override") != "on":
                raise CalculationError(
                    "Para sustituir la asistencia de un cálculo aprobado, activá «Editar asistencia cargada».", "days_worked"
                )
            if (not novelties["daily_attendance"]
                    or str(data.get("days_worked") or "") != str(novelties["observed_worked_days"])):
                raise CalculationError(
                    "Las jornadas no corresponden a la asistencia confirmada. Actualizá la conciliación.", "days_worked"
                )
            try:
                same_hours = Decimal(str(data.get("hours_worked") or "")) == Decimal(novelties["observed_ordinary_hours"])
            except (ValueError, ArithmeticError):
                same_hours = False
            if not same_hours:
                raise CalculationError(
                    "Las horas ordinarias no corresponden a la asistencia confirmada.", "hours_worked"
                )
            if data.get("pay_basis") == "daily" and str(data.get("days_paid") or "") != str(novelties["observed_worked_days"]):
                raise CalculationError(
                    "Revisá las jornadas pagadas del jornalero y su asistencia.", "days_paid"
                )
    verify_attendance_inheritance(db, scoped.get("employee"), data)
    proposal = verify_average_selection(db, scoped.get("employee"), data)
    annual = verify_annual_selection(db, scoped.get("employee"), data)
    judicial = verify_judicial_document(db, scoped.get("employee"), data)
    result = annotate_judicial_document(annotate_annual(annotate_average(calculate(data, judicial_evidence_verified=judicial is not None), proposal), annual), judicial)
    if novelties and novelties["events"]:
        result["facts"].append({"label": "Novedades del período", "value": str(len(novelties["events"]))})
        result["facts"].append({"label": "Ausencias sin goce verificadas", "value": str(novelties["unpaid_days"])})
        result["facts"].append({"label": "Descansos remunerados registrados", "value": str(novelties["paid_leave_days"])})
        if data.get("novelties_applied") == "on":
            result["notes"].append("Días remunerados propuestos desde novedades aprobadas; respaldo y versión conciliados.")
        if data.get("novelties_attendance_confirmed") == "on":
            result["notes"].append("Jornadas y horas efectivamente registradas confirmadas como asistencia completa por el usuario.")
        if novelties["requires_review"] or (novelties["unpaid_days"] and data.get("novelties_applied") != "on"):
            result["warnings"].append(
                "Existen permisos, sanciones, reposos o ausencias que requieren conciliación antes de declarar días remunerados."
            )
    return add_salary_period_warnings(result, db, scoped, data)


@router.get("/api/liquidaciones/documentos-judiciales")
def judicial_documents_proposal(company_id: int, employee_id: int, document_id: OptionalQueryId = None,
                               user: User = Depends(core.require_user), db: Session = Depends(core.get_db)):
    company = core.company_allowed(db, user, company_id)
    employee = db.get(Employee, employee_id)
    if not employee or employee.company_id != company.id:
        raise HTTPException(404, "Funcionario no encontrado en la empresa seleccionada.")
    return JSONResponse({"items":judicial_document_choices(db, employee, document_id)}, headers=HEADERS)


@router.get("/api/liquidaciones/remuneracion-anual")
def payroll_annual_proposal(
    company_id: int, employee_id: int, end_date: date, start_date: date | None = None,
    user: User = Depends(core.require_user), db: Session = Depends(core.get_db),
):
    company = core.company_allowed(db, user, company_id)
    employee = db.get(Employee, employee_id)
    if not employee or employee.company_id != company.id:
        raise HTTPException(404, "Funcionario no encontrado en la empresa seleccionada.")
    try:
        proposal = propose_annual_remuneration(db, employee, end_date, start=start_date)
    except CalculationError as exc:
        raise HTTPException(422, str(exc)) from None
    return JSONResponse(proposal, headers=HEADERS)


@router.post("/herramientas/aguinaldo/previsualizar")
async def annual_accrual_preview(request: Request):
    from .labor_calculator import aguinaldo_accrual, number
    data = await form_values(request)
    try:
        annual = number(data, "annual_remuneration", "remuneración anual", required=True)
        return JSONResponse({"aguinaldo_accrued": aguinaldo_accrual(annual)}, headers=HEADERS)
    except CalculationError as exc:
        return JSONResponse({"error": str(exc), "field": exc.field}, status_code=422, headers=HEADERS)


@router.get("/api/liquidaciones/promedio-salarial")
def payroll_average_proposal(
    company_id: int, employee_id: int, end_date: date, start_date: date | None = None,
    user: User = Depends(core.require_user), db: Session = Depends(core.get_db),
):
    company = core.company_allowed(db, user, company_id)
    employee = db.get(Employee, employee_id)
    if not employee or employee.company_id != company.id:
        raise HTTPException(404, "Funcionario no encontrado en la empresa seleccionada.")
    try:
        proposal = propose_monthly_average(db, employee, end_date, start=start_date)
    except CalculationError as exc:
        raise HTTPException(422, str(exc)) from None
    return JSONResponse(proposal, headers=HEADERS)


@router.get("/herramientas")
def public_page(request: Request, tipo: str = "salary", ejemplo: bool = False):
    values = example_values(tipo, context(tipo)["values"]) if ejemplo and tipo in {"salary", "settlement"} else None
    return page(request, tipo, values)


@router.get("/app/liquidaciones/conciliar-planilla")
def accounting_salary_audit_page(
    request: Request,
    user: User = Depends(core.require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(core.get_db),
):
    return core.render(
        request, "salary_accounting_audit.html", db, user,
        report=None, error="", period=request.query_params.get("period", ""),
    )


@router.post("/app/liquidaciones/conciliar-planilla")
async def accounting_salary_audit_upload(
    request: Request,
    upload: UploadFile = File(...),
    period: str = Form(""),
    user: User = Depends(core.require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(core.get_db),
):
    """Previsualización efímera sin crear ni modificar cálculos o legajos."""
    from .salary_accounting_audit import (
        AccountingPayrollError, MAX_UPLOAD, reconcile_accounting_payroll,
    )
    error = ""
    report = None
    try:
        filename = str(upload.filename or "").lower()
        if not filename.endswith(".xlsx"):
            raise AccountingPayrollError("Subí un archivo .xlsx de la planilla contable.")
        raw = await upload.read(MAX_UPLOAD + 1)
        report = await run_in_threadpool(reconcile_accounting_payroll, raw, period=period)
    except AccountingPayrollError as exc:
        error = str(exc)
    finally:
        await upload.close()
    return core.render(
        request, "salary_accounting_audit.html", db, user,
        report=report, error=error, period=period,
    )


@router.get("/app/liquidaciones")
def professional_page(request: Request, tipo: str = "settlement", company_id: OptionalQueryId = None, employee_id: OptionalQueryId = None, exit_id: OptionalQueryId = None,
                      month: str = "", calculation_id: OptionalQueryId = None,
                      user: User = Depends(core.require_user), db: Session = Depends(core.get_db)):
    allowed_company_ids = core.company_ids_for_user(db, user)
    company_id, employee_id = core.default_labor_context(
        request, db, user, allowed_company_ids, company_id, employee_id
    )
    values = dict(context(tipo)["values"], company_id=company_id or 0, employee_id=employee_id or 0, prepared_by=user.full_name)
    if tipo == "salary" and month:
        if not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", month):
            raise HTTPException(422, "Seleccioná un mes válido.")
        values["month"] = month
    if calculation_id:
        if user.role not in {"administrador", "contador", "auxiliar"}:
            raise HTTPException(403, "No tenés permiso para cargar un cálculo salarial de origen.")
        origin = db.get(CalculationRecord, calculation_id)
        if (tipo != "salary" or not origin or origin.company_id != company_id
                or origin.employee_id != employee_id or origin.calculation_type not in SALARY_TYPES):
            raise HTTPException(404, "El cálculo no corresponde a la empresa y funcionario seleccionados.")
        if month and month != origin.reference_period:
            raise HTTPException(409, "El mes seleccionado no corresponde al cálculo de origen.")
        values["month"] = origin.reference_period
    if exit_id:
        from .employee_exit_routes import EXIT_REASONS
        exit_record = db.get(EmployeeExit, exit_id)
        if (tipo != "settlement" or not exit_record or
                exit_record.company_id not in allowed_company_ids or
                exit_record.employee_id != employee_id or
                exit_record.status == "Cancelado"):
            raise HTTPException(404, "No se encontró un egreso válido para esta liquidación.")
        values.update(
            employee_exit_id=str(exit_record.id),
            end_date=exit_record.effective_date.isoformat(),
            reason=exit_record.reason,
        )
    scoped = private_context(db, user, values)
    if employee := scoped["employee"]:
        if tipo == "settlement" and employee.termination_date and not exit_id:
            values["end_date"] = employee.termination_date.isoformat()
        today = datetime.now(ZoneInfo("America/Asuncion")).date()
        effective_on = today
        if tipo == "salary":
            month = str(values.get("month") or "")
            if re.fullmatch(r"\d{4}-\d{2}", month):
                try:
                    effective_on = date.fromisoformat(month + "-01")
                except ValueError:
                    pass
        elif tipo == "settlement":
            try:
                effective_on = date.fromisoformat(str(values.get("end_date") or ""))
            except ValueError:
                pass
        effective_salary = salary_from_history(employee, scoped["salary_history"], effective_on)
        values.update(salary=str(effective_salary), start_date=employee.admission_date.isoformat(),
                      apply_ips="on" if employee.ips_contributor else "",
                      indefinite="on" if employee.contract_type == "Tiempo indefinido" else "")
        if tipo in {"salary", "settlement"}:
            frequency = (employee.payment_frequency or "").strip().lower()
            is_daily = any(word in frequency for word in ("jornal", "diario", "diaria"))
            unknown_modality = frequency in {"", "no especificado", "sin especificar", "indefinido"}
            values["pay_basis"] = ("" if tipo == "settlement" and unknown_modality
                                   else "daily" if is_daily else "monthly")
            if tipo == "salary":
                # No presumir 26 días efectivamente trabajados por ser jornalero.
                values["days_paid"] = "" if is_daily else "30"
            elif is_daily:
                # La unidad de employee.salary no es inequívoca en registros
                # históricos: no fabricar un jornal dividiendo por 26.
                values["daily_rate"] = ""
        if tipo == "salary" and user.role in {"administrador", "contador", "auxiliar"}:
            try:
                attendance = attendance_proposal(db, employee.company_id, employee.id, values["month"])
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            if calculation_id and attendance["calculation_id"] != calculation_id:
                raise HTTPException(409, "Ese cálculo no es la aprobación vigente. Cargá el funcionario y el mes para usar la versión actual.")
            apply_attendance_proposal(values, attendance)
            if is_daily and str(values.get("days_worked") or "").strip():
                values["days_paid"] = str(values["days_worked"])
        if tipo == "settlement":
            try:
                annual = propose_annual_remuneration(db, employee, effective_on)
            except CalculationError:
                annual = None  # The source panel reports the interval error without blocking the form.
            if annual and annual["is_available"]:
                values.update(annual_remuneration=str(annual["annual_remuneration"]),
                              annual_origin=annual["origin"], annual_payroll_fingerprint=annual["fingerprint"])
    return page(request, tipo, values, db=db, user=user)


@router.get("/api/liquidaciones/asistencia-salarial")
def salary_attendance_proposal(company_id: int, employee_id: int, period: str,
                               user: User = Depends(core.require_roles("administrador", "contador", "auxiliar")), db: Session = Depends(core.get_db)):
    company = core.company_allowed(db, user, company_id)
    employee = db.get(Employee, employee_id)
    if not employee or employee.company_id != company.id:
        raise HTTPException(404, "Funcionario no encontrado en la empresa seleccionada.")
    try:
        proposal = attendance_proposal(db, company.id, employee.id, period)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return JSONResponse(proposal, headers=HEADERS)


@router.get("/api/liquidaciones/novedades-salariales")
def salary_novelties_proposal(
    company_id: int, employee_id: int, period: str, pay_basis: str = "monthly",
    user: User = Depends(core.require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(core.get_db),
):
    company = core.company_allowed(db, user, company_id)
    employee = db.get(Employee, employee_id)
    if not employee or employee.company_id != company.id:
        raise HTTPException(404, "Funcionario no encontrado en la empresa seleccionada.")
    try:
        payload = salary_novelties(db, company.id, employee.id, period, pay_basis)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return JSONResponse(payload, headers=HEADERS)


@router.post("/herramientas/calcular")
async def public_calculate(request: Request):
    data = await form_values(request)
    try:
        result = calculate(data)
    except CalculationError as exc:
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse({"error": str(exc), "field": exc.field}, status_code=422, headers=HEADERS)
        return page(request, data["kind"], data, error=exc)
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse(calculation_summary(result), headers=HEADERS)
    return page(request, data["kind"], data, result=result)


@router.post("/herramientas/liquidacion/previsualizar")
async def settlement_preview(request: Request):
    """Stateless numeric projection, shared by public and private calculators."""
    data = await form_values(request)
    if data["kind"] != "settlement":
        raise HTTPException(422, "La vista previa corresponde a liquidación de haberes.")
    try:
        return JSONResponse(settlement_projection(data), headers=HEADERS)
    except CalculationError as exc:
        return JSONResponse({"error": str(exc), "field": exc.field}, status_code=422, headers=HEADERS)


@router.post("/app/liquidaciones/calcular")
async def professional_calculate(request: Request, user: User = Depends(core.require_user),
                                 db: Session = Depends(core.get_db)):
    data = await form_values(request)
    scoped = private_context(db, user, data)
    try:
        result = calculate_scoped(data, db, scoped)
    except CalculationError as exc:
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse({"error": str(exc), "field": exc.field}, status_code=422, headers=HEADERS)
        return page(request, data["kind"], data, error=exc, db=db, user=user)
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse(calculation_summary(result), headers=HEADERS)
    return page(request, data["kind"], data, result=result, db=db, user=user)


async def download(result, fmt):
    if fmt not in {"pdf", "csv"}:
        raise HTTPException(404)
    builder = build_liquidation_pdf if fmt == "pdf" else build_liquidation_csv
    content = await run_in_threadpool(builder, result)
    # A distinct, ASCII-safe name makes monthly downloads easy to identify.
    parts = [result["kind"], result.get("period", ""), result.get("identity", {}).get("employee", "")]
    def slug(part):
        ascii_text = unicodedata.normalize("NFKD", str(part)).encode("ascii", "ignore").decode()
        return re.sub(r"[^A-Za-z0-9_-]+", "-", ascii_text).strip("-")[:70]
    name = "-".join(filter(None, (slug(part) for part in parts)))
    return Response(content, media_type="application/pdf" if fmt == "pdf" else "text/csv; charset=utf-8",
                    headers={**HEADERS, "Content-Disposition": f'attachment; filename="digit-laboral-{name}.{fmt}"'})


@router.post("/herramientas/exportar/{fmt}")
async def public_export(request: Request, fmt: str):
    data = await form_values(request)
    try:
        return await download(calculate(data), fmt)
    except CalculationError as exc:
        return page(request, data["kind"], data, error=exc)


@router.post("/app/liquidaciones/exportar/{fmt}")
async def professional_export(request: Request, fmt: str, user: User = Depends(core.require_user),
                              db: Session = Depends(core.get_db)):
    data = await form_values(request)
    scoped = private_context(db, user, data)
    try:
        result = calculate_scoped(data, db, scoped)
        return await download(result, fmt)
    except CalculationError as exc:
        return page(request, data["kind"], data, error=exc, db=db, user=user)


@router.post("/app/liquidaciones/guardar")
async def save_calculation(request: Request,
                           user: User = Depends(core.require_roles("administrador", "contador", "auxiliar")),
                           db: Session = Depends(core.get_db)):
    data = await form_values(request)
    scoped = private_context(db, user, data)
    # First check a cross-month correction's target. This must happen before
    # calculating attendance, which may otherwise pick an unrelated approved
    # salary in that month and raise an unhelpful validation error.
    if data.get("kind") == "salary" and data.get("rectifies_record_id"):
        try:
            origin_id = int(data["rectifies_record_id"])
        except (ValueError, TypeError):
            raise HTTPException(422, "La liquidación original seleccionada no es válida.") from None
        origin = db.get(CalculationRecord, origin_id)
        if (
            not origin or not scoped.get("company") or not scoped.get("employee")
            or origin.company_id != scoped["company"].id
            or origin.employee_id != scoped["employee"].id
            or origin.calculation_type != "suite_salary"
            or origin.source != SOURCE
            or origin.status in {"Anulado", "Rectificado"}
        ):
            raise HTTPException(409, "El cálculo de origen no corresponde al funcionario o ya fue sustituido.")
        target_month = str(data.get("month") or "")
        if re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", target_month) and target_month != origin.reference_period:
            duplicate = db.scalar(select(CalculationRecord.id).where(
                CalculationRecord.company_id == origin.company_id,
                CalculationRecord.employee_id == origin.employee_id,
                CalculationRecord.reference_period == target_month,
                CalculationRecord.calculation_type.in_(SALARY_TYPES),
                CalculationRecord.status.in_(("Aprobado", "Validado")),
            ).limit(1))
            if duplicate is not None:
                return page(
                    request, "salary", data,
                    error=CalculationError(
                        "Ya existe una liquidación aprobada en el mes de destino. "
                        "Rectificá esa liquidación o elegí otro mes.", "month",
                    ),
                    db=db, user=user, copied_from=origin.id,
                )
    linked_settlement = None
    linked_exit = None
    if data.get("employee_exit_id"):
        from .employee_exit_routes import EXIT_REASONS
        try:
            requested_exit_id = int(data["employee_exit_id"])
        except (ValueError, TypeError):
            raise HTTPException(422, "El identificador de egreso es inválido.")
        linked_exit = db.get(EmployeeExit, requested_exit_id)
        if (data.get("kind") != "settlement" or not linked_exit or
            linked_exit.company_id not in core.company_ids_for_user(db, user) or
            not scoped["employee"] or scoped["employee"].id != linked_exit.employee_id or
            linked_exit.status == "Cancelado"):
            raise HTTPException(409, "El cálculo no corresponde al egreso seleccionado.")
        linked_settlement = db.scalar(select(FinalSettlement).where(
            FinalSettlement.employee_exit_id == linked_exit.id
        ))
        if not linked_settlement or linked_settlement.status not in {"Pendiente de Cálculo", "En Revisión"}:
            raise HTTPException(409, "Esta liquidación ya fue aprobada o pagada; no puede reemplazarse.")
        if (data.get("end_date") != linked_exit.effective_date.isoformat() or
            data.get("reason") != linked_exit.reason or
            data.get("start_date") != scoped["employee"].admission_date.isoformat()):
            raise HTTPException(422, "La causal y las fechas deben coincidir con el procedimiento de egreso.")
    try:
        if not scoped["company"] or not scoped["employee"]:
            raise CalculationError("Seleccioná empresa y funcionario para guardar el cálculo.")
        result = calculate_scoped(data, db, scoped)
        if result["net"] > 2147483647:
            raise CalculationError("Este monto supera el límite del historial actual; podés descargar el cálculo.")
    except CalculationError as exc:
        return page(request, data["kind"], data, error=exc, db=db, user=user)
    correction_origin = None
    if data.get("rectifies_record_id"):
        if data["kind"] != "salary":
            raise HTTPException(422, "La rectificación desde trazabilidad está disponible para cálculos salariales.")
        try:
            original_id = int(data["rectifies_record_id"])
        except (ValueError, TypeError):
            raise HTTPException(422, "El cálculo de origen es inválido.") from None
        correction_origin = db.get(CalculationRecord, original_id)
        if (correction_origin is None or correction_origin.source != SOURCE
            or correction_origin.calculation_type != "suite_salary"
            or correction_origin.company_id != scoped["company"].id
            or correction_origin.employee_id != scoped["employee"].id
            or correction_origin.status in {"Anulado", "Rectificado"}):
            raise HTTPException(409, "El cálculo de origen no pertenece a esta empresa y funcionario o ya fue sustituido.")
        if correction_origin.reference_period != result["period"][:20]:
            # A cross-month rectification corrects the original period, not
            # just the amount. Keep the original intact until the new draft
            # has passed a separate approval, and block conflicting approvals.
            target_approved = db.scalar(select(CalculationRecord.id).where(
                CalculationRecord.company_id == correction_origin.company_id,
                CalculationRecord.employee_id == correction_origin.employee_id,
                CalculationRecord.reference_period == result["period"][:20],
                CalculationRecord.calculation_type.in_(SALARY_TYPES),
                CalculationRecord.status.in_(("Aprobado", "Validado")),
            ).limit(1))
            if target_approved is not None:
                return page(
                    request, data["kind"], data,
                    error=CalculationError(
                        "Ya existe una liquidación aprobada en el mes de destino. "
                        "Revisá ese cálculo antes de trasladar otra liquidación al mismo mes.",
                        "month",
                    ),
                    db=db, user=user, copied_from=correction_origin.id,
                )
            if official_salary_period_submitted(db, correction_origin.company_id, correction_origin.reference_period):
                raise HTTPException(
                    409, "El período original ya tiene una comunicación REOP/REI presentada. "
                    "Primero rectificá la comunicación ante el organismo; no se cambiará el registro interno automáticamente.",
                )
        if db.scalar(select(FinalSettlement.id).where(
            FinalSettlement.calculation_record_id == correction_origin.id
        )):
            raise HTTPException(409, "Un cálculo vinculado a una liquidación final se revisa desde ese procedimiento.")
        reason = clean(data.get("rectification_reason"), 300)
        if len(reason) < 12:
            return page(request, data["kind"], data,
                        error=CalculationError("Explicá el motivo de la rectificación (mínimo 12 caracteres).", "rectification_reason"),
                        db=db, user=user, copied_from=correction_origin.id)
        data["rectification_reason"] = reason
        data["rectifies_record_id"] = str(correction_origin.id)
        period_shift = correction_origin.reference_period != result["period"][:20]
        if period_shift:
            data["rectification_original_period"] = correction_origin.reference_period
        result.setdefault("notes", []).append(
            f"Rectificación del cálculo #{correction_origin.id}: {reason}. "
            + (f"Cambio de mes {correction_origin.reference_period} → {result['period'][:20]}. "
               if period_shift else "")
            + "El cálculo original permanece conservado; este registro requiere aprobación independiente."
        )
    item = CalculationRecord(company_id=scoped["company"].id, employee_id=scoped["employee"].id,
        calculation_type="suite_" + data["kind"], reference_period=result["period"][:20],
        input_json=json.dumps(data, ensure_ascii=False), result_json=json.dumps(result, ensure_ascii=False),
        amount=result["net"], status="Borrador", source=SOURCE, notes=clean(data.get("notes"),600), created_by=user.full_name)
    db.add(item)
    db.flush()
    if linked_settlement:
        linked_settlement.calculation_record_id = item.id
        linked_settlement.calculated_amount = int(result["net"])
        linked_settlement.status = "En Revisión"
        core.add_employee_event(
            db, scoped["employee"], user, "Liquidación", "Liquidación final calculada",
            f"Procedimiento #{linked_exit.id}; liquidación #{linked_settlement.id}; cálculo #{item.id}.",
            core.current_paraguay_date(), int(result["net"]),
        )
    origin_note = ""
    if data["kind"] == "salary" and data.get("attendance_source_id"):
        origin_note = f" · asistencia del cálculo #{data['attendance_source_id']} · " + ("modificada manualmente" if data.get("attendance_override") == "on" else "heredada")
    core.write_audit(db, user, "rectificar" if correction_origin else "crear", "liquidacion",
                     str(item.id), ("Rectifica #" + str(correction_origin.id) + " · " +
                                    data["rectification_reason"] if correction_origin
                                    else "Motor " + VERSION + origin_note))
    db.commit()
    if linked_settlement:
        return RedirectResponse(f"/app/final-settlements/{linked_settlement.id}", status_code=303)
    return RedirectResponse(f"/app/liquidaciones/{item.id}", status_code=303)


def saved_result(db, user, record_id):
    item = db.get(CalculationRecord, record_id)
    if not item or item.source != SOURCE or item.company_id not in core.company_ids_for_user(db, user):
        raise HTTPException(404)
    result = json.loads(item.result_json)
    result["status"] = f"Registro #{item.id} · {item.status} · no acredita pago ni firma"
    return item, result


@router.get("/app/liquidaciones/{record_id}")
def saved_page(request: Request, record_id: int, user: User = Depends(core.require_user), db: Session = Depends(core.get_db)):
    item, result = saved_result(db, user, record_id)
    metadata = json.loads(item.input_json or "{}")
    origin_id = metadata.get("rectifies_record_id")
    origin = None
    if origin_id:
        try:
            origin = db.get(CalculationRecord, int(origin_id))
        except (ValueError, TypeError):
            pass
        if origin and (origin.company_id != item.company_id or origin.employee_id != item.employee_id):
            origin = None
    revisions = []
    if item.calculation_type == "suite_salary" and item.employee_id:
        related = db.scalars(select(CalculationRecord).where(
            CalculationRecord.company_id == item.company_id,
            CalculationRecord.employee_id == item.employee_id,
            CalculationRecord.calculation_type == item.calculation_type,
            CalculationRecord.source == SOURCE,
            CalculationRecord.id != item.id,
        ).order_by(CalculationRecord.id.desc())).all()
        for candidate in related:
            if candidate.status not in {"Aprobado", "Validado"}:
                continue
            try:
                candidate_inputs = json.loads(candidate.input_json or "{}")
            except (ValueError, TypeError):
                continue
            if str(candidate_inputs.get("rectifies_record_id") or "") == str(item.id):
                revisions.append(candidate)
    response = core.render(request, "liquidation_saved.html", db, user, item=item, result=result,
                           rectification_origin=origin, approved_rectifications=revisions)
    response.headers.update(HEADERS)
    return response


@router.get("/app/liquidaciones/{record_id}/rectificar")
def rectify_saved_calculation(
    request: Request, record_id: int,
    user: User = Depends(core.require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(core.get_db),
):
    item, _ = saved_result(db, user, record_id)
    if item.calculation_type != "suite_salary" or item.status in {"Anulado", "Rectificado"}:
        raise HTTPException(409, "Solo se pueden rectificar cálculos salariales que no estén anulados ni sustituidos.")
    if db.scalar(select(FinalSettlement.id).where(FinalSettlement.calculation_record_id == item.id)):
        raise HTTPException(409, "Esta liquidación se rectifica desde el procedimiento de egreso.")
    values = json.loads(item.input_json)
    # The canonical identity and salary month live on the approved record,
    # not on an old form snapshot. Legacy/stale input_json may contain a
    # different "month", which otherwise causes a spurious 409 on save.
    values.update(
        kind="salary",
        company_id=item.company_id, employee_id=item.employee_id or 0,
        month=item.reference_period,
        rectifies_record_id=str(item.id), rectification_reason="",
        attendance_source_id="", attendance_source_sha256="", attendance_override="on",
        prepared_by=user.full_name,
    )
    return page(request, "salary", values, db=db, user=user, copied_from=item.id)


@router.get("/app/liquidaciones/{record_id}/copiar")
def copy_saved_calculation(request: Request, record_id: int, user: User = Depends(core.require_user),
                           db: Session = Depends(core.get_db)):
    item, _ = saved_result(db, user, record_id)
    values = json.loads(item.input_json)
    # «Usar como base» crea un cálculo independiente; no lo marca como
    # rectificación ni reutiliza por accidente un motivo anterior.
    values.pop("rectifies_record_id", None)
    values.pop("rectification_reason", None)
    if values.get("kind") == "salary":
        # Copying a historical snapshot is explicit; it is not a live source link.
        values.update(attendance_source_id="", attendance_source_sha256="", attendance_override="on")
    values.update(company_id=item.company_id, employee_id=item.employee_id or 0, prepared_by=user.full_name,
                  issued_date=context(values["kind"])["values"]["issued_date"])
    # The saved result remains immutable. This opens a new form for review.
    return page(request, values["kind"], values, db=db, user=user, copied_from=item.id)


@router.get("/app/liquidaciones/{record_id}/exportar/{fmt}")
async def saved_export(record_id: int, fmt: str, user: User = Depends(core.require_user), db: Session = Depends(core.get_db)):
    _, result = saved_result(db, user, record_id)
    return await download(result, fmt)



# REST API for the existing professional calculator engine. The HTML screens above
# and this API share the same calculation and tenant-scoping logic.
def _calculation_api_item(item: CalculationRecord) -> dict:
    try:
        inputs = json.loads(item.input_json or "{}")
    except (ValueError, TypeError):
        inputs = {}
    try:
        result = json.loads(item.result_json or "{}")
    except (ValueError, TypeError):
        result = {}
    return {
        "id": item.id,
        "company_id": item.company_id,
        "employee_id": item.employee_id,
        "calculation_type": item.calculation_type,
        "reference_period": item.reference_period or "",
        "amount": item.amount,
        "status": item.status,
        "source": item.source,
        "notes": item.notes or "",
        "inputs": inputs,
        "result": result,
        "created_by": item.created_by or "",
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


@router.get("/api/calculations")
def api_list_calculations(
    company_id: int | None = None,
    employee_id: int | None = None,
    tipo: str | None = None,
    limit: int = 100,
    user: User = Depends(core.require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(core.get_db),
):
    company_ids = core.company_ids_for_user(db, user)
    if limit < 1 or limit > 500:
        raise HTTPException(422, "El límite debe estar entre 1 y 500.")
    query = select(CalculationRecord).where(
        CalculationRecord.company_id.in_(company_ids), CalculationRecord.source == SOURCE
    ) if company_ids else select(CalculationRecord).where(False)
    if company_id:
        if company_id not in company_ids:
            raise HTTPException(404, "Empresa no encontrada.")
        query = query.where(CalculationRecord.company_id == company_id)
    if employee_id:
        employee = db.get(Employee, employee_id)
        if not employee or employee.company_id not in company_ids or (company_id and employee.company_id != company_id):
            raise HTTPException(404, "Funcionario no encontrado.")
        query = query.where(CalculationRecord.employee_id == employee_id)
    if tipo:
        if tipo not in TITLES:
            raise HTTPException(422, "Tipo de cálculo no válido.")
        query = query.where(CalculationRecord.calculation_type == "suite_" + tipo)
    items = list(db.scalars(query.order_by(CalculationRecord.created_at.desc()).limit(limit)))
    return {"items": [_calculation_api_item(item) for item in items], "count": len(items), "limit": limit}


@router.get("/api/calculations/{record_id}")
def api_get_calculation(
    record_id: int,
    user: User = Depends(core.require_user),
    db: Session = Depends(core.get_db),
):
    item, _ = saved_result(db, user, record_id)
    return _calculation_api_item(item)


@router.post("/api/calculations", status_code=201)
async def api_create_calculation(
    request: Request,
    user: User = Depends(core.require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(core.get_db),
):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Se esperaba un cuerpo JSON válido.") from None
    if not isinstance(payload, dict):
        raise HTTPException(422, "El cuerpo debe ser un objeto JSON.")
    data = {key: str(value) for key, value in payload.items() if value is not None}
    if data.get("kind") not in TITLES:
        raise HTTPException(422, "Tipo de cálculo no válido.")
    scoped = private_context(db, user, data)
    if not scoped["company"] or not scoped["employee"]:
        raise HTTPException(422, "Seleccioná empresa y funcionario para guardar el cálculo.")
    try:
        result = calculate_scoped(data, db, scoped)
    except CalculationError as exc:
        raise HTTPException(422, str(exc)) from None
    if result["net"] > 2147483647:
        raise HTTPException(422, "El resultado supera el límite de importe admitido.")
    item = CalculationRecord(
        company_id=scoped["company"].id,
        employee_id=scoped["employee"].id,
        calculation_type="suite_" + data["kind"],
        reference_period=result["period"][:20],
        input_json=json.dumps(data, ensure_ascii=False),
        result_json=json.dumps(result, ensure_ascii=False),
        amount=result["net"], status="Borrador", source=SOURCE,
        notes=clean(data.get("notes"), 600), created_by=user.full_name,
    )
    db.add(item)
    db.flush()
    core.write_audit(db, user, "crear_api", "liquidacion", str(item.id), "Motor " + VERSION)
    db.commit()
    db.refresh(item)
    return JSONResponse(_calculation_api_item(item), status_code=201)


@router.put("/api/calculations/{record_id}")
async def api_replace_calculation(
    record_id: int,
    request: Request,
    user: User = Depends(core.require_roles("administrador", "contador")),
    db: Session = Depends(core.get_db),
):
    item, _ = saved_result(db, user, record_id)
    if item.status in {"Aprobado", "Validado", "Anulado"}:
        raise HTTPException(409, "Este registro aprobado o anulado no puede sobrescribirse. Creá una rectificación desde su detalle.")
    if db.scalar(select(FinalSettlement.id).where(FinalSettlement.calculation_record_id == item.id)):
        raise HTTPException(409, "Los cálculos vinculados a egresos solo se sustituyen desde el procedimiento de liquidación final.")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Se esperaba un cuerpo JSON válido.") from None
    if not isinstance(payload, dict):
        raise HTTPException(422, "El cuerpo debe ser un objeto JSON.")
    data = {key: str(value) for key, value in payload.items() if value is not None}
    expected_kind = item.calculation_type.removeprefix("suite_")
    if data.get("kind", expected_kind) != expected_kind:
        raise HTTPException(422, "No se puede cambiar el tipo de una liquidación existente.")
    data["kind"] = expected_kind
    data["company_id"] = str(item.company_id)
    data["employee_id"] = str(item.employee_id or "")
    scoped = private_context(db, user, data)
    if not scoped["company"] or not scoped["employee"] or scoped["company"].id != item.company_id:
        raise HTTPException(422, "El funcionario debe permanecer dentro de la empresa del registro.")
    try:
        result = calculate_scoped(data, db, scoped)
    except CalculationError as exc:
        raise HTTPException(422, str(exc)) from None
    if result["net"] > 2147483647:
        raise HTTPException(422, "El resultado supera el límite de importe admitido.")
    item.reference_period = result["period"][:20]
    item.input_json = json.dumps(data, ensure_ascii=False)
    item.result_json = json.dumps(result, ensure_ascii=False)
    item.amount = result["net"]
    item.notes = clean(data.get("notes"), 600)
    item.status = "Borrador"
    core.write_audit(db, user, "actualizar_api", "liquidacion", str(item.id), "Motor " + VERSION)
    db.commit()
    db.refresh(item)
    return _calculation_api_item(item)


@router.patch("/api/calculations/{record_id}")
async def api_update_calculation_status(
    record_id: int,
    request: Request,
    user: User = Depends(core.require_roles("administrador", "contador")),
    db: Session = Depends(core.get_db),
):
    item, _ = saved_result(db, user, record_id)
    linked = db.scalar(select(FinalSettlement).where(FinalSettlement.calculation_record_id == item.id))
    if linked:
        raise HTTPException(409, "Este cálculo pertenece a un procedimiento de egreso; se aprueba desde Liquidación Final.")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Se esperaba un cuerpo JSON válido.") from None
    if not isinstance(payload, dict):
        raise HTTPException(422, "El cuerpo debe ser un objeto JSON.")
    if "status" in payload:
        if item.status == "Anulado":
            raise HTTPException(409, "Una carga eliminada no puede modificarse.")
        if payload["status"] not in {"Borrador", "Revisar", "Aprobado"}:
            raise HTTPException(422, "Estado no válido.")
        if payload["status"] == "Aprobado":
            core._revalidate_calculation_before_approval(item, db)
        item.status = payload["status"]
    if "notes" in payload:
        item.notes = clean(payload["notes"], 600)
    core.write_audit(db, user, "actualizar_api", "liquidacion", str(item.id), item.status)
    db.commit()
    db.refresh(item)
    return _calculation_api_item(item)


@router.delete("/api/calculations/{record_id}", status_code=204)
def api_delete_calculation(
    record_id: int,
    request: Request,
    user: User = Depends(core.require_roles("administrador", "contador")),
    db: Session = Depends(core.get_db),
):
    item, _ = saved_result(db, user, record_id)
    core._delete_calculation_operational(db, user, item, request.query_params.get("motivo", ""))
    db.commit()
    return Response(status_code=204)


def payroll_result(payroll, line, detail=None):
    names = (("base_salary","Salario base"), ("overtime","Horas extras"), ("commissions","Comisiones"),
             ("bonuses","Bonificaciones"), ("other_income","Otros ingresos"))
    discounts = (("ips_employee","Aporte IPS"), ("absences_discount","Ausencias"), ("advances","Anticipos"),
                 ("other_discount","Otros descuentos"))
    def rows(fields):
        return [dict(label=label, amount=getattr(line,key), formula="Importe guardado en la nómina", legal="")
                for key,label in fields if getattr(line,key)]
    earnings, deductions = rows(names), rows(discounts)
    gross, total = sum(r["amount"] for r in earnings), sum(r["amount"] for r in deductions)
    if (any(r["amount"] < 0 for r in earnings + deductions) or
        gross != line.gross or total != line.total_discounts or gross - total != line.net or line.net < 0):
        raise HTTPException(409, "La nómina contiene importes inconsistentes. Revisá y guardá los conceptos antes de emitir.")
    # When a saved IPS base/rate exists, the receipt must not display a deduction
    # that conflicts with the formula printed underneath it. Legacy rows with both
    # values absent remain exportable, while partially migrated snapshots fail closed.
    if (line.ips_base is None) != (line.ips_rate is None):
        raise HTTPException(409, "La nómina tiene una base o tasa IPS incompleta. Revisá la línea antes de emitir.")
    if line.ips_base is not None and line.ips_rate is not None:
        if line.ips_base < 0 or line.ips_rate < 0 or line.ips_rate > 100:
            raise HTTPException(409, "La nómina contiene una base o tasa IPS inválida.")
        expected_ips = round_gs(Decimal(str(line.ips_base)) * Decimal(str(line.ips_rate)) / Decimal("100"))
        if line.ips_employee != expected_ips:
            raise HTTPException(409, "El aporte IPS guardado no coincide con la base y la tasa registradas. Revisá la línea antes de emitir.")
        for row in deductions:
            if row["label"] == "Aporte IPS":
                row["formula"] = f"Base guardada Gs. {line.ips_base:,} × {line.ips_rate}%"
    if line.other_discount_note:
        for row in deductions:
            if row["label"] == "Otros descuentos":
                row["formula"] = line.other_discount_note
    employee, company = line.employee, payroll.company
    return dict(kind="salary", title="Liquidación de salario", engine_version=VERSION,
        identity=dict(employer=company.legal_name, ruc=company.ruc, employee=employee.full_name,
            ci=employee.document_number, position=employee.position, prepared_by="",
            reference=f"Nómina {payroll.id} / funcionario {employee.id}", payment_method=detail.payment_method if detail else ""),
        issued_date=datetime.now(ZoneInfo("America/Asuncion")).strftime("%d/%m/%Y"),
        period=payroll.period, status=f"Nómina {payroll.status} · pendiente de constancia de pago y firma",
        earnings=earnings, deductions=deductions, gross=gross, discounts=total, net=line.net,
        net_label="Neto a percibir", partial=False, employer_cost=None, copies=2,
        facts=[dict(label="Jornadas trabajadas", value=str(detail.days_worked))] if detail else [],
        warnings=[] if detail else ["Completá las jornadas trabajadas antes de firmar el recibo (art. 235)."],
        notes=([line.ips_basis_note] if line.ips_basis_note else []) + ["Importes guardados en la nómina. La descarga conserva sus valores; no aplica las tasas actuales.",
               "Revisar respaldo de ausencias, anticipos y otros descuentos. No implica renuncia de derechos."], sources=[])


@router.get("/app/payrolls/{payroll_id}/recibos.pdf")
async def payroll_receipts(payroll_id: int, line_id: int | None = None,
                           user: User = Depends(core.require_roles("administrador", "contador", "auxiliar", "empresa")), db: Session = Depends(core.get_db)):
    payroll = db.get(Payroll, payroll_id)
    if not payroll or payroll.company_id not in core.company_ids_for_user(db, user):
        raise HTTPException(404)
    query = select(PayrollLine).where(PayrollLine.payroll_id == payroll.id)
    if line_id is not None:
        query = query.where(PayrollLine.id == line_id)
    lines = list(db.scalars(query.order_by(PayrollLine.id)))
    if not lines:
        raise HTTPException(404, "No hay recibos para emitir.")
    if len(lines) > 500:
        raise HTTPException(422, "Descargá los recibos por funcionario para nóminas de más de 500 personas.")
    details = {d.payroll_line_id: d for d in db.scalars(select(PayrollComplianceDetail).where(
        PayrollComplianceDetail.payroll_line_id.in_([line.id for line in lines])))}
    results = [payroll_result(payroll, line, details.get(line.id)) for line in lines]
    if len(results) == 1:
        return await download(results[0], "pdf")
    def archive():
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as bundle:
            for line, result in zip(lines, results):
                bundle.writestr(f"recibo-{payroll.id}-{line.id}.pdf", build_liquidation_pdf(result))
        return stream.getvalue()
    return Response(await run_in_threadpool(archive), media_type="application/zip",
                    headers={**HEADERS, "Content-Disposition": f'attachment; filename="recibos-nomina-{payroll.id}.zip"'})


core.app.include_router(router)
