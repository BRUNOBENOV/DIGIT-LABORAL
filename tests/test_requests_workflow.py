from __future__ import annotations

import csv
import io
import re
import uuid
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import hash_password
from app.database import SessionLocal
from app.main import app
from app.models import Company, CompanyRequest, Employee, Notification, RequestWorkflow, SalaryHistory, Studio, User


def ensure_admin() -> tuple[str, str, int, int]:
    email = "workflow@test.py"
    password = "demo123"
    with SessionLocal() as db:
        studio = db.scalar(select(Studio).order_by(Studio.id))
        assert studio is not None
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(studio_id=studio.id, full_name="Workflow Admin", email=email, password_hash=hash_password(password), role="administrador", active=True, must_change_password=False)
            db.add(user)
            db.commit()
        company = db.scalar(select(Company).where(Company.studio_id == studio.id).order_by(Company.id))
        assert company is not None
        employee = db.scalar(select(Employee).where(Employee.company_id == company.id).order_by(Employee.id))
        assert employee is not None
        company_email = "workflow-company@test.py"
        company_user = db.scalar(select(User).where(User.email == company_email))
        if company_user is None:
            company_user = User(
                studio_id=studio.id, company_id=company.id, full_name="Workflow Company",
                email=company_email, password_hash=hash_password(password), role="empresa",
                active=True, must_change_password=False,
            )
            db.add(company_user)
            db.commit()
        return email, password, company.id, employee.id


def token_from_page(client: TestClient, path: str) -> str:
    response = client.get(path)
    assert response.status_code == 200
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    assert match, f"CSRF token not found in {path}"
    return match.group(1)


def login(client: TestClient, email: str, password: str) -> str:
    token = token_from_page(client, "/login")
    response = client.post("/login", data={"email": email, "password": password, "csrf_token": token}, follow_redirects=False)
    assert response.status_code == 303
    return token_from_page(client, "/app/requests")


