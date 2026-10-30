from __future__ import annotations

import csv
import io
import re
import uuid
import zipfile
from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import hash_password
from app.database import SessionLocal
from app.main import UPLOAD_DIR, app
from app.backup_service import build_studio_export
from app.config import settings
from app.models import Company, CompanyRequest, Document, Employee, EmployeeEvent, IntegrationBatch, Notification, NotificationDelivery, RequestAttachment, RequestWorkflow, SalaryHistory, Studio, User, Vacation
from app.storage_service import storage


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


def test_employee_status_requires_dedicated_egreso_workflow():
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
        for status_value in ("Activo", "Desvinculado", "Inactivo"):
            response = client.post(
                f"/app/employees/{employee_id}/status",
                data={"csrf_token": csrf, "status": status_value, "termination_date": date.today().isoformat()},
                follow_redirects=False,
            )
            assert response.status_code == 410

    with SessionLocal() as db:
        employee = db.get(Employee, employee_id)
        assert employee is not None
        assert employee.status == "Activo"
        assert employee.termination_date is None


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



def test_review_route_notifies_new_assignee():
    email, password, company_id, _ = ensure_admin()
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.email == email))
        assert admin is not None and admin.studio_id is not None
        assignee_email = "workflow-assignee@test.py"
        assignee = db.scalar(select(User).where(User.email == assignee_email))
        if assignee is None:
            assignee = User(
                studio_id=admin.studio_id,
                full_name="Workflow Assignee",
                email=assignee_email,
                password_hash=hash_password("demo123"),
                role="auxiliar",
                active=True,
                must_change_password=False,
            )
            db.add(assignee)
            db.commit()
        assignee_id = assignee.id

    with TestClient(app) as client:
        csrf = login(client, email, password)
        created = client.post(
            "/app/requests",
            data={
                "csrf_token": csrf,
                "company_id": str(company_id),
                "request_type": "Otra consulta",
                "subject": "Prueba de asignación",
                "detail": "Comprobar que la ruta de revisión notifica al nuevo responsable.",
                "priority": "Normal",
            },
            follow_redirects=False,
        )
        assert created.status_code == 303
        request_id = int(created.headers["location"].rstrip("/").split("/")[-1])

        csrf = token_from_page(client, f"/app/requests/{request_id}")
        reviewed = client.post(
            f"/app/requests/{request_id}/review",
            data={
                "csrf_token": csrf,
                "status": "En revisión",
                "response": "",
                "assigned_user_id": str(assignee_id),
            },
            follow_redirects=False,
        )
        assert reviewed.status_code == 303

    with SessionLocal() as db:
        notice = db.scalar(select(Notification).where(
            Notification.recipient_user_id == assignee_id,
            Notification.related_request_id == request_id,
            Notification.event_type == "solicitud_asignada",
        ))
        assert notice is not None
        assert notice.target_url == f"/app/requests/{request_id}"


def test_notification_outbox_recovers_stale_sending_delivery(monkeypatch):
    from dataclasses import replace

    from app import notification_service

    monkeypatch.setattr(
        notification_service,
        "settings",
        replace(notification_service.settings, smtp_host="", smtp_from_email=""),
    )
    email, password, _, _ = ensure_admin()
    with SessionLocal() as db:
        recipient = db.scalar(select(User).where(User.email == email))
        assert recipient is not None
        now = datetime.now(UTC)
        notice = Notification(
            studio_id=recipient.studio_id,
            recipient_user_id=recipient.id,
            event_type="prueba_recuperacion",
            title="Recuperación de cola",
            body="Prueba de recuperación de un proceso interrumpido.",
            target_url="/app/notifications",
            created_at=now - timedelta(hours=1),
        )
        db.add(notice)
        db.flush()
        delivery = NotificationDelivery(
            studio_id=recipient.studio_id,
            notification_id=notice.id,
            channel="email",
            status="Enviando",
            attempts=1,
            last_error="",
            created_at=now - timedelta(hours=1),
            updated_at=now - timedelta(minutes=30),
        )
        db.add(delivery)
        db.commit()
        delivery_id = delivery.id

    notification_service.dispatch_notification_outbox(limit=500)

    with SessionLocal() as db:
        recovered = db.get(NotificationDelivery, delivery_id)
        assert recovered is not None
        assert recovered.status == "Pendiente"
        assert recovered.attempts == 1
        assert recovered.last_error == "SMTP no está configurado."



