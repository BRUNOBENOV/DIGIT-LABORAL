"""Download complete REOP/REI files through the actual authenticated POST route."""
import hashlib
import io
import json
import zipfile

import pytest
from bs4 import BeautifulSoup
from openpyxl import load_workbook
from sqlalchemy import func, select

from app import main as core
from app.models import AuditLog, CalculationRecord, Employee, IntegrationBatch
from app.official_salary_import import MIME_REI, MIME_REOP, REOP_HEADERS
from app.storage_service import LocalStorage
from tests.test_labor_suite import token, web_case
from tests.test_salary_attendance_flow import attendance_case


@pytest.fixture
def download_case(attendance_case, monkeypatch, tmp_path):
    monkeypatch.setattr(core, "storage", LocalStorage(tmp_path / "downloads"))
    return attendance_case


def data(case, **changes):
    client, _, _, company, employee, *_ = case
    return dict({"csrf_token": token(client), "company_id": company.id, "employee_id": employee.id,
                 "period": "2026-10", "authority": "REOP", "payment_code": "1",
                 "source_type": "auto", "confirmed": "si"}, **changes)


@pytest.mark.parametrize("authority,mime,extension", [("REOP", MIME_REOP, "xlsx"), ("REI", MIME_REI, "txt")])
def test_salary_file_download_preserves_bytes_attendance_audit_and_source(download_case, authority, mime, extension):
    client, db, _, company, employee, _, source = download_case
    original = source.input_json, source.result_json, source.amount, source.status
    # fetch(FormData) uses multipart, while the no-JS fallback is URL-encoded.
    fields = data(download_case, authority=authority, name_order="apellido_primero", rei_category="E")
    response = client.post("/app/compliance/salary-import/export",
        files=[(key, (None, str(value))) for key, value in fields.items()],
        headers={"Accept": "application/json"})
    assert response.status_code == 200, response.text[:400]
    assert response.headers["content-type"].split(";")[0] == mime.split(";")[0]
    assert response.headers["content-disposition"].endswith(f'.{extension}"')
    assert response.headers["cache-control"] == "no-store"
    assert int(response.headers["content-length"]) == len(response.content)
    if authority == "REOP":
        workbook = load_workbook(io.BytesIO(response.content), data_only=True)
        rows = list(workbook.active.values)
        assert tuple(rows[0]) == REOP_HEADERS and len(rows) == 2
        assert rows[1][5] == 22 and rows[1][7] == 176.5
        assert rows[1][9] == 3_500_000 and rows[1][25] == 315_000
        workbook.close()
    else:
        lines = response.content.decode("cp1252").splitlines()
        assert len(lines) == 1
        fields = lines[0].split("\t")
        assert len(fields) == 11 and fields[6] == "22" and fields[7] == "3500000"
    batch = db.scalar(select(IntegrationBatch))
    assert response.headers["X-Integration-Batch-Id"] == str(batch.id)
    assert batch.status == "Generado" and batch.item_count == 1
    assert batch.file_sha256 == hashlib.sha256(response.content).hexdigest()
    assert core.storage.get(batch.storage_key) == response.content
    assert json.loads(batch.payload_json)["source_type"] == "approved"
    assert db.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == "exportar_importacion_salarios")) == 1
    db.refresh(source)
    assert original == (source.input_json, source.result_json, source.amount, source.status)


def test_partial_export_keeps_excluded_workers_out_and_requires_confirmation(download_case):
    client, db, _, company, _, _, source = download_case
    excluded = Employee(company_id=company.id, full_name="OTRO TRABAJADOR SINTETICO", document_number="9999988", employee_code=999)
    db.add(excluded); db.flush()
    db.add(CalculationRecord(company_id=company.id, employee_id=excluded.id, calculation_type="salary", reference_period="2026-10", status="Borrador"))
    db.commit()
    payload = data(download_case)
    payload.pop("employee_id")
    blocked = client.post("/app/compliance/salary-import/export", data=payload, headers={"Accept": "application/json"})
    assert blocked.status_code == 409 and "1 legajo" in blocked.json()["detail"]
    assert db.scalar(select(func.count(IntegrationBatch.id))) == 0
    downloaded = client.post("/app/compliance/salary-import/export", data=dict(payload, accept_partial="si"))
    assert downloaded.status_code == 200
    wb = load_workbook(io.BytesIO(downloaded.content), data_only=True)
    assert len(list(wb.active.values)) == 2
    wb.close()
    saved = json.loads(db.scalar(select(IntegrationBatch)).payload_json)
    assert saved["partial_export_confirmed"] is True and len(saved["excluded_calculation_ids"]) == 1


