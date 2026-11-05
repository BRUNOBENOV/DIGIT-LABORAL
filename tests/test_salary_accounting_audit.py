"""No importa ni muta sueldos: valida una planilla contable en vista previa."""
from io import BytesIO

import pytest
from openpyxl import Workbook

from app.salary_accounting_audit import (
    AccountingPayrollError, reconcile_accounting_payroll,
)
from tests.test_labor_suite import web_case, token


def workbook_bytes(*, mismatch=True):
    wb = Workbook()
    sh = wb.active
    sh.title = "OCTUBRE"
    sh["B2"] = "EMPRESA PRUEBA A - COMISIONES CONTABILIDAD 10/2026"
    sh["B3"] = "EMPLEADOS"
    sh["D3"] = "SALARIO MENSUAL CONTABILIDAD"
    sh["B4"], sh["C4"] = 1, "TRABAJADOR A PRUEBA"
    data = [3_044_000, 351_168, 14_063, 3_409_231, 306_831, 562_523.115]
    for col, value in zip("DEFGHI", data):
        sh[f"{col}4"] = value
    sh["B5"], sh["C5"] = 2, "TRABAJADOR B PRUEBA"
    data = [3_044_000, 2_414_170, 0, 5_458_170, 375_990 if mismatch else 491_235.30, 900_598.05]
    for col, value in zip("DEFGHI", data):
        sh[f"{col}5"] = value
    sh["B7"] = "EMPRESA PRUEBA B - COMISIONES CONTABILIDAD 10/2026"
    sh["B8"], sh["D8"] = "EMPLEADOS", "SALARIO MENSUAL CONTABILIDAD"
    sh["B9"], sh["C9"] = 1, "TRABAJADOR C PRUEBA"
    for col, value in zip("DEFGHI", [0, 0, 0, 0, 0, 0]):
        sh[f"{col}9"] = value
    stream = BytesIO()
    wb.save(stream)
    return stream.getvalue()


def test_reconciles_two_companies_and_blocks_inconsistent_ips_without_changing_data():
    report = reconcile_accounting_payroll(workbook_bytes(), period="2026-10")
    assert report["companies"] == 2
    assert report["workers"] == 3
    assert report["workers_paid"] == 2
    assert report["gross"] == 3_409_231 + 5_458_170
    assert report["errors"] == 1
    bad = report["groups"][0]["rows"][1]
    assert bad["ips_worker"] == 375_990
    assert bad["expected_ips_worker"] == 491_235
    assert any("IPS obrero" in msg for msg in bad["errors"])
    assert "Sin remuneración" in report["groups"][1]["rows"][0]["warnings"][0]


def test_verified_ips_is_not_flagged_with_fractional_source_guaranies():
    report = reconcile_accounting_payroll(workbook_bytes(mismatch=False), period="2026-10")
    assert report["errors"] == 0
    assert report["groups"][0]["rows"][1]["expected_ips_employer"] == 900_598


@pytest.mark.parametrize("payload,period", [
    (b"not an xlsx", "2026-10"), (b"", "2026-10"),
    (b"x" * (2*1024*1024+1), "2026-10"),
    (b"not xlsx", "2026-13"),
])
def test_invalid_uploads_are_rejected(payload, period):
    with pytest.raises(AccountingPayrollError):
        reconcile_accounting_payroll(payload, period=period)


def test_accounting_preview_is_private_and_does_not_create_calculations(web_case):
    client, db, *_ = web_case
    payload = workbook_bytes()
    from app.models import CalculationRecord
    from sqlalchemy import select, func
    original = db.scalar(select(func.count(CalculationRecord.id)))
    page = client.get("/app/liquidaciones/conciliar-planilla")
    assert page.status_code == 200
    assert "Conciliar planilla contable" in page.text
    response = client.post(
        "/app/liquidaciones/conciliar-planilla",
        data={"csrf_token": token(client), "period": "2026-10"},
        files={"upload": ("sueldo-octubre.xlsx", payload, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200, response.text[:450]
    assert "TRABAJADOR B PRUEBA" in response.text
    assert "IPS obrero" in response.text
    db.expire_all()
    assert db.scalar(select(func.count(CalculationRecord.id))) == original
