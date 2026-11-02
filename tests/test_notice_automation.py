"""Notice calculation from employee + dated, versioned scale, without production data."""
import importlib.util
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from bs4 import BeautifulSoup
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select

from app.database import Base
from app.labor_calculator import notice_days
from app.main import _revalidate_calculation_before_approval
from app.models import AuditLog, CalculationRecord, Employee, NoticeRuleBand, NoticeRuleSet
from app.notice_rule_schema import install_notice_rules
from app.notice_scale import service_tenure
from app.notice_service import NoticeError, notice_proposal, notice_results, reference_date_from
from tests.test_labor_suite import token, web_case


@pytest.fixture
def notice_case(web_case):
    client, db, box, company, employee, other = web_case
    with db.bind.begin() as connection:
        install_notice_rules(connection)
    employee.admission_date = date(1999, 2, 11)
    employee.base_salary = 3_044_000
    db.commit()
    return web_case


def proposal(case, **changes):
    client, _, _, company, employee, _ = case
    return client.get("/api/calculations/preaviso-proposal", headers={"Accept": "application/json"}, params=dict(
        {"company_id": company.id, "employee_id": employee.id, "reference_date": "2026-11-02"}, **changes
    ))


def form(case, **changes):
    client, _, _, company, employee, _ = case
    return dict({"csrf_token": token(client), "calculation_type": "notice", "company_id": company.id,
                 "employee_id": employee.id, "reference_date": "2026-11-02", "salary": "3044000", "days": "0",
                 "notice_automation_version": "1", "notice_fingerprint": proposal(case).json()["fingerprint"]}, **changes)


def latest(case):
    case[1].expire_all()
    return case[1].scalar(select(CalculationRecord).order_by(CalculationRecord.id.desc()))


@pytest.mark.parametrize("reference,expected", [
    ("2021-01-01", 30), ("2021-01-02", 45), ("2025-01-01", 45),
    ("2025-01-02", 60), ("2030-01-01", 60), ("2030-01-02", 90),
])
def test_database_scale_uses_inclusive_calendar_anniversaries(notice_case, reference, expected):
    _, db, _, _, employee, _ = notice_case
    employee.admission_date = date(2020, 1, 1)
    db.commit()
    actual = proposal(notice_case, reference_date=reference)
    assert actual.status_code == 200, actual.text
    assert actual.json()["days"] == expected == notice_days(employee.admission_date, date.fromisoformat(reference))


def test_leap_day_and_month_end_have_exact_tenure(notice_case):
    _, db, _, _, employee, _ = notice_case
    employee.admission_date = date(2020, 2, 29)
    db.commit()
    payload = proposal(notice_case, reference_date="2021-02-28").json()
    assert payload["days"] == 30
    assert payload["tenure"] == {"years": 1, "months": 0, "days": 0}
    assert proposal(notice_case, reference_date="2021-03-01").json()["days"] == 45
    assert service_tenure(date(2026, 1, 31), date(2026, 2, 28)) == {"years": 0, "months": 1, "days": 0}


def test_apply_renders_days_and_total_without_javascript(notice_case):
    client, _, _, company, employee, _ = notice_case
    response = client.get("/app/calculations", params={"tipo": "notice", "company_id": company.id,
                         "employee_id": employee.id, "reference_date": "2026-11-02"})
    assert response.status_code == 200, response.text
    page = BeautifulSoup(response.text, "html.parser")
    assert page.select_one("#calcNoticeDays")["value"] == "90"
    assert page.select_one("#calcNoticeDays").has_attr("readonly")
    assert page.select_one("#calcNoticeSalary")["value"] == "3044000"
    assert page.select_one("#calcNoticeResult").text.strip() == "Gs. 9.132.000"
    assert "27 años y 8 meses (22 días adicionales)" in page.select_one("#noticeTenure").text
    assert page.select_one("#noticeOverride") is None  # contador
    assert not page.select_one("#noticeSave").has_attr("disabled")


@pytest.mark.parametrize("posted_days", ["0", "", "999", "manipulado", "NaN"])
def test_automatic_save_ignores_posted_days_and_replays(notice_case, posted_days):
    client, db, _, company, employee, _ = notice_case
    response = client.post("/app/calculations", data=form(notice_case, days=posted_days), follow_redirects=False)
    assert response.status_code == 303, response.text
    assert "tipo=notice" in response.headers["location"] and "reference_date=2026-11-02" in response.headers["location"]
    item = latest(notice_case)
    inputs = json.loads(item.input_json)
    assert inputs["days"] == 90
    assert item.reference_period == "2026-11" and item.amount == 9_132_000
    assert inputs["notice_proposal"]["tenure"] == {"years": 27, "months": 8, "days": 22}
    before = (item.input_json, item.result_json, employee.admission_date, employee.status)
    _revalidate_calculation_before_approval(item, db)
    approved = client.post(f"/app/calculations/{item.id}/status", data={"csrf_token": token(client), "status": "Aprobado"}, follow_redirects=False)
    assert approved.status_code == 303, approved.text
    db.refresh(item)
    assert item.status == "Aprobado" and before == (item.input_json, item.result_json, employee.admission_date, employee.status)