@pytest.mark.parametrize("changes,status", [({"period": "not-a-month"},409), ({"confirmed": ""},400), ({"company_id": ""},422)])
def test_ajax_export_errors_remain_readable_and_create_no_batch(download_case, changes, status):
    client, db, *_ = download_case
    response = client.post("/app/compliance/salary-import/export", data=data(download_case, **changes), headers={"Accept": "application/json"})
    assert response.status_code == status and isinstance(response.json()["detail"], str)
    assert db.scalar(select(func.count(IntegrationBatch.id))) == 0


def test_download_still_requires_csrf_and_company_access(download_case):
    client, db, _, _, _, other, _ = download_case
    payload = data(download_case)
    payload.pop("csrf_token")
    assert client.post("/app/compliance/salary-import/export", data=payload).status_code == 403
    foreign = data(download_case, company_id=other.company_id, employee_id=other.id)
    response = client.post("/app/compliance/salary-import/export", data=foreign, headers={"Accept": "application/json"})
    assert response.status_code == 404
    assert db.scalar(select(func.count(IntegrationBatch.id))) == 0


def test_preview_has_recoverable_download_and_versioned_shared_scripts(download_case):
    client, _, _, company, employee, *_ = download_case
    response = client.get("/app/compliance/salary-import", params={"company_id": company.id, "employee_id": employee.id,
        "period": "2026-10", "authority": "REOP", "payment_code": "1", "source_type": "auto"})
    assert response.status_code == 200
    html = BeautifulSoup(response.text, "html.parser")
    form = html.select_one("form[data-download-form]")
    assert form["data-download-format"] == "xlsx"
    assert form.select_one("[data-download-status]")["aria-live"] == "polite"
    for file in ("v20.js", "experience.js", "download-form.js"):
        script = html.select_one(f'script[src*="/{file}"]')
        assert script and "?v=" in script["src"]


def reop_review_from_preview(case):
    client, _, _, company, employee, *_ = case
    response = client.get("/app/compliance/salary-import", params={
        "company_id": company.id, "employee_id": employee.id, "period": "2026-10", "payment_code": "1",
    })
    html = BeautifulSoup(response.text, "html.parser")
    form = html.select_one("form[data-reop-assistant-id]")
    assert form and form.select_one("[data-reop-browser]")
    return form.select_one('[name="reop_review"]')["value"], form["data-reop-assistant-id"]


def test_reop_assistant_uses_same_reviewed_workbook_and_audited_batch(download_case):
    client, db, *_ = download_case
    review, extension_id = reop_review_from_preview(download_case)
    download = client.get("/app/compliance/reop-assistant.zip")
    assert download.status_code == 200 and download.headers["cache-control"] == "no-store"
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        assert set(archive.namelist()) == {
            "digit-laboral-reop/manifest.json", "digit-laboral-reop/worker.js", "digit-laboral-reop/portal.js",
        }
        manifest = json.loads(archive.read("digit-laboral-reop/manifest.json"))
    assert set(manifest["permissions"]) == {"activeTab", "scripting", "storage", "alarms"}
    assert "host_permissions" not in manifest and "content_scripts" not in manifest
    assert len(extension_id) == 32

    response = client.post("/app/compliance/salary-import/export", data=data(
        download_case, delivery="reop-browser", reop_review=review,
    ))
    assert response.status_code == 200, response.text[:400]
    assert response.headers["X-REOP-Patronal"] == "123456"
    assert response.headers["X-REOP-Period"] == "2026-10" and response.headers["X-REOP-Rows"] == "1"
    batch = db.get(IntegrationBatch, int(response.headers["X-Integration-Batch-Id"]))
    assert response.headers["X-REOP-SHA256"] == batch.file_sha256 == hashlib.sha256(response.content).hexdigest()
    assert json.loads(batch.payload_json)["delivery"] == "reop-browser" and batch.status == "Generado"


def test_reop_assistant_rejects_changed_patronal_or_other_authority_without_creating_batch(download_case):
    client, db, _, company, *_ = download_case
    review, _ = reop_review_from_preview(download_case)
    company.mtess_employer_number = "654321"
    db.commit()
    payload = data(download_case, delivery="reop-browser", reop_review=review)
    stale = client.post("/app/compliance/salary-import/export", data=payload, headers={"Accept": "application/json"})
    assert stale.status_code == 409 and "Verificar archivo" in stale.json()["detail"]
    assert client.post("/app/compliance/salary-import/export", data=dict(payload, authority="REI")).status_code == 422
    assert db.scalar(select(func.count(IntegrationBatch.id))) == 0
