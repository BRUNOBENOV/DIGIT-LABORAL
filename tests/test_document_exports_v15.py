import re
import uuid
from datetime import date, datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.config import settings
from app.database import SessionLocal
from app.models import Company, Employee, Vacation

from app.document_export import (
    DOCUMENT_LABELS,
    ExportData,
    build_document_body,
    build_docx_bytes,
    build_pdf_bytes,
    document_detail_table_data,
    export_data_from_certificate,
    document_signature_mode,
    document_receipt_mode,
    guaranies_in_words,
)
from docx import Document as WordDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH
from pypdf import PdfReader
import io
from app.main import APP_BUILD, APP_VERSION, app


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


def test_app_version_and_build_are_visible_in_the_global_header():
    with TestClient(app) as client:
        login(client)
        response = client.get("/app")
        assert response.status_code == 200
        assert "app-version-indicator" in response.text
        assert f"v{APP_VERSION}" in response.text
        assert f"BUILD {APP_BUILD}" in response.text
        assert app.version == APP_VERSION



def test_certificate_a_preview_uses_model_text_and_uncached_static_asset():
    with TestClient(app) as client:
        login(client)
        page = client.get("/app/certificates")
        assert page.status_code == 200
        assert "no-store" in page.headers.get("cache-control", "")
        assert f"app.js?v={APP_VERSION}" in page.text
        script = client.get(f"/static/app.js?v={APP_VERSION}")
        assert script.status_code == 200
        assert "prestó servicios en la firma comercial" in script.text
        assert "se retira por su propia voluntad" not in script.text
        assert "a nuestra entera satisfacción" not in script.text
        assert "scheduleCanonicalCertificatePreview(type)" in script.text
        assert "formData.set('intent', 'preview')" in script.text
        assert "if (!companySelect.value || !employeeSelect.value) return;" in script.text
        assert "[NOMBRE DE LA EMPRESA]" in script.text
        assert "[NOMBRE COMPLETO DEL FUNCIONARIO]" in script.text
        assert "certificado_trabajo_b: 'Certificado de Trabajo B'" in script.text
        assert "if (!['certificado_trabajo_a', 'certificado_trabajo_b', 'constancia'].includes(type)) return;" in script.text
        assert 'data-address="' in page.text
        assert 'data-vacation-days=' not in page.text
        assert 'id="certificatePreviewPhone"' in page.text
        assert 'data-legal-representative=' in page.text
        assert 'id="certificatePreviewAddress"' in page.text
        assert "C E R T I F I C O:" in script.text
        assert "previewDate.style.display = '';" in script.text
        assert "previewDate.style.textAlign = certificateModelTypes.has(type) ? 'right' : '';" in script.text
        assert ".certificate-preview-signature-pair b,.certificate-preview-signature-pair small{display:block" in page.text
        assert 'id="certificatePreviewSignaturePair" style="display:none!important;"' in page.text
        assert 'id="certificatePreviewReceipt"' in page.text
        assert 'data-signature-mode="employer"' in page.text
        assert "signatureMode === 'both'" in script.text
        assert "style.setProperty('display', usePair ? 'grid' : 'none', 'important')" in script.text