def test_historical_month_client_uses_month_end_not_today(notice_case):
    client, _, _, _, _, _ = notice_case
    data = form(notice_case, reference_date="", reference_period="2000-01", notice_automation_version="", notice_fingerprint="")
    response = client.post("/app/calculations", data=data, follow_redirects=False)
    assert response.status_code == 303, response.text
    inputs = json.loads(latest(notice_case).input_json)
    assert inputs["days"] == 30 and inputs["reference_date"] == "2000-01-31"
    assert latest(notice_case).amount == 3_044_000


@pytest.mark.parametrize("bad_date", ["2026-99-99", "1999-02-10", "", "2101-01-01"])
def test_invalid_or_before_hire_reference_never_saves(notice_case, bad_date):
    client = notice_case[0]
    response = client.post("/app/calculations", data=form(notice_case, reference_date=bad_date), follow_redirects=False)
    assert response.status_code == 422
    assert latest(notice_case) is None


def test_registered_exit_bounds_reference_and_scope_is_enforced(notice_case):
    client, db, _, company, employee, other = notice_case
    assert proposal(notice_case, employee_id=other.id).status_code == 404
    assert proposal(notice_case, company_id=other.company_id, employee_id=other.id).status_code == 404
    employee.termination_date = date(2026, 10, 31)
    db.commit()
    assert proposal(notice_case).status_code == 422
    assert proposal(notice_case, reference_date="2026-10-31").status_code == 200
    assert client.get("/api/calculations/preaviso-proposal").status_code == 422


@pytest.mark.parametrize("role", ["contador", "auxiliar"])
def test_non_administrators_cannot_override(notice_case, role):
    client, db, box, *_ = notice_case
    box["user"].role = role
    db.commit()
    response = client.post("/app/calculations", data=form(notice_case, notice_override="on", days="120", notice_override_reason="Excepción acreditada para prueba"))
    assert response.status_code == 403
    assert latest(notice_case) is None


@pytest.mark.parametrize("manual_days", ["0", "120"])
def test_administrator_override_has_audit_and_replay(notice_case, manual_days):
    client, db, box, company, employee, _ = notice_case
    box["user"].role = "administrador"
    db.commit()
    data = form(notice_case, notice_override="on", days=manual_days, notice_override_reason="Excepción legal documentada en expediente sintético")
    response = client.post("/app/calculations", data=data, follow_redirects=False)
    assert response.status_code == 303, response.text
    item = latest(notice_case)
    _revalidate_calculation_before_approval(item, db)
    recorded = json.loads(item.input_json)["notice_override"]
    assert recorded["days"] == int(manual_days) and recorded["user_email"] == box["user"].email
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "excepcion_preaviso"))
    assert audit and "automático 90 días" in audit.detail and f"excepción {manual_days} días" in audit.detail
    page = BeautifulSoup(client.get(f"/app/calculations?tipo=notice&company_id={company.id}&employee_id={employee.id}").text, "html.parser")
    assert page.select_one("#noticeOverride") is not None


@pytest.mark.parametrize("changes", [{"days": ""}, {"days": "3.5"}, {"days": "366"}, {"days": "-1"}, {"notice_override_reason": ""}])
def test_admin_override_requires_integer_days_and_documentation(notice_case, changes):
    client, db, box, *_ = notice_case
    box["user"].role = "administrador"
    db.commit()
    data = form(notice_case, notice_override="on", days="120", notice_override_reason="Excepción documentada sintética")
    data.update(changes)
    response = client.post("/app/calculations", data=data, follow_redirects=False)
    assert response.status_code == 422
    assert latest(notice_case) is None


@pytest.mark.parametrize("mutation", ["employee", "rule"])
def test_stale_sources_are_rejected_at_save_and_approval(notice_case, mutation):
    client, db, _, _, employee, _ = notice_case
    data = form(notice_case)
    assert client.post("/app/calculations", data=data, follow_redirects=False).status_code == 303
    item = latest(notice_case)
    if mutation == "employee":
        employee.admission_date = date(2000, 2, 11)
    else:
        db.scalar(select(NoticeRuleBand).where(NoticeRuleBand.position == 4)).notice_days = 95
    db.commit()
    response = client.post("/app/calculations", data=data, follow_redirects=False)
    assert response.status_code == 409
    with pytest.raises(HTTPException) as exc:
        _revalidate_calculation_before_approval(item, db)
    assert exc.value.status_code == 409
    assert db.scalar(select(func.count(CalculationRecord.id))) == 1


