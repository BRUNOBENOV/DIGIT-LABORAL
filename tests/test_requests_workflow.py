from __future__ import annotations

import re

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import hash_password
from app.database import SessionLocal
from app.main import app
from app.models import Company, CompanyRequest, Employee, Notification, RequestWorkflow, Studio, User


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


def test_notification_reads_are_scoped_to_the_logged_in_user():
    email, password, _, _ = ensure_admin()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        note = Notification(
            studio_id=user.studio_id, recipient_user_id=user.id, event_type="prueba",
            title="Aviso de prueba", body="Notificación privada.", target_url="/app/requests",
        )
        db.add(note)
        db.commit()
        notification_id = note.id
    with TestClient(app) as client:
        login(client, email, password)
        page = client.get("/app/notifications")
        assert page.status_code == 200 and "Aviso de prueba" in page.text
        csrf = token_from_page(client, "/app/notifications")
        marked = client.post(
            f"/app/notifications/{notification_id}/read", data={"csrf_token": csrf}, follow_redirects=False,
        )
        assert marked.status_code == 303
    with SessionLocal() as db:
        note = db.get(Notification, notification_id)
        assert note.read_at is not None
