from codecs import BOM_UTF8
from datetime import date
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
from sqlalchemy import select

from app import main as core
from app.models import Branch, BranchComplianceProfile, ComplianceEvent, IntegrationBatch, IntegrationBatchItem
from app.rei_movement_routes import PATH
from app.rei_movements import MOVEMENT_BATCH_TYPE
from app.storage_service import LocalStorage
from tests.test_labor_suite import token, web_case


def add_event(db, company, employee, *, event_type="Entrada", status="Validado", authority="REI", branch_id=None):
    event = ComplianceEvent(
        company_id=company.id, employee_id=employee.id, authority=authority, branch_id=branch_id,
        event_type=event_type, event_date=date(2026, 11, 4), status=status,
    )
    db.add(event)
    db.flush()
    return event


def layout_request(client, csrf, company_id, ids, model, **options):
    fields = {
        "csrf_token": csrf, "company_id": str(company_id), "period": "2026-11", "movement": "Entrada",
        "separator": "semicolon", "encoding": "utf-8", "first_row": "header", **options,
    }
    files = [(key, (None, value)) for key, value in fields.items()]
    files.extend(("event_ids", (None, str(item))) for item in ids)
    files.append(("template", ("modelo.csv", model, "text/csv")))
    return client.post(PATH + "/layout", files=files)


def hidden(response, field):
    assert response.status_code == 200, response.text
    return BeautifulSoup(response.text, "html.parser").select_one(f'input[name="{field}"]')["value"]


def preview_request(client, csrf, review, patronal="004-9", document_field="document"):
    return client.post(PATH + "/preview", data={
        "csrf_token": csrf, "review": review, "patronal": patronal, "date_format": "dma",
        "field": [document_field, "event_date", "fixed", "patronal"], "constant": ["", "", "A1", ""],
    })


def test_rei_movement_csv_download_and_receipt(web_case, monkeypatch, tmp_path):
    client, db, _, company, employee, other = web_case
    monkeypatch.setattr(core, "storage", LocalStorage(tmp_path / "files"))
    company.ips_employer_number = "004-9"
    employee.document_number = "001.234"
    employee.status = "Inactivo"
    exit_event = add_event(db, company, employee, event_type="Salida")
    draft = add_event(db, company, employee, event_type="Salida", status="Borrador")
    other_authority = add_event(db, company, employee, event_type="Salida", authority="REOP")
    db.commit()
    csrf = token(client)
    page = client.get(PATH, params={"company_id": company.id, "movement": "Salida", "period": "2026-11"})
    assert page.status_code == 200 and "no-store" in page.headers["cache-control"]
    selected_options = BeautifulSoup(page.text, "html.parser").select('input[name="event_ids"]')
    assert [item["value"] for item in selected_options] == [str(exit_event.id)]
    assert client.get(PATH, params={"company_id": other.company_id}).status_code == 404
    assert draft.id != exit_event.id and other_authority.id != exit_event.id

    model = BOM_UTF8 + '"Cédula";Fecha;Código;Patronal\r\n'.encode()
    layout = layout_request(client, csrf, company.id, [exit_event.id], model, movement="Salida")
    review = hidden(layout, "review")
    bad_patronal = preview_request(client, csrf, review, patronal="OTRA")
    assert "confirmá ese mismo número" in bad_patronal.text
    preview = preview_request(client, csrf, review, document_field="document_compact")
    export_token = hidden(preview, "export_token")
    assert "04/11/2026" in preview.text and "001234" in preview.text

    export_fields = {"csrf_token": csrf, "export_token": export_token, "confirmed": "si"}
    assert client.post(PATH + "/export", data={**export_fields, "confirmed": ""}).status_code == 400
    saved = client.post(PATH + "/export", data=export_fields, follow_redirects=False)
    assert saved.status_code == 303, saved.text
    batch_id = int(parse_qs(urlsplit(saved.headers["location"]).query)["batch_id"][0])
    assert "Movimiento por Lotes" in client.get(saved.headers["location"]).text
    batch = db.get(IntegrationBatch, batch_id)
    db.refresh(exit_event)
    assert batch.batch_type == MOVEMENT_BATCH_TYPE and batch.item_count == 1
    assert exit_event.status == "Exportado" and exit_event.batch_id == batch_id
    assert db.scalar(select(IntegrationBatchItem.compliance_event_id)) == exit_event.id

    download = client.get(f"/app/compliance/batches/{batch_id}/download")
    assert download.status_code == 200 and download.headers["content-type"] == "text/csv; charset=utf-8"
    assert download.content == model + b"001234;04/11/2026;A1;004-9\r\n"
    assert client.post(PATH + "/export", data=export_fields).status_code == 409
    assert client.post(f"/app/compliance/batches/{batch_id}/receipt", data={
        "csrf_token": csrf, "status": "Presentado", "external_reference": "REI-QA-0001",
    }, follow_redirects=False).status_code == 303
    db.refresh(exit_event)
    assert exit_event.status == "Presentado"


