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
    if authority == "REOP":
        company.mtess_employer_number = "45.815"
        db.commit()
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
        assert rows[1][0] == "45815"
        assert rows[1][5] == 22 and rows[1][7] == 176.5
        assert rows[1][9] == 3_500_000 and rows[1][25] == 315_000
        workbook.close()
        db.refresh(company)
        assert company.mtess_employer_number == "45.815"
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
    assert form.select_one("[data-reop-file]").has_attr("hidden")
    for file in ("v20.js", "experience.js", "download-form.js"):
        script = html.select_one(f'script[src*="/{file}"]')
        assert script and "?v=" in script["src"]


def test_saved_salary_batch_reopens_with_workers_and_reuses_identical_bytes(download_case):
    client, db, _, company, employee, outsider, source = download_case
    original = client.post("/app/compliance/salary-import/export", data=data(download_case))
    assert original.status_code == 200
    batch_id = original.headers["X-Integration-Batch-Id"]
    page = client.get("/app/compliance/salary-import", params={
        "company_id": company.id, "employee_id": employee.id, "period": "2026-10", "payment_code": "1",
    })
    html = BeautifulSoup(page.text, "html.parser")
    reviewed = html.select_one("[data-import-worker-row]")
    assert employee.document_number in reviewed.text and employee.full_name in reviewed.text
    saved = html.select_one("form[data-saved-batch]")
    assert saved and json.loads(saved["data-saved-batch"])["id"] == int(batch_id)
    assert html.select_one("[data-salary-import-filters]")
    assert html.select_one('script[src*="salary-import.js"]')
    reused = client.post("/app/compliance/salary-import/export", data=data(download_case, reuse_batch_id=batch_id))
    assert reused.status_code == 200 and reused.content == original.content
    assert db.scalar(select(func.count(IntegrationBatch.id))) == 1
    rejected = client.post("/app/compliance/salary-import/export", data=data(
        download_case, reuse_batch_id=batch_id, company_id=outsider.company_id, employee_id=outsider.id,
    ))
    assert rejected.status_code == 404
    inputs = json.loads(source.input_json)
    inputs["hours_worked"] = "180"
    source.input_json = json.dumps(inputs)
    db.commit()
    changed = client.post("/app/compliance/salary-import/export", data=data(download_case, reuse_batch_id=batch_id))
    assert changed.status_code == 409
    assert db.scalar(select(func.count(IntegrationBatch.id))) == 1


def test_reop_progress_is_saved_as_an_observation_and_cannot_forge_completion(download_case):
    client, db, _, _, _, _, _ = download_case
    original = client.post("/app/compliance/salary-import/export", data=data(download_case))
    batch_id = original.headers["X-Integration-Batch-Id"]
    url = f"/app/compliance/salary-import/batches/{batch_id}/progress"
    assert client.post(url, json={"phase": "prevalidated", "valid": 1, "errors": 0, "imported": 0}).status_code == 403
    headers = {"X-CSRF-Token": token(client)}
    assert client.post(url, headers=headers, json={
        "phase": "imported", "valid": 1, "errors": 0, "imported": 2,
    }).status_code == 422
    state = {"phase": "prevalidated", "valid": 1, "errors": 0, "imported": 0}
    assert client.post(url, headers=headers, json=state).status_code == 200
    batch = db.get(IntegrationBatch, int(batch_id))
    assert batch.status == "Generado"
    assert json.loads(batch.payload_json)["assistant_progress"]["phase"] == "prevalidated"
    assert client.post(url, headers=headers, json={**state, "phase": "imported", "imported": 1}).status_code == 200
    assert client.post(url, headers=headers, json={"phase": "attached"}).status_code == 200
    db.refresh(batch)
    assert json.loads(batch.payload_json)["assistant_progress"]["phase"] == "imported"
    assert batch.status == "Generado"


def test_attendance_correction_returns_to_the_full_company_review(download_case):
    from urllib.parse import parse_qs, urlsplit
    client, _, _, company, _, _, _ = download_case
    page = client.get("/app/compliance/salary-import", params={
        "company_id": company.id, "period": "2026-10", "source_type": "auto", "payment_code": "1",
    })
    html = BeautifulSoup(page.text, "html.parser")
    form = html.select_one("[data-salary-import-details]")
    fields = {node["name"]: node.get("value", "") for node in form.select("input[name]") if node.get("type") != "checkbox"}
    response = client.post("/app/compliance/salary-import/details", data={**fields, "confirmed": "si"}, follow_redirects=False)
    assert response.status_code == 303
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["company_id"] == [str(company.id)] and query["payment_code"] == ["1"]
    assert query["source_type"] == ["auto"] and "employee_id" not in query


