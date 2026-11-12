from __future__ import annotations

import hashlib
import io
import json
from collections import Counter
from datetime import date, datetime
from typing import Iterable

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import (
    Branch,
    BranchComplianceProfile,
    Company,
    CompanyComplianceProfile,
    ComplianceEvent,
    Employee,
    EmployeeComplianceProfile,
    IntegrationBatch,
    IntegrationBatchItem,
    LaborOperation,
    Payroll,
    PayrollComplianceDetail,
    PayrollLine,
)

OFFICIAL_SOURCES = {
    "REI": "https://portal.ips.gov.py/sistemas/ipsportal/contenido.php?c=119",
    "REOP": "https://www.mtess.gov.py/?page_id=31365",
}
OFFICIAL_PORTALS = {
    "REI": "https://servicios.ips.gov.py/newrei/rei/",
    "REOP": "https://regobpat.mtess.gov.py/",
}
REOP_PERMISSIONS_PORTAL = OFFICIAL_PORTALS["REOP"] + "permisos_obreros_list.php"

REOP_EVENT_TYPES = {
    "Entrada", "Salida", "Permiso", "Vacaciones", "Amonestación", "Ausencia",
    "Suspensión", "Preaviso", "Accidente laboral", "Liquidación salarial", "Aguinaldo",
}
REI_EVENT_TYPES = {"Entrada", "Salida", "Declaración salarial", "Aportes", "Reposo"}
PENDING_COMPLIANCE_STATUSES = ("Borrador", "Validado", "Exportado", "Observado", "Rechazado")

COMPLIANCE_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "Borrador": {"Borrador", "Validado", "Anulado"},
    "Validado": {"Validado", "Borrador", "Presentado", "Anulado"},
    "Exportado": {"Exportado", "Presentado", "Observado", "Anulado"},
    "Presentado": {"Presentado", "Aceptado", "Observado", "Rechazado"},
    "Aceptado": {"Aceptado"},
    "Observado": {"Observado", "Borrador", "Validado", "Anulado"},
    "Rechazado": {"Rechazado", "Borrador", "Anulado"},
    "Anulado": {"Anulado"},
}

# Los lotes anuales no tienen eventos individuales, por eso su estado propio
# debe mantener la misma trazabilidad que los lotes de comunicaciones.
INTEGRATION_BATCH_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "Generado": {"Presentado"},
    "Validado": {"Validado", "Presentado"},
    "Presentado": {"Presentado", "Aceptado", "Observado", "Rechazado"},
    "Aceptado": {"Aceptado"},
    "Observado": {"Observado"},
    "Rechazado": {"Rechazado"},
}


def can_transition_compliance_status(current: str, target: str) -> bool:
    return target in COMPLIANCE_STATUS_TRANSITIONS.get(current, {current})


def reop_permission_data(operation: LaborOperation) -> dict | None:
    if (operation.operation_type != "discipline" or operation.status != "Aprobado"
            or not operation.end_date or operation.end_date < operation.effective_date):
        return None
    try:
        payload = json.loads(operation.payload_json or "{}")
    except (TypeError, ValueError):
        return None
    subtype = payload.get("subtype") if isinstance(payload, dict) else None
    if subtype not in ("Permiso", "Reposo", "Licencia"):
        return None
    return {
        "operation_id": operation.id,
        "subtype": subtype,
        "end_date": operation.end_date.isoformat(),
        "hours": format(operation.quantity, "f") if operation.quantity is not None else None,
    }


def reop_permission_source_issue(db: Session, event: ComplianceEvent) -> str:
    if (event.authority != "REOP" or event.event_type != "Permiso"
            or not (event.source_key or "").endswith(":reop-permission")):
        return ""
    try:
        payload = json.loads(event.payload_json or "{}")
    except (TypeError, ValueError):
        payload = {}
    permission = payload.get("reop_permission") if isinstance(payload, dict) else None
    operation_id = permission.get("operation_id") if isinstance(permission, dict) else None
    operation = db.get(LaborOperation, operation_id) if isinstance(operation_id, int) else None
    if (not operation or event.source_key != f"labor-operation:{operation.id}:reop-permission"
            or operation.company_id != event.company_id or operation.employee_id != event.employee_id
            or operation.effective_date != event.event_date or reop_permission_data(operation) != permission):
        return f"Comunicación #{event.id}. La novedad cambió o dejó de estar aprobada. Revisá el registro de origen."
    return ""


