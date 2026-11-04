"""La rectificación aprobada reemplaza visualmente al original sin borrarlo."""
from datetime import datetime
import json

from bs4 import BeautifulSoup
from sqlalchemy import select

from app.models import CalculationRecord
from app.salary_data import approved_salary
from app.unified_labor_history import calculation_history_page
from tests.test_unified_labor_history import setup_records
from tests.test_labor_suite import web_case  # noqa: F401


def _salary_record(*, id, company_id, employee_id, status, rectifies=None,
                   day=1, period="2026-10"):
    return CalculationRecord(
        id=id, company_id=company_id, employee_id=employee_id,
        calculation_type="suite_salary", reference_period=period,
        source="Centro laboral", status=status, amount=2770040,
        created_at=datetime(2026, 10, day),
        input_json=json.dumps(
            {"kind": "salary", "month": period, **(
                {"rectifies_record_id": str(rectifies)} if rectifies else {}
            )}
        ), result_json=json.dumps({"net": 2770040}),
    )


def test_approved_rectification_hides_original_only_after_approval():
    db, engine = setup_records()
    try:
        original = _salary_record(id=401, company_id=11, employee_id=21,
                                  status="Aprobado", day=1)
        replacement = _salary_record(id=402, company_id=11, employee_id=21,
                                     status="Borrador", rectifies=401, day=2)
        db.add_all([original, replacement])
        db.commit()

        pending = calculation_history_page(db, {11}, include_center_calculations=True)
        ids = {r["id"] for r in pending["rows"] if r["origin"] == "current"}
        assert {401, 402} <= ids
        assert pending["superseded_count"] == 0
        assert approved_salary(db, 11, 21, "2026-10").id == 401

        replacement.status = "Aprobado"
        db.commit()
        visible = calculation_history_page(db, {11}, include_center_calculations=True)
        visible_ids = {r["id"] for r in visible["rows"] if r["origin"] == "current"}
        assert 401 not in visible_ids and 402 in visible_ids
        assert visible["superseded_count"] == 1
        assert visible["total"] == pending["total"] - 1
        assert approved_salary(db, 11, 21, "2026-10").id == 402

        full = calculation_history_page(
            db, {11}, include_center_calculations=True,
            include_superseded_salary=True, page_size=1, page=1,
        )
        assert full["total"] == pending["total"]
        assert full["pages"] == pending["total"]
        all_full = calculation_history_page(
            db, {11}, include_center_calculations=True,
            include_superseded_salary=True,
        )
        older = next(row for row in all_full["rows"] if row["id"] == 401)
        assert older["superseded"] and older["display_status"] == "Sustituido"
        assert db.get(CalculationRecord, 401).status == "Aprobado"
    finally:
        db.close()
        engine.dispose()


def test_supersession_is_tenant_employee_and_period_scoped_and_chains():
    db, engine = setup_records()
    try:
        original = _salary_record(id=411, company_id=11, employee_id=21,
                                  status="Aprobado", day=1)
        cross_company = _salary_record(id=412, company_id=12, employee_id=22,
                                       status="Aprobado", rectifies=411, day=2)
        wrong_period = _salary_record(id=413, company_id=11, employee_id=21,
                                      status="Aprobado", rectifies=411,
                                      period="2026-11", day=3)
        replacement = _salary_record(id=414, company_id=11, employee_id=21,
                                     status="Aprobado", rectifies=411, day=4)
        second = _salary_record(id=415, company_id=11, employee_id=21,
                                status="Borrador", rectifies=414, day=5)
        db.add_all([original, cross_company, wrong_period, replacement, second])
        db.commit()
        current = calculation_history_page(
            db, {11}, employee_id=21, include_center_calculations=True,
        )
        visible = {row["id"] for row in current["rows"] if row["origin"] == "current"}
        assert 411 not in visible
        assert {413, 414, 415} <= visible
        assert calculation_history_page(
            db, {12}, include_center_calculations=True,
        )["superseded_count"] == 0
        second.status = "Aprobado"
        db.commit()
        again = calculation_history_page(
            db, {11}, employee_id=21, include_center_calculations=True,
        )
        now = {row["id"] for row in again["rows"] if row["origin"] == "current"}
        assert 411 not in now and 414 not in now and 415 in now
        assert again["superseded_count"] == 2
    finally:
        db.close()
        engine.dispose()


def test_liquidation_history_hides_old_version_but_can_show_it_for_audit(web_case):
    client, db, _, company, employee, _ = web_case
    original = CalculationRecord(
        company_id=company.id, employee_id=employee.id,
        calculation_type="suite_salary", reference_period="2026-10",
        source="Centro laboral", status="Aprobado", amount=2770040,
        input_json=json.dumps({"kind": "salary", "month": "2026-10"}),
        result_json=json.dumps({"net": 2770040}),
    )
    db.add(original)
    db.flush()
    new = CalculationRecord(
        company_id=company.id, employee_id=employee.id,
        calculation_type="suite_salary", reference_period="2026-10",
        source="Centro laboral", status="Aprobado", amount=2770040,
        input_json=json.dumps({
            "kind": "salary", "month": "2026-10",
            "rectifies_record_id": str(original.id),
        }),
        result_json=json.dumps({"net": 2770040}),
    )
    db.add(new)
    db.commit()
    url = "/app/liquidaciones?tipo=salary&company_id=" + str(company.id) + "&employee_id=" + str(employee.id)
    response = client.get(url)
    assert response.status_code == 200
    soup = BeautifulSoup(response.text, "html.parser")
    trace = soup.select_one("#labor-history")
    assert trace
    assert not trace.select_one(f'a[href="/app/liquidaciones/{original.id}"]')
    assert trace.select_one(f'a[href="/app/liquidaciones/{new.id}"]')
    assert "Ver versiones anteriores (1)" in trace.get_text(" ", strip=True)

    full = client.get(url + "&history_all=1")
    assert full.status_code == 200
    full_trace = BeautifulSoup(full.text, "html.parser").select_one("#labor-history")
    assert full_trace.select_one(f'a[href="/app/liquidaciones/{original.id}"]')
    assert "Sustituido" in full_trace.get_text(" ", strip=True)
    assert db.scalar(select(CalculationRecord).where(CalculationRecord.id == original.id))
