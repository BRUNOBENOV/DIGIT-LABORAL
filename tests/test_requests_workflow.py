from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import hash_password
from app.database import SessionLocal
from app.main import app
from app.models import Company, CompanyRequest, Employee, RequestWorkflow, Studio, User


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
        employee = db.scalar(select(Employee).where(Employee.company_id == company.id).order_by(Employee.id))
        assert company is not None and employee is not None
        return email, password, company.id, employee.id


def test_salary_request_can_be_approved_and_applied():
    email, password, company_id, employee_id = ensure_admin()
    with SessionLocal() as db:
        employee = db.get(Employee, employee_id)
        original_salary = employee.base_salary
    with TestClient(app) as client:
        login = client.post("/login", data={"email": email, "password": password}, follow_redirects=False)
        assert login.status_code == 303
        response = client.post(
            "/app/requests",
            data={
                "company_id": str(company_id),
                "request_type": "Cambio salarial",
                "subject": "Ajuste de prueba",
                "detail": "Actualizar salario para comprobar el flujo.",
                "priority": "Normal",
                "employee_id": str(employee_id),
                "effective_date": "2026-08-01",
                "amount": str(original_salary + 100000),
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        request_id = int(response.headers["location"].split("/")[-1].split("?")[0])
        review = client.post(f"/app/requests/{request_id}/review", data={"status": "Aprobada", "response": "Aprobado", "assigned_to": "Workflow Admin"}, follow_redirects=False)
        assert review.status_code == 303
        apply_response = client.post(f"/app/requests/{request_id}/apply", follow_redirects=False)
        assert apply_response.status_code == 303
    with SessionLocal() as db:
        item = db.get(CompanyRequest, request_id)
        workflow = db.scalar(select(RequestWorkflow).where(RequestWorkflow.request_id == request_id))
        employee = db.get(Employee, employee_id)
        assert item.status == "Aplicada"
        assert workflow is not None and workflow.applied is True
        assert employee.base_salary == original_salary + 100000