def _sheet_style(sheet) -> None:  # noqa: ANN001
    fill = PatternFill("solid", fgColor="173B86")
    for cell in sheet[1]:
        cell.fill = fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column in sheet.columns:
        for cell in column:
            if cell.data_type == "f":
                cell.data_type = "s"
        width = min(42, max(12, max(len(str(cell.value or "")) for cell in column) + 2))
        sheet.column_dimensions[column[0].column_letter].width = width


def _profile_map(db: Session, company_id: int) -> tuple[CompanyComplianceProfile | None, dict[int, EmployeeComplianceProfile]]:
    company_profile = db.scalar(select(CompanyComplianceProfile).where(CompanyComplianceProfile.company_id == company_id))
    employee_profiles = list(
        db.scalars(
            select(EmployeeComplianceProfile)
            .join(Employee, Employee.id == EmployeeComplianceProfile.employee_id)
            .where(Employee.company_id == company_id)
        )
    )
    return company_profile, {item.employee_id: item for item in employee_profiles}


def _branch_context(
    db: Session, company_id: int
) -> tuple[dict[int, Branch], dict[int, BranchComplianceProfile]]:
    branches = list(db.scalars(select(Branch).where(Branch.company_id == company_id)))
    branch_map = {item.id: item for item in branches}
    profiles = list(
        db.scalars(
            select(BranchComplianceProfile)
            .join(Branch, Branch.id == BranchComplianceProfile.branch_id)
            .where(Branch.company_id == company_id)
        )
    )
    return branch_map, {item.branch_id: item for item in profiles}


def _patronal_for_branch(
    company: Company,
    authority: str,
    branch_id: int | None,
    branch_profiles: dict[int, BranchComplianceProfile],
) -> str:
    profile = branch_profiles.get(branch_id) if branch_id else None
    if authority == "REI":
        return (profile.ips_employer_number if profile else "") or company.ips_employer_number
    return (profile.mtess_employer_number if profile else "") or company.mtess_employer_number


def company_profile_issues(company: Company, profile: CompanyComplianceProfile | None, authority: str) -> list[str]:
    errors: list[str] = []
    if not (company.ruc or "").strip():
        errors.append("RUC de la empresa")
    if not (_patronal_for_branch(company, authority, None, {}) or "").strip():
        errors.append(f"Número patronal {'IPS' if authority == 'REI' else 'MTESS'} de la matriz")
    for key, label in (("department", "Departamento"), ("district", "Distrito"), ("economic_activity", "Actividad económica")):
        if not (getattr(profile, key, "") or "").strip():
            errors.append(label)
    return errors


def create_compliance_event(
    db: Session,
    *,
    company_id: int,
    employee_id: int | None,
    branch_id: int | None = None,
    authority: str,
    event_type: str,
    event_date: date,
    due_date: date | None,
    payload: dict,
    created_by: str,
    source_key: str | None = None,
) -> ComplianceEvent:
    authority = authority.upper()
    if authority not in {"REI", "REOP"}:
        raise ValueError("Autoridad de cumplimiento no reconocida.")
    valid = REI_EVENT_TYPES if authority == "REI" else REOP_EVENT_TYPES
    if event_type not in valid:
        raise ValueError("Tipo de comunicación no reconocido.")
    event = ComplianceEvent(
        company_id=company_id,
        employee_id=employee_id,
        branch_id=branch_id,
        authority=authority,
        event_type=event_type,
        event_date=event_date,
        due_date=due_date,
        status="Borrador",
        source_key=source_key or None,
        payload_json=json.dumps(payload, ensure_ascii=False),
        created_by=created_by,
    )
    db.add(event)
    return event




