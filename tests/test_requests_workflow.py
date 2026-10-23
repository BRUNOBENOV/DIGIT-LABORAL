from __future__ import annotations

import csv
import io
import re
import zipfile
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import hash_password
from app.config import settings
from app.storage_service import storage
from app.database import SessionLocal
from app.main import app
from app.models import Company, CompanyRequest, Document, Employee, IntegrationBatch, Notification, RequestAttachment, RequestWorkflow, SalaryHistory, Studio, User
from app.backup_service import build_studio_export
from app.main import UPLOAD_DIR


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

        # Request attachments retain a PostgreSQL copy in local-storage mode.
        attachment_content = b"%PDF-1.7\nrequest attachment durability test\n"
        uploaded_attachment = client.post(
            f"/app/requests/{request_id}/attachments",
            data={"csrf_token": csrf},
            files={"file": ("workflow-attachment.pdf", attachment_content, "application/pdf")},
            follow_redirects=False,
        )
        assert uploaded_attachment.status_code == 303
        with SessionLocal() as db:
            attachment = db.scalar(
                select(RequestAttachment).where(RequestAttachment.request_id == request_id)
                .order_by(RequestAttachment.id.desc())
            )
            assert attachment is not None
            attachment_id = attachment.id
            stored_key = attachment.stored_name
            if settings.storage_backend == "local":
                assert bytes(attachment.content_bytes) == attachment_content
        if settings.storage_backend == "local":
            storage.delete(stored_key)
        downloaded_attachment = client.get(
            f"/app/requests/{request_id}/attachments/{attachment_id}/download"
        )
        assert downloaded_attachment.status_code == 200
        assert downloaded_attachment.content == attachment_content

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
                "notes": "",
            },
            follow_redirects=False,
        )
        assert rejected.status_code == 409
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

    with SessionLocal() as db:
        employee = db.get(Employee, employee_id)
        assert employee is not None
        assert employee.base_salary == original_salary
        assert employee.notes == "Prueba de actualización no salarial."


def test_general_document_upload_survives_loss_of_local_file_copy():
    email, password, company_id, employee_id = ensure_admin()
    content = b"%PDF-1.7\ngeneral document durability test\n"
    title = "Respaldo de documento automatizado"
    with TestClient(app) as client:
        csrf = login(client, email, password)
        uploaded = client.post(
            "/app/documents",
            data={
                "csrf_token": csrf,
                "company_id": str(company_id),
                "employee_id": str(employee_id),
                "title": title,
                "category": "Prueba",
            },
            files={"file": ("document-durability-test.pdf", content, "application/pdf")},
            follow_redirects=False,
        )
        assert uploaded.status_code == 303
        with SessionLocal() as db:
            document = db.scalar(
                select(Document).where(Document.company_id == company_id, Document.title == title)
                .order_by(Document.id.desc())
            )
            assert document is not None
            document_id = document.id
            stored_key = document.stored_name
            if settings.storage_backend == "local":
                assert bytes(document.content_bytes) == content
        if settings.storage_backend == "local":
            storage.delete(stored_key)
        downloaded = client.get(f"/app/documents/{document_id}/download")
        assert downloaded.status_code == 200
        assert downloaded.content == content



