from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from . import main as core
from .calculator_fields import GROUPS
from .labor_calculator import CalculationError, SOURCE, TITLES, VERSION, calculate, clean
from .liquidation_export import build_liquidation_pdf, build_liquidation_csv
from .models import CalculationRecord, Company, Employee, Payroll, PayrollLine, PayrollComplianceDetail, User

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
    companies = list(db.scalars(select(Company).where(Company.id.in_(company_ids)).order_by(Company.legal_name)))
    try:
        company_id = int(data.get("company_id") or 0)
        employee_id = int(data.get("employee_id") or 0)
    except (ValueError, TypeError):
        raise HTTPException(422, "Selección inválida de empresa o funcionario.")
    company = core.company_allowed(db, user, company_id) if company_id else None
    employee = db.get(Employee, employee_id) if employee_id else None
    if employee_id and (not employee or not company or employee.company_id != company.id):
        raise HTTPException(404, "Funcionario no encontrado en la empresa seleccionada.")
    employees = list(db.scalars(select(Employee).where(Employee.company_id == company_id).order_by(Employee.full_name))) if company else []
    query = select(CalculationRecord).where(CalculationRecord.company_id.in_(company_ids), CalculationRecord.source == SOURCE)
    if company:
        query = query.where(CalculationRecord.company_id == company.id)
    if employee:
        query = query.where(CalculationRecord.employee_id == employee.id)
    history = list(db.scalars(query.order_by(CalculationRecord.id.desc()).limit(30)))
    if company:
        data.update(employer=company.legal_name, ruc=company.ruc)
    if employee:
        data.update(employee=employee.full_name, ci=employee.document_number, position=employee.position)
    return dict(private=True, companies=companies, employees=employees, company=company,
                employee=employee, company_id=company_id, employee_id=employee_id, history=history)


def page(request, kind, data=None, result=None, error=None, db=None, user=None):
    values = dict(data) if data is not None else None
    private = private_context(db, user, values if values is not None else {}) if user else {}
    ctx = context(kind, values)
    ctx.update(private, result=result, error=str(error or ""), error_field=getattr(error, "field", ""))
    response = core.render(request, "labor_workbench.html", db, user, **ctx)
    response.headers.update(HEADERS)
    if error:
        response.status_code = 422
    return response


@router.get("/herramientas")
def public_page(request: Request, tipo: str = "salary"):
    return page(request, tipo)


@router.get("/app/liquidaciones")
def professional_page(request: Request, tipo: str = "salary", company_id: int = 0, employee_id: int = 0,
                      user: User = Depends(core.require_user), db: Session = Depends(core.get_db)):
    values = dict(context(tipo)["values"], company_id=company_id, employee_id=employee_id, prepared_by=user.full_name)
    scoped = private_context(db, user, values)
    if employee := scoped["employee"]:
        values.update(salary=str(employee.base_salary), start_date=employee.admission_date.isoformat(),
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


@router.post("/app/liquidaciones/calcular")
async def professional_calculate(request: Request, user: User = Depends(core.require_user),
                                 db: Session = Depends(core.get_db)):
    data = await form_values(request)
    private_context(db, user, data)
    try:
        result = calculate(data)
    except CalculationError as exc:
        return page(request, data["kind"], data, error=exc, db=db, user=user)
    return page(request, data["kind"], data, result=result, db=db, user=user)


async def download(result, fmt):
    if fmt not in {"pdf", "csv"}:
        raise HTTPException(404)
    builder = build_liquidation_pdf if fmt == "pdf" else build_liquidation_csv
    content = await run_in_threadpool(builder, result)
    return Response(content, media_type="application/pdf" if fmt == "pdf" else "text/csv; charset=utf-8",
                    headers={**HEADERS, "Content-Disposition": f'attachment; filename="digit-laboral-{result["kind"]}.{fmt}"'})


@router.post("/herramientas/exportar/{fmt}")
async def public_export(request: Request, fmt: str):
    data = await form_values(request)
    try:
        return await download(calculate(data), fmt)
    except CalculationError as exc:
        return page(request, data["kind"], data, error=exc)


@router.post("/app/liquidaciones/guardar")
async def save_calculation(request: Request,
                           user: User = Depends(core.require_roles("administrador", "contador", "auxiliar")),
                           db: Session = Depends(core.get_db)):
    data = await form_values(request)
    scoped = private_context(db, user, data)
    try:
        if not scoped["company"] or not scoped["employee"]:
            raise CalculationError("Seleccioná empresa y funcionario para guardar el cálculo.")
        result = calculate(data)
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
    core.write_audit(db, user, "crear", "liquidacion", str(item.id), "Motor " + VERSION)
    db.commit()
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


@router.get("/app/liquidaciones/{record_id}/exportar/{fmt}")
async def saved_export(record_id: int, fmt: str, user: User = Depends(core.require_user), db: Session = Depends(core.get_db)):
    _, result = saved_result(db, user, record_id)
    return await download(result, fmt)


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
    if line.ips_base is not None:
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
                           user: User = Depends(core.require_user), db: Session = Depends(core.get_db)):
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