@pytest.mark.parametrize("mutation", ["amount", "days", "results", "reference", "override"])
def test_persisted_snapshot_tampering_blocks_approval(notice_case, mutation):
    client, db, *_ = notice_case
    assert client.post("/app/calculations", data=form(notice_case), follow_redirects=False).status_code == 303
    item = latest(notice_case)
    inputs, results = json.loads(item.input_json), json.loads(item.result_json)
    if mutation == "amount":
        item.amount += 1
    elif mutation == "days":
        inputs["days"] = 0
    elif mutation == "results":
        results["daily_value"] += 1
    elif mutation == "reference":
        item.reference_period = "2025-01"
    else:
        inputs["notice_override"] = {"days": 90, "role": "contador"}
    item.input_json, item.result_json = json.dumps(inputs), json.dumps(results)
    with pytest.raises(HTTPException) as exc:
        _revalidate_calculation_before_approval(item, db)
    assert exc.value.status_code == 409


@pytest.mark.parametrize("problem", ["missing", "overlap", "no_final", "unordered"])
def test_invalid_scale_does_not_silently_return_zero(notice_case, problem):
    _, db, *_ = notice_case
    rule = db.scalar(select(NoticeRuleSet))
    if problem == "missing":
        rule.active = False
    elif problem == "overlap":
        db.add(NoticeRuleSet(code="OVERLAP_TEST", jurisdiction="PY", effective_from=date(2026, 1, 1), active=True,
                            legal_basis="Synthetic test", source_url="https://example.invalid"))
    elif problem == "no_final":
        rule.bands[-1].max_service_months = 240
    else:
        rule.bands[0].max_service_months = 100
    db.commit()
    response = proposal(notice_case)
    assert response.status_code == 422 and "escala" in response.json()["detail"]


def test_reference_version_switch_and_single_final_money_rounding(notice_case):
    _, db, _, _, employee, _ = notice_case
    original = db.scalar(select(NoticeRuleSet))
    original.effective_to = date(2026, 12, 31)
    future = NoticeRuleSet(code="SYNTHETIC_FUTURE", jurisdiction="PY", effective_from=date(2027, 1, 1), active=True,
                           legal_basis="Synthetic test only", source_url="https://example.invalid",
                           bands=[NoticeRuleBand(position=1, max_service_months=None, notice_days=100)])
    db.add(future)
    db.commit()
    assert notice_proposal(db, employee, date(2026, 12, 31))["days"] == 90
    assert notice_proposal(db, employee, date(2027, 1, 1))["days"] == 100
    results = notice_results(Decimal("3185221.66"), 90, "test")
    assert results["total"] == 9_555_665  # full precision base / 30, rounded only at the end
    assert notice_results(Decimal("3044000"), 90, "test")["total"] == 9_132_000
    assert reference_date_from({"reference_period": "2024-02"}) == date(2024, 2, 29)


@pytest.mark.parametrize("base", ["NaN", "Infinity", "-1", "2.001", "2147483648", ""])
def test_invalid_base_is_rejected(notice_case, base):
    response = notice_case[0].post("/app/calculations", data=form(notice_case, salary=base), follow_redirects=False)
    assert response.status_code == 422


def test_cents_base_survives_save_approval_and_certificate_api(notice_case):
    client, db, box, company, employee, _ = notice_case
    response = client.post("/app/calculations", data=form(notice_case, salary="3185221.66"), follow_redirects=False)
    assert response.status_code == 303, response.text
    item = latest(notice_case)
    assert item.amount == 9_555_665 and json.loads(item.input_json)["monthly_average_base"] == "3185221.66"
    _revalidate_calculation_before_approval(item, db)
    linked = client.get("/api/certificates/preaviso-calculations", params={"company_id": company.id, "employee_id": employee.id})
    assert linked.status_code == 200
    assert linked.json()["calculations"][0]["days"] == 90


def test_migration_is_idempotent_with_precreated_tables_and_preserves_custom_rules(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    Base.metadata.create_all(engine)
    path = next((Path(__file__).parents[1] / "alembic" / "versions").glob("0021_*.py"))
    spec = importlib.util.spec_from_file_location("migration_notice", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            mod.upgrade()
            first = list(connection.execute(select(NoticeRuleBand.notice_days)))
            connection.execute(NoticeRuleBand.__table__.update().where(NoticeRuleBand.position == 4).values(notice_days=95))
            mod.upgrade()
        assert connection.scalar(select(func.count(NoticeRuleSet.id))) == 1
        assert len(first) == connection.scalar(select(func.count(NoticeRuleBand.id))) == 4
        assert connection.scalar(select(NoticeRuleBand.notice_days).where(NoticeRuleBand.position == 4)) == 95
    engine.dispose()
