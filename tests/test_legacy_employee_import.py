from __future__ import annotations

from datetime import date, datetime
from io import BytesIO

from openpyxl import Workbook

from app.legacy_employee_import import parse_legacy_employee_workbook


def _book_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "BASE DE DATOS TRABAJADORES"
    headers = [
        "CODTRA", "NOMTRA", "APETRA", "CODEMP", "CODSEC", "CEDIDE",
        "ENTMAN", "SALMAN", "ENTTAR", "SALTAR", "ESTCIV", "NACION",
        "FECNAC", "LUGNAC", "PROFES", "DOMACT", "SEXOXX", "CIUDAD",
        "TELEFO", "NUMIPS", "IPSXXX", "OCUPAC", "CANHIJ", "SALACT",
        "FECENT", "FECSAL",
    ]
    sheet.append(headers)
    sheet.append([
        "10001", "ANA", "PEREZ", "1001", "001", "1234567",
        "08:00", "12:00", "13:00", "17:00", "S", "Paraguaya",
        datetime(2000, 1, 1), "CDE", "Comerciante", "Centro", "F", "CDE",
        "061000000", "12345", "S", "Vendedora", "1", 1500000,
        datetime(2020, 1, 2), datetime(2021, 1, 2),
    ])
    sheet.append([
        "10002", "ANA", "PEREZ", "1001", "001", "1234567",
        "08:00", "12:00", "13:00", "17:00", "S", "Paraguaya",
        datetime(2025, 1, 1), "CDE", "Comerciante", "Centro", "F", "CDE",
        "061000000", "12345", "S", "Vendedora", "1", 2500000,
        datetime(2022, 2, 3), None,
    ])
    sheet.append([
        "10003", "LUIS", "VERA", "1001", "001", "0",
        None, None, None, None, "C", "Paraguaya",
        None, None, "Operario", "Barrio", "M", "CDE",
        None, None, "N", "Operario", "0", 1800000,
        datetime(2019, 3, 1), datetime(2019, 12, 1),
    ])
    sheet.append([
        "10004", None, None, "1001", "001", "1234568",
        None, None, None, None, None, "Paraguaya",
        None, None, None, None, None, None, None, None, "N",
        "Auxiliar", "0", 1500000, datetime(2018, 1, 1), datetime(2018, 6, 1),
    ])
    sheet.append([
        "10005", "MARTA", "GOMEZ", "1001", "001", "1234569",
        None, None, None, None, None, "Paraguaya",
        None, None, "Comerciante", None, "F", "CDE",
        None, None, "N", "Vendedora", "0", 1500000, None, datetime(2018, 6, 1),
    ])
    sheet.append([
        "10006", "CARLOS", "DIAZ", "1002", "001", "9988776",
        None, None, None, None, None, "Paraguaya",
        None, None, "Operario", None, "M", "CDE",
        None, None, "N", "Operario", "0", 2000000,
        datetime(2017, 5, 1), datetime(2018, 5, 1),
    ])
    sheet.append([
        "10007", "JOSE", "LOPEZ", "1001", "001", "7777777",
        None, None, None, None, None, "Paraguaya",
        None, None, "Operario", None, "M", "CDE",
        None, None, "N", "Operario", "0", 2000000,
        datetime(2020, 5, 1), datetime(2019, 5, 1),
    ])
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def test_legacy_import_groups_rehires_and_preserves_history_without_duplicate_people():
    """Consolidate rehires and reject untrustworthy dates without losing the timeline."""
    company_map = {
        "1001": [{
            "id": 11, "name": "Empresa Uno", "status": "Activa",
            "branch_id": 21, "department": "Alto Paraná",
        }],
        "1002": [
            {"id": 12, "name": "Empresa Dos", "status": "Activa", "branch_id": 22, "department": ""},
            {"id": 13, "name": "Otra Empresa Dos", "status": "Activa", "branch_id": 23, "department": ""},
        ],
    }
    result = parse_legacy_employee_workbook(
        _book_bytes(), "trabajadores.xlsx", company_map, today=date(2026, 10, 30)
    )

    assert result["summary"]["source_rows"] == 7
    assert result["summary"]["identity_groups"] == 6
    assert result["summary"]["importable"] == 3
    assert result["summary"]["excluded"] == 3
    assert result["summary"]["active"] == 1
    assert result["summary"]["terminated"] == 2
    assert result["summary"]["invalid_termination_dates"] == 1
    assert result["summary"]["repeated_identity_groups"] == 1
    assert result["summary"]["without_cedula"] == 1

    ana = next(item for item in result["candidates"] if item["full_name"] == "ANA PEREZ")
    assert ana["document_number"] == "1234567"
    assert ana["status"] == "Activo"
    assert ana["admission_date"] == "2022-02-03"
    assert ana["base_salary"] == 2500000
    assert ana["termination_date"] is None
    assert [event["event_type"] for event in ana["events"]] == [
        "Ingreso histórico", "Egreso histórico", "Reingreso histórico"
    ]
    assert ana["profile"]["work_schedule"].startswith("Mañana: 08:00–12:00")

    luis = next(item for item in result["candidates"] if item["full_name"] == "LUIS VERA")
    assert luis["document_number"] == "S/D-1001-10003"
    assert luis["synthetic_document"] is True
    assert luis["status"] == "Desvinculado"
    assert luis["termination_date"] == "2019-12-01"

    jose = next(item for item in result["candidates"] if item["full_name"] == "JOSE LOPEZ")
    assert jose["status"] == "Desvinculado"
    assert jose["termination_date"] is None
    assert "fechas de egreso" in jose["notes"]

    reasons = {item["reason"] for item in result["excluded"]}
    assert any("nombre" in reason.lower() for reason in reasons)
    assert any("fecha de ingreso" in reason.lower() for reason in reasons)
    assert any("código patronal" in reason.lower() for reason in reasons)


def test_legacy_import_rejects_non_xlsx_and_missing_company_mapping():
    try:
        parse_legacy_employee_workbook(b"not an xlsx", "trabajadores.csv", {})
    except ValueError as exc:
        assert ".xlsx" in str(exc)
    else:
        raise AssertionError("CSV must not be accepted by the legacy workbook importer")
