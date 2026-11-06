"""Reports -> Liquidación Aguinaldo: list, view, print and download identical PDFs."""
from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import main as core
from .aguinaldo_receipt_pdf import build_aguinaldo_receipt_pdf
from .aguinaldo_receipt_service import (
    PAYMENT_METHODS, read_payment_detail, read_record, receipt_model, report_rows,
)
from .models import AguinaldoReceiptDetail, Company, Employee, User

router = APIRouter()
BASE = "/app/reports/liquidaciones-aguinaldo"


def _record_for_user(db, user, source_kind, record_id):
    result = read_record(db, core.company_ids_for_user(db, user), source_kind, record_id)
    if result is None:
        raise HTTPException(404, "Liquidación de aguinaldo no encontrada en tu estudio.")
    return result


def _model(db, user, source_kind, record_id):
    item, employee, company = _record_for_user(db, user, source_kind, record_id)
    detail = read_payment_detail(db, source_kind, record_id, company.id, employee.id)
    return receipt_model(item, employee, company, source_kind, detail), item, detail


@router.get(BASE)
def aguinaldo_report_index(
    request: Request, company_id: int | None = None, employee_id: int | None = None,
    q: str = "", status: str = "", year: int | None = None,
    page: int = 1, page_size: int = 25,
    user: User = Depends(core.require_user), db: Session = Depends(core.get_db),
):
    company_ids = core.company_ids_for_user(db, user)
    if company_id is not None and company_id not in company_ids:
        raise HTTPException(404, "Empresa no encontrada.")
    if employee_id is not None:
        employee = db.get(Employee, employee_id)
        if not employee or employee.company_id not in company_ids or (company_id and employee.company_id != company_id):
            raise HTTPException(404, "Funcionario no encontrado.")
    if year is not None and not 1900 <= year <= 2100:
        raise HTTPException(422, "El ejercicio debe estar entre 1900 y 2100.")
    records = report_rows(db, company_ids, company_id=company_id, employee_id=employee_id,
                          q=q, status=status, year=year, page=page, page_size=page_size)
    company_query = select(Company).where(Company.id.in_(company_ids)).order_by(Company.legal_name)
    companies = core.seed_choices(db, company_query, Company, request=request) if company_ids else []
    response = core.render(request, "aguinaldo_report_index.html", db, user,
        records=records, companies=companies,
        filters={"company_id": company_id, "employee_id": employee_id,
                 "q": q, "status": status, "year": year},
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response


@router.get(BASE + "/{source_kind}/{record_id}")
def aguinaldo_report_detail(
    source_kind: str, record_id: int, request: Request,
    user: User = Depends(core.require_user), db: Session = Depends(core.get_db),
):
    model, item, detail = _model(db, user, source_kind, record_id)
    response = core.render(request, "aguinaldo_report_detail.html", db, user,
        model=model, record=item, payment_detail=detail, payment_methods=PAYMENT_METHODS,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response


@router.post(BASE + "/{source_kind}/{record_id}/payment")
def aguinaldo_report_payment(
    source_kind: str, record_id: int,
    payment_method: Annotated[str, Form()] = "",
    payment_date: Annotated[date | None, Form()] = None,
    user: User = Depends(core.require_roles("administrador", "contador")),
    db: Session = Depends(core.get_db),
):
    item, employee, company = _record_for_user(db, user, source_kind, record_id)
    if (item.status or "").lower() == "anulado":
        raise HTTPException(409, "El registro está anulado; no admite modificaciones.")
    if payment_method not in PAYMENT_METHODS:
        raise HTTPException(422, "La forma de pago seleccionada no es válida.")
    if bool(payment_method) != bool(payment_date):
        raise HTTPException(422, "Para registrar un pago indicá tanto la forma como la fecha real; dejá ambos campos vacíos si no fue pagado.")
    if payment_date and payment_date > core.current_paraguay_date():
        raise HTTPException(422, "La fecha real de pago no puede ser futura.")
    detail = read_payment_detail(db, source_kind, record_id, company.id, employee.id)
    if not detail:
        detail = AguinaldoReceiptDetail(
            source_kind=source_kind, source_id=item.id,
            company_id=company.id, employee_id=employee.id,
        )
        db.add(detail)
    previous = {
        "payment_method": detail.payment_method or "",
        "payment_date": detail.payment_date.isoformat() if detail.payment_date else None,
    }
    detail.payment_method = payment_method
    detail.payment_date = payment_date
    detail.updated_by = user.email
    detail.updated_at = datetime.now(UTC)
    core.write_audit(db, user, "actualizar_datos_recibo_aguinaldo", "aguinaldo",
                     f"{source_kind}:{item.id}",
                     json.dumps({
                         "previous": previous,
                         "current": {"payment_method": payment_method,
                                     "payment_date": payment_date.isoformat() if payment_date else None},
                     }, ensure_ascii=False))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Los datos del recibo cambiaron simultáneamente; revisá y volvé a intentar.") from None
    return RedirectResponse(f"{BASE}/{source_kind}/{record_id}?datos_guardados=1", status_code=303)


@router.get(BASE + "/{source_kind}/{record_id}/pdf")
def aguinaldo_report_pdf(
    source_kind: str, record_id: int, vista: bool = False,
    user: User = Depends(core.require_user), db: Session = Depends(core.get_db),
):
    model, _item, _detail = _model(db, user, source_kind, record_id)
    payload = build_aguinaldo_receipt_pdf(model)
    if not payload.startswith(b"%PDF"):
        raise HTTPException(500, "No se pudo generar un archivo PDF válido.")
    if not vista:
        core.write_audit(db, user, "descarga_pdf_liquidacion_aguinaldo",
                         "aguinaldo", f"{source_kind}:{record_id}",
                         json.dumps({"code": model["code"], "year": model["exercise"],
                                     "amount": model["amount"], "status": model["status"]}, ensure_ascii=False))
        db.commit()
    disposition = "inline" if vista else "attachment"
    name = f"Digit-Laboral-Aguinaldo-{model['code']}{'-ANULADO' if model['annulled'] else ''}.pdf"
    return Response(content=payload, media_type="application/pdf", headers={
        "Content-Disposition": f'{disposition}; filename="{name}"',
        "Cache-Control": "private, no-store",
    })