def reop_review_from_preview(case):
    client, _, _, company, employee, *_ = case
    response = client.get("/app/compliance/salary-import", params={
        "company_id": company.id, "employee_id": employee.id, "period": "2026-10", "payment_code": "1",
    })
    html = BeautifulSoup(response.text, "html.parser")
    form = html.select_one("form[data-reop-assistant-id]")
    assert form and form.select_one("[data-reop-browser]")
    return form.select_one('[name="reop_review"]')["value"], form["data-reop-assistant-id"]


def observe_salary_list(case, records=(), *, previous="", patronal="123456"):
    client, _, _, company, *_ = case
    snapshot = {"source": "REOP", "complete": True, "patronal": patronal, "period": "2026-10",
                "total": len(records), "inspected": len(records), "records": list(records)}
    response = client.post(f"/app/compliance/salary-import/{company.id}/2026-10/ledger",
        headers={"X-CSRF-Token": token(client)}, json={"patronal": patronal, "previous": previous, "snapshot": snapshot})
    assert response.status_code == 200, response.text
    return response.json()["digest"]


def test_reop_assistant_uses_same_reviewed_workbook_and_audited_batch(download_case):
    client, db, *_ = download_case
    review, extension_id = reop_review_from_preview(download_case)
    download = client.get("/app/compliance/reop-assistant.zip")
    assert download.status_code == 200 and download.headers["cache-control"] == "no-store"
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        assert set(archive.namelist()) == {
            "digit-laboral-reop/manifest.json", "digit-laboral-reop/worker.js", "digit-laboral-reop/portal.js",
            "digit-laboral-reop/salary-list.js",
        }
        manifest = json.loads(archive.read("digit-laboral-reop/manifest.json"))
    assert set(manifest["permissions"]) == {"activeTab", "scripting", "storage", "alarms"}
    assert "host_permissions" not in manifest and "content_scripts" not in manifest
    assert len(extension_id) == 32

    response = client.post("/app/compliance/salary-import/export", data=data(
        download_case, delivery="reop-browser", reop_review=review, ledger_digest=observe_salary_list(download_case),
    ))
    assert response.status_code == 200, response.text[:400]
    assert response.headers["X-REOP-Patronal"] == "123456"
    assert response.headers["X-REOP-Period"] == "2026-10" and response.headers["X-REOP-Rows"] == "1"
    batch = db.get(IntegrationBatch, int(response.headers["X-Integration-Batch-Id"]))
    assert response.headers["X-REOP-SHA256"] == batch.file_sha256 == hashlib.sha256(response.content).hexdigest()
    assert json.loads(batch.payload_json)["delivery"] == "reop-browser" and batch.status == "Generado"
    saved = client.get(f"/app/compliance/batches/{batch.id}/download")
    assert saved.status_code == 200 and saved.content == response.content
    assert db.scalar(select(func.count(IntegrationBatch.id))) == 1


def test_reop_assistant_rejects_changed_patronal_or_other_authority_without_creating_batch(download_case):
    client, db, _, company, *_ = download_case
    review, _ = reop_review_from_preview(download_case)
    company.mtess_employer_number = "654321"
    db.commit()
    payload = data(download_case, delivery="reop-browser", reop_review=review,
                   ledger_digest=observe_salary_list(download_case, patronal="654321"))
    stale = client.post("/app/compliance/salary-import/export", data=payload, headers={"Accept": "application/json"})
    assert stale.status_code == 409 and "Verificar archivo" in stale.json()["detail"]
    assert client.post("/app/compliance/salary-import/export", data=dict(payload, authority="REI")).status_code == 422
    assert db.scalar(select(func.count(IntegrationBatch.id))) == 0


