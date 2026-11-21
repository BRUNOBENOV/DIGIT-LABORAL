"""Operator actions for salary reconciliation and the study's monthly REOP view."""
from __future__ import annotations
from typing import Annotated
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import main as core
from .approved_salary_import import choose_salary_source, salary_excluded_records
from .models import CalculationRecord, Company, Employee, IntegrationBatch, Payroll, ReopSalaryMonth, User
from .official_salary_import import REOP_PAYMENT_LABELS, SalaryImportError, prepare_import
from .reop_ledger import MONTH, PATRONAL, STAGES, checked_snapshot, compare_ledger
from .reop_month import lock_month, payment_settings
from .salary_data import APPROVED, SALARY_TYPES, object_json

router = APIRouter()
PATH = "/app/compliance/salary-import"
Operator = Annotated[User, Depends(core.require_roles("administrador", "contador"))]
Database = Annotated[Session, Depends(core.get_db)]


def valid_period(period):
    if not MONTH.fullmatch(period):
        raise HTTPException(422, "Seleccioná un mes válido.")
    return period


@router.post(PATH + "/{company_id}/{period}/payments")
async def save_payments(company_id: int, period: str, request: Request, user: Operator, db: Database):
    core.company_allowed(db, user, company_id)
    valid_period(period)
    form = await request.form(max_fields=20000)
    group = form.get("default", "auto")
    allowed = {"auto", *REOP_PAYMENT_LABELS}
    updates = {key[4:]: val for key, val in form.items() if key.startswith("pay_")}
    if group not in allowed or any(not k.isascii() or not k.isdigit() or len(k) > 12 or v not in allowed for k,v in updates.items()):
        raise HTTPException(422, "Forma de pago inválida.")
    ids = set(map(int, updates))
    if ids != set(db.scalars(select(Employee.id).where(Employee.company_id == company_id, Employee.id.in_(ids)))):
        raise HTTPException(404, "El trabajador no pertenece a la empresa.")
    month = lock_month(db, company_id, period)
    settings = payment_settings(db, company_id, period, month)
    if form.get("revision", "") != settings.get("revision", ""):
        raise HTTPException(409, "Las formas de pago cambiaron. Recargá la página para revisarlas.")
    overrides = dict(settings["overrides"])
    for key, value in updates.items():
        if value == "auto":
            overrides.pop(key, None)
        else:
            overrides[key] = value
    month.payments = {"default": group, "overrides": overrides, "apply_group": group in REOP_PAYMENT_LABELS,
                      "revision": uuid4().hex}
    core.write_audit(db, user, "revisar_formas_pago_reop", "empresa", str(company_id), period)
    db.commit()
    params = {"company_id": company_id, "period": period, "authority": "REOP"}
    params.update({k: form[k] for k in ("employee_id", "source_type", "other_category") if form.get(k)})
    return RedirectResponse(PATH + "?" + urlencode(params), status_code=303)


@router.post(PATH + "/{company_id}/{period}/ledger")
async def observe_list(company_id: int, period: str, request: Request, user: Operator, db: Database):
    company = core.company_allowed(db, user, company_id)
    valid_period(period)
    body = await core._json_object(request)
    patronal = body.get("patronal")
    if not isinstance(patronal, str) or not PATRONAL.fullmatch(patronal):
        raise HTTPException(422, "Seleccioná una patronal.")
    source = body.get("source_type", "auto")
    category = body.get("other_category", "")
    employee_id = body.get("employee_id")
    if not isinstance(source, str) or not isinstance(category, str):
        raise HTTPException(422, "Origen de la planilla inválido.")
    if employee_id is not None and (type(employee_id) is not int or not db.scalar(
            select(Employee.id).where(Employee.company_id == company_id, Employee.id == employee_id))):
        raise HTTPException(404, "El trabajador no pertenece a la empresa.")
    month = lock_month(db, company_id, period)
    choices = payment_settings(db, company_id, period, month)
    try:
        rows, _ = prepare_import(db, company, period, "REOP", source_type=source, other_category=category, employee_id=employee_id,
                                 payment_code=choices["default"], payment_overrides=choices["overrides"],
                                 apply_group=choices.get("apply_group", False))
        if patronal not in {str(row[0]) for row in rows}:
            raise ValueError("La patronal no corresponde a la planilla seleccionada.")
        snapshot = checked_snapshot(body.get("snapshot"), patronal, period)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    prior = month.snapshots.get(patronal, {})
    if prior.get("digest", "") != body.get("previous", "") and prior.get("digest") != snapshot["digest"]:
        raise HTTPException(409, "Hay una lectura más reciente. Recargá y volvé a consultar REOP.")
    month.snapshots = {**month.snapshots, patronal: snapshot}
    core.write_audit(db, user, "conciliar_listado_reop", "empresa", str(company_id),
                     f"{period} · patronal {patronal} · {len(snapshot['records'])} comunicaciones")
    db.commit()
    selected = [row for row in rows if str(row[0]) == patronal]
    review = compare_ledger(selected, {patronal: snapshot}, include_extras=False)
    return {"digest": snapshot["digest"], "checked_rows": len(selected), "missing": review["counts"]["missing"],
            "confirmed": review["counts"]["confirmed"]}


