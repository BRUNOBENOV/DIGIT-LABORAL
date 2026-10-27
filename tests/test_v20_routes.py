from __future__ import annotations

import re
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from app.config import settings

from app.main import app


def _login(client: TestClient) -> str:
    page = client.get("/login")
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert page.status_code == 200 and match
    response = client.post(
        "/login",
        data={"email": "admin@digitlaboral.com.py", "password": settings.demo_admin_password, "csrf_token": match.group(1)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    dashboard = client.get("/app")
    dashboard_token = re.search(r'name="csrf_token" value="([^"]+)"', dashboard.text)
    assert dashboard.status_code == 200 and dashboard_token
    return dashboard_token.group(1)


def test_critical_authenticated_pages_render_html():
    paths = (
        "/app",
        "/app/companies",
        "/app/employees",
        "/app/requests",
        "/app/payrolls",
        "/app/vacations",
        "/app/aguinaldo",
        "/app/documents",
        "/app/certificates",
        "/app/reports",
        "/app/calendar",
        "/app/compliance",
        "/app/labor-code",
        "/app/ai",
        "/app/parameters",
        "/app/users",
        "/app/audit",
        "/app/security",
    )
    with TestClient(app) as client:
        _login(client)
        for path in paths:
            response = client.get(path)
            assert response.status_code == 200, path
            assert "text/html" in response.headers.get("content-type", ""), path
            assert "Digit Laboral" in response.text, path
            assert not response.text.lstrip().startswith('{"detail"'), path


def test_post_forms_include_csrf_tokens():
    with TestClient(app) as client:
        _login(client)
        for path in ("/app/companies", "/app/employees", "/app/users", "/app/compliance", "/app/security"):
            response = client.get(path)
            soup = BeautifulSoup(response.text, "html.parser")
            post_forms = [form for form in soup.find_all("form") if (form.get("method") or "get").lower() == "post"]
            assert post_forms, path
            for form in post_forms:
                token = form.find("input", attrs={"name": "csrf_token"})
                assert token is not None, f"{path}: formulario POST sin CSRF"
                assert token.get("value"), f"{path}: token CSRF vacío"


def test_friendly_html_error_page_replaces_raw_json():
    with TestClient(app) as client:
        _login(client)
        response = client.get("/app/companies/999999999")
        assert response.status_code == 404
        assert "No se pudo completar la operación" in response.text
        assert "application/json" not in response.headers.get("content-type", "")
        assert response.headers.get("x-request-id")


def test_branch_compliance_profile_can_be_saved():
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models import Branch, BranchComplianceProfile, Company

    with SessionLocal() as db:
        company = db.scalar(select(Company).order_by(Company.id))
        assert company is not None
        branch = db.scalar(select(Branch).where(Branch.company_id == company.id).order_by(Branch.id))
        assert branch is not None
        company_id = company.id
        branch_id = branch.id

    with TestClient(app) as client:
        csrf = _login(client)
        response = client.post(
            "/app/compliance/branch-profile",
            data={
                "csrf_token": csrf,
                "company_id": str(company_id),
                "branch_id": str(branch_id),
                "ips_employer_number": "IPS-TEST-001",
                "mtess_employer_number": "MTESS-TEST-001",
                "department": "Alto Paraná",
                "district": "Ciudad del Este",
                "locality": "Centro",
                "economic_activity": "Servicios contables",
                "activity_code": "TEST",
                "establishment_type": "Sucursal",
                "rei_status": "Verificado",
                "reop_status": "Verificado",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"].endswith("saved=branch")

    with SessionLocal() as db:
        profile = db.scalar(select(BranchComplianceProfile).where(BranchComplianceProfile.branch_id == branch_id))
        assert profile is not None
        assert profile.ips_employer_number == "IPS-TEST-001"
        assert profile.mtess_employer_number == "MTESS-TEST-001"



def test_company_logo_presentation_preferences_are_saved_and_bounded():
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models import Company, CompanyBranding

    with SessionLocal() as db:
        company = db.scalar(select(Company).order_by(Company.id))
        assert company is not None
        company_id = company.id

    with TestClient(app) as client:
        csrf = _login(client)
        saved = client.post(
            f"/app/companies/{company_id}/branding",
            data={
                "csrf_token": csrf,
                "logo_fit": "cover",
                "logo_scale": "120",
                "logo_alignment": "right",
                "logo_background": "navy",
                "primary_color": "#112233",
                "secondary_color": "#445566",
                "document_footer": "Pie personalizado de prueba",
                "signature_name": "Representante de prueba",
                "signature_title": "Representante legal",
                "document_prefix": "DLTEST",
                "show_ruc": "on",
                "show_contact": "on",
            },
            follow_redirects=False,
        )
        assert saved.status_code == 303

    with SessionLocal() as db:
        branding = db.scalar(select(CompanyBranding).where(CompanyBranding.company_id == company_id))
        assert branding is not None
        assert branding.logo_fit == "cover"
        assert branding.logo_scale == 120
        assert branding.logo_alignment == "right"
        assert branding.logo_background == "navy"

    with TestClient(app) as client:
        csrf = _login(client)
        invalid = client.post(
            f"/app/companies/{company_id}/branding",
            data={
                "csrf_token": csrf,
                "logo_fit": "invalid",
                "logo_scale": "999",
                "logo_alignment": "outside",
                "logo_background": "purple",
            },
            follow_redirects=False,
        )
        assert invalid.status_code == 303

    with SessionLocal() as db:
        branding = db.scalar(select(CompanyBranding).where(CompanyBranding.company_id == company_id))
        assert branding is not None
        assert branding.logo_fit == "contain"
        assert branding.logo_scale == 140
        assert branding.logo_alignment == "center"
        assert branding.logo_background == "white"



def test_saved_calculators_use_commercial_half_up_rounding():
    import json
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models import CalculationRecord, Company

    with SessionLocal() as db:
        company = db.scalar(select(Company).order_by(Company.id))
        assert company is not None
        company_id = company.id

    cases = [
        {
            "calculation_type": "hours",
            "reference_period": "round-hours",
            "salary": "1",
            "monthly_hours": "2",
            "hours_quantity": "1",
            "multiplier": "1",
            "expected_amount": 1,
            "expected_result": {"hour_value": 1, "total": 1},
        },
        {
            "calculation_type": "aguinaldo",
            "reference_period": "round-aguinaldo",
            "total_remunerations": "6",
            "expected_amount": 1,
            "expected_result": {
                "aguinaldo": 1,
                "total_remunerations": 6,
                "legal_basis": "Código del Trabajo, arts. 243 y 244",
            },
        },
    ]

    with TestClient(app) as client:
        csrf = _login(client)
        for case in cases:
            data = {
                "csrf_token": csrf,
                "calculation_type": case["calculation_type"],
                "company_id": str(company_id),
                "employee_id": "",
                "reference_period": case["reference_period"],
                "salary": case.get("salary", ""),
                "monthly_hours": case.get("monthly_hours", ""),
                "hours_quantity": case.get("hours_quantity", ""),
                "multiplier": case.get("multiplier", ""),
                "total_remunerations": case.get("total_remunerations", ""),
                "gross": "",
                "other_income": "",
                "other_discount": "",
                "ips_base": "",
            }
            response = client.post("/app/calculations", data=data, follow_redirects=False)
            assert response.status_code == 303, response.text

            with SessionLocal() as db:
                item = db.scalar(
                    select(CalculationRecord)
                    .where(
                        CalculationRecord.company_id == company_id,
                        CalculationRecord.calculation_type == case["calculation_type"],
                        CalculationRecord.reference_period == case["reference_period"],
                    )
                    .order_by(CalculationRecord.id.desc())
                )
                assert item is not None
                assert item.amount == case["expected_amount"]
                assert json.loads(item.result_json) == case["expected_result"]



def test_closed_payroll_cannot_be_reopened_or_reset_by_reclosing():
    from datetime import datetime
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models import Company, Payroll

    with SessionLocal() as db:
        company = db.scalar(select(Company).order_by(Company.id))
        assert company is not None
        company_id = company.id
        used_periods = set(db.scalars(select(Payroll.period).where(Payroll.company_id == company_id)))
        period = next(
            f"{year}-{month:02d}"
            for year in range(2090, 2100)
            for month in range(1, 13)
            if f"{year}-{month:02d}" not in used_periods
        )
        closed_at = datetime(2026, 10, 20, 12, 30, 0)
        payroll = Payroll(
            company_id=company_id,
            period=period,
            status="Cerrada",
            created_by="qa",
            reviewed_by="reviewer-qa",
            closed_at=closed_at,
        )
        db.add(payroll)
        db.commit()
        payroll_id = payroll.id

    with TestClient(app) as client:
        csrf = _login(client)
        page = client.get(f"/app/payrolls/{payroll_id}")
        assert page.status_code == 200
        assert "no se puede reabrir desde este formulario" in page.text.lower()
        assert 'id="payroll-status"' not in page.text

        reopen = client.post(
            f"/app/payrolls/{payroll_id}/status",
            data={"csrf_token": csrf, "status": "Borrador"},
            follow_redirects=False,
        )
        assert reopen.status_code == 409

        close_again = client.post(
            f"/app/payrolls/{payroll_id}/status",
            data={"csrf_token": csrf, "status": "Cerrada"},
            follow_redirects=False,
        )
        assert close_again.status_code == 303

    with SessionLocal() as db:
        payroll = db.get(Payroll, payroll_id)
        assert payroll is not None
        assert payroll.status == "Cerrada"
        assert payroll.closed_at is not None
        assert payroll.closed_at.year == 2026
        assert payroll.closed_at.month == 10
        assert payroll.reviewed_by == "reviewer-qa"


def test_aguinaldo_rejects_invalid_year_and_unrepresentable_amounts():
    from datetime import date
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models import Employee

    with SessionLocal() as db:
        employee = db.scalar(select(Employee).where(Employee.status == "Activo").order_by(Employee.id))
        assert employee is not None
        employee_id = employee.id

    invalid_cases = [
        {"year": "2200", "total_remunerations": "1000"},
        {"year": str(date.today().year), "total_remunerations": "-1"},
        {"year": str(date.today().year), "total_remunerations": "2147483648"},
    ]
    with TestClient(app) as client:
        csrf = _login(client)
        for case in invalid_cases:
            response = client.post(
                "/app/aguinaldo",
                data={"csrf_token": csrf, "employee_id": str(employee_id), **case},
                follow_redirects=False,
            )
            assert response.status_code == 400, (case, response.status_code, response.text[:300])


def test_vacation_rejects_invalid_status_counts_and_overlarge_days():
    from datetime import date
    from sqlalchemy import select, func
    from app.database import SessionLocal
    from app.models import Employee, Vacation

    with SessionLocal() as db:
        employee = db.scalar(select(Employee).where(Employee.status == "Activo").order_by(Employee.id))
        assert employee is not None
        employee_id = employee.id

    year = date.today().year
    cases = [
        {"entitled_days": "366", "used_days": "0", "status": "Pendiente"},
        {"entitled_days": "", "used_days": "0", "status": "Estado inventado"},
        {"entitled_days": "abc", "used_days": "0", "status": "Pendiente"},
        {"entitled_days": "12", "used_days": "366", "status": "Pendiente"},
    ]
    with SessionLocal() as db:
        before = db.scalar(select(func.count(Vacation.id)).where(
            Vacation.employee_id == employee_id, Vacation.period_year == year
        )) or 0

    with TestClient(app) as client:
        csrf = _login(client)
        for case in cases:
            response = client.post(
                "/app/vacations",
                data={
                    "csrf_token": csrf,
                    "employee_id": str(employee_id),
                    "period_year": str(year),
                    **case,
                },
                follow_redirects=False,
            )
            assert response.status_code == 303, (case, response.status_code, response.text[:300])
            error_page = client.get(response.headers["location"])
            assert error_page.status_code == 200
            assert "vacationModal" in error_page.text

    with SessionLocal() as db:
        after = db.scalar(select(func.count(Vacation.id)).where(
            Vacation.employee_id == employee_id, Vacation.period_year == year
        )) or 0
        assert after == before



def test_vacation_rejects_malformed_partial_and_inconsistent_dates_and_statuses():
    from datetime import date, timedelta
    from sqlalchemy import select, func
    from app.database import SessionLocal
    from app.models import Employee, Vacation, ComplianceEvent

    today = date.today()
    year = today.year
    past_start = (today - timedelta(days=3)).isoformat()
    past_end = (today - timedelta(days=1)).isoformat()
    future_start = (today + timedelta(days=1)).isoformat()
    future_end = (today + timedelta(days=3)).isoformat()

    with SessionLocal() as db:
        employee = db.scalar(select(Employee).where(Employee.status == "Activo").order_by(Employee.id))
        assert employee is not None
        employee_id = employee.id
        admission_date = employee.admission_date
        before = db.scalar(select(func.count(Vacation.id)).where(
            Vacation.employee_id == employee_id, Vacation.period_year == year
        )) or 0

    invalid_cases = [
        # A vacation cannot start before the worker's recorded admission date.
        {"status": "Pendiente", "used_days": "0",
         "start_date": (admission_date - timedelta(days=1)).isoformat(),
         "end_date": (admission_date - timedelta(days=1)).isoformat()},
        # Pending entries may omit dates, but cannot provide just one endpoint.
        {"status": "Pendiente", "used_days": "0", "start_date": past_start, "end_date": ""},
        # Invalid ISO dates must not silently turn into an empty date.
        {"status": "Pendiente", "used_days": "0", "start_date": f"{year}-02-30", "end_date": ""},
        # A date range must be present for an approved leave.
        {"status": "Aprobada", "used_days": "0", "start_date": "", "end_date": ""},
        # Days can only be accounted as used once the leave is completed.
        {"status": "Aprobada", "used_days": "2", "start_date": past_start, "end_date": past_end},
        # Completed leave requires positive used days and cannot end in the future.
        {"status": "Completada", "used_days": "0", "start_date": past_start, "end_date": past_end},
        {"status": "Completada", "used_days": "2", "start_date": future_start, "end_date": future_end},
    ]

    with TestClient(app) as client:
        csrf = _login(client)
        for case in invalid_cases:
            response = client.post(
                "/app/vacations",
                data={
                    "csrf_token": csrf,
                    "employee_id": str(employee_id),
                    "period_year": str(year),
                    "entitled_days": "12",
                    **case,
                },
                follow_redirects=False,
            )
            assert response.status_code == 303, (case, response.status_code, response.text[:300])
            assert "form_error=" in response.headers.get("location", ""), case

        with SessionLocal() as db:
            after_invalid = db.scalar(select(func.count(Vacation.id)).where(
                Vacation.employee_id == employee_id, Vacation.period_year == year
            )) or 0
            assert after_invalid == before

        marker = "qa-valid-completed-vacation"
        valid = client.post(
            "/app/vacations",
            data={
                "csrf_token": csrf,
                "employee_id": str(employee_id),
                "period_year": str(year),
                "entitled_days": "12",
                "used_days": "3",
                "status": "Completada",
                "start_date": past_start,
                "end_date": past_end,
                "notes": marker,
            },
            follow_redirects=False,
        )
        assert valid.status_code == 303
        assert "form_error=" not in valid.headers.get("location", "")

    vacation_id = None
    event_id = None
    try:
        with SessionLocal() as db:
            item = db.scalar(select(Vacation).where(
                Vacation.employee_id == employee_id,
                Vacation.period_year == year,
                Vacation.notes.like(f"{marker}%"),
            ).order_by(Vacation.id.desc()))
            assert item is not None
            vacation_id = item.id
            event = db.scalar(select(ComplianceEvent).where(
                ComplianceEvent.source_key == f"vacation:{vacation_id}:reop"
            ))
            if event is not None:
                event_id = event.id
    finally:
        with SessionLocal() as db:
            if event_id is not None:
                event = db.get(ComplianceEvent, event_id)
                if event is not None:
                    db.delete(event)
            if vacation_id is not None:
                item = db.get(Vacation, vacation_id)
                if item is not None:
                    db.delete(item)
            db.commit()



def test_compliance_events_validate_authority_type_and_due_date():
    from datetime import date
    from sqlalchemy import select, func
    from app.database import SessionLocal
    from app.models import Company, ComplianceEvent

    with SessionLocal() as db:
        company = db.scalar(select(Company).order_by(Company.id))
        assert company is not None
        company_id = company.id
        before = db.scalar(select(func.count(ComplianceEvent.id)).where(
            ComplianceEvent.company_id == company_id
        )) or 0

    invalid_events = [
        {"authority": "OTHER", "event_type": "Entrada", "due_date": ""},
        {"authority": "REI", "event_type": "Accidente laboral", "due_date": ""},
        {"authority": "REOP", "event_type": "Entrada", "due_date": "fecha-inválida"},
    ]
    with TestClient(app) as client:
        csrf = _login(client)
        for case in invalid_events:
            response = client.post(
                "/app/compliance/events",
                data={
                    "csrf_token": csrf,
                    "company_id": str(company_id),
                    "employee_id": "",
                    "event_date": date.today().isoformat(),
                    "detail": "Prueba de validación",
                    **case,
                },
                follow_redirects=False,
            )
            assert response.status_code == 400, (case, response.status_code, response.text[:200])

    with SessionLocal() as db:
        after = db.scalar(select(func.count(ComplianceEvent.id)).where(
            ComplianceEvent.company_id == company_id
        )) or 0
        assert after == before


def test_compliance_event_submission_requires_reference_and_exported_state_comes_from_batch():
    from datetime import date
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models import Company, ComplianceEvent

    with SessionLocal() as db:
        company = db.scalar(select(Company).order_by(Company.id))
        assert company is not None
        event = ComplianceEvent(
            company_id=company.id,
            authority="REOP",
            event_type="Entrada",
            event_date=date.today(),
            status="Exportado",
            payload_json="{}",
            created_by="qa-other-reviewer",
        )
        db.add(event)
        db.commit()
        event_id = event.id

    try:
        with TestClient(app) as client:
            csrf = _login(client)
            manual_export = client.post(
                f"/app/compliance/events/{event_id}/status",
                data={"csrf_token": csrf, "status": "Exportado", "external_reference": ""},
                follow_redirects=False,
            )
            assert manual_export.status_code == 409

            missing_reference = client.post(
                f"/app/compliance/events/{event_id}/status",
                data={"csrf_token": csrf, "status": "Presentado", "external_reference": ""},
                follow_redirects=False,
            )
            assert missing_reference.status_code == 400

            submitted = client.post(
                f"/app/compliance/events/{event_id}/status",
                data={"csrf_token": csrf, "status": "Presentado", "external_reference": "REOP-REF-QA"},
                follow_redirects=False,
            )
            assert submitted.status_code == 303

            with SessionLocal() as db:
                event = db.get(ComplianceEvent, event_id)
                assert event is not None
                submitted_at = event.submitted_at
                assert submitted_at is not None
                assert event.external_reference == "REOP-REF-QA"

            accepted = client.post(
                f"/app/compliance/events/{event_id}/status",
                data={"csrf_token": csrf, "status": "Aceptado", "external_reference": "REOP-REF-QA"},
                follow_redirects=False,
            )
            assert accepted.status_code == 303

        with SessionLocal() as db:
            event = db.get(ComplianceEvent, event_id)
            assert event is not None
            assert event.status == "Aceptado"
            assert event.submitted_at == submitted_at
    finally:
        with SessionLocal() as db:
            event = db.get(ComplianceEvent, event_id)
            if event is not None:
                db.delete(event)
                db.commit()


def test_employee_compliance_boolean_fields_parse_false_strings_as_false():
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models import Company, Employee, EmployeeComplianceProfile

    with SessionLocal() as db:
        employee = db.scalar(select(Employee).order_by(Employee.id))
        assert employee is not None
        company_id, employee_id = employee.company_id, employee.id

    with TestClient(app) as client:
        csrf = _login(client)
        response = client.post(
            "/app/compliance/employee-profile",
            data={
                "csrf_token": csrf,
                "company_id": str(company_id),
                "employee_id": str(employee_id),
                "indigenous": "false",
                "disability": "0",
                "weekly_hours": "48",
                "dependent_children": "0",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

    with SessionLocal() as db:
        profile = db.scalar(select(EmployeeComplianceProfile).where(
            EmployeeComplianceProfile.employee_id == employee_id
        ))
        assert profile is not None
        assert profile.indigenous is False
        assert profile.disability is False


def test_annual_batch_receipt_is_stored_downloadable_and_stateful():
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models import Company, IntegrationBatch
    from app.storage_service import storage

    with SessionLocal() as db:
        company = db.scalar(select(Company).order_by(Company.id))
        assert company is not None
        batch = IntegrationBatch(
            studio_id=company.studio_id,
            company_id=company.id,
            authority="REOP",
            batch_type="Planillas anuales",
            period="2098",
            status="Generado",
            file_name="qa_reop_annual.xlsx",
            file_sha256="a" * 64,
            item_count=0,
            created_by="qa",
        )
        db.add(batch)
        db.commit()
        batch_id, company_id = batch.id, company.id

    receipt_key = f"integrations/{company_id}/receipts/batch-{batch_id}.pdf"
    try:
        with TestClient(app) as client:
            csrf = _login(client)
            missing_evidence = client.post(
                f"/app/compliance/batches/{batch_id}/receipt",
                data={"csrf_token": csrf, "status": "Presentado", "external_reference": ""},
                follow_redirects=False,
            )
            assert missing_evidence.status_code == 400

            fake_pdf = client.post(
                f"/app/compliance/batches/{batch_id}/receipt",
                data={
                    "csrf_token": csrf,
                    "status": "Presentado",
                    "external_reference": "REOP-QA-2026-01",
                },
                files={"receipt": ("fake.pdf", b"no es PDF", "application/pdf")},
                follow_redirects=False,
            )
            assert fake_pdf.status_code == 415

            pdf_bytes = b"%PDF-1.4\n% Digit Laboral receipt test\n"
            registered = client.post(
                f"/app/compliance/batches/{batch_id}/receipt",
                data={
                    "csrf_token": csrf,
                    "status": "Presentado",
                    "external_reference": "REOP-QA-2026-01",
                },
                files={"receipt": ("comprobante.pdf", pdf_bytes, "application/pdf")},
                follow_redirects=False,
            )
            assert registered.status_code == 303

            download = client.get(f"/app/compliance/batches/{batch_id}/receipt")
            assert download.status_code == 200
            assert download.content == pdf_bytes
            assert download.headers["content-type"].startswith("application/pdf")

            with SessionLocal() as db:
                batch = db.get(IntegrationBatch, batch_id)
                assert batch is not None
                submitted_at = batch.submitted_at
                assert batch.status == "Presentado"
                assert submitted_at is not None
                assert batch.external_reference == "REOP-QA-2026-01"

            accepted = client.post(
                f"/app/compliance/batches/{batch_id}/receipt",
                data={
                    "csrf_token": csrf,
                    "status": "Aceptado",
                    "external_reference": "REOP-QA-2026-01",
                },
                follow_redirects=False,
            )
            assert accepted.status_code == 303

            forbidden_reversal = client.post(
                f"/app/compliance/batches/{batch_id}/receipt",
                data={
                    "csrf_token": csrf,
                    "status": "Rechazado",
                    "external_reference": "REOP-QA-2026-01",
                },
                follow_redirects=False,
            )
            assert forbidden_reversal.status_code == 409

        with SessionLocal() as db:
            batch = db.get(IntegrationBatch, batch_id)
            assert batch is not None
            assert batch.status == "Aceptado"
            assert batch.submitted_at == submitted_at
            assert batch.approved_by == "admin@digitlaboral.com.py"
    finally:
        if storage.exists(receipt_key):
            storage.delete(receipt_key)
        with SessionLocal() as db:
            batch = db.get(IntegrationBatch, batch_id)
            if batch is not None:
                db.delete(batch)
                db.commit()



def test_audit_search_filters_and_paginates_study_logs():
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models import AuditLog, Company

    with SessionLocal() as db:
        company = db.scalar(select(Company).order_by(Company.id))
        assert company is not None
        studio_id = company.studio_id
        rows = [
            AuditLog(
                studio_id=studio_id,
                user_email="qa-audit@test.py",
                action="qa_filter_action",
                entity="qa_compliance",
                entity_id=f"audit-{i:02d}",
                detail=f"audit-find-me row {i:02d}",
            )
            for i in range(52)
        ]
        db.add_all(rows)
        db.commit()
        audit_ids = [item.id for item in rows]

    try:
        with TestClient(app) as client:
            csrf = _login(client)
            page_one = client.get(
                "/app/audit",
                params={"q": "audit-find-me", "action": "qa_filter_action", "entity": "qa_compliance"},
            )
            assert page_one.status_code == 200
            assert "52 resultados" in page_one.text
            assert "página 1 de 2" in page_one.text
            soup_one = BeautifulSoup(page_one.text, "html.parser")
            assert len(soup_one.select("tbody tr")) == 50

            page_two = client.get(
                "/app/audit",
                params={
                    "q": "audit-find-me", "action": "qa_filter_action",
                    "entity": "qa_compliance", "page": "2",
                },
            )
            assert page_two.status_code == 200
            assert "página 2 de 2" in page_two.text
            soup_two = BeautifulSoup(page_two.text, "html.parser")
            assert len(soup_two.select("tbody tr")) == 2

            invalid_range = client.get(
                "/app/audit",
                params={"date_from": "2026-10-25", "date_to": "2026-10-24"},
            )
            assert invalid_range.status_code == 400
    finally:
        with SessionLocal() as db:
            for item in db.scalars(select(AuditLog).where(AuditLog.id.in_(audit_ids))):
                db.delete(item)
            db.commit()


def test_audit_and_data_csv_exports_escape_spreadsheet_formulas():
    import csv
    import io
    import uuid
    from datetime import date
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models import AuditLog, CalculationRecord, Company, Employee

    with SessionLocal() as db:
        company = db.scalar(select(Company).order_by(Company.id))
        assert company is not None
        company_id, studio_id = company.id, company.studio_id
        marker = uuid.uuid4().hex[:10]
        employee = Employee(
            company_id=company_id,
            full_name="=1+1",
            document_number=f"CSV-{marker}",
            position="=HYPERLINK(\"https://example.invalid\",\"open\")",
            admission_date=date.today(),
            base_salary=0,
            status="Activo",
        )
        db.add(employee)
        db.flush()
        calculation = CalculationRecord(
            company_id=company_id,
            employee_id=employee.id,
            calculation_type="hours",
            reference_period="=1+1",
            input_json="{}",
            result_json="{}",
            amount=1,
            status="Borrador",
            source="QA",
            created_by="qa@test.py",
        )
        audit = AuditLog(
            studio_id=studio_id,
            user_email="qa-audit@test.py",
            action=f"formula_export_{marker}",
            entity="qa_csv",
            entity_id=marker,
            detail="=1+1",
        )
        db.add_all([calculation, audit])
        db.commit()
        employee_id, calculation_id, audit_id = employee.id, calculation.id, audit.id

    try:
        with TestClient(app) as client:
            csrf = _login(client)
            audit_response = client.get(
                "/app/audit/export.csv",
                params={"action": f"formula_export_{marker}"},
            )
            assert audit_response.status_code == 200
            audit_rows = list(csv.reader(io.StringIO(audit_response.content.decode("utf-8-sig"))))
            audit_row = next(row for row in audit_rows[1:] if row[3] == "qa_csv")
            assert audit_row[5] == "'=1+1"

            employee_response = client.get("/app/export/employees.csv")
            assert employee_response.status_code == 200
            employee_rows = list(csv.reader(io.StringIO(employee_response.content.decode("utf-8-sig"))))
            employee_row = next(row for row in employee_rows[1:] if row[3] == f"CSV-{marker}")
            assert employee_row[2] == "'=1+1"
            assert employee_row[4].startswith("'=HYPERLINK(")

            report_response = client.get(
                "/app/reports/export.csv",
                params={"company_id": str(company_id), "employee_id": str(employee_id)},
            )
            assert report_response.status_code == 200
            report_rows = list(csv.reader(io.StringIO(report_response.content.decode("utf-8-sig"))))
            report_row = next(row for row in report_rows[1:] if row[2] == "'=1+1")
            assert report_row[4] == "'=1+1"
    finally:
        with SessionLocal() as db:
            audit = db.get(AuditLog, audit_id)
            calculation = db.get(CalculationRecord, calculation_id)
            employee = db.get(Employee, employee_id)
            if audit is not None:
                db.delete(audit)
            if calculation is not None:
                db.delete(calculation)
            if employee is not None:
                db.delete(employee)
            db.commit()



def test_totp_login_failures_lock_temporary_account():
    import uuid
    from datetime import UTC, datetime
    from sqlalchemy import select
    from app.auth import hash_password
    from app.database import SessionLocal
    from app.models import SecurityEvent, Studio, User, UserSecurity
    from app.security_service import _totp_at

    marker = uuid.uuid4().hex[:12]
    email = f"totp-lockout-{marker}@test.py"
    password = f"Qa-Password-{marker}!A9"
    secret = "JBSWY3DPEHPK3PXP"
    counter = int(datetime.now(UTC).timestamp() // 30)
    valid_codes = {_totp_at(secret, step) for step in range(counter - 3, counter + 12)}
    invalid_code = next(f"{candidate:06d}" for candidate in range(1_000_000) if f"{candidate:06d}" not in valid_codes)
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.email == "admin@digitlaboral.com.py"))
        assert admin is not None and admin.studio_id is not None
        user = User(
            studio_id=admin.studio_id,
            full_name="QA TOTP Lockout",
            email=email,
            password_hash=hash_password(password),
            role="administrador",
            active=True,
            must_change_password=False,
        )
        db.add(user)
        db.commit()
        user_id = user.id
        # The application may initialize security metadata as part of user creation.
        # Update that row when it exists instead of inserting a duplicate.
        security = db.scalar(select(UserSecurity).where(UserSecurity.user_id == user_id))
        if security is None:
            security = UserSecurity(user_id=user_id)
            db.add(security)
        security.totp_secret = secret
        security.totp_enabled = True
        security.failed_attempts = 0
        security.locked_until = None
        db.commit()
        assert db.get(Studio, admin.studio_id) is not None

    try:
        with TestClient(app) as client:
            login_page = client.get("/login")
            match = re.search(r'name="csrf_token" value="([^"]+)"', login_page.text)
            assert match
            authenticated_password = client.post(
                "/login",
                data={"email": email, "password": password, "csrf_token": match.group(1)},
                follow_redirects=False,
            )
            assert authenticated_password.status_code == 303
            assert authenticated_password.headers["location"] == "/login/2fa"

            second_factor_page = client.get("/login/2fa")
            match = re.search(r'name="csrf_token" value="([^"]+)"', second_factor_page.text)
            assert second_factor_page.status_code == 200 and match
            csrf = match.group(1)
            for _ in range(settings.login_max_attempts):
                invalid = client.post(
                    "/login/2fa",
                    data={"csrf_token": csrf, "code": invalid_code},
                    follow_redirects=False,
                )
                assert invalid.status_code == 200
            blocked = client.post(
                "/login/2fa",
                data={"csrf_token": csrf, "code": invalid_code},
                follow_redirects=False,
            )
            assert blocked.status_code == 200
            assert "bloqueada temporalmente" in blocked.text.lower()

        with SessionLocal() as db:
            security = db.scalar(select(UserSecurity).where(UserSecurity.user_id == user_id))
            assert security is not None
            assert security.failed_attempts >= settings.login_max_attempts
            assert security.locked_until is not None
            assert len(list(db.scalars(select(SecurityEvent).where(
                SecurityEvent.user_id == user_id,
                SecurityEvent.event_type == "segundo_factor",
                SecurityEvent.success.is_(False),
            )))) >= settings.login_max_attempts
    finally:
        with SessionLocal() as db:
            for event in db.scalars(select(SecurityEvent).where(SecurityEvent.user_id == user_id)):
                db.delete(event)
            security = db.scalar(select(UserSecurity).where(UserSecurity.user_id == user_id))
            user = db.get(User, user_id)
            if security is not None:
                db.delete(security)
            if user is not None:
                db.delete(user)
            db.commit()


def test_production_readiness_warns_when_csrf_protection_is_disabled():
    from dataclasses import replace
    from app.config import settings

    production = replace(settings, environment="production", csrf_enabled=False)
    issues = production.production_issues()
    assert any("CSRF_ENABLED" in issue for issue in issues)



def test_dark_module_navigation_styles_are_versioned_and_accessible():
    with TestClient(app) as client:
        login_page = client.get("/login")
        assert login_page.status_code == 200
        base = client.get("/app")
        assert base.status_code == 200
        assert "brand-identity.css?v=20261024c" in base.text

        stylesheet = client.get("/static/brand-identity.css?v=20261024c")
        assert stylesheet.status_code == 200
        css = stylesheet.text
        assert ".modern-mobile-nav.workspace-sidebar" in css
        assert "background:#0B1730" in css
        assert "workspace-nav-link.active" in css
        assert "outline:3px solid #84BCFF" in css