def test_integration_batch_and_receipt_survive_local_file_loss_and_backup():
    from app.models import Studio

    email, password, company_id, _ = ensure_admin()
    workbook_content = b"synthetic-xlsx-content-for-persistence-test"
    receipt_content = b"%PDF-1.7\nsynthetic receipt persistence test\n"
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        assert user is not None and user.studio_id is not None
        batch = IntegrationBatch(
            studio_id=user.studio_id,
            company_id=company_id,
            authority="REOP",
            batch_type="Prueba de persistencia",
            period="2026",
            status="Generado",
            file_name="test-batch.xlsx",
            storage_key=f"integrations/{company_id}/test-batch.xlsx",
            file_bytes=workbook_content,
            file_sha256="a" * 64,
            item_count=1,
            created_by=email,
        )
        db.add(batch)
        db.commit()
        batch_id = batch.id
        studio_id = user.studio_id

    with TestClient(app) as client:
        csrf = login(client, email, password)
        posted = client.post(
            f"/app/compliance/batches/{batch_id}/receipt",
            data={"csrf_token": csrf, "status": "Presentado", "external_reference": "REG-TEST-001"},
            files={"receipt": ("comprobante-test.pdf", receipt_content, "application/pdf")},
            follow_redirects=False,
        )
        assert posted.status_code == 303

    with SessionLocal() as db:
        batch = db.get(IntegrationBatch, batch_id)
        assert batch is not None
        receipt_key = batch.receipt_storage_key
        assert receipt_key
        assert batch.receipt_file_name == "comprobante-test.pdf"
        if settings.storage_backend == "local":
            assert bytes(batch.receipt_bytes) == receipt_content
            storage.delete(receipt_key)
        studio = db.get(Studio, studio_id)
        assert studio is not None
        backup_content = build_studio_export(db, studio, UPLOAD_DIR)

    with TestClient(app) as client:
        login(client, email, password)
        workbook = client.get(f"/app/compliance/batches/{batch_id}/download")
        receipt = client.get(f"/app/compliance/batches/{batch_id}/receipt")
        assert workbook.status_code == 200
        assert workbook.content == workbook_content
        assert receipt.status_code == 200
        assert receipt.content == receipt_content
        assert receipt.headers["content-type"].startswith("application/pdf")

    with zipfile.ZipFile(io.BytesIO(backup_content)) as archive:
        names = archive.namelist()
        batch_file = next(n for n in names if n.endswith(f"/lotes/{batch_id}_test-batch.xlsx"))
        receipt_file = next(n for n in names if n.endswith(f"/comprobantes/{batch_id}_comprobante-test.pdf"))
        assert archive.read(batch_file) == workbook_content
        assert archive.read(receipt_file) == receipt_content



def test_studio_backup_reads_configured_storage_when_binary_database_copy_is_missing(monkeypatch):
    from app.models import Studio
    email, _, company_id, employee_id = ensure_admin()
    object_key = f"documents/backup-provider-test-{company_id}.pdf"
    payload = b"%PDF-1.7\nstorage provider backup fallback\n"
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        assert user is not None
        document = Document(
            company_id=company_id,
            employee_id=employee_id,
            category="Prueba",
            title="Documento guardado en proveedor",
            stored_name=object_key,
            original_name="provider-document.pdf",
            content_type="application/pdf",
            content_bytes=None,
            uploaded_by=email,
        )
        db.add(document)
        db.commit()
        studio = db.get(Studio, user.studio_id)
        assert studio is not None
        monkeypatch.setattr(storage, "exists", lambda key: key == object_key)
        monkeypatch.setattr(storage, "get", lambda key: payload if key == object_key else b"")
        archive_content = build_studio_export(db, studio, UPLOAD_DIR)

    with zipfile.ZipFile(io.BytesIO(archive_content)) as archive:
        saved = next(
            name for name in archive.namelist()
            if name.endswith("_provider-document.pdf")
        )
        assert archive.read(saved) == payload



def test_employee_bulk_import_cannot_bypass_salary_approval():
    from app.main import IMPORT_DIR
    email, password, company_id, employee_id = ensure_admin()
    with SessionLocal() as db:
        employee = db.get(Employee, employee_id)
        assert employee is not None
        original_salary = employee.base_salary
        original_document = employee.document_number
        original_admission = employee.admission_date
        original_name = employee.full_name
        salary_history_before = db.scalar(
            select(__import__("sqlalchemy").func.count(SalaryHistory.id)).where(
                SalaryHistory.employee_id == employee_id
            )
        ) or 0

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

        confirm = client.post(
            f"{preview_url}/confirm",
            data={"csrf_token": csrf, "duplicate_action": "update"},
            follow_redirects=False,
        )
        assert confirm.status_code == 303
        assert "salary_changes=1" in confirm.headers["location"]
        result_page = client.get(confirm.headers["location"])
        assert result_page.status_code == 200
        assert "1 cambios salariales no se aplicaron" in result_page.text or "1 cambio salarial no se aplicaron" in result_page.text

    with SessionLocal() as db:
        employee = db.get(Employee, employee_id)
        assert employee is not None
        assert employee.base_salary == original_salary
        assert employee.position == "Cargo importado de prueba"
        salary_history_after = db.scalar(
            select(__import__("sqlalchemy").func.count(SalaryHistory.id)).where(
                SalaryHistory.employee_id == employee_id
            )
        ) or 0
        assert salary_history_after == salary_history_before
