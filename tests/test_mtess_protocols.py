"""Pruebas del módulo Certificados > Protocolos y Declaraciones MTESS."""
from __future__ import annotations

from datetime import date

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
    assert "denuncias@example.invalid" in record.body
    pdf = client.get(f"/app/certificates/mtess/{record.id}/download.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    docx = client.get(f"/app/certificates/mtess/{record.id}/download.docx")
    assert docx.status_code == 200 and docx.content[:2] == b"PK"
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
    assert "NO acredita homologación" in item.body


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
