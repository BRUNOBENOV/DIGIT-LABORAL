import re
from datetime import date
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.config import settings

from app.document_export import (
    DOCUMENT_LABELS,
    ExportData,
    build_document_body,
    build_docx_bytes,
    build_pdf_bytes,
    document_detail_table_data,
    guaranies_in_words,
)
from docx import Document as WordDocument
from pypdf import PdfReader
import io
from app.main import app


def login(client: TestClient) -> str:
    page = client.get("/login")
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert page.status_code == 200 and match
    response = client.post(
        "/login",
        data={"email": "admin@digitlaboral.com.py", "password": settings.demo_admin_password, "csrf_token": match.group(1)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    dashboard = client.get("/app")
    dashboard_token = re.search(r'name="csrf_token" value="([^"]+)"', dashboard.text)
    assert dashboard.status_code == 200 and dashboard_token
    return dashboard_token.group(1)


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
        csrf = login(client)
        generator_page = client.get("/app/certificates")
        assert generator_page.status_code == 200
        assert "certificateLastPeriodSalary" in generator_page.text
        assert "certificateSalaryBasic" in generator_page.text
        assert "Resolución MTESS N.º 1163/2025" in generator_page.text
        assert "notificacion_vacaciones" in generator_page.text
        response = client.post(
            "/app/certificates",
            data={
                "csrf_token": csrf,
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



def test_work_certificate_uses_article_93_end_date_and_last_pay_period():
    title, body = build_document_body(
        "certificado_trabajo_a",
        company_name="Empresa Demo S.A.",
        employee_name="María González",
        employee_document="1.234.567",
        position="Auxiliar administrativa",
        admission_date=date(2022, 3, 1),
        salary=3_800_000,
        issue_date=date(2026, 10, 23),
        city="Ciudad del Este",
        metadata={
            "effective_date": "2026-10-15",
            "last_period_salary_amount": 3_550_000,
            "include_salary": False,
        },
    )
    assert title == "Certificado de Trabajo"
    assert "desde el 1 de marzo de 2022 hasta el 15 de octubre de 2026" in body
    assert "salario devengado durante el último período de pago" in body.lower()
    assert "Gs. 3.550.000" in body
    assert "Remuneración mensual registrada: Gs. 3.800.000" not in body


def test_internal_contract_models_have_type_specific_official_model_fields():
    metadata = {
        "contract_modality": "mipyme_plazo_fijo",
        "contract_end_date": "2026-12-31",
        "contract_cause": "Necesidad temporal específica y documentada",
        "previous_contract_number": "CT-2026-01",
        "workplace": "Local comercial, Ciudad del Este",
        "job_functions": "Atención al cliente y caja",
        "work_schedule": "Lunes a viernes, 08:00 a 17:00",
        "weekly_rest": "Domingo",
        "payment_frequency": "Mensual",
        "probation_period": "Según procedencia legal",
    }
    types = (
        "contrato_trabajo",
        "contrato_tiempo_parcial",
        "contrato_mipymes_plazo_determinado",
        "contrato_mipymes_80",
        "adenda_prorroga_contrato",
    )
    for document_type in types:
        assert document_type in DOCUMENT_LABELS
        title, body = build_document_body(
            document_type,
            company_name="Empresa Demo S.A.",
            employee_name="María González",
            employee_document="1.234.567",
            position="Auxiliar administrativa",
            admission_date=date(2026, 1, 2),
            salary=3_800_000,
            issue_date=date(2026, 10, 23),
            city="Ciudad del Este",
            metadata=metadata,
            company_ruc="80000000-0",
            company_address="Centro, Ciudad del Este",
            legal_representative="José Pérez",
        )
        assert title == DOCUMENT_LABELS[document_type]
        assert "Atención al cliente y caja" in body
        assert "Lunes a viernes, 08:00 a 17:00" in body
        assert "BORRADOR" in body or "REVISAR" in body


def test_payroll_receipt_table_breaks_down_official_income_and_deductions():
    metadata = {
        "salary_basic_amount": 3_500_000,
        "overtime_day_amount": 150_000,
        "overtime_night_amount": 100_000,
        "ips_deduction_amount": 341_000,
        "advance_deduction_amount": 100_000,
    }
    detail = document_detail_table_data("recibo_salario", metadata, 3_500_000)
    assert detail is not None
    assert detail["headers"] == ["Concepto", "Haberes (Gs.)", "Descuentos (Gs.)"]
    text = " ".join(str(cell) for row in detail["rows"] for cell in row["cells"])
    assert "Horas extras diurnas (50%)" in text
    assert "Horas extras nocturnas (100%)" in text
    assert "TOTAL INGRESOS" in text
    assert "TOTAL DESCUENTOS" in text
    assert "NETO A PERCIBIR" in text
    assert "3.750.000" in text
    assert "441.000" in text
    assert "3.309.000" in text


def test_payroll_detail_table_appears_in_generated_word_and_pdf():
    data = ExportData(
        document_type="recibo_salario",
        title="Recibo de Salario",
        city="Ciudad del Este",
        issue_date=date(2026, 10, 23),
        company_name="Empresa Demo S.A.",
        company_ruc="80000000-0",
        employee_name="María González",
        employee_document="1.234.567",
        position="Auxiliar administrativa",
        admission_date=date(2024, 2, 1),
        salary=3_500_000,
        body="Liquidación de salario correspondiente al período declarado.",
        status="Emitido",
        metadata={
            "document_number": "DL-REC-0001",
            "period_start": "2026-10-01",
            "period_end": "2026-10-31",
            "payment_date": "2026-10-31",
            "payment_method": "Transferencia bancaria",
            "days_worked": "30",
            "hours_worked": "240",
            "salary_basic_amount": 3_500_000,
            "overtime_day_amount": 150_000,
            "ips_deduction_amount": 341_000,
            "advance_deduction_amount": 100_000,
        },
    )
    word = WordDocument(io.BytesIO(build_docx_bytes(data)))
    word_text = "\n".join(paragraph.text for paragraph in word.paragraphs)
    word_text += "\n" + "\n".join(cell.text for table in word.tables for row in table.rows for cell in row.cells)
    assert "TOTAL INGRESOS" in word_text
    assert "NETO A PERCIBIR" in word_text

    pdf = PdfReader(io.BytesIO(build_pdf_bytes(data)))
    pdf_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "TOTAL INGRESOS" in pdf_text
    assert "NETO A PERCIBIR" in pdf_text
