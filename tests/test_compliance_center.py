from datetime import UTC, datetime, timedelta
from io import BytesIO
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
from openpyxl import load_workbook
from sqlalchemy import select

from app import main as core
from app.models import ComplianceEvent, IntegrationBatch, IntegrationBatchItem, Payroll, PayrollLine
from app.period_coverage import current_paraguay_date
from app.storage_service import LocalStorage
from tests.test_labor_suite import token, web_case


CENTER = "/app/compliance"


def test_filters_count_all_communications_and_isolate_company(web_case):
    client, db, _, company, _, other = web_case
    today = current_paraguay_date()
    older = today - timedelta(days=1)
    db.add_all(
        ComplianceEvent(company_id=company.id, authority="REOP", event_type="Entrada", event_date=older, status="Borrador")
        for _ in range(101)
    )
    db.add_all([
        ComplianceEvent(company_id=company.id, authority="REOP", event_type="Salida", event_date=older, due_date=older, status="Rechazado"),
        ComplianceEvent(company_id=company.id, authority="REI", event_type="Salida", event_date=older, due_date=older, status="Aceptado"),
        ComplianceEvent(company_id=other.company_id, authority="REOP", event_type="Permiso", event_date=older, due_date=older, status="Borrador"),
    ])
    db.commit()

    page = client.get(CENTER, params={"company_id": company.id})
    assert page.status_code == 200
    html = BeautifulSoup(page.text, "html.parser")
    assert [node.text for node in html.select(".compliance-metrics strong")] == ["102", "1", "1"]
    assert len(html.select(".compliance-event-table tbody tr")) == 25
    assert "Vencida" in html.select_one(".compliance-event-table tbody tr").text
    assert html.select_one("a[rel=next]")
    assert html.select_one(f'a[href="{core.OFFICIAL_PORTALS["REOP"]}"]')
    assert html.select_one(f'a[href="{core.OFFICIAL_PORTALS["REI"]}"]')

    overdue = client.get(CENTER, params={"company_id": company.id, "authority": "REOP", "status": "Vencidas"})
    html = BeautifulSoup(overdue.text, "html.parser")
    assert len(html.select(".compliance-event-table tbody tr")) == 1
    assert "Rechazado" in html.select_one(".compliance-event-table tbody tr").text
    assert client.get(CENTER, params={"company_id": other.company_id}).status_code == 404