def test_salary_request_is_approved_applied_and_notified():
    email, password, company_id, employee_id = ensure_admin()
    with SessionLocal() as db:
        employee = db.get(Employee, employee_id)
        original_salary = employee.base_salary
    with TestClient(app) as client:
        csrf = login(client, email, password)
        response = client.post(
            "/app/requests",
            data={
                "csrf_token": csrf, "company_id": str(company_id), "request_type": "Cambio salarial",
                "subject": "Ajuste de prueba", "detail": "Actualizar salario para comprobar el flujo.",
                "priority": "Normal", "employee_id": str(employee_id), "effective_date": "2026-08-01",
                "amount": str(original_salary + 100000),
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        request_id = int(response.headers["location"].rstrip("/").split("/")[-1])
        with SessionLocal() as db:
            item = db.get(CompanyRequest, request_id)
            assert item is not None
            assert item.requested_by_user_id is not None
            assert item.employee_id == employee_id
            assert item.effective_date.isoformat() == "2026-08-01"
            assert item.amount == original_salary + 100000
        csrf = token_from_page(client, f"/app/requests/{request_id}")
        review = client.post(
            f"/app/requests/{request_id}/review",
            data={"csrf_token": csrf, "status": "Aprobada", "response": "Aprobado", "assigned_to": "Workflow Admin"},
            follow_redirects=False,
        )
        assert review.status_code == 303
        csrf = token_from_page(client, f"/app/requests/{request_id}")
        applied = client.post(f"/app/requests/{request_id}/apply", data={"csrf_token": csrf}, follow_redirects=False)
        assert applied.status_code == 303
        csrf = token_from_page(client, f"/app/requests/{request_id}")
        locked = client.post(
            f"/app/requests/{request_id}/status",
            data={"csrf_token": csrf, "status": "Resuelta", "response": "Cambio posterior", "assigned_user_id": "", "due_date": "", "internal_notes": ""},
            follow_redirects=False,
        )
        assert locked.status_code == 409
        # Applying twice is idempotent and must never change the salary twice.
        csrf = token_from_page(client, f"/app/requests/{request_id}")
        applied_again = client.post(f"/app/requests/{request_id}/apply", data={"csrf_token": csrf}, follow_redirects=False)
        assert applied_again.status_code == 303
        assert client.get("/app/notifications").status_code == 200
    with SessionLocal() as db:
        item = db.get(CompanyRequest, request_id)
        workflow = db.scalar(select(RequestWorkflow).where(RequestWorkflow.request_id == request_id))
        employee = db.get(Employee, employee_id)
        assert item.status == "Aplicada"
        assert workflow is not None and workflow.applied is True and workflow.applied_at is not None
        assert employee.base_salary == original_salary + 100000
        assert db.scalar(select(Notification.id).where(Notification.related_request_id == request_id)) is not None


def test_request_form_accepts_blank_optional_fields():
    email, password, company_id, _ = ensure_admin()
    with TestClient(app) as client:
        csrf = login(client, email, password)
        response = client.post(
            "/app/requests",
            data={
                "csrf_token": csrf, "company_id": str(company_id), "request_type": "Otra consulta",
                "subject": "Consulta con campos opcionales vacíos",
                "detail": "Comprueba el formulario con campos opcionales en blanco.", "priority": "Normal",
                "employee_id": "", "effective_date": "", "start_date": "", "end_date": "",
                "period_year": "", "requested_days": "", "entitled_days": "", "amount": "",
                "leave_type": "", "hours_requested": "",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        request_id = int(response.headers["location"].rstrip("/").split("/")[-1])
        with SessionLocal() as db:
            item = db.get(CompanyRequest, request_id)
            assert item.employee_id is None and item.amount is None and item.requested_days is None


def test_incomplete_vacation_request_is_rejected():
    email, password, company_id, employee_id = ensure_admin()
    with TestClient(app) as client:
        csrf = login(client, email, password)
        response = client.post(
            "/app/requests",
            data={
                "csrf_token": csrf, "company_id": str(company_id), "request_type": "Vacaciones",
                "subject": "Vacaciones sin fechas", "detail": "Debe requerir los datos del periodo.",
                "priority": "Normal", "employee_id": str(employee_id), "period_year": "",
                "requested_days": "", "start_date": "", "end_date": "",
            },
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert "requiere funcionario, periodo" in response.text


def test_notification_reads_are_scoped_to_the_logged_in_user():
    email, password, _, _ = ensure_admin()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        assert user is not None
        company_user = db.scalar(select(User).where(User.email == "workflow-company@test.py"))
        assert company_user is not None
        note = Notification(
            studio_id=user.studio_id, recipient_user_id=user.id, event_type="prueba",
            title="Aviso de prueba", body="Notificación privada.", target_url="/app/requests",
        )
        other_note = Notification(
            studio_id=company_user.studio_id, recipient_user_id=company_user.id, event_type="prueba_privada",
            title="Aviso privado de empresa", body="Solo para la empresa.", target_url="/app/requests",
        )
        db.add_all([note, other_note])
        db.commit()
        notification_id = note.id
        other_notification_id = other_note.id
    with TestClient(app) as client:
        login(client, email, password)
        page = client.get("/app/notifications")
        assert page.status_code == 200 and "Aviso de prueba" in page.text
        assert "Aviso privado de empresa" not in page.text
        csrf = token_from_page(client, "/app/notifications")
        forbidden = client.post(
            f"/app/notifications/{other_notification_id}/read", data={"csrf_token": csrf}, follow_redirects=False,
        )
        assert forbidden.status_code == 404
        marked = client.post(
            f"/app/notifications/{notification_id}/read", data={"csrf_token": csrf}, follow_redirects=False,
        )
        assert marked.status_code == 303
    with SessionLocal() as db:
        note = db.get(Notification, notification_id)
        other_note = db.get(Notification, other_notification_id)
        assert note.read_at is not None
        assert other_note.read_at is None



def test_direct_employee_edit_cannot_bypass_salary_approval():
    email, password, _, employee_id = ensure_admin()
    with SessionLocal() as db:
        employee = db.get(Employee, employee_id)
        assert employee is not None
        original_salary = employee.base_salary
        original_name = employee.full_name
        original_position = employee.position
        original_notes = employee.notes

    with TestClient(app) as client:
        csrf = login(client, email, password)
        rejected = client.post(
            f"/app/employees/{employee_id}/edit",
            data={
                "csrf_token": csrf,
                "full_name": original_name,
                "position": original_position,
                "base_salary": str(original_salary + 150000),
                "email": "",
                "phone": "",
                "address": "",
                "notes": original_notes,
            },
            follow_redirects=False,
        )
        assert rejected.status_code == 409
        assert "solicitud salarial aprobada" in rejected.text.lower()

        updated = client.post(
            f"/app/employees/{employee_id}/edit",
            data={
                "csrf_token": csrf,
                "full_name": original_name,
                "position": original_position,
                "email": "",
                "phone": "",
                "address": "",
                "notes": "Prueba de actualización no salarial.",
            },
            follow_redirects=False,
        )
        assert updated.status_code == 303

        restored = client.post(
            f"/app/employees/{employee_id}/edit",
            data={
                "csrf_token": csrf,
                "full_name": original_name,
                "position": original_position,
                "email": "",
                "phone": "",
                "address": "",
                "notes": original_notes or "",
            },
            follow_redirects=False,
        )
        assert restored.status_code == 303

    with SessionLocal() as db:
        employee = db.get(Employee, employee_id)
        assert employee is not None
        assert employee.base_salary == original_salary
        assert employee.notes == original_notes


def test_employee_import_cannot_change_existing_salary():
    email, password, company_id, employee_id = ensure_admin()
    with SessionLocal() as db:
        employee = db.get(Employee, employee_id)
        assert employee is not None
        original_salary = employee.base_salary
        original_document = employee.document_number
        original_admission = employee.admission_date
        original_name = employee.full_name
        original_position = employee.position
        original_notes = employee.notes
        salary_history_before = len(list(db.scalars(
            select(SalaryHistory).where(SalaryHistory.employee_id == employee_id)
        )))

    csv_buffer = io.StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerow([
        "nombre_completo", "cedula", "cargo", "fecha_ingreso", "salario_base",
        "fecha_nacimiento", "tipo_contrato", "frecuencia_pago", "aporta_ips",
        "correo", "telefono", "direccion", "observaciones",
    ])
    writer.writerow([
        original_name, original_document, "Cargo importado de prueba",
        original_admission.isoformat(), original_salary + 777000, "",
        "Tiempo indefinido", "Mensual", "Sí", "", "", "",
        "Ficha actualizada por prueba de importación",
    ])
    file_content = csv_buffer.getvalue().encode("utf-8-sig")

    with TestClient(app) as client:
        csrf = login(client, email, password)
        preview_response = client.post(
            "/app/import/employees/preview",
            data={"csrf_token": csrf, "company_id": str(company_id)},
            files={"file": ("salary-bypass-test.csv", file_content, "text/csv")},
            follow_redirects=False,
        )
        assert preview_response.status_code == 303
        preview_url = preview_response.headers["location"]
        preview_page = client.get(preview_url)
        assert preview_page.status_code == 200
        assert "salario vigente se conservará" in preview_page.text
        assert "1 funcionario existente" in preview_page.text
        assert f"Gs. {original_salary:,}".replace(",", ".") in preview_page.text

        confirm = client.post(
            f"{preview_url}/confirm",
            data={"csrf_token": csrf, "duplicate_action": "update"},
            follow_redirects=False,
        )
        assert confirm.status_code == 303
        assert "salary_changes=1" in confirm.headers["location"]
        result_page = client.get(confirm.headers["location"])
        assert result_page.status_code == 200
        assert "1 cambio salarial no se aplicó" in result_page.text

    with SessionLocal() as db:
        employee = db.get(Employee, employee_id)
        assert employee is not None
        assert employee.base_salary == original_salary
        assert employee.position == "Cargo importado de prueba"
        salary_history_after = len(list(db.scalars(
            select(SalaryHistory).where(SalaryHistory.employee_id == employee_id)
        )))
        assert salary_history_after == salary_history_before
        employee.position = original_position
        employee.notes = original_notes
        db.commit()


def test_employee_status_treats_blank_date_as_empty_and_requires_exit_date():
    email, password, company_id, _ = ensure_admin()
    with SessionLocal() as db:
        employee = Employee(
            company_id=company_id,
            full_name="Funcionario de prueba de estado",
            document_number=f"STATUS-TEST-{uuid.uuid4().hex[:12]}",
            position="Auxiliar",
            admission_date=date.today(),
            base_salary=0,
            status="Activo",
        )
        db.add(employee)
        db.commit()
        employee_id = employee.id

    with TestClient(app) as client:
        csrf = login(client, email, password)
        active = client.post(
            f"/app/employees/{employee_id}/status",
            data={"csrf_token": csrf, "status": "Activo", "termination_date": ""},
            follow_redirects=False,
        )
        assert active.status_code == 303

        missing_exit_date = client.post(
            f"/app/employees/{employee_id}/status",
            data={"csrf_token": csrf, "status": "Desvinculado", "termination_date": ""},
            follow_redirects=False,
        )
        assert missing_exit_date.status_code == 303
        error_page = client.get(missing_exit_date.headers["location"])
        assert error_page.status_code == 200
        assert "fecha efectiva de salida" in error_page.text.lower()

        with SessionLocal() as db:
            employee = db.get(Employee, employee_id)
            assert employee is not None
            assert employee.status == "Activo"
            assert employee.termination_date is None

        exit_date = date.today().isoformat()
        terminated = client.post(
            f"/app/employees/{employee_id}/status",
            data={"csrf_token": csrf, "status": "Desvinculado", "termination_date": exit_date},
            follow_redirects=False,
        )
        assert terminated.status_code == 303

    with SessionLocal() as db:
        employee = db.get(Employee, employee_id)
        assert employee is not None
        assert employee.status == "Desvinculado"
        assert employee.termination_date == date.today()



def test_request_numeric_limits_and_hour_precision_are_enforced():
    email, password, company_id, employee_id = ensure_admin()
    today = date.today().isoformat()
    with TestClient(app) as client:
        csrf = login(client, email, password)
        oversized_salary = client.post(
            "/app/requests",
            data={
                "csrf_token": csrf, "company_id": str(company_id), "request_type": "Cambio salarial",
                "detail": "Prueba de límite numérico.", "priority": "Normal",
                "employee_id": str(employee_id), "effective_date": today,
                "amount": "2147483648",
            },
            follow_redirects=False,
        )
        assert oversized_salary.status_code == 400

        too_many_vacation_days = client.post(
            "/app/requests",
            data={
                "csrf_token": csrf, "company_id": str(company_id), "request_type": "Vacaciones",
                "detail": "Prueba de límite de días.", "priority": "Normal",
                "employee_id": str(employee_id), "period_year": str(date.today().year),
                "requested_days": "366", "start_date": today, "end_date": today,
            },
            follow_redirects=False,
        )
        assert too_many_vacation_days.status_code == 400

        hours_with_excess_precision = client.post(
            "/app/requests",
            data={
                "csrf_token": csrf, "company_id": str(company_id), "request_type": "Permiso/licencia",
                "detail": "Prueba de precisión horaria.", "priority": "Normal",
                "employee_id": str(employee_id), "leave_type": "Otro",
                "start_date": today, "end_date": today, "hours_requested": "0.001",
            },
            follow_redirects=False,
        )
        assert hours_with_excess_precision.status_code == 400


def test_salary_request_cannot_be_resolved_without_apply_and_invalid_legacy_request_fails_closed():
    email, password, company_id, employee_id = ensure_admin()
    with SessionLocal() as db:
        employee = db.get(Employee, employee_id)
        assert employee is not None
        original_salary = employee.base_salary

    today = date.today().isoformat()
    with TestClient(app) as client:
        csrf = login(client, email, password)
        submitted = client.post(
            "/app/requests",
            data={
                "csrf_token": csrf, "company_id": str(company_id), "request_type": "Cambio salarial",
                "subject": "Prueba de aplicación segura", "detail": "Validar el flujo formal de aprobación.",
                "priority": "Normal", "employee_id": str(employee_id),
                "effective_date": today, "amount": str(original_salary + 100000),
            },
            follow_redirects=False,
        )
        assert submitted.status_code == 303
        request_id = int(submitted.headers["location"].rstrip("/").split("/")[-1])

        csrf = token_from_page(client, f"/app/requests/{request_id}")
        approved = client.post(
            f"/app/requests/{request_id}/review",
            data={"csrf_token": csrf, "status": "Aprobada", "response": "Aprobación de prueba"},
            follow_redirects=False,
        )
        assert approved.status_code == 303

        csrf = token_from_page(client, f"/app/requests/{request_id}")
        resolved_without_apply = client.post(
            f"/app/requests/{request_id}/status",
            data={
                "csrf_token": csrf, "status": "Resuelta", "response": "",
                "assigned_user_id": "", "due_date": "", "internal_notes": "",
            },
            follow_redirects=False,
        )
        assert resolved_without_apply.status_code == 409

        with SessionLocal() as db:
            item = db.get(CompanyRequest, request_id)
            assert item is not None
            item.amount = 0
            db.commit()

        csrf = token_from_page(client, f"/app/requests/{request_id}")
        zero_salary = client.post(
            f"/app/requests/{request_id}/apply",
            data={"csrf_token": csrf},
            follow_redirects=False,
        )
        assert zero_salary.status_code == 400

        with SessionLocal() as db:
            item = db.get(CompanyRequest, request_id)
            assert item is not None
            item.amount = original_salary + 100000
            item.effective_date = None
            db.commit()

        csrf = token_from_page(client, f"/app/requests/{request_id}")
        missing_effective_date = client.post(
            f"/app/requests/{request_id}/apply",
            data={"csrf_token": csrf},
            follow_redirects=False,
        )
        assert missing_effective_date.status_code == 400

    with SessionLocal() as db:
        employee = db.get(Employee, employee_id)
        item = db.get(CompanyRequest, request_id)
        workflow = db.scalar(select(RequestWorkflow).where(RequestWorkflow.request_id == request_id))
        assert employee is not None and item is not None and workflow is not None
        assert employee.base_salary == original_salary
        assert item.status == "Aprobada"
        assert not workflow.applied


def test_request_comments_and_attachments_reject_empty_or_misrepresented_content():
    email, password, company_id, _ = ensure_admin()
    with TestClient(app) as client:
        csrf = login(client, email, password)
        created = client.post(
            "/app/requests",
            data={
                "csrf_token": csrf, "company_id": str(company_id), "request_type": "Otra consulta",
                "detail": "Solicitud para validar comentarios y adjuntos.", "priority": "Normal",
            },
            follow_redirects=False,
        )
        assert created.status_code == 303
        request_id = int(created.headers["location"].rstrip("/").split("/")[-1])

        csrf = token_from_page(client, f"/app/requests/{request_id}")
        blank_comment = client.post(
            f"/app/requests/{request_id}/comments",
            data={"csrf_token": csrf, "body": "   ", "visibility": "Empresa"},
            follow_redirects=False,
        )
        assert blank_comment.status_code == 400

        long_comment = client.post(
            f"/app/requests/{request_id}/comments",
            data={"csrf_token": csrf, "body": "x" * 10001, "visibility": "Empresa"},
            follow_redirects=False,
        )
        assert long_comment.status_code == 400

        fake_pdf = client.post(
            f"/app/requests/{request_id}/attachments",
            data={"csrf_token": csrf},
            files={"file": ("not-a-pdf.pdf", b"not a PDF document", "application/pdf")},
            follow_redirects=False,
        )
        assert fake_pdf.status_code == 415

        empty_pdf = client.post(
            f"/app/requests/{request_id}/attachments",
            data={"csrf_token": csrf},
            files={"file": ("empty.pdf", b"", "application/pdf")},
            follow_redirects=False,
        )
        assert empty_pdf.status_code == 400