def test_rei_preview_discards_sample_values_and_blocks_stale_export(web_case, monkeypatch, tmp_path):
    client, db, box, company, employee, _ = web_case
    monkeypatch.setattr(core, "storage", LocalStorage(tmp_path / "files"))
    company.ips_employer_number = "004-9"
    event = add_event(db, company, employee)
    db.commit()
    csrf = token(client)
    layout = layout_request(
        client, csrf, company.id, [event.id], b'998877;12/11/2026;"ejemplo";ejemplo\n', first_row="sample",
    )
    assert "998877" not in layout.text and "Columna 1" in layout.text
    review = hidden(layout, "review")
    preview = preview_request(client, csrf, review)
    assert "998877" not in preview.text
    export_token = hidden(preview, "export_token")
    employee.document_number = "5555555"
    db.commit()
    assert client.post(PATH + "/export", data={
        "csrf_token": csrf, "export_token": export_token, "confirmed": "si",
    }).status_code == 409
    assert db.scalar(select(IntegrationBatch)) is None

    current = hidden(preview_request(client, csrf, review), "export_token")
    saved = client.post(PATH + "/export", data={
        "csrf_token": csrf, "export_token": current, "confirmed": "si",
    }, follow_redirects=False)
    assert saved.status_code == 303
    batch_id = int(parse_qs(urlsplit(saved.headers["location"]).query)["batch_id"][0])
    assert client.get(f"/app/compliance/batches/{batch_id}/download").content == b"5555555;04/11/2026;A1;004-9\n"

    box["user"].role = "auxiliar"
    assert client.get(PATH, params={"company_id": company.id}).status_code == 403


def test_rei_batch_rejects_duplicates_and_mixed_patronals(web_case):
    client, db, _, company, employee, _ = web_case
    company.ips_employer_number = "004-9"
    first = add_event(db, company, employee)
    duplicate = add_event(db, company, employee)
    branch = Branch(company_id=company.id, name="Sucursal sintética")
    db.add(branch)
    db.flush()
    db.add(BranchComplianceProfile(branch_id=branch.id, ips_employer_number="005-9"))
    different = add_event(db, company, employee, branch_id=branch.id)
    db.commit()
    csrf = token(client)
    model = b"CI;FECHA;TIPO;PATRONAL\r\n"
    assert layout_request(client, csrf, company.id, [first.id, different.id], model).status_code == 409
    assert layout_request(client, csrf, company.id, [first.id, first.id], model).status_code == 400
    for ids in ([first.id], [first.id, duplicate.id]):
        review = hidden(layout_request(client, csrf, company.id, ids, model), "review")
        assert "movimientos repetidos" in preview_request(client, csrf, review).text
    branch_review = hidden(layout_request(client, csrf, company.id, [different.id], model), "review")
    assert hidden(preview_request(client, csrf, branch_review, patronal="005-9"), "export_token")
    assert db.scalar(select(IntegrationBatch)) is None
