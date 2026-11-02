import io
import json
import re
from datetime import date

import pytest
from bs4 import BeautifulSoup
from docx import Document
from pypdf import PdfReader
from sqlalchemy import select

from app.document_export import decode_metadata
from app.models import CalculationRecord, GeneratedCertificate
from app.notice_documents import notice_date_defaults, saved_notice_dates
from tests.test_labor_suite import token, web_case


@pytest.fixture
def notice_case(web_case):
    client, db, box, company, employee, other = web_case
    company.legal_name = "Empresa del modelo"
    company.city = "Ciudad del Este"
    company.address = "Domicilio sintético"
    company.legal_representative = "Representante sintético"
    employee.full_name = "PERSONA DEL MODELO"
    employee.position = "Auxiliar"
    employee.admission_date = date(2024, 1, 1)
    record = CalculationRecord(company_id=company.id, employee_id=employee.id, calculation_type="notice",
        reference_period="2026-07", amount=5_400_000, status="Revisar", source="Calculadora",
        input_json=json.dumps({"salary": 3_600_000, "days": 45, "notice_start_date": "2026-07-17", "effective_date": "2026-08-31"}),
        result_json=json.dumps({"days": 45}), notes="Plazo revisado para prueba")
    db.add(record); db.commit()
    return client, db, box, company, employee, other, record


def notice_form(case, **changes):
    client, _, _, company, employee, _, record = case
    return {"csrf_token": token(client), "company_id": str(company.id), "employee_id": str(employee.id),
        "calculation_id": str(record.id), "notice_reference_period": record.reference_period,
        "document_type": "notificacion_preaviso", "issue_date": "2026-07-17", "city": "Ciudad del Este",
        "document_number": "0000980", "intent": "save", **changes}


def created_notice(client, response):
    assert response.status_code == 303, response.text
    item_id = int(re.search(r"created=(\d+)", response.headers["location"]).group(1))
    return item_id


def test_saved_notice_dates_are_exposed_only_for_the_authorized_employee(notice_case):
    client, _, _, company, employee, other, record = notice_case
    response = client.get("/api/certificates/preaviso-calculations", params={"company_id": company.id, "employee_id": employee.id})
    assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
    item = next(row for row in response.json()["calculations"] if row["id"] == record.id)
    assert item["notice_start_date"] == "2026-07-17" and item["effective_date"] == "2026-08-31"
    assert item["salary"] == 3_600_000 and item["days"] == 45
    assert client.get("/api/certificates/preaviso-calculations", params={"company_id": company.id, "employee_id": other.id}).status_code == 404


@pytest.mark.parametrize("saved,expected", [
    ({}, "2026-08-31"), ({"effective_date": "2026-09-01"}, "2026-09-01"),
    ({"notice_end_date": "2026-09-02"}, "2026-09-02"),
    ({"effective_date": "invalid", "start_date": "1999-01-01"}, "2026-08-31"),
])
def test_date_defaults_use_explicit_notice_dates_and_do_not_mistake_hire_dates(saved, expected):
    values = notice_date_defaults(saved, date(2026, 7, 17), 45)
    assert values["effective_date"] == expected
    assert values["notice_start_date"] == "2026-07-17"
    assert saved_notice_dates({"effective_date": "invalid"})["effective_date"] == ""


def test_letter_uses_dossier_and_saved_dates_without_manual_retyping(notice_case):
    client, db, _, company, employee, _, _ = notice_case
    item_id = created_notice(client, client.post("/app/certificates", data=notice_form(notice_case), follow_redirects=False))
    item = db.get(GeneratedCertificate, item_id)
    assert item.body.startswith("Señor(a)\nPERSONA DEL MODELO\n\n")
    assert "Firma Comercial Empresa del modelo" in item.body and "a partir del 31/08/26." in item.body
    assert "licencia diaria de dos horas" in item.body and "un día a la semana" in item.body
    assert item.body.endswith("Muy atentamente.")
    assert "Cargo registrado" not in item.body and "Ref.:" not in item.body and "←G" not in item.body
    metadata = decode_metadata(item.observations)
    assert metadata["notice_template_version"] == "1"
    assert metadata["effective_date"] == "2026-08-31" and metadata["notice_start_date"] == "2026-07-17"
    assert metadata["notice_days"] == "45" and metadata["notice_date_source"] == "Cálculo guardado"
    db.refresh(employee)
    assert employee.status == "Activo" and employee.termination_date is None
    assert item.company_name_snapshot == company.legal_name


