from datetime import date
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.document_export import build_document_body, guaranies_in_words
from app.main import app


def login(client: TestClient) -> None:
    response = client.post(
        "/login",
        data={"email": "admin@digitlaboral.com.py", "password": "demo123"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_amount_in_words_and_legal_basis():
    assert guaranies_in_words(2_739_341) == "dos millones setecientos treinta y nueve mil trescientos cuarenta y un guaraníes"
    title, body = build_document_body(
        "aguinaldo_anual",
        company_name="Empresa Demo S.A.",
        employee_name="Juan Pérez",
        employee_document="1.234.567",
        position="Auxiliar",
        admission_date=date(2024, 2, 1),
        salary=3_044_000,
        issue_date=date(2026, 12, 15),
        city="Ciudad del Este",
        metadata={
            "period_start": "2026-01-01",
            "period_end": "2026-12-31",
            "amount": 2_739_341,
            "notes": "",
        },
    )
    assert title == "Recibo de Pago de Aguinaldo"
    assert "artículo 243" in body
    assert "2.739.341" in body


def test_word_and_pdf_downloads():
    with TestClient(app) as client:
        login(client)
        response = client.post(
            "/app/certificates",
            data={
                "company_id": 1,
                "employee_id": 1,
                "document_type": "constancia",
                "city": "Ciudad del Este",
                "issue_date": "2026-08-01",
                "position": "Vendedor",
                "admission_date": "2024-02-01",
                "salary": "3044000",
                "nationality": "paraguaya",
                "civil_status": "",
                "observations": "Presentación bancaria.",
                "intent": "save",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        query = parse_qs(urlparse(response.headers["location"]).query)
        certificate_id = int(query["created"][0])

        docx = client.get(f"/app/certificates/{certificate_id}/download.docx")
        assert docx.status_code == 200
        assert docx.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        assert docx.content[:2] == b"PK"

        pdf = client.get(f"/app/certificates/{certificate_id}/download.pdf")
        assert pdf.status_code == 200
        assert pdf.headers["content-type"].startswith("application/pdf")
        assert pdf.content.startswith(b"%PDF")