def test_certificate_b_matches_requested_model():
    title, body = build_document_body(
        "certificado_trabajo_b",
        company_name="KAMNIZ SRL",
        employee_name="DIEGO DAMIAN, FRANCO TABOADA",
        employee_document="6.638.398",
        position="DEPOSITERO",
        admission_date=date(2026, 7, 1),
        salary=0,
        issue_date=date(2026, 10, 29),
        city="Ciudad del Este",
        metadata={"effective_date": "2026-10-24", "last_period_salary_amount": 2_500_000},
    )
    assert title == "Certificado de Trabajo B"
    assert body.startswith("C E R T I F I C O:")
    assert "prestó servicios en la firma comercial KAMNIZ SRL" in body
    assert "desde el 1 de julio de 2026 hasta el 24 de octubre de 2026" in body
    assert "desempeñándose como DEPOSITERO." in body
    assert "Salario devengado durante el último período de pago: Gs. 2.500.000" in body
    assert "por su propia voluntad" not in body
    assert "a nuestra entera satisfacción" not in body

    data = ExportData(
        document_type="certificado_trabajo_b",
        title=title,
        city="Ciudad del Este",
        issue_date=date(2026, 10, 29),
        company_name="KAMNIZ SRL",
        company_address="PIRIBEBUY E/MNHOR RODRIGUEZ",
        company_phone="(061)518-452",
        employee_name="DIEGO DAMIAN, FRANCO TABOADA",
        employee_document="6.638.398",
        position="DEPOSITERO",
        admission_date=date(2026, 7, 1),
        body=body,
        status="Emitido",
    )
    word = WordDocument(io.BytesIO(build_docx_bytes(data)))
    signature_text = "\n".join(paragraph.text for paragraph in word.paragraphs)
    assert "KAMNIZ SRL" in signature_text
    assert "PIRIBEBUY E/MNHOR RODRIGUEZ" in signature_text
    assert "TEL. (061)518-452" in signature_text
    pdf = PdfReader(io.BytesIO(build_pdf_bytes(data)))
    pdf_text = " ".join(" ".join((page.extract_text() or "").split()) for page in pdf.pages)
    assert "PIRIBEBUY E/MNHOR RODRIGUEZ" in pdf_text
    assert "TEL. (061)518-452" in pdf_text


def test_certificate_preview_endpoint_uses_same_body_as_export_model():
    with TestClient(app) as client:
        csrf = login(client)
        base_data = {
            "csrf_token": csrf,
            "company_id": 1,
            "employee_id": 1,
            "document_type": "certificado_trabajo_a",
            "city": "Ciudad del Este",
            "issue_date": "2026-10-29",
            "position": "Auxiliar",
            "admission_date": "2026-07-01",
            "salary": "3044000",
            "effective_date": "2026-10-24",
            "last_period_salary_amount": "",
            "intent": "preview",
        }
        response = client.post("/app/certificates", data=base_data, follow_redirects=False)
        assert response.status_code == 200
        assert "no-store" in response.headers.get("cache-control", "")
        payload = response.json()
        assert payload["document_type"] == "certificado_trabajo_a"
        assert payload["body"].startswith("C E R T I F I C O:")
        assert "prestó servicios en la firma comercial" in payload["body"]

        base_data["document_type"] = "certificado_trabajo_b"
        base_data["position"] = "DEPOSITERO"
        b_response = client.post("/app/certificates", data=base_data, follow_redirects=False)
        assert b_response.status_code == 200
        b_payload = b_response.json()
        assert b_payload["document_type"] == "certificado_trabajo_b"
        assert b_payload["title"] == "Certificado de Trabajo B"
        assert "prestó servicios en la firma comercial" in b_payload["body"]
        assert "Salario devengado durante el último período de pago" in b_payload["body"] or "importe a completar según el último período de pago" in b_payload["body"]
        assert "desempeñándose como DEPOSITERO." in b_payload["body"]

        base_data["document_type"] = "constancia"
        base_data["effective_date"] = ""
        base_data["last_period_salary_amount"] = ""
        base_data["nationality"] = "paraguaya"
        base_data["civil_status"] = "soltera"
        base_data["include_salary"] = "on"
        constancia_response = client.post("/app/certificates", data=base_data, follow_redirects=False)
        assert constancia_response.status_code == 200
        constancia_body = constancia_response.json()["body"]
        assert "es empleado/a de la firma comercial" in constancia_body
        assert "de nacionalidad PARAGUAYA" in constancia_body
        assert "domiciliado/a en" not in constancia_body
        assert "ubicada sobre la calle" in constancia_body
        assert "remuneración mensual registrada de Gs." in constancia_body
        assert "para los fines y efectos a que hubiere lugar" in constancia_body
        assert "a los veintinueve días" not in constancia_body



