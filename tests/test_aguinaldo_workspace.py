"""Regresiones de Aguinaldo, vista moderna y base anual sin extrapolaciones."""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.database import SessionLocal
from app.labor_calculator import amount as round_gs
from app.main import app, company_ids_for_user
from app.models import Employee, User
from sqlalchemy import select


def _login(client):
    page = client.get("/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert page.status_code == 200 and token
    response = client.post(
        "/login",
        data={"email": "admin@digitlaboral.com.py",
              "password": settings.demo_admin_password,
              "csrf_token": token.group(1)},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_original_annual_bonus_sample_uses_twelfth_not_daily_divisor():
    # Captura histórica: total anual Gs. 15.353.468,29.
    annual = Decimal("15353468.29")
    exact = annual / Decimal(12)
    assert exact.quantize(Decimal("0.01")) == Decimal("1279455.69")
    assert round_gs(exact) == 1_279_456
    # El valor por día que muestra el sistema antiguo es orientativo.
    assert round_gs(exact) != round_gs(exact / Decimal(365))


def test_aguinaldo_screen_shows_employment_fields_and_no_fictitious_months():
    with TestClient(app) as client:
        anonymous = client.get("/app/aguinaldo", follow_redirects=False)
        assert anonymous.status_code in {302, 303, 307, 401, 403}
        _login(client)
        page = client.get("/app/aguinaldo?year=2026")
        assert page.status_code == 200, page.text[:600]
        for fragment in (
            "Cálculo de aguinaldo",
            "Seleccionar empresa, funcionario y ejercicio",
            "Ejercicio",
            "Historial de aguinaldos guardados",
            "÷ 12",
            "Guardar cálculo en Borrador",
        ):
            assert fragment in page.text
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == "admin@digitlaboral.com.py"))
            ids = company_ids_for_user(db, user) if user else []
            worker = db.scalar(
                select(Employee).where(Employee.company_id.in_(ids))
                .order_by(Employee.id).limit(1)
            ) if ids else None
            if not worker:
                return  # App demo may not contain employees.
            worker_id = worker.id
            company_id = worker.company_id
        detail = client.get("/app/aguinaldo", params={
            "company_id": company_id, "employee_id": worker_id, "year": 2026
        })
        assert detail.status_code == 200, detail.text[:600]
        for label in (
            "Código de trabajador", "Código empresa", "Fecha de ingreso",
            "Cálculo desde", "Cálculo hasta", "Salario actual registrado",
            "Remuneraciones brutas documentadas (nóminas y recibos individuales)",
            "Días calendario del ejercicio (referencia)",
            "Detalle mensual y trazabilidad salarial",
            "No se extrapolan salarios ni se completan meses faltantes",
        ):
            assert label in detail.text


def test_aguinaldo_ui_keeps_amount_separate_from_days_and_remuneration_reference():
    path = Path(__file__).resolve().parents[1] / "app/templates/aguinaldo.html"
    content = path.read_text(encoding="utf-8")
    assert "annual.value" in content
    assert "Math.round(amount / 12)" in content
    assert "Días calendario del ejercicio (referencia)" in content
    assert "Los días calendario no son un divisor legal" in content
    assert "Sin aporte IPS" in content
    assert "data-suggested-employee" in content
    assert "data-suggested-year" in content


def test_aguinaldo_page_links_an_individual_salary_receipt_without_closed_payroll():
    """Integración: un recibo en Informes debe constar en Aguinaldo aunque no exista nómina cerrada."""
    import json
    import uuid
    from datetime import date
    from app.models import Company, CalculationRecord

    suffix = uuid.uuid4().hex[:10]
    with TestClient(app) as client:
        _login(client)
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == "admin@digitlaboral.com.py"))
            assert user and user.studio_id
            company = Company(studio_id=user.studio_id,
                              legal_name="Prueba aguinaldo recibo " + suffix,
                              ruc="99990000-0")
            db.add(company)
            db.flush()
            worker = Employee(company_id=company.id, employee_code=int(suffix[:6], 16) % 9_000_000 + 1,
                              full_name="Funcionario prueba aguinaldo " + suffix,
                              document_number=str(int(suffix, 16) % 9_000_000 + 1),
                              admission_date=date(2023, 1, 13), base_salary=3_044_000)
            db.add(worker)
            db.flush()
            calc = CalculationRecord(
                company_id=company.id, employee_id=worker.id,
                calculation_type="suite_salary", reference_period="2026-10",
                input_json=json.dumps({"kind": "salary", "month": "2026-10"}),
                result_json=json.dumps({
                    "kind": "salary", "period": "2026-10",
                    "earnings": [{"label": "Salario del periodo", "amount": 3_044_000}],
                    "deductions": [], "gross": 3_044_000,
                    "discounts": 0, "net": 3_044_000,
                }),
                amount=3_044_000, source="Centro laboral", status="Borrador",
            )
            db.add(calc)
            db.commit()
            company_id, employee_id, calc_id = company.id, worker.id, calc.id
        detail = client.get("/app/aguinaldo", params={
            "company_id": company_id, "employee_id": employee_id, "year": 2026,
        })
        assert detail.status_code == 200, detail.text[:600]
        assert "1 / 11" in detail.text
        assert "3.044.000" in detail.text
        assert "Recibo pendiente de revisión" in detail.text
        assert f"/app/reports/liquidaciones-salarios/{calc_id}" in detail.text
        assert "No se extrapolan salarios ni se completan meses faltantes" in detail.text
        # Cambiar solo estado, sin recalcular importes; ya puede entrar en base preliminar.
        with SessionLocal() as db:
            item = db.get(CalculationRecord, calc_id)
            item.status = "Aprobado"
            db.commit()
        approved = client.get("/app/aguinaldo", params={
            "company_id": company_id, "employee_id": employee_id, "year": 2026,
        })
        assert approved.status_code == 200
        assert "Recibo aprobado" in approved.text
        assert "253.667" in approved.text