def test_vacation_balance_endpoint_and_approval_reservation():
    email, password, company_id, employee_id = ensure_admin()
    period_year = date.today().year + 1
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.email == email))
        assert admin is not None
        existing = list(db.scalars(select(Vacation).where(
            Vacation.employee_id == employee_id,
            Vacation.period_year == period_year,
        )))
        for row in existing:
            db.delete(row)
        db.flush()
        ledger = Vacation(
            employee_id=employee_id,
            period_year=period_year,
            entitled_days=18,
            used_days=5,
            status="Aprobada",
            notes="Saldo anual de prueba",
        )
        db.add(ledger)
        reservation = CompanyRequest(
            company_id=company_id,
            request_type="Vacaciones",
            subject="Reserva existente",
            detail="Reserva aprobada de prueba.",
            requested_by_user_id=admin.id,
            employee_id=employee_id,
            start_date=date(period_year, 6, 1),
            end_date=date(period_year, 6, 4),
            period_year=period_year,
            requested_days=4,
            priority="Normal",
            status="Aprobada",
        )
        db.add(reservation)
        db.flush()
        db.add(RequestWorkflow(
            request_id=reservation.id,
            approved_by_user_id=admin.id,
            approved_at=datetime.now(UTC),
        ))
        db.commit()

    with TestClient(app) as client:
        csrf = login(client, email, password)
        balance = client.get(
            "/app/requests/vacation-balance",
            params={"employee_id": employee_id, "period_year": period_year},
        )
        assert balance.status_code == 200
        assert balance.json() == {
            "entitled_days": 18,
            "used_days": 5,
            "reserved_days": 4,
            "available_days": 9,
        }

        rejected = client.post(
            "/app/requests",
            data={
                "csrf_token": csrf,
                "company_id": str(company_id),
                "request_type": "Vacaciones",
                "subject": "Excede saldo",
                "detail": "Solicitud que excede los días disponibles.",
                "priority": "Normal",
                "employee_id": str(employee_id),
                "period_year": str(period_year),
                "requested_days": "10",
                "start_date": f"{period_year}-07-01",
                "end_date": f"{period_year}-07-10",
            },
            follow_redirects=False,
        )
        assert rejected.status_code == 400
        assert "Saldo insuficiente" in rejected.text

        submitted = client.post(
            "/app/requests",
            data={
                "csrf_token": csrf,
                "company_id": str(company_id),
                "request_type": "Vacaciones",
                "subject": "Solicitud dentro del saldo",
                "detail": "Solicitud que se encuentra dentro del saldo disponible.",
                "priority": "Normal",
                "employee_id": str(employee_id),
                "period_year": str(period_year),
                "requested_days": "9",
                "start_date": f"{period_year}-07-01",
                "end_date": f"{period_year}-07-09",
            },
            follow_redirects=False,
        )
        assert submitted.status_code == 303
        request_id = int(submitted.headers["location"].rstrip("/").split("/")[-1])
        # A pending request does not consume or reserve days until approved.
        unchanged = client.get(
            "/app/requests/vacation-balance",
            params={"employee_id": employee_id, "period_year": period_year},
        )
        assert unchanged.status_code == 200
        assert unchanged.json()["available_days"] == 9

        csrf = token_from_page(client, f"/app/requests/{request_id}")
        approved = client.post(
            f"/app/requests/{request_id}/review",
            data={"csrf_token": csrf, "status": "Aprobada", "response": "Vacaciones aprobadas."},
            follow_redirects=False,
        )
        assert approved.status_code == 303
        csrf = token_from_page(client, f"/app/requests/{request_id}")
        premature_usage = client.post(
            f"/app/requests/{request_id}/apply",
            data={"csrf_token": csrf},
            follow_redirects=False,
        )
        assert premature_usage.status_code == 409
        after_approval = client.get(
            "/app/requests/vacation-balance",
            params={"employee_id": employee_id, "period_year": period_year},
        )
        assert after_approval.status_code == 200
        assert after_approval.json()["available_days"] == 0
        assert after_approval.json()["used_days"] == 5