def test_work_certificate_dates_are_visible_and_right_aligned_in_word_and_pdf():
    date_text = "CIUDAD DEL ESTE, 29 de octubre de 2026"
    for document_type, title in (
        ("certificado_trabajo_a", "Certificado de Trabajo"),
        ("certificado_trabajo_b", "Certificado de Trabajo B"),
        ("constancia", "Constancia de Trabajo"),
    ):
        data = ExportData(
            document_type=document_type,
            title=title,
            city="Ciudad del Este",
            issue_date=date(2026, 10, 29),
            company_name="Empresa Demo S.A.",
            company_address="Centro, Ciudad del Este",
            company_phone="061 500000",
            legal_representative="María Representante",
            signature_title="Representante legal",
            employee_name="Juan Pérez",
            employee_document="1.234.567",
            position="Auxiliar",
            admission_date=date(2022, 3, 1),
            salary=3_800_000,
            body="C E R T I F I C O:\n\nQue Juan Pérez presta servicios en Empresa Demo S.A.",
            status="Emitido",
        )
        word = WordDocument(io.BytesIO(build_docx_bytes(data)))
        date_paragraphs = [p for p in word.paragraphs if date_text in p.text]
        assert len(date_paragraphs) == 1
        assert date_paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.RIGHT
        word_text = "\n".join(p.text for p in word.paragraphs)
        assert "María Representante" in word_text
        assert "Representante legal" in word_text
        assert "Empresa Demo S.A." in word_text

        pdf = PdfReader(io.BytesIO(build_pdf_bytes(data)))
        pdf_text = " ".join(" ".join((page.extract_text() or "").split()) for page in pdf.pages)
        assert pdf_text.count(date_text) == 1
        assert "María Representante" in pdf_text
        assert "Representante legal" in pdf_text
        assert "Empresa Demo S.A." in pdf_text


def test_signature_policy_is_consistent_for_certificates_and_employee_requests():
    for document_type in ("certificado_trabajo_a", "certificado_trabajo_b", "constancia"):
        assert document_signature_mode(document_type) == "employer"
        assert document_receipt_mode(document_type) == ""
    for document_type in ("contrato_trabajo", "recibo_salario", "notificacion_preaviso"):
        assert document_signature_mode(document_type) == "both"
    for document_type in ("renuncia", "solicitud_vacacion", "permiso_laboral", "permiso_paternidad"):
        assert document_signature_mode(document_type) == "employee"
        assert document_receipt_mode(document_type) == "employee_authorization"
    assert document_receipt_mode("notificacion_preaviso") == "receipt_disclaimer"
    assert document_receipt_mode("notificacion_vacaciones") == "receipt_date"


def test_work_certificates_have_no_employee_signature_in_print_word_or_pdf():
    with TestClient(app) as client:
        csrf = login(client)
        for document_type in ("certificado_trabajo_a", "certificado_trabajo_b", "constancia"):
            response = client.post(
                "/app/certificates",
                data={
                    "csrf_token": csrf,
                    "company_id": 1,
                    "employee_id": 1,
                    "document_type": document_type,
                    "city": "Ciudad del Este",
                    "issue_date": "2026-10-29",
                    "position": "Auxiliar",
                    "admission_date": "2024-02-01",
                    "salary": "3044000",
                    "effective_date": "",
                    "last_period_salary_amount": "",
                    "calculation_id": "",
                    "intent": "save",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            certificate_id = int(parse_qs(urlparse(response.headers["location"]).query)["created"][0])

            printed = client.get(f"/app/certificates/{certificate_id}/print")
            assert printed.status_code == 200
            assert printed.text.count('class="date" style="text-align:right;"') == 1
            assert "CIUDAD DEL ESTE, 29 de octubre de 2026" in printed.text
            assert 'class="signature work-certificate-signature"' in printed.text
            assert 'Se expide la presente constancia en' not in printed.text
            assert "Firma / recepción del trabajador/a" not in printed.text
            assert "Firma del trabajador/a" not in printed.text
            assert "Firma del empleador/a" not in printed.text

            word_response = client.get(f"/app/certificates/{certificate_id}/download.docx")
            assert word_response.status_code == 200
            word_document = WordDocument(io.BytesIO(word_response.content))
            word_text = "\n".join([paragraph.text for paragraph in word_document.paragraphs] + [
                cell.text
                for table in word_document.tables
                for row in table.rows
                for cell in row.cells
            ])
            assert "Firma / recepción del trabajador/a" not in word_text
            assert "Firma del trabajador/a" not in word_text
            assert "Firma del empleador/a" not in word_text

            pdf_response = client.get(f"/app/certificates/{certificate_id}/download.pdf")
            assert pdf_response.status_code == 200
            pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf_response.content)).pages)
            assert "Firma / recepción del trabajador/a" not in pdf_text
            assert "Firma del trabajador/a" not in pdf_text
            assert "Firma del empleador/a" not in pdf_text



