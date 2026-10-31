from __future__ import annotations

import io
import json
import re
import unicodedata
from calendar import monthrange
import zipfile
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from . import main as core
from .entity_selects import seed_choices
from .calculator_fields import GROUPS
from .form_utils import OptionalQueryId
from .labor_calculator import CalculationError, SOURCE, TITLES, VERSION, amount as round_gs, calculate, clean, settlement_projection
from .liquidation_export import build_liquidation_pdf, build_liquidation_csv
from .labor_examples import example_values
from .models import CalculationRecord, Company, Employee, EmployeeExit, FinalSettlement, Payroll, PayrollLine, PayrollComplianceDetail, User
from .salary_history import employee_salary_history, salary_from_history, salary_for_period
from .payroll_average import annotate_average, propose_monthly_average, verify_average_selection

router = APIRouter()
HEADERS = {"Cache-Control": "no-store", "X-Digit-Laboral-Version": VERSION}


def context(kind, values=None):
    if kind not in TITLES:
        raise HTTPException(404, "Calculadora no encontrada.")
    today = datetime.now(ZoneInfo("America/Asuncion")).date()
    defaults = {f["name"]: f["value"] for g in GROUPS[kind] for f in g["fields"]}
    defaults.update(issued_date=today.isoformat(), month=today.strftime("%Y-%m"),
                    year=str(today.year), end_date=today.isoformat())
    if values is not None:
        defaults.update(values)
    return dict(kind=kind, titles=TITLES, groups=GROUPS[kind], values=defaults, result=None,
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
    return data


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
    return dict(private=True, companies=companies, employees=employees, company=company,
                employee=employee, company_id=company_id, employee_id=employee_id, history=history,
                salary_history=salary_history)


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
    existing = result.setdefault("warnings", [])
    for warning in period_warnings:
        if warning not in existing:
            existing.append(warning)
    return result


def page(request, kind, data=None, result=None, error=None, db=None, user=None, copied_from=None):
    values = dict(data) if data is not None else None
    private = private_context(db, user, values if values is not None else {}) if user else {}
    ctx = context(kind, values)
    salary_history_data = [
        {"id": item.id, "effective_from": item.effective_from.isoformat(), "new_salary": int(item.new_salary or 0)}
        for item in private.get("salary_history", [])
    ]
    ctx.update(private, salary_history_data=salary_history_data, result=result, error=str(error or ""),
               error_field=getattr(error, "field", ""), copied_from=copied_from)
    response = core.render(request, "labor_workbench.html", db, user, **ctx)
    response.headers.update(HEADERS)
    if error:
        response.status_code = 422
    return response


def calculate_scoped(data, db, scoped):
    proposal = verify_average_selection(db, scoped.get("employee"), data)
    result = annotate_average(calculate(data), proposal)
    return add_salary_period_warnings(result, db, scoped, data)


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


@router.get("/app/liquidaciones")
def professional_page(request: Request, tipo: str = "settlement", company_id: OptionalQueryId = None, employee_id: OptionalQueryId = None, exit_id: OptionalQueryId = None,
                      user: User = Depends(core.require_user), db: Session = Depends(core.get_db)):
    allowed_company_ids = core.company_ids_for_user(db, user)
    company_id, employee_id = core.default_labor_context(
        request, db, user, allowed_company_ids, company_id, employee_id
    )
    values = dict(context(tipo)["values"], company_id=company_id or 0, employee_id=employee_id or 0, prepared_by=user.full_name)
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
    return page(request, tipo, values, db=db, user=user)


@router.post("/herramientas/calcular")
async def public_calculate(request: Request):
    data = await form_values(request)
    try:
        result = calculate(data)
    except CalculationError as exc:
        return page(request, data["kind"], data, error=exc)
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
        return page(request, data["kind"], data, error=exc, db=db, user=user)
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
    core.write_audit(db, user, "crear", "liquidacion", str(item.id), "Motor " + VERSION)
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
    response = core.render(request, "liquidation_saved.html", db, user, item=item, result=result)
    response.headers.update(HEADERS)
    return response


@router.get("/app/liquidaciones/{record_id}/copiar")
def copy_saved_calculation(request: Request, record_id: int, user: User = Depends(core.require_user),
                           db: Session = Depends(core.get_db)):
    item, _ = saved_result(db, user, record_id)
    values = json.loads(item.input_json)
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
        if payload["status"] not in {"Borrador", "Revisar", "Aprobado", "Anulado"}:
            raise HTTPException(422, "Estado no válido.")
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
    user: User = Depends(core.require_roles("administrador", "contador")),
    db: Session = Depends(core.get_db),
):
    item, _ = saved_result(db, user, record_id)
    if db.scalar(select(FinalSettlement.id).where(FinalSettlement.calculation_record_id == item.id)):
        raise HTTPException(409, "No se puede anular un cálculo asociado a un procedimiento de egreso.")
    item.status = "Anulado"
    core.write_audit(db, user, "anular_api", "liquidacion", str(item.id), item.status)
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