def test_absent_saved_dates_get_an_explicit_date_proposal(notice_case):
    client, db, _, _, _, _, record = notice_case
    record.input_json = json.dumps({"salary": 3_600_000, "days": 45})
    db.commit()
    item_id = created_notice(client, client.post("/app/certificates", data=notice_form(notice_case, notice_start_date="2026-08-01"), follow_redirects=False))
    metadata = decode_metadata(db.get(GeneratedCertificate, item_id).observations)
    assert metadata["effective_date"] == "2026-09-15"
    assert metadata["notice_date_source"].startswith("Propuesta")


def test_manual_dates_take_priority_and_still_compute_the_interval(notice_case):
    client, db, *_ = notice_case
    item_id = created_notice(client, client.post("/app/certificates", data=notice_form(notice_case,
        notice_start_date="2026-07-20", effective_date="2026-09-03", notice_days="999"), follow_redirects=False))
    item = db.get(GeneratedCertificate, item_id)
    assert "a partir del 03/09/26." in item.body
    assert decode_metadata(item.observations)["notice_days"] == "45"


@pytest.mark.parametrize("failure", ["missing", "foreign", "annulled", "superseded"])
def test_no_notification_is_issued_without_a_current_matching_calculation(notice_case, failure):
    client, db, _, _, _, other, record = notice_case
    values = notice_form(notice_case)
    if failure == "missing": values["calculation_id"] = ""
    elif failure == "foreign": record.employee_id = other.id
    elif failure == "annulled": record.status = "Anulado"
    else:
        db.add(CalculationRecord(company_id=record.company_id, employee_id=record.employee_id,
            calculation_type="notice", reference_period=record.reference_period, input_json=record.input_json,
            result_json=record.result_json, amount=record.amount, source="Calculadora"))
    db.commit()
    response = client.post("/app/certificates", data=values, follow_redirects=False)
    assert response.status_code == 400
    assert not db.scalar(select(GeneratedCertificate.id))


def test_print_word_pdf_share_letter_and_number_date_order(notice_case):
    client, db, *_ = notice_case
    item_id = created_notice(client, client.post("/app/certificates", data=notice_form(notice_case), follow_redirects=False))
    soup = BeautifulSoup(client.get(f"/app/certificates/{item_id}/print").text, "html.parser")
    paper = soup.select_one("main.notice-letter")
    assert paper and not paper.select_one("h1")
    assert paper.select_one(".number").text == "N.º 0000980"
    assert paper.select_one(".number").find_next("p").get("class") == ["date"]
    assert len(paper.select(".sigline")) == 2
    document = Document(io.BytesIO(client.get(f"/app/certificates/{item_id}/download.docx").content))
    paragraphs = [p.text for p in document.paragraphs]
    assert paragraphs.index("N.º 0000980") < paragraphs.index("CIUDAD DEL ESTE, 17 de julio de 2026")
    assert "DOCUMENTO LABORAL" not in paragraphs and "NOTIFICACIÓN DE PREAVISO" not in paragraphs
    pdf = PdfReader(io.BytesIO(client.get(f"/app/certificates/{item_id}/download.pdf").content))
    assert len(pdf.pages) == 1
    pdf_text = "\n".join(page.extract_text() for page in pdf.pages)
    assert pdf_text.index("0000980") < pdf_text.index("CIUDAD DEL ESTE")
    word_text = "\n".join(paragraphs)
    for text in (paper.select_one(".body").get_text(" ", strip=True), word_text, pdf_text):
        normalized = " ".join(text.split())
        assert "Me dirijo a usted para notificarle que la Firma Comercial Empresa del modelo" in normalized
        assert "a partir del 31/08/26." in normalized and "Muy atentamente." in normalized
        assert "Cargo registrado" not in normalized and "←G" not in normalized


def test_historical_notification_body_and_layout_remain_original(notice_case):
    client, db, _, company, employee, *_ = notice_case
    old = GeneratedCertificate(company_id=company.id, employee_id=employee.id, document_type="notificacion_preaviso",
        title="Notificación de Preaviso", company_name_snapshot=company.legal_name, employee_name_snapshot=employee.full_name,
        body="TEXTO ORIGINAL DEL DOCUMENTO HISTÓRICO", status="Emitido", observations="")
    db.add(old); db.commit()
    soup = BeautifulSoup(client.get(f"/app/certificates/{old.id}/print").text, "html.parser")
    assert soup.select_one("main h1") and not soup.select_one("main.notice-letter")
    assert "TEXTO ORIGINAL DEL DOCUMENTO HISTÓRICO" in soup.select_one(".body").text
    db.refresh(old)
    assert old.body == "TEXTO ORIGINAL DEL DOCUMENTO HISTÓRICO"
