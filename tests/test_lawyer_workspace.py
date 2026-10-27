from __future__ import annotations

import re
import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import hash_password
from app.database import SessionLocal
from app.models import Company, CompanyRequest, Employee, RequestWorkflow, Studio, User, UserSecurity
from app.runtime import app


def _new_user(role: str, company_id: int | None = None) -> tuple[str, str, int, int]:
    email = f"{role}-{uuid.uuid4().hex[:12]}@persona.test"
    password = "Persona-Check-2026!"
    with SessionLocal() as db:
        studio = db.scalar(select(Studio).order_by(Studio.id))
        assert studio is not None, "Startup must seed or provision a studio in the test database"
        company = db.scalar(
            select(Company)
            .where(Company.studio_id == studio.id)
            .order_by(Company.id)
        )
        assert company is not None, "A test company is required"
        selected_company_id = company_id or company.id
        user = User(
            studio_id=studio.id,
            company_id=selected_company_id if role == "empresa" else None,
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
        return email, password, user.id, selected_company_id


def _login(client: TestClient, email: str, password: str) -> str:
    page = client.get("/login")
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert page.status_code == 200 and match
    response = client.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": match.group(1)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    home = client.get("/app")
    token = re.search(r'name="csrf_token" value="([^"]+)"', home.text)
    assert home.status_code == 200 and token
    return token.group(1)


def test_lawyer_workspace_filters_assigned_cases_and_enforces_role_boundaries() -> None:
    with TestClient(app) as client:
        email, password, lawyer_id, company_id = _new_user("abogado")
        _, _, other_lawyer_id, _ = _new_user("abogado")
        csrf = _login(client, email, password)

        with SessionLocal() as db:
            company = db.get(Company, company_id)
            assert company is not None
            subject = f"QA-LEGAL-{uuid.uuid4().hex[:10]}"
            request_item = CompanyRequest(
                company_id=company.id,
                request_type="Otra consulta",
                subject=subject,
                detail="Caso de prueba para validar la bandeja del abogado.",
                requested_by_user_id=lawyer_id,
                priority="Alta",
                status="Pendiente",
            )
            other_subject = f"QA-LEGAL-OTHER-{uuid.uuid4().hex[:8]}"
            other_item = CompanyRequest(
                company_id=company.id,
                request_type="Otra consulta",
                subject=other_subject,
                detail="Caso asignado a otro profesional.",
                requested_by_user_id=lawyer_id,
                priority="Normal",
                status="Pendiente",
            )
            unassigned_subject = f"QA-LEGAL-UNASSIGNED-{uuid.uuid4().hex[:8]}"
            unassigned_item = CompanyRequest(
                company_id=company.id,
                request_type="Otra consulta",
                subject=unassigned_subject,
                detail="Caso sin profesional asignado.",
                requested_by_user_id=lawyer_id,
                priority="Normal",
                status="Pendiente",
            )
            db.add_all([request_item, other_item, unassigned_item])
            db.flush()
            db.add_all([
                RequestWorkflow(
                    request_id=request_item.id,
                    assigned_user_id=lawyer_id,
                    due_date=date.today() - timedelta(days=1),
                ),
                RequestWorkflow(
                    request_id=other_item.id,
                    assigned_user_id=other_lawyer_id,
                    due_date=date.today() + timedelta(days=3),
                ),
                RequestWorkflow(
                    request_id=unassigned_item.id,
                    assigned_user_id=None,
                    due_date=date.today() + timedelta(days=2),
                ),
            ])
            db.commit()
            request_id = request_item.id
            other_request_id = other_item.id
            unassigned_request_id = unassigned_item.id

        home = client.get("/app")
        assert home.status_code == 200
        assert "Tu trabajo jurídico-laboral, ordenado" in home.text
        assert "Mis trámites asignados" in home.text
        assert 'href="/app/payrolls"' not in home.text
        assert 'href="/app/calculations?tipo=salary"' not in home.text

        guide = client.get("/app/guia")
        assert guide.status_code == 200
        assert "Solicitudes asignadas" in guide.text
        assert 'href="/app/requests?assigned_filter=mine"' in guide.text

        queue = client.get(
            "/app/requests",
            params={
                "assigned_filter": "mine",
                "overdue_only": "1",
                "status_filter": "Pendiente",
                "request_type": "Otra consulta",
            },
        )
        assert queue.status_code == 200
        assert subject in queue.text
        assert other_subject not in queue.text
        assert unassigned_subject not in queue.text
        assert "Solo vencidas" in queue.text
        assert "Mis asignaciones" in queue.text
        assert "+ Nueva solicitud" not in queue.text
        assert '<form method="post" action="/app/requests"' not in queue.text
        assert client.post(
            "/app/requests",
            data={
                "csrf_token": csrf,
                "company_id": str(company_id),
                "request_type": "Otra consulta",
                "subject": "Intento de crear trámite",
                "detail": "El abogado debe trabajar sobre asignaciones existentes.",
            },
            follow_redirects=False,
        ).status_code == 403

        # Clearing the query-string filter must not expose another lawyer's or
        # unassigned request, and guessed detail URLs must return the same 404.
        unfiltered = client.get("/app/requests", params={"assigned_filter": ""})
        assert unfiltered.status_code == 200
        assert subject in unfiltered.text
        assert other_subject not in unfiltered.text
        assert unassigned_subject not in unfiltered.text
        assert client.get(f"/app/requests/{other_request_id}").status_code == 404
        assert client.get(f"/app/requests/{unassigned_request_id}").status_code == 404
        assert client.post(
            f"/app/requests/{unassigned_request_id}/status",
            data={"csrf_token": csrf, "status": "En revisión"},
            follow_redirects=False,
        ).status_code == 404

        filtered_out = client.get(
            "/app/requests",
            params={"assigned_filter": "mine", "status_filter": "Resuelta"},
        )
        assert filtered_out.status_code == 200
        assert subject not in filtered_out.text
        assert "No hay solicitudes para mostrar" in filtered_out.text

        # A lawyer may update their assigned case, but cannot change its assignee.
        updated = client.post(
            f"/app/requests/{request_id}/status",
            data={
                "csrf_token": csrf,
                "status": "En revisión",
                "response": "Revisión jurídica iniciada",
                "assigned_user_id": str(other_lawyer_id),
                "due_date": date.today().isoformat(),
                "internal_notes": "Nota interna de prueba",
            },
            follow_redirects=False,
        )
        assert updated.status_code == 303
        with SessionLocal() as db:
            workflow = db.scalar(select(RequestWorkflow).where(RequestWorkflow.request_id == request_id))
            saved_request = db.get(CompanyRequest, request_id)
            assert workflow is not None and workflow.assigned_user_id == lawyer_id
            assert saved_request is not None and saved_request.status == "En revisión"

        # Legal users can consult the case and draft documents, but cannot administer
        # users, create payrolls, or approve/reject labour requests.
        assert client.get("/app/requests/" + str(request_id)).status_code == 200
        company_page = client.get("/app/companies/" + str(company_id))
        assert company_page.status_code == 200
        assert "Editar datos" not in company_page.text
        assert "Agregar sucursal" not in company_page.text
        assert 'href="/app/payrolls?company_id=' not in company_page.text
        assert client.get("/app/companies").status_code == 200
        assert client.get("/app/employees").status_code == 200
        with SessionLocal() as db:
            employee_id = db.scalar(
                select(Employee.id)
                .where(Employee.company_id == company_id)
                .order_by(Employee.id)
            )
            assert employee_id is not None
        employee_page = client.get("/app/employees/" + str(employee_id))
        assert employee_page.status_code == 200
        assert "Editar ficha" not in employee_page.text
        assert "Registrar evento" not in employee_page.text
        assert 'href="/app/calculations?company_id=' not in employee_page.text
        assert client.get("/app/documents").status_code == 200
        assert client.get("/app/certificates").status_code == 200
        assert 'href="/app/ai' not in client.get("/app/certificates").text
        assert "Revisar con IA" not in client.get("/app/certificates").text
        assert client.get("/app/labor-code").status_code == 200

        calendar = client.get("/app/calendar")
        assert calendar.status_code == 200
        assert "+ Nuevo vencimiento" not in calendar.text
        assert not re.search(r'action="/app/calendar/\d+/status"', calendar.text)

        reports = client.get("/app/reports")
        assert reports.status_code == 200
        assert "Informes del expediente" in reports.text
        assert "Analizar con IA" not in reports.text
        assert "Nuevo cálculo" not in reports.text
        assert "Administrar" not in reports.text

        compliance = client.get("/app/compliance")
        assert compliance.status_code == 200
        assert 'action="/app/compliance/events"' not in compliance.text
        assert 'action="/app/compliance/company-profile"' not in compliance.text

        assert client.get("/app/users").status_code == 403
        assert client.get("/app/payrolls").status_code == 403
        # Internal finance calculators and previous AI consultations must not be
        # available to a lawyer merely by typing their URL.
        assert client.get("/app/calculations").status_code == 403
        assert client.get("/app/ai").status_code == 403
        assert client.get("/app/parameters").status_code == 403
        assert client.post(
            "/app/payrolls",
            data={"csrf_token": csrf, "company_id": str(company_id), "period": "2026-10"},
            follow_redirects=False,
        ).status_code == 403
        assert client.post(
            "/app/requests/" + str(request_id) + "/review",
            data={
                "csrf_token": csrf,
                "status": "Aprobada",
                "response": "Prueba",
                "assigned_to": "",
                "assigned_user_id": "",
            },
            follow_redirects=False,
        ).status_code == 403
        # Invalid document types fail validation (400), not authorization (403):
        # this confirms the lawyer role can reach the document-drafting handler.
        with SessionLocal() as db:
            employee_id = db.scalar(
                select(Employee.id)
                .where(Employee.company_id == company_id)
                .order_by(Employee.id)
            )
            assert employee_id is not None
        draft_attempt = client.post(
            "/app/certificates",
            data={
                "csrf_token": csrf,
                "company_id": str(company_id),
                "employee_id": str(employee_id),
                "document_type": "__invalid_for_test__",
            },
            follow_redirects=False,
        )
        assert draft_attempt.status_code == 400


def test_employer_sees_request_centric_dashboard_without_staff_calculation_tools() -> None:
    with TestClient(app) as client:
        with SessionLocal() as db:
            company = db.scalar(select(Company).order_by(Company.id))
            assert company is not None
            company_id = company.id
        email, password, _, _ = _new_user("empresa", company_id=company_id)
        _login(client, email, password)

        home = client.get("/app")
        assert home.status_code == 200
        assert "Tu empresa, sin vueltas" in home.text
        assert "+ Nueva solicitud" in home.text
        assert "<h3>Cálculo</h3>" not in home.text
        assert 'href="/app/payrolls"' not in home.text

        requests = client.get("/app/requests")
        assert requests.status_code == 200
        assert 'name="status_filter"' not in requests.text
        assert 'name="assigned_filter"' not in requests.text

        calendar = client.get("/app/calendar")
        assert calendar.status_code == 200
        assert "Agenda laboral" in home.text
        assert "+ Nuevo vencimiento" not in calendar.text
        assert not re.search(r'action="/app/calendar/\d+/status"', calendar.text)

        certificates = client.get("/app/certificates")
        assert certificates.status_code == 200
        assert "Para solicitar uno nuevo, utilizá Trámites." in certificates.text
        # The employer has its own public simulators; internal saved calculations,
        # staff AI conversations, and administrative parameters are not exposed.
        assert client.get("/app/calculations").status_code == 403
        assert client.get("/app/ai").status_code == 403
        assert client.get("/app/parameters").status_code == 403
        payroll_list = client.get("/app/payrolls")
        assert payroll_list.status_code == 200
        assert "+ Nueva liquidación" not in payroll_list.text
        assert '<form method="post" action="/app/payrolls"' not in payroll_list.text



def test_unassigned_lawyer_cannot_browse_company_or_unassigned_request() -> None:
    with TestClient(app) as client:
        email, password, lawyer_id, company_id = _new_user("abogado")
        with SessionLocal() as db:
            company = db.get(Company, company_id)
            assert company is not None
            item = CompanyRequest(
                company_id=company_id,
                request_type="Otra consulta",
                subject=f"QA-UNASSIGNED-{uuid.uuid4().hex[:10]}",
                detail="Trámite no asignado a este abogado.",
                requested_by_user_id=lawyer_id,
                priority="Normal",
                status="Pendiente",
            )
            db.add(item)
            db.commit()
            request_id = item.id

        _login(client, email, password)
        companies = client.get("/app/companies")
        assert companies.status_code == 200
        assert "Aún no tenés empresas asignadas" in companies.text
        assert client.get(f"/app/companies/{company_id}").status_code == 404
        assert client.get(f"/app/requests/{request_id}").status_code == 404