def test_communication_export_receipt_and_retry_preserve_prior_batch(web_case, monkeypatch, tmp_path):
    client, db, _, company, employee, other = web_case
    monkeypatch.setattr(core, "storage", LocalStorage(tmp_path / "files"))
    company.mtess_employer_number = "PATRONAL-QA"
    employee.full_name = "=1+1"
    event = ComplianceEvent(
        company_id=company.id, employee_id=employee.id, authority="REOP", event_type="Entrada",
        event_date=current_paraguay_date(), status="Validado",
    )
    db.add(event)
    db.commit()
    csrf = token(client)
    fields = {"csrf_token": csrf, "company_id": company.id, "authority": "REOP"}
    route = f"{CENTER}/export/events.xlsx"

    assert client.get(route, params={"company_id": company.id, "authority": "REOP"}, follow_redirects=False).status_code == 303
    assert db.scalar(select(IntegrationBatch)) is None
    assert client.post(route, data={**fields, "csrf_token": ""}).status_code == 403
    generated = client.post(route, data=fields, follow_redirects=False)
    assert generated.status_code == 303, generated.text
    batch_id = int(parse_qs(urlsplit(generated.headers["location"]).query)["batch_id"][0])
    batch_page = client.get(generated.headers["location"])
    assert batch_page.status_code == 200 and "Registrar resultado del portal" in batch_page.text
    download_url = f"{CENTER}/batches/{batch_id}/download"
    file = client.get(download_url)
    assert file.status_code == 200
    with BytesIO(file.content) as buffer:
        workbook = load_workbook(buffer, read_only=True)
        assert workbook.active["A2"].value == "PATRONAL-QA"
        assert workbook.active["G2"].value == "=1+1" and workbook.active["G2"].data_type == "s"
        assert "Archivo interno" in workbook["METADATOS"]["B6"].value
        workbook.close()

    receipt_url = f"{CENTER}/batches/{batch_id}/receipt"
    receipt = b"%PDF-1.4\n% synthetic receipt\n"
    submitted = client.post(
        receipt_url, data={"csrf_token": csrf, "status": "Presentado"},
        files={"receipt": ("comprobante.pdf", receipt, "application/pdf")}, follow_redirects=False,
    )
    assert submitted.status_code == 303
    rejected = client.post(receipt_url, data={
        "csrf_token": csrf, "status": "Rechazado", "result_detail": "Revisar fecha de entrada",
    }, follow_redirects=False)
    assert rejected.status_code == 303
    assert "Revisar fecha de entrada" in client.get(rejected.headers["location"]).text
    retry = client.post(f"{CENTER}/events/{event.id}/retry", data={"csrf_token": csrf, "batch_id": batch_id}, follow_redirects=False)
    assert retry.status_code == 303
    assert f"Lote anterior #{batch_id}" in client.get(retry.headers["location"]).text
    db.refresh(event)
    assert event.status == "Borrador" and event.batch_id is None and event.submitted_at is None
    assert db.scalar(select(IntegrationBatchItem.batch_id).where(IntegrationBatchItem.compliance_event_id == event.id)) == batch_id

    details = client.post(f"{CENTER}/events/{event.id}/details", data={
        "csrf_token": csrf, "detail": "Fecha revisada", "due_date": current_paraguay_date().isoformat(),
    }, follow_redirects=False)
    assert details.status_code == 303
    assert "Fecha revisada" in client.get(details.headers["location"]).text
    assert client.post(f"{CENTER}/events/{event.id}/status", data={"csrf_token": csrf, "status": "Validado"}, follow_redirects=False).status_code == 303
    assert client.post(route, data=fields, follow_redirects=False).status_code == 303
    db.refresh(event)
    assert event.batch_id != batch_id
    assert client.get(download_url).content == file.content
    assert client.get(receipt_url).content == receipt
    assert db.get(IntegrationBatch, batch_id).status == "Rechazado"

    batch = db.get(IntegrationBatch, batch_id)
    batch.file_bytes = b"invalid contents"
    db.commit()
    assert client.get(download_url).status_code == 409
    assert client.post(route, data={**fields, "company_id": other.company_id}).status_code == 404


def test_annual_summary_uses_saved_closed_payroll_and_is_internal(web_case, monkeypatch, tmp_path):
    client, db, _, company, employee, _ = web_case
    monkeypatch.setattr(core, "storage", LocalStorage(tmp_path / "files"))
    year = current_paraguay_date().year
    closed = Payroll(company_id=company.id, period=f"{year}-01", status="Cerrada", closed_at=datetime.now(UTC))
    draft = Payroll(company_id=company.id, period=f"{year}-02", status="Borrador")
    db.add_all([closed, draft])
    db.flush()
    db.add_all([
        PayrollLine(payroll_id=closed.id, employee_id=employee.id, base_salary=3_500_000),
        PayrollLine(payroll_id=draft.id, employee_id=employee.id, base_salary=4_000_000),
    ])
    db.commit()
    csrf = token(client)
    response = client.post(f"{CENTER}/export/reop-annual.xlsx", data={
        "csrf_token": csrf, "company_id": company.id, "year": year,
    }, follow_redirects=False)
    assert response.status_code == 303
    batch_id = int(parse_qs(urlsplit(response.headers["location"]).query)["batch_id"][0])
    page = client.get(response.headers["location"])
    assert "Resumen anual interno" in page.text and "Registrar resultado del portal" not in page.text
    file = client.get(f"{CENTER}/batches/{batch_id}/download")
    assert file.status_code == 200
    with BytesIO(file.content) as buffer:
        workbook = load_workbook(buffer, read_only=True)
        wages = list(workbook["SUELDOS_Y_JORNALES"].values)
        assert len(wages) == 2 and wages[1][2] == f"{year}-01"
        assert wages[1][7:11] == (None, None, None, 3_500_000)
        workbook.close()
    assert client.post(f"{CENTER}/batches/{batch_id}/receipt", data={
        "csrf_token": csrf, "status": "Presentado", "external_reference": "FOLIO-QA",
    }).status_code == 409
