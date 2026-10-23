from datetime import date, timedelta
import re
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import Document, OfficialCertificateRecord
from app.storage_service import storage
from app.official_certificates import (
    OFFICIAL_CERTIFICATE_TYPES,
    default_expiry_date,
    official_certificate_state,
)


def test_mtess_certificate_uses_official_ninety_day_validity():
    issued = date(2026, 10, 1)
    assert OFFICIAL_CERTIFICATE_TYPES["mtess_certificado_laboral"]["validity_days"] == 90
    assert default_expiry_date("mtess_certificado_laboral", issued) == issued + timedelta(days=90)


def test_ips_aop_validity_and_ips_compliance_are_not_conflated():
    issued = date(2026, 10, 1)
    assert default_expiry_date("ips_constancia_no_asegurado", issued) == issued + timedelta(days=30)
    assert default_expiry_date("ips_consulta_empleador", issued) == issued + timedelta(days=30)
    # IPS's social-security compliance certificate runs until the next payment due date;
    # that date must be recorded from the official document rather than guessed.
    assert default_expiry_date("ips_certificado_cumplimiento", issued) is None


def test_certificate_display_state_handles_fixed_expiry_boundaries():
    today = date(2026, 10, 23)
    assert official_certificate_state("Pendiente", today + timedelta(days=1), today) == "Pendiente"
    assert official_certificate_state("Emitido", today + timedelta(days=16), today) == "Vigente"
    assert official_certificate_state("Emitido", today + timedelta(days=15), today) == "Por vencer"
    assert official_certificate_state("Emitido", today, today) == "Por vencer"
    assert official_certificate_state("Emitido", today - timedelta(days=1), today) == "Vencido"
    assert official_certificate_state("Emitido", None, today) == "Emitido · vigencia por confirmar"


def test_official_catalog_has_official_sources_and_no_issued_document_templates():
    assert len(OFFICIAL_CERTIFICATE_TYPES) >= 8
    for item in OFFICIAL_CERTIFICATE_TYPES.values():
        assert item["institution"] in {"MTESS", "IPS"}
        assert item["source_url"].startswith("https://")
        assert item["requirements"]


def _login(client: TestClient) -> str:
    page = client.get("/login")
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert page.status_code == 200 and match
    response = client.post(
        "/login",
        data={
            "email": "admin@digitlaboral.com.py",
            "password": settings.demo_admin_password,
            "csrf_token": match.group(1),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    dashboard = client.get("/app")
    token_match = re.search(r'name="csrf_token" value="([^"]+)"', dashboard.text)
    assert dashboard.status_code == 200 and token_match
    return token_match.group(1)


def test_official_certificate_workflow_requires_original_and_calculates_expiry():
    with TestClient(app) as client:
        csrf = _login(client)
        page = client.get("/app/certificates/official")
        assert page.status_code == 200
        assert "Certificados oficiales" in page.text
        assert "Certificado Laboral (REOP)" in page.text

        created = client.post(
            "/app/certificates/official",
            data={
                "csrf_token": csrf,
                "company_id": "1",
                "certificate_type": "mtess_certificado_laboral",
                "request_date": "2026-09-30",
                "notes": "Prueba automatizada del seguimiento.",
            },
            follow_redirects=False,
        )
        assert created.status_code == 303
        record_id = int(parse_qs(urlparse(created.headers["location"]).query)["created"][0])

        # A record must not be marked as officially issued without the original.
        missing_original = client.post(
            f"/app/certificates/official/{record_id}/update",
            data={
                "csrf_token": csrf,
                "status": "Emitido",
                "issue_date": "2026-10-01",
                "result_status": "CUMPLE",
                "official_number": "TEST-0001",
                "notes": "Original exigido por el flujo.",
            },
            follow_redirects=False,
        )
        assert missing_original.status_code == 400

        issued = client.post(
            f"/app/certificates/official/{record_id}/update",
            data={
                "csrf_token": csrf,
                "status": "Emitido",
                "issue_date": "2026-10-01",
                "result_status": "CUMPLE",
                "official_number": "TEST-0001",
                "notes": "Original de prueba adjuntado.",
            },
            files={"file": ("mtess-test.pdf", b"%PDF-1.7\noriginal de prueba", "application/pdf")},
            follow_redirects=False,
        )
        assert issued.status_code == 303
        refreshed = client.get("/app/certificates/official")
        assert refreshed.status_code == 200
        assert "TEST-0001" in refreshed.text
        assert "30/12/2026" in refreshed.text
        assert "Descargar original archivado" in refreshed.text

        with SessionLocal() as db:
            saved_record = db.get(OfficialCertificateRecord, record_id)
            assert saved_record is not None and saved_record.document_id is not None
            saved_document = db.get(Document, saved_record.document_id)
            assert saved_document is not None
            document_id = saved_document.id
            stored_key = saved_document.stored_name
            original_bytes = bytes(saved_document.content_bytes) if saved_document.content_bytes is not None else None

        # The configured Render-like local-storage mode keeps the official original
        # in PostgreSQL too, so a transient file-system loss does not erase it.
        if settings.storage_backend == "local":
            assert original_bytes == b"%PDF-1.7\\noriginal de prueba"
            storage.delete(stored_key)
            recovered = client.get(f"/app/documents/{document_id}/download")
            assert recovered.status_code == 200
            assert recovered.content == original_bytes
