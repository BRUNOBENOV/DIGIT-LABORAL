import json
from typing import Annotated
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from . import main as core
from .employee_deletion import DeletionConflict, REASONS, confirmation_token, deletion_preview, remove_dossier, return_url, verify_confirmation
from .employee_linked_records import linked_record_page
from .models import Employee, User

router = APIRouter()


def allowed_employee(db, user, employee_id, *, lock=False):
    query = select(Employee).where(Employee.id == employee_id, Employee.company_id.in_(core.company_ids_for_user(db, user)))
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    employee = db.scalar(query)
    if employee is None:
        raise HTTPException(404, "Funcionario no encontrado en tu estudio.")
    return employee


def preview_page(request, db, user, employee, back, *, error="", status=200):
    preview = deletion_preview(db, employee)
    response = core.render(request, "employee_delete.html", db, user, employee=employee,
        deletion=preview, deletion_token=confirmation_token(user, employee, preview) if preview["can_delete"] else "",
        deletion_reasons=REASONS, return_to=return_url(back, employee.company_id), deletion_error=error)
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/app/employees/{employee_id}/linked-records")
def employee_linked_records(employee_id: int, request: Request, category: str = "", page: int = 1,
    user: User = Depends(core.require_roles("administrador", "contador")), db: Session = Depends(core.get_db)):
    employee = allowed_employee(db, user, employee_id)
    preview = deletion_preview(db, employee)
    categories = preview["blockers"]
    if category and category not in {item["key"] for item in categories}:
        raise HTTPException(404, "No existen registros vinculados de esa categoría para este funcionario.")
    selected = linked_record_page(db, employee, category, page=page) if category else None
    groups = [] if selected else [
        linked_record_page(db, employee, item["key"], page_size=5) for item in categories
    ]
    response = core.render(request, "employee_linked_records.html", db, user,
        employee=employee, categories=categories, groups=groups, selected=selected)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/app/employees/{employee_id}/permanent-delete")
def employee_delete_preview(employee_id: int, request: Request, return_to: str = "",
    user: User = Depends(core.require_roles("administrador", "contador")), db: Session = Depends(core.get_db)):
    return preview_page(request, db, user, allowed_employee(db, user, employee_id), return_to)


@router.post("/app/employees/{employee_id}/permanent-delete")
def employee_delete_confirm(employee_id: int, request: Request,
    token: Annotated[str, Form()] = "", confirmation: Annotated[str, Form()] = "",
    reason: Annotated[str, Form()] = "", notes: Annotated[str, Form()] = "",
    return_to: Annotated[str, Form()] = "",
    user: User = Depends(core.require_roles("administrador", "contador")), db: Session = Depends(core.get_db)):
    employee = allowed_employee(db, user, employee_id, lock=True)
    preview = deletion_preview(db, employee, lock_profile=True)
    error, status = "", 422
    if not preview["can_delete"]:
        error, status = "Este funcionario tiene registros vinculados. Revisá el detalle antes de continuar.", 409
    elif not verify_confirmation(token, user, employee, preview):
        error, status = "La revisión venció o el legajo cambió. Revisá los datos actualizados y confirmá nuevamente.", 409
    elif confirmation.strip() != preview["confirmation"]:
        error = "Escribí exactamente la frase de confirmación indicada para este legajo."
    elif reason not in REASONS or len(notes) > 500 or (reason == "Otro motivo" and len(notes.strip()) < 5):
        error = "Seleccioná un motivo válido. Si elegís Otro motivo, explicalo brevemente (máximo 500 caracteres)."
    if error:
        return preview_page(request, db, user, employee, return_to, error=error, status=status)
    identity = {"employee_id": employee.id, "company_id": employee.company_id, "employee_code": employee.employee_code,
        "employee_name": employee.full_name, "previous_status": employee.status, "reason": reason,
        "notes": notes.strip(), "removed_profile_records": preview["profile"]}
    target = return_url(return_to, employee.company_id, deleted=True)
    try:
        remove_dossier(db, employee, entry_ids=preview["entry_ids"])
        core.write_audit(db, user, "eliminar_definitivamente", "funcionario", str(employee.id), json.dumps(identity, ensure_ascii=False, separators=(",", ":")))
        db.commit()
    except (IntegrityError, DeletionConflict):
        db.rollback()
        return preview_page(request, db, user, allowed_employee(db, user, employee_id), return_to,
            error="Una restricción o un cambio en los registros impide la eliminación. No se borró ningún dato; revisá el expediente.", status=409)
    return RedirectResponse(target, status_code=303)