def ensure_compliance_event(
    db: Session,
    *,
    company_id: int,
    employee_id: int | None,
    branch_id: int | None = None,
    authority: str,
    event_type: str,
    event_date: date,
    due_date: date | None,
    payload: dict,
    created_by: str,
    source_key: str,
) -> ComplianceEvent:
    """Create one draft per source object, avoiding duplicate official communications."""
    source_key = source_key.strip()
    if not source_key:
        raise ValueError("source_key es obligatorio para comunicaciones automáticas.")
    existing = db.scalar(
        select(ComplianceEvent).where(
            ComplianceEvent.company_id == company_id,
            ComplianceEvent.authority == authority.upper(),
            or_(
                ComplianceEvent.source_key == source_key,
                ComplianceEvent.payload_json.contains(f'"source_key": "{source_key}"'),
            ),
            ComplianceEvent.status != "Anulado",
        )
    )
    if existing:
        if not existing.source_key:
            existing.source_key = source_key
        return existing
    merged_payload = {**payload, "source_key": source_key, "generated_automatically": True}
    return create_compliance_event(
        db,
        company_id=company_id,
        employee_id=employee_id,
        branch_id=branch_id,
        authority=authority,
        event_type=event_type,
        event_date=event_date,
        due_date=due_date,
        payload=merged_payload,
        created_by=created_by,
        source_key=source_key,
    )


def build_event_workbook(
    db: Session,
    company: Company,
    authority: str,
    events: Iterable[ComplianceEvent],
    *,
    validate: bool = False,
) -> bytes:
    events = list(events)
    authority = authority.upper()
    wb = Workbook()
    ws = wb.active
    ws.title = f"{authority}_COMUNICACIONES"
    ws.append([
        "Nro Patronal", "Establecimiento", "RUC", "Sistema", "Tipo de comunicación", "Cédula", "Trabajador",
        "Fecha del evento", "Vencimiento", "Estado", "Datos complementarios", "ID Digit Laboral",
    ])
    employee_ids = {event.employee_id for event in events if event.employee_id is not None}
    employee_map = {
        item.id: item for item in db.scalars(
            select(Employee).where(Employee.company_id == company.id, Employee.id.in_(employee_ids))
        )
    } if employee_ids else {}
    branch_map, branch_profiles = _branch_context(db, company.id)
    errors = ["Falta el RUC de la empresa."] if not (company.ruc or "").strip() else []
    for event in events:
        if validate:
            issue = reop_permission_source_issue(db, event)
            if issue:
                errors.append(issue)
        employee = employee_map.get(event.employee_id) if event.employee_id else None
        branch_id = event.branch_id or (employee.branch_id if employee else None)
        branch = branch_map.get(branch_id) if branch_id else None
        patronal = _patronal_for_branch(company, authority, branch_id, branch_profiles)
        if not (patronal or "").strip():
            errors.append(f"Comunicación #{event.id}: falta el número patronal de {branch.name if branch else 'la matriz'}.")
        if event.employee_id is not None and (not employee or not (employee.document_number or "").strip()):
            errors.append(f"Comunicación #{event.id}: falta el documento del funcionario.")
        ws.append([
            patronal,
            branch.name if branch else "Casa matriz",
            company.ruc,
            authority,
            event.event_type,
            employee.document_number if employee else "",
            employee.full_name if employee else "",
            event.event_date.isoformat(),
            event.due_date.isoformat() if event.due_date else "",
            event.status,
            event.payload_json,
            event.id,
        ])
    if validate and errors:
        remaining = f" Hay {len(errors) - 6} observaciones más." if len(errors) > 6 else ""
        raise ValueError(" ".join(errors[:6]) + remaining)
    _sheet_style(ws)
    meta = wb.create_sheet("METADATOS")
    meta.append(["Campo", "Valor"])
    meta.append(["Empresa", company.legal_name])
    meta.append(["RUC", company.ruc])
    meta.append(["Sistema", authority])
    meta.append(["Fuente oficial", OFFICIAL_SOURCES[authority]])
    meta.append(["Uso", "Archivo interno de apoyo. Registrá cada comunicación en el portal oficial y guardá el resultado en Digit Laboral."])
    _sheet_style(meta)
    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


