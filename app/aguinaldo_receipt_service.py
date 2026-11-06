"""Read-only aguinaldo receipts backed by existing saved records.

The report never recalculates amounts, invents REOP numbers or assumes that an
approved calculation proves the employee has been paid.
"""
from __future__ import annotations

import json
from datetime import date

from sqlalchemy import String, cast, func, literal, or_, select, union_all

from .models import Aguinaldo, AguinaldoReceiptDetail, CalculationRecord, Company, Employee

AGUINALDO_CALC_TYPES = ("aguinaldo", "suite_aguinaldo")
PAYMENT_METHODS = ("", "Efectivo", "Transferencia bancaria", "Cheque", "Otro medio")
SOURCE_LABELS = {"registro": "Cálculo de aguinaldo", "calculo": "Calculadora"}


def read_record(db, company_ids: list[int], source_kind: str, record_id: int):
    """Resolve the owner before reading payment metadata or exporting a PDF."""
    if source_kind == "registro":
        item = db.get(Aguinaldo, record_id)
        employee = db.get(Employee, item.employee_id) if item else None
        company = db.get(Company, employee.company_id) if employee else None
    elif source_kind == "calculo":
        item = db.get(CalculationRecord, record_id)
        if item is None or item.calculation_type not in AGUINALDO_CALC_TYPES or item.employee_id is None:
            item, employee, company = None, None, None
        else:
            employee = db.get(Employee, item.employee_id)
            company = db.get(Company, item.company_id)
    else:
        return None
    if not item or not employee or not company:
        return None
    if company.id not in company_ids or employee.company_id != company.id:
        return None
    return item, employee, company


def read_payment_detail(db, source_kind: str, item_id: int, company_id: int, employee_id: int):
    return db.scalar(select(AguinaldoReceiptDetail).where(
        AguinaldoReceiptDetail.source_kind == source_kind,
        AguinaldoReceiptDetail.source_id == item_id,
        AguinaldoReceiptDetail.company_id == company_id,
        AguinaldoReceiptDetail.employee_id == employee_id,
    ))


def _json_dict(value):
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def receipt_model(item, employee, company, source_kind, detail=None):
    if source_kind == "registro":
        exercise = item.year
        amount = item.calculated_amount
        remunerations = item.total_remunerations
        source_description = "Registro anual guardado"
    else:
        period = (item.reference_period or "").strip()
        exercise = int(period[:4]) if len(period) >= 4 and period[:4].isdigit() and 1900 <= int(period[:4]) <= 2100 else None
        amounts = _json_dict(item.result_json)
        inputs = _json_dict(item.input_json)
        remunerations = amounts.get("total_remunerations", inputs.get("total_remunerations"))
        if not isinstance(remunerations, (int, float)) or isinstance(remunerations, bool):
            remunerations = None
        amount = item.amount
        source_description = "Cálculo guardado · " + (item.source or "Sin origen")
    status = item.status or "Borrador"
    code = f"DL-AG-{'A' if source_kind == 'registro' else 'C'}{item.id:06d}"
    return {
        "id": item.id,
        "source_kind": source_kind,
        "source_label": SOURCE_LABELS[source_kind],
        "code": code,
        "exercise": exercise,
        "amount": int(amount or 0),
        "remunerations": int(remunerations) if remunerations is not None else None,
        "status": status,
        "annulled": status.lower() == "anulado",
        "employer_name": company.legal_name,
        "employer_ruc": company.ruc or "",
        "employee_name": employee.full_name,
        "employee_ci": employee.document_number,
        "company_id": company.id,
        "employee_id": employee.id,
        "created_at": item.created_at,
        "source_description": source_description,
        "payment_method": detail.payment_method if detail else "",
        "payment_date": detail.payment_date if detail else None,
        "has_payment_data": bool(detail and detail.payment_date and detail.payment_method),
        "notes": item.notes or "",
    }


def report_rows(db, company_ids, *, company_id=None, employee_id=None, q="", status="", year=None,
                page=1, page_size=25):
    """One bounded SQL result across the two persisted aguinaldo sources."""
    if not company_ids:
        return {"items": [], "total": 0, "page": 1, "pages": 1, "page_size": 25}
    shared_company = (
        Company.id == company_id if company_id is not None else None
    )
    shared_employee = (
        Employee.id == employee_id if employee_id is not None else None
    )
    a = select(
        literal("registro").label("source_kind"),
        Aguinaldo.id.label("id"),
        Company.id.label("company_id"), Company.legal_name.label("company_name"),
        Company.ruc.label("company_ruc"),
        Employee.id.label("employee_id"), Employee.full_name.label("employee_name"),
        Employee.document_number.label("employee_ci"),
        cast(Aguinaldo.year, String).label("exercise"),
        Aguinaldo.status.label("status"), Aguinaldo.calculated_amount.label("amount"),
        Aguinaldo.created_at.label("created_at"),
    ).select_from(Aguinaldo).join(Employee, Employee.id == Aguinaldo.employee_id).join(
        Company, Company.id == Employee.company_id
    ).where(Company.id.in_(company_ids))
    c = select(
        literal("calculo").label("source_kind"),
        CalculationRecord.id.label("id"),
        Company.id.label("company_id"), Company.legal_name.label("company_name"),
        Company.ruc.label("company_ruc"),
        Employee.id.label("employee_id"), Employee.full_name.label("employee_name"),
        Employee.document_number.label("employee_ci"),
        func.substr(CalculationRecord.reference_period, 1, 4).label("exercise"),
        CalculationRecord.status.label("status"), CalculationRecord.amount.label("amount"),
        CalculationRecord.created_at.label("created_at"),
    ).select_from(CalculationRecord).join(
        Employee, Employee.id == CalculationRecord.employee_id
    ).join(Company, Company.id == CalculationRecord.company_id).where(
        Company.id.in_(company_ids), Employee.company_id == Company.id,
        CalculationRecord.calculation_type.in_(AGUINALDO_CALC_TYPES),
    )
    if shared_company is not None:
        a, c = a.where(shared_company), c.where(shared_company)
    if shared_employee is not None:
        a, c = a.where(shared_employee), c.where(shared_employee)
    if status:
        a, c = a.where(Aguinaldo.status == status), c.where(CalculationRecord.status == status)
    if year is not None:
        a = a.where(Aguinaldo.year == year)
        c = c.where(func.substr(CalculationRecord.reference_period, 1, 4) == str(year))
    if q.strip():
        term = f"%{q.strip()[:120]}%"
        a = a.where(or_(Employee.full_name.ilike(term), Employee.document_number.ilike(term), Company.legal_name.ilike(term), Company.ruc.ilike(term)))
        c = c.where(or_(Employee.full_name.ilike(term), Employee.document_number.ilike(term), Company.legal_name.ilike(term), Company.ruc.ilike(term)))
    combined = union_all(a, c).subquery("annual_bonus_records")
    total = int(db.scalar(select(func.count()).select_from(combined)) or 0)
    page_size = page_size if page_size in {25, 50, 100} else 25
    pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, pages))
    rows = db.execute(select(combined).order_by(combined.c.created_at.desc(), combined.c.id.desc(), combined.c.source_kind.asc())
                      .limit(page_size).offset((page - 1) * page_size)).mappings()
    return {"items": [dict(row) for row in rows], "total": total, "page": page, "pages": pages, "page_size": page_size}