def test_completed_vacation_and_permission_requests_apply_only_after_end_date():
    email, password, company_id, employee_id = ensure_admin()
    today = date.today()
    period_year = today.year
    past_end = today - timedelta(days=5)
    past_start = past_end - timedelta(days=3)
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.email == email))
        assert admin is not None
        ledger = Vacation(
            employee_id=employee_id,
            period_year=period_year,
            entitled_days=365,
            used_days=3,
            start_date=date(period_year, 1, 1),
            end_date=date(period_year, 12, 31),
            status="Aprobada",
            notes="Saldo para prueba de aplicación",
        )
        db.add(ledger)
        db.flush()
        vacation_used_before = sum(
            max(0, int(row.used_days or 0))
            for row in db.scalars(select(Vacation).where(
                Vacation.employee_id == employee_id,
                Vacation.period_year == period_year,
                Vacation.status.notin_(("Rechazada", "Anulada", "Cancelada")),
            ))
        )
        vacation = CompanyRequest(
            company_id=company_id,
            request_type="Vacaciones",
            subject="Vacaciones finalizadas",
            detail="Registrar uso después de finalizar el periodo.",
            requested_by_user_id=admin.id,
            employee_id=employee_id,
            start_date=past_start,
            end_date=past_end,
            period_year=period_year,
            requested_days=4,
            priority="Normal",
            status="Aprobada",
        )
        permission = CompanyRequest(
            company_id=company_id,
            request_type="Permiso/licencia",
            subject="Examen finalizado",
            detail="Permiso para rendir examen.",
            requested_by_user_id=admin.id,
            employee_id=employee_id,
            start_date=past_start,
            end_date=past_end,
            leave_type="Exámenes",
            hours_requested=None,
            priority="Normal",
            status="Aprobada",
        )
        db.add_all([vacation, permission])
        db.flush()
        db.add_all([
            RequestWorkflow(request_id=vacation.id, approved_by_user_id=admin.id, approved_at=datetime.now(UTC)),
            RequestWorkflow(request_id=permission.id, approved_by_user_id=admin.id, approved_at=datetime.now(UTC)),
        ])
        vacation_id, permission_id = vacation.id, permission.id
        db.commit()

    with TestClient(app) as client:
        csrf = login(client, email, password)
        token = token_from_page(client, f"/app/requests/{vacation_id}")
        applied = client.post(f"/app/requests/{vacation_id}/apply", data={"csrf_token": token}, follow_redirects=False)
        assert applied.status_code == 303
        applied_again = client.post(f"/app/requests/{vacation_id}/apply", data={"csrf_token": token}, follow_redirects=False)
        assert applied_again.status_code == 303
        permission_token = token_from_page(client, f"/app/requests/{permission_id}")
        permission_applied = client.post(
            f"/app/requests/{permission_id}/apply",
            data={"csrf_token": permission_token},
            follow_redirects=False,
        )
        assert permission_applied.status_code == 303

    with SessionLocal() as db:
        vacation = db.get(CompanyRequest, vacation_id)
        permission = db.get(CompanyRequest, permission_id)
        vacation_workflow = db.scalar(select(RequestWorkflow).where(RequestWorkflow.request_id == vacation_id))
        permission_workflow = db.scalar(select(RequestWorkflow).where(RequestWorkflow.request_id == permission_id))
        ledgers = list(db.scalars(select(Vacation).where(
            Vacation.employee_id == employee_id,
            Vacation.period_year == period_year,
            Vacation.status.notin_(("Rechazada", "Anulada", "Cancelada")),
        )))
        vacation_used_after = sum(max(0, int(row.used_days or 0)) for row in ledgers)
        assert vacation is not None and vacation.status == "Aplicada"
        assert vacation_workflow is not None and vacation_workflow.applied is True
        assert vacation_used_after == vacation_used_before + 4
        assert permission is not None and permission.status == "Aplicada"
        assert permission_workflow is not None and permission_workflow.applied is True
        event = db.scalar(select(EmployeeEvent).where(
            EmployeeEvent.employee_id == employee_id,
            EmployeeEvent.title == f"Exámenes registrado mediante solicitud #{permission_id}",
        ))
        assert event is not None
        assert event.event_type == "Permiso"
        assert "Motivo: Permiso para rendir examen." in event.detail


