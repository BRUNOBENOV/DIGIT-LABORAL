"""Importación no destructiva de planillas REOP en Cálculo → Salarios."""
from __future__ import annotations

import io
import json
import re
import uuid
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import CalculationRecord, Company, Employee, User
from app.official_salary_import import REOP_HEADERS
from app.reop_salary_ingest import parse_reop_workbook, MAX_FILE_BYTES


def _excel_rows(*, start=date(2026, 10, 1), year=2026, duplicate_night=True,
                ci=7654321, patronal=97163, extra_rows=()):
    row = [0] * 32
    row[:9] = [patronal, ci, start, date(year, 10, 31), 1, 30, 0, 216, 12.905545335085414]
    row[9] = 3_000_000
    row[10] = 200_000
    row[11] = 50_000
    row[12] = 3_250_000 if duplicate_night else 100_000
    row[25] = 292500.05
    row[27] = None
    row[29] = None
    row[31] = None
    return [row, *extra_rows]


def _workbook(rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "Hoja1"
    ws.append(list(REOP_HEADERS))
    for row in rows:
        ws.append(row)
    out = io.BytesIO()
    wb.save(out)
    wb.close()
    return out.getvalue()


def test_reop_preview_blocks_total_duplicated_in_nocturnal_column_by_default():
    blob = _workbook(_excel_rows())
    preview = parse_reop_workbook(blob, "source.xlsx")
    assert preview["source_rows"] == 1
    row = preview["rows"][0]
    assert row["period"] == "2026-10"
    assert any("TOTAL BRUTO duplicado" in issue for issue in row["errors"])
    assert row["gross"] == 6_500_000
    assert row["payment_method"] == "Efectivo"


def test_explicit_duplicate_total_option_prevents_double_count_and_rounds_ips():
    blob = _workbook(_excel_rows())
    row = parse_reop_workbook(blob, "source.xlsx", night_column_is_total=True)["rows"][0]
    assert row["errors"] == []
    assert row["gross"] == 3_250_000
    assert row["discounts"] == 292500
    assert row["net"] == 2_957_500
    assert row["night_total_control"] == 3_250_000
    assert len(row["earnings"]) == 3
    assert all(item["label"] != "Recargo horario Nocturno" for item in row["earnings"])


def test_real_night_surcharge_is_preserved_when_not_duplicate():
    row = parse_reop_workbook(_workbook(_excel_rows(duplicate_night=False)),
                              "source.xlsx")["rows"][0]
    assert row["errors"] == []
    assert row["gross"] == 3_350_000
    assert any(item["label"] == "Recargo horario Nocturno" for item in row["earnings"])


def test_excel_swapped_day_month_needs_explicit_opt_in():
    blob = _workbook(_excel_rows(start=date(2026, 1, 10)))
    default = parse_reop_workbook(blob, "source.xlsx", night_column_is_total=True)["rows"][0]
    assert default["errors"]
    assert any("inversión día/mes" in issue for issue in default["errors"])
    corrected = parse_reop_workbook(blob, "source.xlsx",
        night_column_is_total=True, correct_swapped_start=True)["rows"][0]
    assert corrected["errors"] == []
    assert corrected["period_start"] == "2026-10-01"
    assert corrected["period"] == "2026-10"


def test_mixed_periods_are_supported_without_blending_months():
    second = _excel_rows(start=date(2025, 10, 1), year=2025, ci=7654322)[0]
    result = parse_reop_workbook(_workbook(_excel_rows(extra_rows=[second])),
                                "source.xlsx", night_column_is_total=True)
    assert [row["period"] for row in result["rows"]] == ["2026-10", "2025-10"]


def test_duplicate_ci_period_and_malformed_file_are_rejected():
    row = _excel_rows()[0]
    parsed = parse_reop_workbook(_workbook([row, row]), "source.xlsx",
                                 night_column_is_total=True)
    assert any("duplicado dentro" in x for x in parsed["rows"][1]["errors"])
    with pytest.raises(ValueError, match="5 MB"):
        parse_reop_workbook(b"A" * (MAX_FILE_BYTES + 1), "source.xlsx")
    with pytest.raises(ValueError):
        parse_reop_workbook(b"invalid", "source.xlsx")


def _login(client):
    page = client.get("/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    response = client.post("/login",
        data={"email":"admin@digitlaboral.com.py","password":settings.demo_admin_password,"csrf_token":token},
        follow_redirects=False)
    assert response.status_code == 303
    return token


def _test_company():
    doc = str(1_000_000 + uuid.uuid4().int % 8_000_000)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "admin@digitlaboral.com.py"))
        assert user and user.studio_id
        company = Company(studio_id=user.studio_id,
            legal_name="Empresa REOP de prueba " + uuid.uuid4().hex[:7],
            ruc="89999999-0", mtess_employer_number="97163")
        db.add(company)
        db.flush()
        worker = Employee(company_id=company.id, full_name="Funcionario REOP de prueba",
            document_number=doc, admission_date=date(2024, 1, 1),
            base_salary=3_000_000, ips_contributor=True)
        db.add(worker)
        db.commit()
        return company.id, worker.id, int(doc)