@router.get("/app/compliance/reop-month")
def monthly_view(request: Request, user: Operator, db: Database, period: str = "", status: str = "", q: str = "", page: int = 1):
    period = valid_period(period or core.current_paraguay_date().strftime("%Y-%m"))
    if status and status not in STAGES:
        raise HTTPException(422, "Estado mensual desconocido.")
    companies = list(db.scalars(select(Company).where(
        Company.id.in_(core.company_ids_for_user(db, user)), Company.status != "Archivada"
    ).order_by(Company.legal_name, Company.id)))
    search = q.strip().casefold()
    if search:
        companies = [c for c in companies if search in " ".join(str(x or "") for x in
                     (c.legal_name, c.legacy_code, c.company_code, c.ruc, c.mtess_employer_number)).casefold()]
    ids = [c.id for c in companies]
    months = {m.company_id: m for m in db.scalars(select(ReopSalaryMonth).where(
        ReopSalaryMonth.company_id.in_(ids), ReopSalaryMonth.period == period))}
    histories = {}
    for cid, raw, state in db.execute(select(IntegrationBatch.company_id, IntegrationBatch.payload_json, IntegrationBatch.status)
            .where(IntegrationBatch.company_id.in_(ids), IntegrationBatch.period == period,
                   IntegrationBatch.authority == "REOP", IntegrationBatch.batch_type == "Importación de salarios")
            .order_by(IntegrationBatch.id.desc())):
        histories.setdefault(cid, []).append((object_json(raw), state))
    active = set(db.scalars(select(CalculationRecord.company_id).where(CalculationRecord.company_id.in_(ids),
        CalculationRecord.reference_period == period, CalculationRecord.calculation_type.in_(SALARY_TYPES),
        CalculationRecord.status.in_(APPROVED)).distinct()))
    active.update(db.scalars(select(Payroll.company_id).where(Payroll.company_id.in_(ids),
                              Payroll.period == period, Payroll.status == "Cerrada")))
    items, counts = [], dict.fromkeys(STAGES, 0)
    for company in companies:
        month = months.get(company.id)
        history = histories.get(company.id, [])
        imported = any((p.get("assistant_progress") or {}).get("phase") == "imported" or s in {"Presentado", "Aceptado"}
                       for p,s in history)
        stage = "imported" if imported else "prepare"
        count = confirmed = 0
        if company.id in active or month:
            payments = month.payments if month and month.payments else next((
                {"default": p.get("payment_code") or "auto", "overrides": p.get("payment_overrides") or {},
                 "apply_group": bool(p.get("apply_group"))}
                for p,_ in history if p.get("employee_scope_id") is None), {"default":"auto", "overrides":{}})
            snapshots = month.snapshots if month else {}
            try:
                source = choose_salary_source(db, company.id, period, "auto")
                category = next((p.get("other_category") or "" for p,_ in history if p.get("employee_scope_id") is None), "")
                rows, errors = prepare_import(db, company, period, "REOP", source_type=source, other_category=category,
                    payment_code=payments["default"], payment_overrides=payments["overrides"], apply_group=payments.get("apply_group", False))
            except SalaryImportError:
                rows, errors = [], ["Sin planilla"]
            review = compare_ledger(rows, snapshots)
            count, confirmed = len(rows), review["counts"]["confirmed"]
            incomplete = count and source == "approved" and bool(salary_excluded_records(db, company.id, period))
            if count and not errors and review["all_confirmed"] and not incomplete:
                stage = "confirmed"
            elif imported or any(s["records"] for s in snapshots.values()):
                stage = "imported"
            elif count and not errors and not incomplete:
                stage = "ready"
        counts[stage] += 1
        if not status or status == stage:
            items.append(dict(company=company, stage=stage, count=count, confirmed=confirmed, observed=bool(month and month.snapshots)))
    pages = max(1, (len(items) + 49) // 50)
    page = max(1, min(page, pages))
    return core.render(request, "reop_month.html", db, user, period=period, status=status, stages=STAGES, q=q,
                       counts=counts, items=items[(page-1)*50:page*50], page=page, pages=pages)
