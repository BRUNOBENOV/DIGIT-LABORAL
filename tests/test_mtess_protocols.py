"""Pruebas del módulo Certificados > Protocolos y Declaraciones MTESS."""
from __future__ import annotations

from datetime import date
import io

from docx import Document
from pypdf import PdfReader
from PIL import Image

from app.document_export import decode_metadata
from app.models import CompanyBranding

import pytest

from app.mtess_protocols import DECLARATION, PROTOCOL, applicable_type
from app.models import Employee, GeneratedCertificate
from tests.test_labor_suite import token, web_case


@pytest.mark.parametrize("count,expected", [(0, DECLARATION), (1, DECLARATION),
                                            (10, DECLARATION), (11, PROTOCOL),
                                            (80, PROTOCOL)])
def test_mtess_applicable_document_threshold(count, expected):
    assert applicable_type(count) == expected


def test_mtess_declaration_generation_and_downloads(web_case):
    client, db, _, company, employee, _ = web_case
    csrf = token(client, f"/app/certificates/mtess?company_id={company.id}")
    page = client.get("/app/certificates/mtess", params={"company_id": company.id})
    assert page.status_code == 200
    assert "Hasta 10" in page.text
    assert "Anexo III" in page.text
    submission = {
        "csrf_token": csrf, "company_id": str(company.id),
        "responsible": "Responsable sintético",
        "channel": "denuncias@example.invalid", "hours": "08:00 a 16:00",
        "rit_status": "sin",
    }
    created = client.post("/app/certificates/mtess/generate",
                          data=submission, follow_redirects=False)
    assert created.status_code == 303, created.text
    db.expire_all()
    record = db.query(GeneratedCertificate).filter(
        GeneratedCertificate.company_id == company.id,
        GeneratedCertificate.document_type == DECLARATION,
    ).one()
    assert record.status == "Borrador"
    assert "Empresa sintética" in record.body
    assert "denuncias@example.invalid" not in record.body
    assert decode_metadata(record.observations)["channel"] == "denuncias@example.invalid"
    assert "MODELO ORIENTATIVO DE DECLARACIÓN DE TOLERANCIA CERO" in record.body
    assert "no admitirá represalias" in record.body
    assert "MUNDO DEL TRABAJO" in record.body
    assert "RUC:" not in record.body
    pdf = client.get(f"/app/certificates/mtess/{record.id}/download.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    docx = client.get(f"/app/certificates/mtess/{record.id}/download.docx")
    assert docx.status_code == 200 and docx.content[:2] == b"PK"
    parsed = Document(io.BytesIO(docx.content))
    text = "\n".join(p.text for p in parsed.paragraphs)
    assert "ANEXO III" in text
    assert "MUNDO DEL TRABAJO" in text
    assert "declara expresamente su política de tolerancia cero" in text
    assert any(run.bold for p in parsed.paragraphs for run in p.runs)
    assert len(parsed.inline_shapes) == 0  # Sin logo no hay gráfico de reserva.
    assert len(parsed.tables) == 0
    assert not any(word in text for word in (
        "BORRADOR - REVISAR ANTES DE FIRMAR",
        "Generado por Digit Laboral", "DOCUMENTO LABORAL",
    ))
    pdf_reader = PdfReader(io.BytesIO(pdf.content))
    pdf_text = "\n".join(p.extract_text() or "" for p in pdf_reader.pages)
    assert "ANEXO III" in pdf_text
    assert "MUNDO DEL TRABAJO" in pdf_text
    assert "Empresa sintética" in pdf_text
    assert "BORRADOR" not in pdf_text
    assert "Generado por Digit Laboral" not in pdf_text
    assert "DOCUMENTO LABORAL" not in pdf_text
    assert "Página 1" not in pdf_text
    preview = client.get("/app/certificates/mtess", params={"company_id": company.id})
    assert "Vista previa fiel del Anexo III" in preview.text
    assert "data:image/" not in preview.text
    receipt = client.get(
        f"/app/certificates/mtess/{record.id}/download.pdf",
        params={"kind": "receipt", "employee_id": employee.id},
    )
    assert receipt.status_code == 200 and receipt.content.startswith(b"%PDF")
    # No duplicate if data and issue date have not changed.
    again = client.post("/app/certificates/mtess/generate",
                        data=submission, follow_redirects=False)
    assert again.status_code == 303
    db.expire_all()
    assert db.query(GeneratedCertificate).filter_by(
        company_id=company.id, document_type=DECLARATION,
    ).count() == 1


def test_mtess_protocol_for_eleven_and_requires_rit_selection(web_case):
    client, db, _, company, _, _ = web_case
    for n in range(10):
        db.add(Employee(company_id=company.id, full_name=f"Persona adicional {n}",
                        document_number=f"90000{n}", status="Activo"))
    db.commit()
    csrf = token(client, f"/app/certificates/mtess?company_id={company.id}")
    data = {
        "csrf_token": csrf, "company_id": str(company.id),
        "responsible": "Unidad de prevención",
        "channel": "contacto@example.invalid", "rit_status": "unknown",
    }
    invalid = client.post("/app/certificates/mtess/generate", data=data)
    assert invalid.status_code == 422
    data["rit_status"] = "homologado"
    res = client.post("/app/certificates/mtess/generate",
                      data=data, follow_redirects=False)
    assert res.status_code == 303, res.text
    db.expire_all()
    item = db.query(GeneratedCertificate).filter(
        GeneratedCertificate.company_id == company.id,
        GeneratedCertificate.document_type == PROTOCOL,
    ).one()
    assert "Reglamento Interno de Trabajo" in item.body
    assert "ANEXO II" in item.body
    assert "MODELO ORIENTATIVO DE PROTOCOLO" in item.body
    assert "I. EJE DE PREVENCIÓN" in item.body
    assert "II. EJE DE IDENTIFICACIÓN Y DETECCIÓN DE CASOS" in item.body
    assert "III. EJE DE ATENCIÓN, MEDIDAS DE RESGUARDO Y MEDIDAS CORRECTIVAS" in item.body
    assert "IV. EJE DE SEGUIMIENTO Y EVALUACIÓN DEL PROTOCOLO" in item.body
    assert "7. Flujograma orientativo del procedimiento interno de denuncias." in item.body
    assert "Seguridad y vigilancia" in item.body
    assert "¿Se siente seguro en el trabajo?" in item.body
    assert "Unidad de prevención" in item.body
    assert "Empresa sintética" in item.body
    assert "RUC: 80000001-0" in item.body
    assert "Secretaria General" not in item.body
    assert "Página 35 de 36" not in item.body
    assert "Resolución MTESS N° XX" not in item.body
    pdf = client.get(f"/app/certificates/mtess/{item.id}/download.pdf")
    assert pdf.status_code == 200
    pdf_text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "Generado por Digit Laboral" not in pdf_text
    assert "BORRADOR - REVISAR ANTES DE FIRMAR" not in pdf_text
    assert "ANEXO II" in pdf_text
    assert "I. EJE DE PREVENCIÓN" in pdf_text
    assert "IV. EJE DE SEGUIMIENTO" in pdf_text
    assert "Seguridad y vigilancia" in pdf_text
    assert len(PdfReader(io.BytesIO(pdf.content)).pages) >= 6
    docx = client.get(f"/app/certificates/mtess/{item.id}/download.docx")
    assert docx.status_code == 200
    parsed = Document(io.BytesIO(docx.content))
    assert len(parsed.tables) == 1
    assert len(parsed.tables[0].rows) == 4
    assert len(parsed.inline_shapes) == 0
    doc_text = "\n".join(p.text for p in parsed.paragraphs)
    assert "IV. EJE DE SEGUIMIENTO" in doc_text
    assert "Generado por Digit Laboral" not in doc_text
    preview = client.get(f"/app/certificates/mtess?company_id={company.id}")
    assert "Vista previa fiel del Anexo II" in preview.text
    assert "Seguridad y vigilancia" in preview.text


def test_mtess_cross_tenant_and_role_access(web_case):
    client, _, box, company, _, outsider = web_case
    token(client, f"/app/certificates/mtess?company_id={company.id}")
    assert client.get("/app/certificates/mtess", params={
        "company_id": outsider.company_id,
    }).status_code == 404
    box["user"].role = "empresa"
    box["user"].company_id = company.id
    assert client.get(f"/app/certificates/mtess?company_id={company.id}").status_code == 403


def test_mtess_does_not_mark_generated_document_as_homologated(web_case):
    client, db, _, company, _, _ = web_case
    csrf = token(client, f"/app/certificates/mtess?company_id={company.id}")
    post = client.post("/app/certificates/mtess/generate",
                       data={"csrf_token": csrf, "company_id": company.id,
                             "responsible": "Responsable", "channel": "canal@example.invalid",
                             "rit_status": "sin"}, follow_redirects=False)
    assert post.status_code == 303
    db.expire_all()
    item = db.query(GeneratedCertificate).filter_by(
        company_id=company.id, document_type=DECLARATION,
    ).one()
    bad = client.post(f"/app/certificates/mtess/{item.id}/evidence",
                      data={"csrf_token": csrf, "stage": "Difundido",
                            "evidence_date": date.today().isoformat(),
                            "evidence_reference": ""})
    assert bad.status_code == 422
    good = client.post(f"/app/certificates/mtess/{item.id}/evidence",
                       data={"csrf_token": csrf, "stage": "Firmado",
                             "evidence_date": date.today().isoformat(),
                             "evidence_reference": "Acta sintética N.º 1"},
                       follow_redirects=False)
    assert good.status_code == 303
    db.expire_all()
    assert item.status == "Firmado"


def test_mtess_change_from_ten_to_eleven_keeps_old_version_but_warns(web_case):
    client, db, _, company, _, _ = web_case
    csrf = token(client, f"/app/certificates/mtess?company_id={company.id}")
    response = client.post("/app/certificates/mtess/generate",
                           data={"csrf_token": csrf, "company_id": company.id,
                                 "responsible": "Responsable", "channel": "canal@example.invalid",
                                 "rit_status": "sin"}, follow_redirects=False)
    assert response.status_code == 303
    for n in range(10):
        db.add(Employee(company_id=company.id, full_name=f"Otro trabajador {n}",
                        document_number=f"8011{n}", status="Activo"))
    db.commit()
    page = client.get("/app/certificates/mtess", params={"company_id": company.id})
    assert page.status_code == 200
    assert "cambió de régimen" in page.text
    assert "11 o más" in page.text
    assert "generá el documento correspondiente" in page.text


def test_mtess_declared_company_logo_is_rendered_without_default_branding(web_case):
    client, db, _, company, _, _ = web_case
    image = Image.new("RGB", (150, 45), "white")
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    db.add(CompanyBranding(company_id=company.id,
                           logo_bytes=stream.getvalue(), logo_content_type="image/png"))
    db.commit()
    csrf = token(client, f"/app/certificates/mtess?company_id={company.id}")
    result = client.post("/app/certificates/mtess/generate",
                         data={"csrf_token": csrf, "company_id": company.id,
                               "responsible": "Responsable", "channel": "canal@example.invalid",
                               "rit_status": "sin"}, follow_redirects=False)
    assert result.status_code == 303
    db.expire_all()
    record = db.query(GeneratedCertificate).filter_by(
        company_id=company.id, document_type=DECLARATION,
    ).one()
    preview = client.get("/app/certificates/mtess", params={"company_id": company.id})
    assert 'data:image/png;base64,' in preview.text
    docx_resp = client.get(f"/app/certificates/mtess/{record.id}/download.docx")
    doc = Document(io.BytesIO(docx_resp.content))
    assert len(doc.inline_shapes) == 1
    assert "Digit Laboral" not in "\n".join(p.text for p in doc.paragraphs)
    pdf_resp = client.get(f"/app/certificates/mtess/{record.id}/download.pdf")
    assert pdf_resp.status_code == 200 and pdf_resp.content.startswith(b"%PDF")


def test_official_annex_two_transcription_is_complete_and_versioned():
    from app.mtess_annex_ii import source_pages, build_annex_ii_body, QUESTIONNAIRE, EJE_TITLES
    from datetime import date
    original = source_pages()
    assert sorted(original) == list(range(22, 36))
    assert all(original[page].strip() for page in original)
    result = build_annex_ii_body(
        company_name="Industria de Prueba SA", ruc="80001234-5",
        legal_representative="Representante válido", city="Ciudad del Este",
        issued_on=date(2026, 11, 13), responsible="Responsable interno",
        channel="denuncias@example.invalid", hours="08 a 17",
        rit_status="homologado",
    )
    assert all(eje in result for eje in EJE_TITLES)
    assert "7. Flujograma orientativo" in result
    assert "[[CUESTIONARIO_ANEXO_II]]" in result
    assert "[[FIN_CUESTIONARIO_ANEXO_II]]" in result
    assert "POLÍTICA DE TOLERANCIA CERO FRENTE" in result
    assert len(QUESTIONNAIRE) == 4
    assert sum(len(questions) for _, questions in QUESTIONNAIRE) == 15
    assert "Industri" in result
    assert "[Nombre de la empresa]" not in result
    assert "RESOLUCIÓN MTESS Nº 195/2026" not in result
    assert "Página 35 de 36" not in result
    assert "MARTA" not in result
    assert "Secretaria General" not in result