def test_upload_preview_confirm_creates_draft_once_with_correct_provenance():
    company_id, employee_id, ci = _test_company()
    # Intentionally ambiguous workbook, requiring both explicit options.
    blob = _workbook(_excel_rows(start=date(2026, 1, 10), ci=ci))
    url = "/app/liquidaciones/salarios/importar-reop"
    with TestClient(app) as client:
        _login(client)
        before = client.get(url)
        assert before.status_code == 200
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', before.text).group(1)
        assert "Importar planilla salarial desde REOP" in before.text
        assert 'type="checkbox"' not in before.text
        upload = client.post(url + "/previsualizar", data={
            "csrf_token": csrf, "company_id": str(company_id),
        }, files={"file":("reop.xlsx",blob,"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        follow_redirects=False)
        assert upload.status_code == 303, upload.text[:400]
        preview_url = upload.headers["location"]
        preview = client.get(preview_url)
        assert preview.status_code == 200
        assert "Fechas DESDE invertidas" in preview.text
        assert "Posible total bruto" in preview.text
        assert "2026-10 · pendiente" in preview.text
        assert 'type="checkbox"' not in preview.text
        assert "3.250.000" in preview.text
        # Resoluciones separadas: antes de autorizarlas no hay salario apto.
        dates = client.post(preview_url + "/resolver",
            data={"csrf_token": csrf, "action": "fecha_invertida"},
            follow_redirects=False)
        assert dates.status_code == 303
        assert "Fechas revisadas" in client.get(preview_url).text
        night = client.post(preview_url + "/resolver",
            data={"csrf_token": csrf, "action": "total_nocturno"},
            follow_redirects=False)
        assert night.status_code == 303
        assert "APTA" in client.get(preview_url).text
        with SessionLocal() as db:
            assert not db.scalar(select(CalculationRecord.id).where(
                CalculationRecord.company_id == company_id,
                CalculationRecord.employee_id == employee_id))
        confirmation = client.post(preview_url+"/confirmar",
              data={"csrf_token":csrf,"confirm":"true"},follow_redirects=False)
        assert confirmation.status_code == 303
        with SessionLocal() as db:
            record = db.scalar(select(CalculationRecord).where(
                CalculationRecord.company_id == company_id,
                CalculationRecord.employee_id == employee_id,
                CalculationRecord.reference_period == "2026-10"))
            assert record is not None
            assert record.status == "Borrador"
            assert record.source == "Importación Excel REOP"
            assert record.amount == 2_957_500
            result = json.loads(record.result_json)
            inputs = json.loads(record.input_json)
            assert result["gross"] == 3_250_000
            assert inputs["reop_import_source_row"] == 2
            assert inputs["reop_original_night_total_control"] == 3_250_000
            assert inputs["period_start"] == "2026-10-01"
            assert inputs["payment_method"] == "Efectivo"
        assert client.get(preview_url).status_code == 410
        reupload = client.post(url + "/previsualizar", data={
            "csrf_token": csrf, "company_id": str(company_id),
        }, files={"file":("reop.xlsx",blob,"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        follow_redirects=False)
        next_preview = reupload.headers["location"]
        assert client.post(next_preview + "/resolver", data={
            "csrf_token": csrf, "action": "fecha_invertida"}, follow_redirects=False).status_code == 303
        assert client.post(next_preview + "/resolver", data={
            "csrf_token": csrf, "action": "total_nocturno"}, follow_redirects=False).status_code == 303
        check = client.get(next_preview)
        assert "YA EXISTE" in check.text
        assert "No se sobrescribe" in check.text


def test_reop_realistic_file_without_nocturnal_surcharge_only_suggests_date_fix():
    first = _excel_rows(start=date(2026, 1, 10), duplicate_night=False)[0]
    first[12] = 0
    second = _excel_rows(start=date(2025, 1, 10), year=2025, ci=7654322, duplicate_night=False)[0]
    second[12] = 0
    payload = parse_reop_workbook(_workbook([first, second]), "octubre.xlsx")
    assert payload["source_rows"] == 2
    assert all(row["date_swap_proposal"] for row in payload["rows"])
    assert all(row["night_total_proposal"] is None for row in payload["rows"])
    assert [row["period_hint"] for row in payload["rows"]] == ["2026-10", "2025-10"]
    resolved = parse_reop_workbook(_workbook([first, second]), "octubre.xlsx",
                                  correct_swapped_start=True)
    assert [row["period"] for row in resolved["rows"]] == ["2026-10", "2025-10"]
    assert all(not row["errors"] for row in resolved["rows"])
