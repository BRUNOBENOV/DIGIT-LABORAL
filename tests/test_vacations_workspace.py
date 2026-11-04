"""Vacaciones: filtros globales, trazabilidad legible y validaciones del registro."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup
from sqlalchemy import select

from app.legacy_vacation_import import EVENT_TYPE, MARKER
from app.models import EmployeeEvent, Vacation
from app.unified_labor_history import vacation_history_page
from tests.test_labor_suite import token, web_case  # noqa: F401
from tests.test_unified_labor_history import setup_records

ROOT = Path(__file__).resolve().parents[1]


def test_vacation_filters_query_all_rows_before_pagination():
    db, engine = setup_records()
    try:
        assert vacation_history_page(db, {11}, source="all")["total"] == 2
        current = vacation_history_page(db, {11}, source="current")
        assert current["total"] == 1 and current["rows"][0]["id"] == 301
        historic = vacation_history_page(db, {11}, source="imported")
        assert historic["total"] == 1 and historic["rows"][0]["id"] == 202
        assert historic["rows"][0]["status"] == "Sin conciliar"
        assert historic["rows"][0]["balance"] is None
        assert vacation_history_page(db, {11}, status="Aprobada")["total"] == 1
        assert vacation_history_page(db, {11}, status="Sin conciliar")["total"] == 1
        assert vacation_history_page(db, {11}, q="FUNCIONARIO A")["total"] == 2
        assert vacation_history_page(db, {11}, q="900001")["total"] == 2
        assert vacation_history_page(db, {11}, q="2023")["rows"][0]["origin"] == "imported"
        assert vacation_history_page(db, {11}, q="2026")["rows"][0]["origin"] == "current"
        assert vacation_history_page(db, {11}, q="sin coincidencia")["total"] == 0
        assert vacation_history_page(db, {11}, q="FUNCIONARIO B")["total"] == 0
        assert vacation_history_page(db, {11}, source="imported", status="Aprobada")["total"] == 0
        assert vacation_history_page(db, {11}, sort_order="oldest")["rows"][0]["origin"] == "imported"
        assert vacation_history_page(db, {11}, page_size=1, page=2)["total"] == 2
        assert vacation_history_page(db, {11}, page_size=1, page=2)["rows"][0]["id"] == 202
        assert current["rows"][0]["url"] == "/app/vacations/301"
    finally:
        db.close()
        engine.dispose()


def test_vacation_workspace_has_one_search_controls_and_clear_origin_badges(web_case):
    client, db, _, company, employee, _ = web_case
    history = {
        "source": "LSVAC", "source_row": 12, "company_code": "1", "employee_code": "200",
        "legacy_key": "vac-workspace", "source_hash": "f" * 64,
        "period_from": "2023-01-01", "period_to": "2023-12-31",
        "vacation_start": "2024-08-01", "vacation_end": "2024-08-12",
        "days": 12, "vacation_amount": "500000",
    }
    db.add(EmployeeEvent(
        employee_id=employee.id, event_type=EVENT_TYPE, title="Vacaciones históricas",
        detail=MARKER + json.dumps(history), effective_date=date(2024, 8, 1),
        created_by="test",
    ))
    db.add(Vacation(
        employee_id=employee.id, period_year=2026, entitled_days=18,
        used_days=5, status="Aprobada", start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 18),
    ))
    db.commit()
    params = {"company_id": company.id, "employee_id": employee.id}
    page = client.get("/app/vacations", params=params)
    assert page.status_code == 200
    soup = BeautifulSoup(page.text, "html.parser")
    section = soup.select_one("#vacations-records")
    assert section is not None and section.has_attr("data-server-search")
    assert len(section.select("tbody tr")) == 2
    assert len(soup.select("#vacationFilters input[name=q]")) == 1
    assert section.select_one("table[data-ui-no-enhance]") is not None
    assert "Histórico DOS" in section.get_text(" ", strip=True)
    assert "Registro actual" in section.get_text(" ", strip=True)
    assert "/app/vacations/history/" in page.text
    assert "Ver detalle" in page.text
    assert "no tienen saldo conciliado" in page.text
    assert "vacations-workspace-2693.css" in page.text
    assert "vacations-workspace-2693.js" in page.text

    for source, wanted in (("current", "Registro actual"), ("imported", "Histórico DOS")):
        filtered = client.get("/app/vacations", params={**params, "source": source})
        markup = BeautifulSoup(filtered.text, "html.parser")
        assert len(markup.select("#vacations-records tbody tr")) == 1
        assert wanted in markup.select_one("#vacations-records").get_text(" ", strip=True)

    by_year = client.get("/app/vacations", params={**params, "q": "2023"})
    assert by_year.status_code == 200
    assert len(BeautifulSoup(by_year.text, "html.parser").select("#vacations-records tbody tr")) == 1
    by_status = client.get("/app/vacations", params={**params, "status": "Sin conciliar"})
    assert by_status.status_code == 200
    assert len(BeautifulSoup(by_status.text, "html.parser").select("#vacations-records tbody tr")) == 1

    assert client.get("/app/vacations", params={**params, "source": "invalid"}).status_code == 422
    assert client.get("/app/vacations", params={**params, "page_size": 500}).status_code == 422


def test_vacation_current_detail_restricted_to_visible_worker(web_case):
    client, db, _, company, employee, _ = web_case
    item = Vacation(
        employee_id=employee.id, period_year=2026,
        entitled_days=18, used_days=5,
        start_date=date(2026, 8, 1), end_date=date(2026, 8, 18),
        status="Aprobada", notes="Movimiento sintético autorizado",
    )
    db.add(item)
    db.commit()
    detail = client.get(f"/app/vacations/{item.id}")
    assert detail.status_code == 200
    assert "Movimiento sintético autorizado" in detail.text
    assert "13" in detail.text
    assert f"/app/vacations?company_id={company.id}" in detail.text
    assert client.get("/app/vacations/999999999").status_code == 404


def test_vacation_create_checks_dates_days_and_redirects_to_detail(web_case):
    client, db, _, company, employee, _ = web_case
    employee.admission_date = date(2020, 1, 1)
    db.commit()
    csrf = token(client, "/app/vacations")
    data = {
        "csrf_token": csrf, "employee_id": str(employee.id), "period_year": "2026",
        "entitled_days": "18", "used_days": "5", "status": "Completada",
        "start_date": "2026-08-01", "end_date": "2026-08-18",
        "notes": "Cargado con respaldo sintético",
    }
    # El flujo profesional v24 devuelve al formulario con el error, en vez
    # de mostrar una página HTTP 422; no debe guardar el movimiento inválido.
    for bad in (
        {**data, "used_days": "20"},
        {**data, "start_date": "2026-08-25"},
        {**data, "entitled_days": "-5"},
        {**data, "status": "Desconocido"},
        {**data, "status": "Pendiente"},  # Días usados sin estado Completada.
    ):
        invalid = client.post("/app/vacations", data=bad, follow_redirects=False)
        assert invalid.status_code == 303
        assert "form_error=" in invalid.headers["location"]
        assert db.scalars(select(Vacation).where(Vacation.employee_id == employee.id)).all() == []
    response = client.post("/app/vacations", data=data, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/app/vacations/")
    target = client.get(response.headers["location"])
    assert target.status_code == 200
    assert "Movimiento sintético" not in target.text
    assert "Cargado con respaldo sintético" in target.text


def test_other_table_filters_remain_intact_and_vacation_filters_not_duplicated():
    html = (ROOT / "app/templates/vacations.html").read_text(encoding="utf-8")
    experience_js = (ROOT / "app/static/experience.js").read_text(encoding="utf-8")
    ui_js = (ROOT / "app/static/ui-system-264.js").read_text(encoding="utf-8")
    assert 'data-server-search' in html
    assert 'data-ui-no-enhance' in html
    assert 'panel.hasAttribute("data-server-search")' in experience_js
    assert 'table:not([data-ui-no-enhance])' in ui_js
    assert 'name="q"' in html
