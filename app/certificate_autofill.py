"""Read-only, document-scoped suggestions from the selected employee's dossier."""
from __future__ import annotations

import re
import unicodedata
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Company, Employee, EmployeeComplianceProfile
from .salary_history import salary_at


CONTRACT_REQUIRED = {
    "employee_name": "Nombre completo", "employee_document": "Cédula",
    "employee_address": "Dirección del funcionario", "position": "Cargo",
    "admission_date": "Fecha de ingreso", "salary": "Salario",
    "contract_worker_age": "Edad", "contract_worker_gender": "Sexo",
    "contract_worker_civil_status": "Estado civil", "contract_worker_nationality": "Nacionalidad",
    "contract_modality": "Modalidad del contrato", "workplace": "Lugar de trabajo",
    "job_functions": "Funciones y tareas", "work_schedule": "Jornada y horario",
    "weekly_rest": "Descanso semanal", "payment_frequency": "Frecuencia de pago",
    "contract_payment_method": "Forma de pago",
}


def has_pending_marker(value: object) -> bool:
    text = str(value or "")
    return bool(re.search(r"\[\s*(?:completar|pendiente)\b[^\]]*\]", text, re.IGNORECASE)
                or re.search(r"\bCOMPLETAR(?::|(?=\s*(?:$|\n)))", text))


def recorded_text(value: object) -> str:
    """Legacy unknown labels and template markers are not recorded personal facts."""
    text = str(value or "").strip()
    normalized = "".join(
        char for char in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(char)
    )
    if normalized in {"no especificado", "no especificada", "no consignado", "no consignada", "sin datos", "n/a", "-"}:
        return ""
    if has_pending_marker(text):
        return ""
    return text


def certificate_dossier_data(db: Session, company: Company, employee: Employee, issued_on: date) -> dict:
    """Only fetch this dossier; never create profiles or infer absent duties/hours."""
    if employee.company_id != company.id:
        raise ValueError("Employee and company must match")
    profile = db.scalar(select(EmployeeComplianceProfile).where(EmployeeComplianceProfile.employee_id == employee.id))
    fields: dict[str, str] = {}
    sources: dict[str, str] = {}

    def put(key: str, value: object, source: str = "Legajo del funcionario") -> None:
        fields[key] = recorded_text(value)
        if fields[key]:
            sources[key] = source

    for key, value in {
        "employee_name": employee.full_name, "employee_document": employee.document_number,
        "employee_address": employee.address, "position": employee.position,
        "admission_date": employee.admission_date.isoformat() if employee.admission_date else "",
        "employee_section": employee.section.name if employee.section and employee.section.company_id == company.id else "",
        "payment_frequency": employee.payment_frequency,
    }.items():
        put(key, value)
    salary = salary_at(db, employee, issued_on)
    put("salary", salary if salary > 0 else "", "Salario del legajo vigente a la fecha de emisión")
    age = None
    if employee.birth_date and employee.birth_date <= issued_on:
        age = issued_on.year - employee.birth_date.year - (
            (issued_on.month, issued_on.day) < (employee.birth_date.month, employee.birth_date.day)
        )
    put("contract_worker_age", str(age) if age is not None and 0 <= age <= 120 else "", "Fecha de nacimiento del legajo; edad a la fecha de emisión")
    for key, attr in {
        "contract_worker_gender": "sex", "contract_worker_civil_status": "marital_status",
        "contract_worker_nationality": "nationality", "work_schedule": "work_schedule",
        "employee_profession": "profession",
    }.items():
        put(key, getattr(profile, attr, "") if profile else "", "Datos laborales del legajo")
    branch = employee.branch
    if branch and branch.company_id == company.id and recorded_text(branch.address):
        put("workplace", branch.address, "Sucursal asignada al funcionario")
    else:
        put("workplace", company.work_location, "Lugar de trabajo registrado en la empresa")
    contract_type = recorded_text(employee.contract_type).casefold()
    modality = {
        "tiempo indefinido": "indefinido", "indefinido": "indefinido",
        "tiempo determinado": "plazo_fijo", "plazo fijo": "plazo_fijo",
        "tiempo parcial": "tiempo_parcial",
    }.get(contract_type, "")
    put("contract_modality", modality)
    # There are no dossier columns for these facts. Do not turn free-form notes,
    # default hours, legal domicile or payroll payment methods into an agreement.
    for key in ("job_functions", "weekly_rest", "contract_payment_method"):
        put(key, "")
    put("city", company.city, "Empresa seleccionada")
    put("nationality", fields["contract_worker_nationality"], "Datos personales del legajo")
    put("civil_status", fields["contract_worker_civil_status"], "Datos personales del legajo")
    branding = company.branding
    signatory = company.legal_representative or (branding.signature_name if branding else "") or company.responsible_name or ""
    signature_title = "Representante legal" if company.legal_representative else (
        branding.signature_title if branding and branding.signature_title and branding.signature_title.replace(".", "").casefold() != "representante legal" else "Responsable autorizado"
    )
    return {
        "company_id": company.id, "employee_id": employee.id, "issue_date": issued_on.isoformat(),
        "fields": fields, "sources": sources,
        "company": {"name": company.legal_name, "ruc": company.ruc, "address": company.address,
                    "phone": company.phone, "city": company.city, "representative": company.legal_representative,
                    "signature": signatory, "signatureTitle": signature_title,
                    "logoUrl": f"/app/companies/{company.id}/logo/print" if branding and branding.logo_bytes else "",
                    "primary": branding.primary_color if branding else "#173B86"},
        "missing_fields": missing_contract_fields(fields, company),
    }


def missing_contract_fields(fields: dict, company: Company | None = None) -> dict[str, str]:
    missing = {key: label for key, label in CONTRACT_REQUIRED.items() if not recorded_text(fields.get(key))}
    try:
        if int(fields.get("salary") or 0) <= 0:
            missing["salary"] = CONTRACT_REQUIRED["salary"]
    except (ValueError, TypeError):
        missing["salary"] = CONTRACT_REQUIRED["salary"]
    if company:
        for key, label, value in (
            ("company_name", "Razón social de la empresa", company.legal_name),
            ("company_ruc", "RUC de la empresa", company.ruc),
            ("company_address", "Dirección de la empresa", company.address),
        ):
            if not recorded_text(value):
                missing[key] = label
    return missing
