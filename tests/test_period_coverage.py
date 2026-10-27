from __future__ import annotations

from datetime import date

from app.period_coverage import build_annual_coverage, expected_months


def test_expected_months_only_cover_employment_and_elapsed_months():
    assert expected_months(
        2026,
        date(2026, 2, 15),
        date(2026, 4, 10),
        today=date(2026, 10, 27),
    ) == ["2026-02", "2026-03", "2026-04"]


def test_current_year_does_not_expect_future_periods():
    assert expected_months(
        2026, date(2025, 6, 1), today=date(2026, 3, 5)
    ) == ["2026-01", "2026-02", "2026-03"]


def test_coverage_sums_only_closed_consistent_payrolls():
    report = build_annual_coverage(
        year=2026,
        admission_date=date(2026, 1, 1),
        termination_date=None,
        today=date(2026, 4, 15),
        payroll_by_period={
            "2026-01": {
                "status": "Cerrada",
                "gross": 2_000_000,
                "base_salary": 1_800_000,
                "amounts_consistent": True,
            },
            "2026-02": {
                "status": "Borrador",
                "gross": 2_100_000,
                "base_salary": 1_800_000,
                "amounts_consistent": True,
            },
            "2026-04": {
                "status": "Cerrada",
                "gross": 2_500_000,
                "base_salary": 1_800_000,
                "amounts_consistent": False,
            },
        },
        saved_salary_periods={"2026-03"},
    )

    assert report["expected_count"] == 4
    assert report["closed_count"] == 1
    assert report["open_count"] == 1
    assert report["missing_count"] == 1
    assert report["inconsistent_count"] == 1
    assert report["suggested_total"] == 2_000_000
    assert report["is_complete"] is False
    assert report["periods"][1]["status"] == "Nómina abierta"
    assert report["periods"][2]["status"] == "Solo cálculo guardado"
    assert report["periods"][3]["gross"] is None


def test_salary_variation_is_flagged_and_never_called_legal_base():
    report = build_annual_coverage(
        year=2025,
        admission_date=date(2025, 1, 1),
        termination_date=None,
        today=date(2026, 10, 27),
        payroll_by_period={
            "2025-01": {
                "status": "Cerrada",
                "gross": 2_000_000,
                "base_salary": 1_800_000,
                "amounts_consistent": True,
            },
            "2025-02": {
                "status": "Cerrada",
                "gross": 2_200_000,
                "base_salary": 2_000_000,
                "amounts_consistent": True,
            },
        },
    )
    assert report["salary_changes_detected"] is True
    assert report["suggested_total"] == 4_200_000
    assert "No constituye automáticamente la base legal" in report["legal_note"]


def test_period_coverage_screen_is_protected_and_renders():
    import re

    from fastapi.testclient import TestClient
    from app.config import settings
    from app.main import app

    with TestClient(app) as client:
        anonymous = client.get("/app/calculations/periodos", follow_redirects=False)
        assert anonymous.status_code in {302, 303, 307, 401, 403}

        login_page = client.get("/login")
        token = re.search(r'name="csrf_token" value="([^"]+)"', login_page.text)
        assert login_page.status_code == 200 and token
        login = client.post(
            "/login",
            data={
                "email": "admin@digitlaboral.com.py",
                "password": settings.demo_admin_password,
                "csrf_token": token.group(1),
            },
            follow_redirects=False,
        )
        assert login.status_code == 303

        response = client.get("/app/calculations/periodos")
        assert response.status_code == 200
        assert "Cobertura de períodos" in response.text
        assert "Seleccioná un funcionario" in response.text or "Elegí un funcionario" in response.text
