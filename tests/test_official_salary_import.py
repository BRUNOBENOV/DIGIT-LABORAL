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
        termination_date=None, status="Activo", ips_contributor=True,
    )
    detail = SimpleNamespace(
        days_worked=30, hours_worked=Decimal("176"), payment_method="Transferencia",
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


def test_reop_payment_codes_export_as_official_numeric_values(monkeypatch):
    company, _, _, _ = fixture_records(monkeypatch)
    from openpyxl import load_workbook

    for code, label in (
        ("1", "Efectivo"),
        ("2", "Cheque"),
        ("3", "Banco"),
        ("4", "Giro"),
    ):
        rows, errors = service.prepare_import(
            None, company, "2026-10", "REOP", payment_code=code
        )
        assert not errors, f"{label}: {errors}"
        assert rows[0][4] == int(code)
        workbook = load_workbook(io.BytesIO(service.build_reop_xlsx(rows)), read_only=True)
        assert workbook.active.cell(2, 5).value == int(code)
        workbook.close()


def test_reop_payment_selector_names_are_visible_to_accountant():
    from pathlib import Path
    template = (Path(__file__).resolve().parents[1] / "app/templates/salary_import.html").read_text(
        encoding="utf-8"
    )
    for option in ("('1','Efectivo')", "('2','Cheque')",
                   "('3','Banco (depósito o transferencia)')", "('4','Giro')"):
        assert option in template
    assert "Código {{ value }} — confirmar significado en REOP" not in template


def test_rei_2016_tabbed_text_no_headers(monkeypatch):
    company, _, _, _ = fixture_records(monkeypatch)
    rows, errors = service.prepare_import(SimpleNamespace(scalar=lambda query: None), company, "2026-10", "REI",
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
    _, errors = service.prepare_import(SimpleNamespace(scalar=lambda query: None), company, "2026-10", "REI",
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


def test_invalid_payroll_hours_are_reported_without_crashing(monkeypatch):
    company, _, _, detail = fixture_records(monkeypatch)
    for invalid in ("NaN", "Infinity", "-1", "745"):
        detail.hours_worked = Decimal(invalid)
        rows, errors = service.prepare_import(None, company, "2026-10", "REOP", payment_code="1")
        assert any("horas trabajadas inválida" in error for error in errors)
        assert len(rows) == 1 and rows[0][7] == 0


def test_rei_payroll_filters_ips_no_inactive_and_archived_without_blocking(monkeypatch):
    company, line, employee, detail = fixture_records(monkeypatch)
    non_ips = SimpleNamespace(**vars(employee))
    non_ips.id, non_ips.ips_contributor = 4, False
    non_ips.document_number = "2222222"
    inactive = SimpleNamespace(**vars(employee))
    inactive.id, inactive.status = 5, "Desvinculado"
    inactive.document_number = "3333333"
    archived = SimpleNamespace(**vars(employee))
    archived.id, archived.status = 6, "Archivado"
    archived.document_number = "4444444"
    source_lines = [(line, person, detail) for person in (employee, non_ips, inactive, archived)]
    monkeypatch.setattr(service, "_source", lambda db, company, period:
                        (SimpleNamespace(status="Cerrada"), source_lines))
    db = SimpleNamespace(scalar=lambda query: None)
    rei_rows, errors = service.prepare_import(
        db, company, "2026-10", "REI", source_type="payroll",
        name_order="apellido_primero", rei_category="E",
    )
    assert not errors
    assert len(rei_rows) == 1
    assert rei_rows[0][2] == employee.document_number
    assert rei_rows[0][7] == line.ips_base
    reop_rows, reop_errors = service.prepare_import(
        db, company, "2026-10", "REOP", source_type="payroll",
        payment_code="1",
    )
    assert not reop_errors
    assert len(reop_rows) == 4


def test_rei_does_not_export_inactive_or_ips_no_employee_even_with_loaded_salary(monkeypatch):
    company, _line, employee, _detail = fixture_records(monkeypatch)
    db = SimpleNamespace(scalar=lambda query: None)
    employee.ips_contributor = False
    rows, errors = service.prepare_import(
        db, company, "2026-10", "REI",
        name_order="apellido_primero", rei_category="E",
    )
    assert rows == []
    assert any("no hay salarios guardados de funcionarios activos con IPS marcado Sí" in e for e in errors)
    employee.ips_contributor = True
    employee.status = "Desvinculado"
    rows, errors = service.prepare_import(
        db, company, "2026-10", "REI",
        name_order="apellido_primero", rei_category="E",
    )
    assert rows == []
    assert any("no hay salarios guardados" in e for e in errors)


def test_rei_never_uses_employee_base_salary_without_saved_salary_record(monkeypatch):
    company, _line, employee, _detail = fixture_records(monkeypatch)
    employee.base_salary = 3044000
    monkeypatch.setattr(service, "_source", lambda db, company, period:
                        (SimpleNamespace(status="Cerrada"), []))
    rows, errors = service.prepare_import(
        None, company, "2026-10", "REI", name_order="apellido_primero",
        rei_category="E", source_type="payroll",
    )
    assert rows == []
    assert any("no hay salarios guardados" in e for e in errors)