def test_month_deduplicates_exports_missing_and_reconciles_the_result(download_case):
    client, db, _, company, worker, _, source = download_case
    second = Employee(company_id=company.id, full_name="Segundo trabajador de prueba", document_number="1000022",
                      ips_contributor=True, admission_date=worker.admission_date, employee_code=702)
    db.add(second)
    db.flush()
    db.add(CalculationRecord(company_id=company.id, employee_id=second.id, calculation_type=source.calculation_type,
                             reference_period=source.reference_period, status=source.status, input_json=source.input_json,
                             result_json=source.result_json, amount=source.amount))
    db.commit()
    period = "2026-10"
    dashboard = "/app/compliance/reop-month"
    filters = {"company_id": company.id, "period": period, "authority": "REOP"}
    page = "/app/compliance/salary-import"
    export = page + "/export"
    def companies_in(state):
        html = BeautifulSoup(client.get(dashboard, params={"period": period, "status": state}).text, "html.parser")
        return html.select_one("tbody").get_text(" ", strip=True)
    assert company.legal_name in companies_in("ready")
    assert "Empresa ajena" not in companies_in("prepare")
    payload = data(download_case, delivery="reop-browser")
    del payload["employee_id"]
    assert client.post(export, data=payload).status_code == 409
    record = {"document": worker.document_number, "income": 3500000, "status": "Pendiente", "number": "100",
              "period": period, "patronal": "123456", "receipt": ""}
    digest = observe_salary_list(download_case, [record])
    full = BeautifulSoup(client.get(page, params=filters).text, "html.parser")
    assert full.select_one("#control-reop").find(string="Preparar solo los faltantes (1)")
    review = full.select_one('input[name="reop_review"]')["value"]
    assert client.post(export, data={**payload, "ledger_digest": digest, "reop_review": review}).status_code == 409
    partial = BeautifulSoup(client.get(page, params={**filters, "only_missing": 1}).text, "html.parser")
    form = partial.select_one("[data-download-form]")
    review = form.select_one('[name="reop_review"]')["value"]
    assert form.select_one('[name="ledger_digest"]')["value"] == digest
    response = client.post(export, data={**payload, "ledger_digest": digest, "reop_review": review, "only_missing": "true"})
    assert response.status_code == 200, response.text[:200]
    wb = load_workbook(io.BytesIO(response.content))
    assert [str(r[1]) for r in list(wb.active.values)[1:]] == [second.document_number]
    wb.close()
    assert company.legal_name in companies_in("imported")
    assert company.legal_name not in companies_in("confirmed")
    revised = [{**record, "status": "Confirmado", "receipt": "EOF/001"},
               {**record, "status": "Confirmado", "number": "101", "document": second.document_number}]
    newest = observe_salary_list(download_case, revised, previous=digest)
    assert newest != digest and company.legal_name in companies_in("confirmed")
    html = BeautifulSoup(client.get(page, params=filters).text, "html.parser")
    assert "Constancia EOF/001" in html.select_one("#control-reop").get_text(" ", strip=True)
    assert client.post(export, data={**payload, "ledger_digest": newest, "reop_review": review, "only_missing": "true"}).status_code == 409
    assert db.scalar(select(func.count(IntegrationBatch.id))) == 1


def test_group_and_exception_reopen_by_month_and_by_original_batch(download_case):
    client, db, _, company, worker, foreign, source = download_case
    config = f"/app/compliance/salary-import/{company.id}/2026-10/payments"
    preview = "/app/compliance/salary-import"
    original = source.input_json, source.result_json
    form = {"csrf_token": token(client), "default": "1", "revision": ""}
    assert client.post(config, data={**form, f"pay_{foreign.id}": "2"}, follow_redirects=False).status_code == 404
    assert client.post(config, data=form, follow_redirects=False).status_code == 303
    params = {"company_id": company.id, "period": "2026-10"}
    html = BeautifulSoup(client.get(preview, params=params).text, "html.parser")
    assert html.select_one('#pagos-reop [name="default"] option[selected]')["value"] == "1"
    assert html.select_one("[data-import-worker-row]").find(string="Efectivo")
    saved = client.post(preview + "/export", data=data(download_case))
    assert saved.status_code == 200
    wb = load_workbook(io.BytesIO(saved.content))
    assert wb.active.cell(2, 5).value == 1
    wb.close()
    assert client.post(config, data=form, follow_redirects=False).status_code == 409
    rev = html.select_one('[name="revision"]')["value"]
    assert client.post(config, data={**form, "revision": rev, f"pay_{worker.id}": "2"}, follow_redirects=False).status_code == 303
    html = BeautifulSoup(client.get(preview, params=params).text, "html.parser")
    assert html.select_one("[data-import-worker-row]").find(string="Cheque")
    batch = BeautifulSoup(client.get(preview, params={**params, "batch_id": saved.headers["X-Integration-Batch-Id"]}).text, "html.parser")
    assert batch.select_one("[data-import-worker-row]").find(string="Efectivo")
    another_month = BeautifulSoup(client.get(preview, params={**params, "period": "2026-09"}).text, "html.parser")
    assert another_month.select_one('select[name="payment_code"] option[selected]')["value"] == "auto"
    db.refresh(source)
    assert (source.input_json, source.result_json) == original