def build_reop_annual_workbook(db: Session, company: Company, year: int) -> bytes:
    company_profile, employee_profiles = _profile_map(db, company.id)
    branch_map, branch_profiles = _branch_context(db, company.id)
    year_start, year_end = date(year, 1, 1), date(year, 12, 31)
    employees = list(db.scalars(
        select(Employee).where(
            Employee.company_id == company.id, Employee.admission_date <= year_end,
            or_(Employee.termination_date.is_(None), Employee.termination_date >= year_start),
        ).order_by(Employee.full_name, Employee.id)
    ))
    payrolls = list(db.scalars(
        select(Payroll).where(
            Payroll.company_id == company.id, Payroll.period.like(f"{year}-%"),
            Payroll.status == "Cerrada", Payroll.closed_at.is_not(None),
        ).order_by(Payroll.period, Payroll.id)
    ))
    payroll_ids = [item.id for item in payrolls]
    lines = list(db.scalars(select(PayrollLine).where(PayrollLine.payroll_id.in_(payroll_ids)))) if payroll_ids else []
    line_details = list(db.scalars(select(PayrollComplianceDetail).where(PayrollComplianceDetail.payroll_line_id.in_([line.id for line in lines])))) if lines else []
    details_by_line = {item.payroll_line_id: item for item in line_details}
    payroll_by_id = {item.id: item for item in payrolls}
    employee_by_id = {item.id: item for item in employees}
    missing_employee_ids = {line.employee_id for line in lines} - employee_by_id.keys()
    if missing_employee_ids:
        employee_by_id.update(
            (item.id, item) for item in db.scalars(select(Employee).where(
                Employee.company_id == company.id, Employee.id.in_(missing_employee_ids),
            ))
        )

    wb = Workbook()
    workers = wb.active
    workers.title = "EMPLEADOS_Y_OBREROS"
    workers.append([
        "Nro Patronal MTESS", "Establecimiento", "RUC", "Tipo Documento", "Documento", "Nombres y apellidos",
        "Nacionalidad", "Estado civil", "Fecha nacimiento", "Sexo", "Departamento", "Distrito",
        "Domicilio", "Profesión/Ocupación", "Código ocupación", "Cargo", "Fecha entrada", "Fecha salida",
    ])
    for employee in employees:
        profile = employee_profiles.get(employee.id)
        branch = branch_map.get(employee.branch_id) if employee.branch_id else None
        workers.append([
            _patronal_for_branch(company, "REOP", employee.branch_id, branch_profiles),
            branch.name if branch else "Casa matriz",
            company.ruc,
            profile.document_type if profile else "CI",
            employee.document_number,
            employee.full_name,
            profile.nationality if profile else "",
            profile.marital_status if profile else "",
            employee.birth_date.isoformat() if employee.birth_date else "",
            profile.sex if profile else "",
            profile.department if profile else "",
            profile.district if profile else "",
            employee.address,
            profile.profession if profile else "",
            profile.occupation_code if profile else "",
            employee.position,
            employee.admission_date.isoformat(),
            employee.termination_date.isoformat() if employee.termination_date else "",
        ])
    _sheet_style(workers)

    wages = wb.create_sheet("SUELDOS_Y_JORNALES")
    wages.append([
        "Nro Patronal MTESS", "Establecimiento", "Periodo", "Documento", "Trabajador", "Desde", "Hasta", "Forma de pago",
        "Días trabajados", "Horas trabajadas", "Salario básico", "Recargo nocturno", "Horas extra diurnas",
        "Horas extra nocturnas", "Feriados", "Vacaciones", "Asignación familiar", "Comisiones",
        "Gratificaciones/Premios", "Bonificaciones", "Otros ingresos", "Aporte IPS trabajador",
        "Otros descuentos", "Total bruto", "Total descuentos", "Neto",
    ])
    for line in lines:
        payroll = payroll_by_id[line.payroll_id]
        employee = employee_by_id.get(line.employee_id)
        detail = details_by_line.get(line.id)
        branch = branch_map.get(employee.branch_id) if employee and employee.branch_id else None
        wages.append([
            _patronal_for_branch(company, "REOP", employee.branch_id if employee else None, branch_profiles),
            branch.name if branch else "Casa matriz",
            payroll.period,
            employee.document_number if employee else "",
            employee.full_name if employee else "",
            detail.period_start.isoformat() if detail and detail.period_start else "",
            detail.period_end.isoformat() if detail and detail.period_end else "",
            detail.payment_method if detail else "",
            detail.days_worked if detail else None,
            detail.hours_worked if detail else None,
            line.base_salary,
            detail.night_surcharge if detail else 0,
            detail.overtime_day if detail else line.overtime,
            detail.overtime_night if detail else 0,
            detail.holidays if detail else 0,
            detail.vacation_pay if detail else 0,
            detail.family_allowance if detail else 0,
            line.commissions,
            line.bonuses,
            line.other_income,
            detail.other_income_detail if detail else 0,
            line.ips_employee,
            line.other_discount + line.advances + line.absences_discount,
            line.gross,
            line.total_discounts,
            line.net,
        ])
    _sheet_style(wages)

    summary = wb.create_sheet("RESUMEN_GENERAL")
    sex_counts = Counter((employee_profiles[item.id].sex or "Sin dato") if item.id in employee_profiles else "Sin dato" for item in employees)
    summary.append(["Concepto", "Cantidad"])
    summary.append(["Legajos con fechas de vínculo en el ejercicio", len(employees)])
    for key, value in sorted(sex_counts.items()):
        summary.append([f"Sexo: {key}", value])
    summary.append(["Empresa", company.legal_name])
    summary.append(["Actividad económica", company_profile.economic_activity if company_profile else ""])
    summary.append(["Año", year])
    _sheet_style(summary)

    metadata = wb.create_sheet("CONTROL_DIGIT_LABORAL")
    metadata.append(["Campo", "Valor"])
    metadata.append(["Generado", datetime.now().isoformat(timespec="seconds")])
    metadata.append(["Fuente oficial de referencia", OFFICIAL_SOURCES["REOP"]])
    metadata.append(["Uso", "Reporte interno. Los Libros de Información Laboral se gestionan en el portal REOP."])
    metadata.append(["Períodos con nómina cerrada", ", ".join(sorted({item.period for item in payrolls})) or "Sin nóminas cerradas"])
    metadata.append(["Cobertura", "Incluye nóminas cerradas. Las celdas vacías indican datos sin registrar."])
    _sheet_style(metadata)

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


def register_batch(
    db: Session,
    *,
    company: Company,
    authority: str,
    batch_type: str,
    period: str,
    content: bytes,
    created_by: str,
    events: list[ComplianceEvent] | None = None,
) -> IntegrationBatch:
    digest = hashlib.sha256(content).hexdigest()
    batch = IntegrationBatch(
        studio_id=company.studio_id,
        company_id=company.id,
        authority=authority,
        batch_type=batch_type,
        period=period,
        status="Generado",
        file_name=f"{authority.lower()}_{company.ruc}_{period or date.today().isoformat()}.xlsx".replace("/", "-"),
        file_sha256=digest,
        item_count=len(events or []),
        created_by=created_by,
    )
    db.add(batch)
    db.flush()
    for event in events or []:
        db.add(IntegrationBatchItem(batch_id=batch.id, compliance_event_id=event.id, status="Incluido"))
        event.status = "Exportado"
        event.batch_id = batch.id
    return batch
