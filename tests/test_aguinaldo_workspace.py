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
            "Remuneraciones brutas registradas en nóminas cerradas",
            "Días calendario del período de referencia",
            "Detalle mensual y trazabilidad salarial",
            "No se extrapolan salarios ni se completan meses faltantes",
        ):
            assert label in detail.text


def test_aguinaldo_ui_keeps_amount_separate_from_days_and_remuneration_reference():
    path = Path(__file__).resolve().parents[1] / "app/templates/aguinaldo.html"
    content = path.read_text(encoding="utf-8")
    assert "annual.value" in content
    assert "Math.round(amount / 12)" in content
    assert "Días calendario del período de referencia" in content
    assert "Los días calendario no son un divisor legal" in content
    assert "Sin aporte IPS" in content
    assert "data-suggested-employee" in content
    assert "data-suggested-year" in content
