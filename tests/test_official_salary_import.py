"""Pruebas contractuales de importación: columnas, importes, controles y TXT."""
from __future__ import annotations

import csv
import io
import zipfile
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from xml.etree import ElementTree

from app import official_salary_import as service


def fixture_records(monkeypatch, *, override=None):
    values = dict(
        base_salary=3000000, overtime=0, commissions=0, bonuses=0, other_income=0,
        absences_discount=0, advances=0, other_discount=0, ips_employee=270000,
        ips_base=3000000, ips_rate=Decimal("9.00"),
        other_discount_note="", gross=3000000, total_discounts=270000, net=2730000,
    )
    values.update(override or {})
    line = SimpleNamespace(**values)
    employee = SimpleNamespace(
        id=3, employee_code=9, company_id=1, branch_id=None,
        full_name="PEREZ GOMEZ JUAN LUIS", document_number="1234567",
        payment_frequency="Mensual", admission_date=date(2020, 1, 1),
        termination_date=None, ips_contributor=True,
    )
    detail = SimpleNamespace(
        days_worked=30, hours_worked=Decimal("176"),
        period_start=date(2026, 10, 1), period_end=date(2026, 10, 31),
        overtime_day=0, overtime_night=0, night_surcharge=0,
        holidays=0, family_allowance=0, other_income_detail=0, vacation_pay=0,
    )
    company = SimpleNamespace(id=1, ruc="80000000-1",
                              mtess_employer_number="0000123", ips_employer_number="0000456")
    monkeypatch.setattr(service, "_source", lambda db, company, period:
                        (SimpleNamespace(status="Cerrada"), [(line, employee, detail)]))
    monkeypatch.setattr(service, "_patronal", lambda db, company, employee, authority:
                        company.mtess_employer_number if authority == "REOP" else company.ips_employer_number)
    return company, line, employee, detail


def test_reop_32_exact_columns_and_excel_dates(monkeypatch):
    company, _, _, _ = fixture_records(monkeypatch)
    rows, errors = service.prepare_import(None, company, "2026-10", "REOP", payment_code="1")
    assert not errors
    assert len(rows) == 1 and len(rows[0]) == 32
    assert rows[0][0] == "0000123" and rows[0][1] == "1234567"
    assert rows[0][9] == 3000000 and rows[0][25] == 270000
    data = service.build_reop_xlsx(rows)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = ElementTree.fromstring(z.read("xl/worksheets/sheet1.xml"))
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        result = xml.findall("m:sheetData/m:row", ns)
        assert len(result) == 2
        header = [cell.find("m:is/m:t", ns).text for cell in result[0]]
        assert header == list(service.REOP_HEADERS)
        cells = {c.attrib["r"]: c for c in result[1]}
        assert cells["A2"].find("m:is/m:t", ns).text == "0000123"
        assert cells["C2"].attrib["s"] == "1"
        assert int(cells["C2"].find("m:v", ns).text) > 46000


def test_rei_2016_tabbed_text_no_headers(monkeypatch):
    company, _, _, _ = fixture_records(monkeypatch)
    rows, errors = service.prepare_import(None, company, "2026-10", "REI",
                                          name_order="apellido_primero", rei_category="E")
    assert errors == []
    data = service.build_rei_txt(rows)
    assert data.endswith(b"\r\n")
    result = list(csv.reader(io.StringIO(data.decode("cp1252")), delimiter="\t"))
    assert len(result) == 1 and len(result[0]) == 11
    assert result[0] == [
        "0000456", "", "1234567", "PEREZ GOMEZ", "JUAN LUIS", "E",
        "30", "3000000", "102026", "", "3000000",
    ]


def test_inconsistent_ips_base_is_blocked(monkeypatch):
    company, _, _, _ = fixture_records(monkeypatch, override={"ips_base": 1000000})
    _, errors = service.prepare_import(None, company, "2026-10", "REI",
                                       name_order="apellido_primero", rei_category="E")
    assert any("base IPS" in item for item in errors)


def test_unclassified_reop_other_income_is_blocked(monkeypatch):
    company, line, _, _ = fixture_records(monkeypatch)
    line.bonuses = 250000
    line.gross += 250000
    line.net += 250000
    rows, errors = service.prepare_import(None, company, "2026-10", "REOP",
                                          payment_code="1")
    assert len(rows) == 1
    assert any("otros ingresos no clasificados" in item for item in errors)
    rows, errors = service.prepare_import(None, company, "2026-10", "REOP",
                                          payment_code="1", other_category="premios")
    assert not errors
    assert rows[0][14] == 250000
    assert rows[0][9] + rows[0][14] == line.gross


def test_missing_details_blocked(monkeypatch):
    company, _, _, _ = fixture_records(monkeypatch)
    monkeypatch.setattr(service, "_source", lambda db, c, period: (
        SimpleNamespace(status="Cerrada"),
        [(SimpleNamespace(
            base_salary=3000000, overtime=0, commissions=0, bonuses=0,
            other_income=0, absences_discount=0, advances=0, other_discount=0,
            ips_employee=270000, ips_base=3000000, ips_rate=Decimal("9"),
            gross=3000000, total_discounts=270000, net=2730000,
            other_discount_note="",
        ), SimpleNamespace(
            id=3, employee_code=3, full_name="PEREZ JUAN",
            document_number="1234567", branch_id=None, admission_date=date(2020, 1, 1),
            termination_date=None, payment_frequency="Mensual", ips_contributor=True,
        ), None)]
    ))
    _, errors = service.prepare_import(None, company, "2026-10", "REOP", payment_code="1")
    assert any("falta el detalle" in item for item in errors)