def test_notification_cron_endpoint_requires_bearer_token(monkeypatch):
    from dataclasses import replace

    from app import main as main_module

    monkeypatch.setattr(
        main_module,
        "settings",
        replace(main_module.settings, notification_cron_token="test-scheduler-secret"),
    )
    monkeypatch.setattr(main_module, "create_due_request_notifications", lambda: 2)
    monkeypatch.setattr(main_module, "create_due_official_certificate_notifications", lambda: 1)
    monkeypatch.setattr(main_module, "dispatch_notification_outbox", lambda: {"sent": 3, "failed": 0, "checked": 3})

    with TestClient(app) as client:
        unauthorized = client.post("/internal/cron/notifications")
        assert unauthorized.status_code == 401
        authorized = client.post(
            "/internal/cron/notifications",
            headers={"Authorization": "Bearer test-scheduler-secret"},
        )
        assert authorized.status_code == 200
        assert authorized.json() == {
            "ok": True,
            "request_notices_created": 2,
            "certificate_notices_created": 1,
            "deliveries": {"sent": 3, "failed": 0, "checked": 3},
        }


def test_local_uploads_remain_downloadable_and_exportable_after_storage_copy_is_lost():
    if settings.storage_backend != "local":
        import pytest
        pytest.skip("Este escenario verifica el respaldo para el backend local.")

    email, password, company_id, employee_id = ensure_admin()
    attachment_content = b"%PDF-1.7\nDigit Laboral attachment durability test\n"
    document_content = b"%PDF-1.7\nDigit Laboral document durability test\n"
    batch_content = b"synthetic-xlsx-content-for-durability-test"
    receipt_content = b"%PDF-1.7\nDigit Laboral receipt durability test\n"
    request_id = document_id = attachment_id = batch_id = None
    attachment_key = document_key = receipt_key = ""

    with TestClient(app) as client:
        csrf = login(client, email, password)
        request_response = client.post(
            "/app/requests",
            data={
                "csrf_token": csrf, "company_id": str(company_id), "request_type": "Otra consulta",
                "subject": "Prueba de persistencia", "detail": "Verificar que el archivo no dependa del disco local.",
                "priority": "Normal", "employee_id": "", "effective_date": "", "start_date": "",
                "end_date": "", "period_year": "", "requested_days": "", "entitled_days": "",
                "amount": "", "leave_type": "", "hours_requested": "",
            },
            follow_redirects=False,
        )
        assert request_response.status_code == 303
        request_id = int(request_response.headers["location"].rstrip("/").split("/")[-1])

        attachment_response = client.post(
            f"/app/requests/{request_id}/attachments",
            data={"csrf_token": csrf},
            files={"file": ("prueba-adjunto.pdf", attachment_content, "application/pdf")},
            follow_redirects=False,
        )
        assert attachment_response.status_code == 303

        document_response = client.post(
            "/app/documents",
            data={
                "csrf_token": csrf, "company_id": str(company_id), "employee_id": str(employee_id),
                "title": "Documento persistente de prueba", "category": "Prueba",
            },
            files={"file": ("prueba-documento.pdf", document_content, "application/pdf")},
            follow_redirects=False,
        )
        assert document_response.status_code == 303

        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == email))
            assert user is not None and user.studio_id is not None
            attachment = db.scalar(
                select(RequestAttachment).where(RequestAttachment.request_id == request_id)
                .order_by(RequestAttachment.id.desc())
            )
            document = db.scalar(
                select(Document).where(Document.title == "Documento persistente de prueba")
                .order_by(Document.id.desc())
            )
            assert attachment is not None and document is not None
            attachment_id, attachment_key = attachment.id, attachment.stored_name
            document_id, document_key = document.id, document.stored_name
            assert bytes(attachment.content_bytes) == attachment_content
            assert bytes(document.content_bytes) == document_content

            batch = IntegrationBatch(
                studio_id=user.studio_id,
                company_id=company_id,
                authority="REOP",
                batch_type="Prueba de persistencia",
                period="2026",
                status="Generado",
                file_name="test-batch.xlsx",
                storage_key=f"integrations/{company_id}/test-batch.xlsx",
                file_bytes=batch_content,
                file_sha256="a" * 64,
                item_count=1,
                created_by=email,
            )
            db.add(batch)
            db.commit()
            batch_id = batch.id

        receipt_response = client.post(
            f"/app/compliance/batches/{batch_id}/receipt",
            data={"csrf_token": csrf, "status": "Presentado", "external_reference": "TEST-RECIBO-001"},
            files={"receipt": ("comprobante-prueba.pdf", receipt_content, "application/pdf")},
            follow_redirects=False,
        )
        assert receipt_response.status_code == 303

    with SessionLocal() as db:
        attachment = db.get(RequestAttachment, attachment_id)
        document = db.get(Document, document_id)
        batch = db.get(IntegrationBatch, batch_id)
        user = db.scalar(select(User).where(User.email == email))
        assert attachment is not None and document is not None and batch is not None and user is not None
        receipt_key = batch.receipt_storage_key
        assert bytes(batch.file_bytes) == batch_content
        assert bytes(batch.receipt_bytes) == receipt_content
        assert batch.receipt_file_name == "comprobante-prueba.pdf"
        # Simulate Render losing its local filesystem before building the ZIP.
        for key in (attachment_key, document_key, receipt_key):
            storage.delete(key)
        studio = db.get(Studio, user.studio_id)
        assert studio is not None
        backup_content = build_studio_export(db, studio, UPLOAD_DIR)

    with TestClient(app) as client:
        login(client, email, password)
        attachment_download = client.get(
            f"/app/requests/{request_id}/attachments/{attachment_id}/download"
        )
        document_download = client.get(f"/app/documents/{document_id}/download")
        batch_download = client.get(f"/app/compliance/batches/{batch_id}/download")
        receipt_download = client.get(f"/app/compliance/batches/{batch_id}/receipt")
        assert attachment_download.status_code == 200 and attachment_download.content == attachment_content
        assert document_download.status_code == 200 and document_download.content == document_content
        assert batch_download.status_code == 200 and batch_download.content == batch_content
        assert receipt_download.status_code == 200 and receipt_download.content == receipt_content
        assert receipt_download.headers["content-type"].startswith("application/pdf")

    with zipfile.ZipFile(io.BytesIO(backup_content)) as archive:
        names = archive.namelist()
        attachment_path = next(n for n in names if n.endswith(f"/{attachment_id}_prueba-adjunto.pdf"))
        document_path = next(n for n in names if n.endswith(f"/{document_id}_prueba-documento.pdf"))
        batch_path = next(n for n in names if n.endswith(f"/lotes/{batch_id}_test-batch.xlsx"))
        receipt_path = next(n for n in names if n.endswith(f"/comprobantes/{batch_id}_comprobante-prueba.pdf"))
        assert archive.read(attachment_path) == attachment_content
        assert archive.read(document_path) == document_content
        assert archive.read(batch_path) == batch_content
        assert archive.read(receipt_path) == receipt_content