def test_constancia_matches_requested_model_and_signature_in_word_pdf():
    metadata = {
        "nationality": "paraguaya",
        "civil_status": "soltera",
        "include_salary": True,
    }
    title, body = build_document_body(
        "constancia",
        company_name="TALLER LUKY - JAVIER MIR",
        employee_name="BLANCA ARAUJO",
        employee_document="1.234.567",
        position="Auxiliar administrativa",
        admission_date=date(2024, 2, 1),
        salary=3_044_000,
        issue_date=date(2026, 10, 29),
        city="Ciudad del Este",
        metadata=metadata,
        company_address="KM 5,5 - LA BLANCA",
        company_phone="573-327",
        legal_representative="JAVIER MIRANDA",
        employee_address="Barrio La Blanca, Ciudad del Este",
    )
    assert title == "Constancia de Trabajo"
    assert body.startswith("C E R T I F I C O:\n\n")
    assert "Que BLANCA ARAUJO, con C.I. N.º 1.234.567, de nacionalidad PARAGUAYA" in body
    assert "de estado civil SOLTERA" in body
    assert "domiciliado/a en Barrio La Blanca, Ciudad del Este" in body
    assert "es empleado/a de la firma comercial TALLER LUKY - JAVIER MIR" in body
    assert "ubicada sobre la calle KM 5,5 - LA BLANCA" in body
    assert "desempeñándose como Auxiliar administrativa" in body
    assert "remuneración mensual registrada de Gs. 3.044.000" in body
    assert "a los veintinueve días del mes de octubre del año dos mil veintiséis" not in body
    assert "para los fines y efectos a que hubiere lugar" in body

    data = ExportData(
        document_type="constancia",
        title=title,
        city="Ciudad del Este",
        issue_date=date(2026, 10, 29),
        company_name="TALLER LUKY - JAVIER MIR",
        company_address="KM 5,5 - LA BLANCA",
        company_phone="573-327",
        legal_representative="JAVIER MIRANDA",
        signature_title="Responsable",
        employee_name="BLANCA ARAUJO",
        employee_document="1.234.567",
        position="Auxiliar administrativa",
        admission_date=date(2024, 2, 1),
        salary=3_044_000,
        body=body,
        status="Emitido",
        metadata=metadata,
    )
    word = WordDocument(io.BytesIO(build_docx_bytes(data)))
    word_text = "\n".join(paragraph.text for paragraph in word.paragraphs)
    assert "domiciliado/a en Barrio La Blanca, Ciudad del Este" in word_text
    assert "JAVIER MIRANDA" in word_text and "Responsable" in word_text
    assert "TEL. 573-327" in word_text
    assert "C E R T I F I C O:" in word_text
    assert "a los veintinueve días del mes de octubre del año dos mil veintiséis" not in word_text

    pdf = PdfReader(io.BytesIO(build_pdf_bytes(data)))
    pdf_text = " ".join(" ".join((page.extract_text() or "").split()) for page in pdf.pages)
    assert "ubicada sobre la calle KM 5,5 - LA BLANCA" in pdf_text
    assert "remuneración mensual registrada de Gs. 3.044.000" in pdf_text
    assert "JAVIER MIRANDA" in pdf_text and "Responsable" in pdf_text
    assert "C E R T I F I C O:" in pdf_text
    assert "a los veintinueve días del mes de octubre del año dos mil veintiséis" not in pdf_text
    assert "TEL. 573-327" in pdf_text

    _, ended_body = build_document_body(
        "constancia",
        company_name="TALLER LUKY - JAVIER MIR",
        employee_name="BLANCA ARAUJO",
        employee_document="1.234.567",
        position="Auxiliar administrativa",
        admission_date=date(2024, 2, 1),
        salary=3_044_000,
        issue_date=date(2026, 10, 29),
        city="Ciudad del Este",
        metadata={"effective_date": "2026-10-24", "last_period_salary_amount": 2_800_000, **metadata},
        company_address="KM 5,5 - LA BLANCA",
        employee_address="Barrio La Blanca, Ciudad del Este",
    )
    assert "fue empleado/a de la firma comercial" in ended_body
    assert "hasta el 24 de octubre de 2026" in ended_body
    assert "Gs. 2.800.000" in ended_body
    assert "remuneración mensual de Gs. 3.044.000" not in ended_body



