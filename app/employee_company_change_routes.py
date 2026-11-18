"""Safe correction of a misassigned company without moving labor history.

This is NOT a transfer or termination workflow. When two employer records already
exist for the same person, the user can open the correct dossier instead.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadData, URLSafeTimedSerializer
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import main as core
from .config import settings
from .employee_deletion import automatic_entry_drafts, deletion_preview
from .import_service import normalize_document_number
from .models import Company, ComplianceEvent, Employee, EmployeeComplianceProfile, EmployeeEvent, SalaryHistory, User
from .period_coverage import current_paraguay_date

router = APIRouter()
TOKEN_SALT = "employee-company-correction-v1"


def allowed_employee(db: Session, user: User, employee_id: int, *, lock=False) -> Employee:
    query = select(Employee).where(
        Employee.id == employee_id,
        Employee.company_id.in_(core.company_ids_for_user(db, user)),
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    employee = db.scalar(query)
    if employee is None:
        raise HTTPException(404, "El legajo no pertenece a tu estudio.")
    return employee


def related_employers(db: Session, user: User, employee: Employee) -> list[Employee]:
    """Only authorized companies, matching the normalized document number."""
    document = normalize_document_number(employee.document_number)
    if not document:
        return []
    cleaned = func.replace(
        func.replace(func.replace(func.replace(Employee.document_number, ".", ""), "-", ""), " ", ""), "/", ""
    )
    query = select(Employee).where(
        Employee.id != employee.id,
        Employee.company_id.in_(core.company_ids_for_user(db, user)),
        cleaned == document,
    ).order_by(Employee.id.desc())
    return list(db.scalars(query))


def correction_issues(db: Session, employee: Employee, review: dict) -> list[str]:
    problems = []
    if employee.status != "Activo" or employee.termination_date is not None:
        problems.append("La rectificación solo se permite para legajos activos sin fecha de egreso.")
    if review["blockers"]:
        problems.append("El legajo ya contiene movimientos, comprobantes, liquidaciones o trámites vinculados; la empresa no puede modificarse administrativamente.")
    histories = list(db.scalars(select(SalaryHistory).where(SalaryHistory.employee_id == employee.id)))
    if len(histories) > 1 or any(
        int(item.previous_salary or 0) != 0 or item.effective_from != employee.admission_date
        for item in histories
    ):
        problems.append("Existe un historial salarial posterior o no conciliado con el alta original.")
    events = list(db.scalars(select(EmployeeEvent).where(EmployeeEvent.employee_id == employee.id)))
    if any(item.event_type != "Alta" for item in events) or len(events) > 1:
        problems.append("Existen actuaciones o antecedentes laborales que deben permanecer vinculados con la empresa original.")
    return problems


def preview_token(user: User, employee: Employee, fingerprint: str) -> str:
    payload = {"uid": user.id, "eid": employee.id, "company": employee.company_id, "fingerprint": fingerprint}
    return URLSafeTimedSerializer(settings.secret_key, salt=TOKEN_SALT).dumps(payload)


def validate_token(token: str, user: User, employee: Employee, fingerprint: str) -> bool:
    try:
        payload = URLSafeTimedSerializer(settings.secret_key, salt=TOKEN_SALT).loads(token, max_age=900)
    except (BadData, ValueError, TypeError):
        return False
    return payload == {"uid": user.id, "eid": employee.id, "company": employee.company_id, "fingerprint": fingerprint}


def review_page(request: Request, db: Session, user: User, employee: Employee, *, error="", status=200):
    review = deletion_preview(db, employee)
    issues = correction_issues(db, employee, review)
    options = list(db.scalars(select(Company).where(
        Company.id.in_(core.company_ids_for_user(db, user)),
        Company.id != employee.company_id,
        Company.status != "Archivada",
    ).order_by(Company.legal_name)))
    linked = related_employers(db, user, employee)
    response = core.render(
        request, "employee_company_change.html", db, user,
        employee=employee, companies=options, related_employers=linked,
        correction_issues=issues, blockers=review["blockers"],
        correction_token=preview_token(user, employee, review["fingerprint"]) if not issues else "",
        new_employment_token=preview_token(user, employee, "new-employment"),
        new_employment_today=current_paraguay_date(),
        correction_error=error,
    )
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/app/employees/{employee_id}/change-company")
def change_company_page(
    employee_id: int, request: Request,
    user: User = Depends(core.require_roles("administrador", "contador")),
    db: Session = Depends(core.get_db),
):
    return review_page(request, db, user, allowed_employee(db, user, employee_id))


@router.post("/app/employees/{employee_id}/change-company")
def change_company_confirm(
    employee_id: int, request: Request,
    destination_company_id: Annotated[int, Form()],
    new_employee_code: Annotated[int, Form()],
    correction_token: Annotated[str, Form()],
    reason: Annotated[str, Form()],
    acknowledgment: Annotated[str, Form()] = "",
    user: User = Depends(core.require_roles("administrador", "contador")),
    db: Session = Depends(core.get_db),
):
    employee = allowed_employee(db, user, employee_id, lock=True)
    review = deletion_preview(db, employee, lock_profile=True)
    issues = correction_issues(db, employee, review)
    if issues:
        return review_page(request, db, user, employee, error="No se puede rectificar: " + " ".join(issues), status=409)
    if not validate_token(correction_token, user, employee, review["fingerprint"]):
        return review_page(request, db, user, employee, error="La revisión venció o el legajo cambió. Volvé a revisar antes de confirmar.", status=409)
    if acknowledgment != "confirm" or not 12 <= len(reason.strip()) <= 500:
        return review_page(request, db, user, employee, error="Confirmá que es una corrección administrativa y explicá el motivo (12 a 500 caracteres).", status=422)
    destination = core.company_allowed(db, user, destination_company_id)
    if destination.studio_id != employee.company.studio_id or destination.id == employee.company_id or destination.status == "Archivada":
        return review_page(request, db, user, employee, error="Seleccioná otra empresa activa del mismo estudio.", status=422)
    if not 1 <= new_employee_code <= 2_147_483_647:
        return review_page(request, db, user, employee, error="El nuevo Código Legajo debe ser positivo.", status=422)
    document = normalize_document_number(employee.document_number)
    # Restrict duplicate checks to the destination company, without loading its employees.
    normalized_sql = func.replace(
        func.replace(func.replace(func.replace(Employee.document_number, ".", ""), "-", ""), " ", ""), "/", ""
    )
    if db.scalar(select(Employee.id).where(
        Employee.company_id == destination.id, normalized_sql == document
    ).limit(1)) is not None:
        return review_page(request, db, user, employee, error="Ya existe un legajo con esta cédula en la empresa destino. Abrí ese expediente; no se fusionan registros.", status=409)
    if db.scalar(select(Employee.id).where(
        Employee.company_id == destination.id, Employee.employee_code == new_employee_code
    ).limit(1)) is not None:
        return review_page(request, db, user, employee, error="El Código Legajo ya está ocupado en la empresa destino.", status=409)

    old_company_id = employee.company_id
    old_company_name = employee.company.legal_name
    old_code = employee.employee_code
    drafts, total = automatic_entry_drafts(db, employee, lock=True)
    if total != len(drafts):
        return review_page(request, db, user, employee, error="Aparecieron trámites oficiales vinculados. No se modificó el legajo.", status=409)
    try:
        # All linked payrolls, documents, notices, exits, and substantive events
        # were excluded by the locked snapshot, not silently reassigned.
        employee.company_id = destination.id
        employee.employee_code = new_employee_code
        employee.branch_id = None
        employee.section_id = None
        employee.updated_by = user.email
        employee.updated_at = datetime.now(UTC)
        for original in drafts:
            compliance = db.get(ComplianceEvent, original["id"])
            compliance.company_id = destination.id
            compliance.branch_id = None
        core.add_employee_event(
            db, employee, user, "Corrección administrativa",
            "Empresa del legajo corregida",
            f"Empresa anterior: {old_company_name} (ID {old_company_id}), legajo {old_code}. "
            f"Empresa rectificada: {destination.legal_name} (ID {destination.id}), legajo {new_employee_code}. "
            f"Motivo: {reason.strip()}",
            current_paraguay_date(),
        )
        core.write_audit(
            db, user, "rectificar_empresa", "funcionario", str(employee.id),
            f"Empresa {old_company_id} → {destination.id}; legajo {old_code} → {new_employee_code}; "
            f"cédula {document}; motivo: {reason.strip()}",
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "El legajo o la cédula ya existe en la empresa destino. No se guardó ningún cambio.")
    return RedirectResponse(f"/app/employees/{employee.id}?company_corrected=1", status_code=303)


@router.post("/app/employees/{employee_id}/new-employment")
def register_new_employer(
    employee_id: int,
    request: Request,
    destination_company_id: Annotated[int, Form()],
    admission_date: Annotated[date, Form()],
    position: Annotated[str, Form()],
    base_salary: Annotated[int, Form()],
    payment_frequency: Annotated[str, Form()],
    contract_type: Annotated[str, Form()],
    ips_contributor: Annotated[str, Form()],
    new_employment_token: Annotated[str, Form()],
    employee_code: Annotated[str, Form()] = "",
    acknowledgement: Annotated[str, Form()] = "",
    user: User = Depends(core.require_roles("administrador", "contador")),
    db: Session = Depends(core.get_db),
):
    """Start a separate employment relationship; never transfer the previous dossier."""
    source = allowed_employee(db, user, employee_id)
    if not validate_token(new_employment_token, user, source, "new-employment"):
        return review_page(request, db, user, source,
            error="La revisión venció o el legajo cambió. Volvé a abrir la pantalla.", status=409)
    if acknowledgement != "new":
        return review_page(request, db, user, source,
            error="Confirmá que estás registrando una relación laboral nueva, no corrigiendo el empleador anterior.", status=422)
    destination = core.company_allowed(db, user, destination_company_id)
    if destination.id == source.company_id or destination.status == "Archivada" or destination.studio_id != source.company.studio_id:
        return review_page(request, db, user, source,
            error="Elegí una empresa distinta y activa dentro de tu estudio.", status=422)
    # Lock the employer row to serialize competing registrations from this wizard.
    db.scalar(select(Company).where(Company.id == destination.id).with_for_update())
    document = normalize_document_number(source.document_number)
    if not document:
        return review_page(request, db, user, source, error="El funcionario no tiene una cédula válida.", status=422)
    normalized_sql = func.replace(
        func.replace(func.replace(func.replace(Employee.document_number, ".", ""), "-", ""), " ", ""), "/", ""
    )
    duplicate = db.scalar(select(Employee.id).where(
        Employee.company_id == destination.id, normalized_sql == document
    ).limit(1))
    if duplicate is not None:
        return review_page(request, db, user, source,
            error="La persona ya tiene un legajo en esa empresa. Abrí el expediente existente; no se crea un segundo registro.", status=409)
    if not 1 <= base_salary <= 2_147_483_647:
        return review_page(request, db, user, source,
            error="Ingresá el salario convenido de la nueva empresa, mayor a cero y en guaraníes.", status=422)
    if not position.strip() or len(position.strip()) > 140:
        return review_page(request, db, user, source, error="Ingresá el nuevo cargo (máximo 140 caracteres).", status=422)
    if payment_frequency not in {"Mensual", "Quincenal", "Semanal", "Jornal"}:
        return review_page(request, db, user, source, error="Seleccioná una frecuencia de pago válida.", status=422)
    if contract_type not in {"Tiempo indefinido", "Plazo determinado", "Obra o servicio", "Aprendizaje", "Otro"}:
        return review_page(request, db, user, source, error="Seleccioná un tipo de contrato válido.", status=422)
    if ips_contributor not in {"true", "false"}:
        return review_page(request, db, user, source, error="Confirmá si la nueva relación aporta al IPS.", status=422)
    if source.birth_date and admission_date <= source.birth_date:
        return review_page(request, db, user, source, error="La fecha de ingreso debe ser posterior al nacimiento.", status=422)
    if admission_date > date(current_paraguay_date().year + 1, 12, 31) or admission_date < date(1900, 1, 1):
        return review_page(request, db, user, source, error="Revisá la fecha de ingreso de la nueva relación laboral.", status=422)
    if employee_code.strip():
        try:
            code = int(employee_code.strip())
        except ValueError:
            return review_page(request, db, user, source, error="El Código Legajo debe ser numérico.", status=422)
    else:
        code = core._next_employee_code(db, destination.id)
    if not 1 <= code <= 2_147_483_647 or db.scalar(select(Employee.id).where(
        Employee.company_id == destination.id, Employee.employee_code == code
    ).limit(1)) is not None:
        return review_page(request, db, user, source, error="El Código Legajo no está disponible en la empresa destino.", status=409)

    old_profile = db.scalar(select(EmployeeComplianceProfile).where(EmployeeComplianceProfile.employee_id == source.id))
    worker = Employee(
        company_id=destination.id, employee_code=code, full_name=source.full_name,
        document_number=document, birth_date=source.birth_date,
        phone=source.phone or "", email=source.email or "", address=source.address or "",
        position=position.strip(), admission_date=admission_date, base_salary=base_salary,
        status="Activo", branch_id=None, section_id=None,
        payment_frequency=payment_frequency, contract_type=contract_type,
        ips_contributor=ips_contributor == "true", notes="",
        updated_at=datetime.now(UTC), updated_by=user.email,
    )
    try:
        db.add(worker)
        db.flush()
        db.add(EmployeeComplianceProfile(
            employee_id=worker.id,
            document_type=old_profile.document_type if old_profile else "CI",
            sex=old_profile.sex if old_profile else "",
            nationality=old_profile.nationality if old_profile else "Paraguaya",
            marital_status=old_profile.marital_status if old_profile else "",
            birth_place=old_profile.birth_place if old_profile else "",
            ips_number=old_profile.ips_number if old_profile else "",
            salary_type=payment_frequency,
        ))
        db.add(SalaryHistory(
            employee_id=worker.id, previous_salary=0, new_salary=base_salary,
            effective_from=admission_date, reason="Salario inicial · nuevo empleador",
            created_by=user.email,
        ))
        core.add_employee_event(
            db, worker, user, "Alta", "Nueva relación laboral",
            f"Alta en {destination.legal_name}. Datos personales tomados del legajo "
            f"{source.employee_code or source.id} de {source.company.legal_name} (ID {source.id}). "
            "El historial del empleador anterior no se transfirió.",
            admission_date, base_salary,
        )
        core.ensure_compliance_event(
            db, company_id=destination.id, employee_id=worker.id, branch_id=None,
            authority="REOP", event_type="Entrada", event_date=admission_date, due_date=None,
            payload={"employee_id": worker.id}, created_by=user.email,
            source_key=f"employee:{worker.id}:entry:reop",
        )
        if worker.ips_contributor:
            core.ensure_compliance_event(
                db, company_id=destination.id, employee_id=worker.id, branch_id=None,
                authority="REI", event_type="Entrada", event_date=admission_date, due_date=None,
                payload={"employee_id": worker.id}, created_by=user.email,
                source_key=f"employee:{worker.id}:entry:rei",
            )
        core.write_audit(
            db, user, "alta_nuevo_empleador", "funcionario", str(worker.id),
            f"Legajo nuevo en empresa {destination.id}, proveniente de ficha "
            f"{source.id} (empresa {source.company_id}). Sin transferencia de historial.",
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "El código o la cédula ya está registrado en la empresa seleccionada.") from exc

    return RedirectResponse(f"/app/employees/{worker.id}?new_employment=1", status_code=303)
