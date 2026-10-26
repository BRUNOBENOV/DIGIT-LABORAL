from __future__ import annotations

import re
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import hash_password
from app.database import SessionLocal
from app.models import Company, CompanyRequest, Studio, User, UserSecurity
from app.runtime import app


def _new_user(role: str) -> tuple[str, str, int, int]:
    email = f"{role}-{uuid.uuid4().hex[:12]}@persona.test"
    password = "Persona-Check-2026!"
    with SessionLocal() as db:
        studio = db.scalar(select(Studio).order_by(Studio.id))
        assert studio is not None
        company = db.scalar(select(Company).where(Company.studio_id == studio.id).order_by(Company.id))
        assert company is not None
        user = User(
            studio_id=studio.id,
            company_id=None,
            full_name=f"Persona {role}",
            email=email,
            password_hash=hash_password(password),
            role=role,
            active=True,
            must_change_password=False,
        )
        db.add(user)
        db.flush()
        db.add(UserSecurity(user_id=user.id))
        db.commit()
        return email, password, user.id, company.id


def _login(client: TestClient, email: str, password: str) -> str:
    page = client.get("/login")
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert page.status_code == 200 and match
    login = client.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": match.group(1)},
        follow_redirects=False,
    )
    assert login.status_code == 303
    home = client.get("/app")
    match = re.search(r'name="csrf_token" value="([^"]+)"', home.text)
    assert home.status_code == 200 and match
    return match.group(1)


def test_accountant_workbench_keeps_operational_tools_and_request_approval() -> None:
    with TestClient(app) as client:
        email, password, accountant_id, company_id = _new_user("contador")
        csrf = _login(client, email, password)

        home = client.get("/app")
        assert home.status_code == 200
        assert "Mantenimientos" in home.text
        assert "Cálculo" in home.text
        assert 'href="/app/calculations?tipo=salary"' in home.text
        assert 'href="/app/payrolls"' in home.text

        for path in (
            "/app/payrolls",
            "/app/calculations",
            "/app/compliance",
            "/app/reports",
            "/app/certificates",
        ):
            response = client.get(path)
            assert response.status_code == 200, path

        assert "Revisar con IA" in client.get("/app/certificates").text
        queue = client.get("/app/requests")
        assert queue.status_code == 200
        assert 'name="status_filter"' in queue.text
        assert 'name="assigned_filter"' in queue.text

        with SessionLocal() as db:
            item = CompanyRequest(
                company_id=company_id,
                request_type="Otra consulta",
                subject=f"QA-ACCOUNTANT-{uuid.uuid4().hex[:10]}",
                detail="Solicitud de prueba para la revisión del contador.",
                requested_by_user_id=accountant_id,
                priority="Normal",
                status="Pendiente",
            )
            db.add(item)
            db.commit()
            request_id = item.id

        approved = client.post(
            f"/app/requests/{request_id}/review",
            data={
                "csrf_token": csrf,
                "status": "Aprobada",
                "response": "Revisión contable finalizada.",
                "assigned_to": "",
                "assigned_user_id": "",
            },
            follow_redirects=False,
        )
        assert approved.status_code == 303
        with SessionLocal() as db:
            item = db.get(CompanyRequest, request_id)
            assert item is not None and item.status == "Aprobada"