def test_company_legal_representative_has_priority_over_branding_signatory_in_exports():
    branding = SimpleNamespace(
        signature_name="Nombre configurado en branding",
        signature_title="Gerencia",
        logo_bytes=None,
        logo_content_type="",
        logo_fit="contain",
        logo_scale=100,
        logo_alignment="center",
        logo_background="white",
        primary_color="#173B86",
        secondary_color="#0B1F48",
        document_footer="Digit Laboral",
    )
    company = SimpleNamespace(
        legal_name="EMPRESA DE PRUEBA S.R.L.",
        legal_representative="JAVIER MIRANDA",
        responsible_name="Responsable alternativo",
        branding=branding,
        ruc="80000000-1",
        address="KM 5,5 - LA BLANCA",
        phone="573-327",
        email="",
    )
    certificate = SimpleNamespace(
        company=company,
        observations="",
        document_type="constancia",
        title="Constancia de Trabajo",
        city="Ciudad del Este",
        issue_date=date(2026, 10, 29),
        company_name_snapshot="EMPRESA DE PRUEBA S.R.L.",
        employee_name_snapshot="BLANCA ARAUJO",
        employee_document_snapshot="1.234.567",
        position_snapshot="Auxiliar administrativa",
        admission_date_snapshot=date(2024, 2, 1),
        salary_snapshot=3_044_000,
        body="C E R T I F I C O:\n\nConstancia de prueba.",
        status="Emitido",
        created_by="Prueba automatizada",
        created_at=datetime(2026, 10, 29, 10, 0, 0),
    )

    data = export_data_from_certificate(certificate)
    assert data.legal_representative == "JAVIER MIRANDA"
    assert data.signature_title == "Representante legal"

    docx = WordDocument(io.BytesIO(build_docx_bytes(data)))
    docx_text = "\n".join([paragraph.text for paragraph in docx.paragraphs] + [
        cell.text for table in docx.tables for row in table.rows for cell in row.cells
    ])
    assert "JAVIER MIRANDA" in docx_text
    assert "Representante legal" in docx_text
    assert "Nombre configurado en branding" not in docx_text
    assert "Responsable alternativo" not in docx_text

    pdf = PdfReader(io.BytesIO(build_pdf_bytes(data)))
    pdf_text = " ".join(" ".join((page.extract_text() or "").split()) for page in pdf.pages)
    assert "JAVIER MIRANDA" in pdf_text
    assert "Representante legal" in pdf_text
    assert "Nombre configurado en branding" not in pdf_text
    assert "Responsable alternativo" not in pdf_text

    certificate.document_type = "certificado_trabajo_b"
    certificate.title = "Certificado de Trabajo B"
    data_b = export_data_from_certificate(certificate)
    assert data_b.legal_representative == "JAVIER MIRANDA"
    assert data_b.signature_title == "Representante legal"
    docx_b = WordDocument(io.BytesIO(build_docx_bytes(data_b)))
    docx_b_text = "\n".join([paragraph.text for paragraph in docx_b.paragraphs] + [
        cell.text for table in docx_b.tables for row in table.rows for cell in row.cells
    ])
    assert "JAVIER MIRANDA" in docx_b_text
    assert "EMPRESA DE PRUEBA S.R.L." in docx_b_text
    assert "KM 5,5 - LA BLANCA" in docx_b_text
    assert "TEL. 573-327" in docx_b_text
    assert "Nombre configurado en branding" not in docx_b_text

    pdf_b = PdfReader(io.BytesIO(build_pdf_bytes(data_b)))
    pdf_b_text = " ".join(" ".join((page.extract_text() or "").split()) for page in pdf_b.pages)
    assert "JAVIER MIRANDA" in pdf_b_text
    assert "EMPRESA DE PRUEBA S.R.L." in pdf_b_text
    assert "KM 5,5 - LA BLANCA" in pdf_b_text
    assert "TEL. 573-327" in pdf_b_text
    assert "Nombre configurado en branding" not in pdf_b_text


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
        assert "Certificado de Trabajo" in generator_page.text
        assert "Referencias oficiales utilizadas" not in generator_page.text
        assert "notificacion_vacaciones" in generator_page.text
        certificate_menu = re.search(
            r'<aside class="certificate-type-menu"[^>]*>(.*?)</aside>',
            generator_page.text,
            re.DOTALL,
        )
        assert certificate_menu
        assert re.findall(
            r'data-certificate-type="([^"]+)"[^>]*>([^<]+)</button>',
            certificate_menu.group(1),
        ) == [
            ("certificado_trabajo_a", "Certificado de Trabajo A"),
            ("certificado_trabajo_b", "Certificado de Trabajo B"),
            ("constancia", "Constancia de Trabajo"),
            ("notificacion_preaviso", "Notificación de Preaviso"),
            ("renuncia", "Notificación de Renuncia"),
            ("despido", "Notificación de Despidos"),
            ("solicitud_vacacion", "Solicitud de Vacación"),
            ("notificacion_vacaciones", "Notificación de Vacación"),
            ("usufructo_vacaciones", "Usufructo de Vacaciones"),
            ("contrato_trabajo", "Contrato de Trabajo"),
        ]
        assert 'id="certificatePreview"' in generator_page.text
        certificate_form = re.search(
            r'<form\b(?=[^>]*id="certificateForm")[^>]*>(.*?)</form>',
            generator_page.text,
            re.DOTALL,
        )
        assert certificate_form
        # A single payment_date control serves aguinaldo receipts and payroll receipts.
        # Duplicate names made the later hidden input override the visible date.
        assert len(re.findall(r'name="payment_date"', certificate_form.group(1))) == 1
        assert 'data-specific="aguinaldo_anual aguinaldo_proporcional recibo_salario"' in certificate_form.group(1)
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
                # Browsers submit empty strings for optional controls. These must
                # be normalized rather than rejected by date/integer validation.
                "effective_date": "",
                "calculation_id": "",
                "period_start": "",
                "period_end": "",
                "leave_start": "",
                "leave_end": "",
                "contract_end_date": "",
                "payment_date": "",
                "vacation_request_date": "",
                "vacation_notice_date": "",
                "vacation_payment_date": "",
                "birth_event_date": "",
                "last_worked_date": "",
                "notice_start_date": "",
                "incident_date": "",
                "sanction_start_date": "",
                "sanction_end_date": "",
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
    assert "C E R T I F I C O:" in body
    assert "prestó servicios en la firma comercial Empresa Demo S.A." in body
    assert "desde el 1 de marzo de 2022 hasta el 15 de octubre de 2026" in body
    assert "salario devengado durante el último período de pago" in body.lower()
    assert "Gs. 3.550.000" in body
    assert "se retira por su propia voluntad" not in body
    assert "a nuestra entera satisfacción" not in body
    assert "para su eventual uso ante terceros" not in body
    assert "Remuneración mensual registrada: Gs. 3.800.000" not in body



