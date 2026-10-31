from __future__ import annotations

import re
import unicodedata

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import String, case, func, or_, select
from sqlalchemy.orm import Session

from . import main as core
from .form_utils import OptionalQueryId
from .models import Company, CompanyBranding, Employee, User, Vacation


router = APIRouter()


def _fold(value: str) -> str:
    return "".join(character for character in unicodedata.normalize("NFD", value.lower()) if unicodedata.category(character) != "Mn")


def _search_text(column, db):
    if db.bind.dialect.name == "postgresql":
        return func.translate(func.lower(column), "áéíóúüñ", "aeiouun")
    result = func.lower(column)
    for accented, plain in zip("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunaeiouun"):
        result = func.replace(result, accented, plain)
    return result


def _company_label(company):
    code = company.legacy_code or company.company_code or "Sin código"
    return f"{code} - {company.legal_name}"


def _company_dataset(db, company):
    branding = db.scalar(select(CompanyBranding).where(CompanyBranding.company_id == company.id))
    representative = company.legal_representative or ""
    title = branding.signature_title if branding else ""
    return {
        "name": company.legal_name, "code": str(company.company_code or company.legacy_code or ""),
        "city": company.city or "", "ruc": company.ruc or "", "address": company.address or "",
        "phone": company.phone or "", "representative": representative,
        "legalRepresentative": representative,
        "signature": representative or (branding.signature_name if branding else "") or company.responsible_name or "",
        "signatureTitle": "Representante legal" if representative else (title if title and title.replace(".", "").lower() != "representante legal" else "Responsable autorizado"),
        "primary": branding.primary_color if branding else "#173B86",
        "logoUrl": f"/app/companies/{company.id}/logo/print" if branding and branding.logo_bytes else "",
        "status": company.status,
    }


def _employee_dataset(db, employee):
    vacation = db.scalar(select(Vacation).where(Vacation.employee_id == employee.id).order_by(Vacation.created_at.desc(), Vacation.id.desc()).limit(1))
    return {
        "company": str(employee.company_id), "name": employee.full_name,
        "code": str(employee.employee_code or ""), "document": employee.document_number,
        "address": employee.address or "", "position": employee.position or "",
        "admission": employee.admission_date.isoformat() if employee.admission_date else "",
        "admissionText": core.templates.env.filters["fecha_larga"](employee.admission_date),
        "salary": str(employee.base_salary or 0), "ips": "true" if employee.ips_contributor else "false",
        "termination": employee.termination_date.isoformat() if employee.termination_date else "",
        "status": employee.status,
        "vacationStart": vacation.start_date.isoformat() if vacation and vacation.start_date else "",
        "vacationEnd": vacation.end_date.isoformat() if vacation and vacation.end_date else "",
        "vacationYear": str(vacation.period_year) if vacation else "",
    }


@router.get("/api/selectors/{entity}")
def entity_options(
    entity: str,
    q: str = "",
    company_id: OptionalQueryId = None,
    selected_id: OptionalQueryId = None,
    scope: str = "all",
    limit: int = 10,
    user: User = Depends(core.require_user),
    db: Session = Depends(core.get_db),
):
    if entity not in {"companies", "employees"}:
        raise HTTPException(404, "Selector no encontrado.")
    allowed = core.company_ids_for_user(db, user)
    if company_id is not None and company_id not in allowed:
        raise HTTPException(404, "Empresa no encontrada.")
    if scope not in {"all", "current", "active", "company-current"}:
        raise HTTPException(422, "El alcance del selector no es válido.")
    limit = min(20, max(1, limit))
    term = q.strip()[:120]
    folded = _fold(term)
    code_term = term.replace(".", "").replace(" ", "")
    if entity == "companies":
        query = select(Company.id, Company.company_code, Company.legacy_code, Company.legal_name, Company.ruc, Company.status).where(Company.id.in_(allowed))
        if scope == "active":
            query = query.where(Company.status == "Activa")
        elif scope in {"current", "company-current"}:
            query = query.where(Company.status != "Archivada")
        if selected_id is not None:
            query = query.where(Company.id == selected_id)
        elif term:
            query = query.where(or_(
                _search_text(Company.legal_name, db).contains(folded, autoescape=True),
                func.cast(Company.company_code, String).contains(code_term, autoescape=True),
                Company.legacy_code.contains(code_term, autoescape=True),
            ))
        priority = case((or_(func.cast(Company.company_code, String) == code_term, Company.legacy_code == code_term), 0), else_=1)
        rows = db.execute(query.order_by(priority, func.lower(Company.legal_name), Company.id).limit(limit+1)).all()
        items = [{"id": row.id, "label": _company_label(row), "name": row.legal_name,
                  "code": row.legacy_code or row.company_code, "description": f"RUC {row.ruc or 'sin registrar'} · {row.status}"} for row in rows[:limit]]
        if selected_id is not None and items:
            company = db.get(Company, selected_id)
            items[0]["dataset"] = _company_dataset(db, company)
    else:
        query = select(Employee.id, Employee.employee_code, Employee.full_name, Employee.document_number, Employee.company_id, Employee.status, Company.company_code, Company.legacy_code, Company.legal_name).join(Company).where(Employee.company_id.in_(allowed))
        if company_id is not None:
            query = query.where(Employee.company_id == company_id)
        if scope == "active":
            query = query.where(Employee.status == "Activo", Company.status == "Activa")
        elif scope == "current":
            query = query.where(Employee.status != "Archivado", Company.status != "Archivada")
        elif scope == "company-current":
            query = query.where(Company.status != "Archivada")
        document = func.replace(func.replace(func.replace(Employee.document_number, ".", ""), "-", ""), " ", "")
        if selected_id is not None:
            query = query.where(Employee.id == selected_id)
        elif term:
            conditions = [
                _search_text(Employee.full_name, db).contains(folded, autoescape=True),
                func.cast(Employee.employee_code, String).contains(code_term, autoescape=True),
                Employee.document_number.contains(term, autoescape=True),
            ]
            if re.fullmatch(r"[\d.\-\s]+", term):
                conditions.append(document.contains(re.sub(r"\D", "", term), autoescape=True))
            query = query.where(or_(*conditions))
        priority = case((or_(func.cast(Employee.employee_code, String) == code_term, document == re.sub(r"\D", "", term)), 0), else_=1)
        rows = db.execute(query.order_by(priority, func.lower(Employee.full_name), Employee.id).limit(limit+1)).all()
        items = [{"id": row.id, "label": f"{row.employee_code or 'Sin legajo'} - {row.full_name}",
                  "name": row.full_name, "code": row.employee_code, "document": row.document_number,
                  "company_id": row.company_id,
                  "description": f"CI {row.document_number} · {_company_label(row)} · {row.status}"} for row in rows[:limit]]
        if selected_id is not None and items:
            employee = db.get(Employee, selected_id)
            items[0]["dataset"] = _employee_dataset(db, employee)
    if selected_id is not None and not items:
        raise HTTPException(404, "Registro no disponible en este selector.")
    return JSONResponse({"items": items, "has_more": len(rows) > limit}, headers={"Cache-Control": "no-store, max-age=0"})