def test_work_certificate_for_active_employee_does_not_claim_termination():
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
        metadata={"include_salary": False},
    )
    assert title == "Certificado de Trabajo"
    assert "C E R T I F I C O:" in body
    assert "presta servicios en la firma comercial Empresa Demo S.A. desde el 1 de marzo de 2022" in body
    assert "por su propia voluntad" not in body
    assert "eventual uso ante terceros" not in body

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
    pdf_text = " ".join(" ".join((page.extract_text() or "").split()) for page in pdf.pages)
    assert "TOTAL INGRESOS" in pdf_text
    assert "NETO A PERCIBIR" in pdf_text



def test_work_constancia_uses_last_pay_period_for_termination():
    title, body = build_document_body(
        "constancia",
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
            "include_salary": "off",
        },
    )
    assert title == "Constancia de Trabajo"
    assert "15 de octubre de 2026" in body
    assert "Salario devengado durante el último período de pago" in body
    assert "3.550.000" in body
    assert "3.800.000" not in body



def test_vacation_request_requires_current_period_and_explicit_days_not_historical_usage():
    with SessionLocal() as db:
        company = db.get(Company, 1)
        assert company is not None
        employee = Employee(
            company_id=company.id,
            full_name=f"Funcionario vacaciones {uuid.uuid4().hex[:8]}",
            document_number=f"VAC-TEST-{uuid.uuid4().hex[:10]}",
            position="Auxiliar",
        )
        db.add(employee)
        db.flush()
        db.add(Vacation(
            employee_id=employee.id,
            period_year=2025,
            entitled_days=12,
            used_days=5,
            start_date=date(2025, 8, 1),
            end_date=date(2025, 8, 5),
            status="Usufructuado",
            notes="Registro histórico para prueba",
        ))
        db.commit()
        employee_id = employee.id
        company_id = company.id

    with TestClient(app) as client:
        csrf = login(client)
        form_data = {
            "csrf_token": csrf,
            "company_id": str(company_id),
            "employee_id": str(employee_id),
            "document_type": "solicitud_vacacion",
            "city": "Ciudad del Este",
            "issue_date": "2026-10-29",
            "position": "Auxiliar",
            "admission_date": "2024-02-01",
            "salary": "3044000",
            "leave_start": "2026-11-02",
            "leave_end": "2026-11-07",
            "vacation_period_year": "2026",
            "vacation_days": "",
            "vacation_request_date": "2026-10-29",
            "intent": "save",
        }
        missing_days = client.post("/app/certificates", data=form_data, follow_redirects=False)
        assert missing_days.status_code == 400
        assert "cantidad entera de días" in missing_days.text.lower()

        form_data["vacation_days"] = "0"
        zero_days = client.post("/app/certificates", data=form_data, follow_redirects=False)
        assert zero_days.status_code == 400
        assert "cantidad entera de días" in zero_days.text.lower()

        form_data["vacation_days"] = "6"
        created = client.post("/app/certificates", data=form_data, follow_redirects=False)
        assert created.status_code == 303
        certificate_id = int(parse_qs(urlparse(created.headers["location"]).query)["created"][0])
        printed = client.get(f"/app/certificates/{certificate_id}/print")
        assert printed.status_code == 200
        assert "Días solicitados: 6" in printed.text
        assert "desde el 02/11/2026 hasta el 07/11/2026" in printed.text
