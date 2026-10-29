import re
from datetime import date

from fastapi.testclient import TestClient

from app.config import settings
from app.database import SessionLocal
from app.document_export import build_document_body, decode_metadata
from app.main import APP_VERSION, app
from app.models import GeneratedCertificate


def login(client: TestClient) -> str:
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
    dashboard_token = re.search(r'name="csrf_token" value="([^"]+)"', dashboard.text)
    assert dashboard.status_code == 200 and dashboard_token
    return dashboard_token.group(1)


def test_contract_individual_contains_article_46_fields_and_full_clauses():
    title, body = build_document_body(
        "contrato_trabajo",
        company_name="Empresa de Prueba S.A.",
        company_ruc="80012345-6",
        company_address="Av. Principal 123",
        legal_representative="Representante de Prueba",
        employee_name="PERSONA TRABAJADORA",
        employee_document="4.332.400",
        employee_address="Barrio Centro",
        employee_birth_date=date(2000, 5, 2),
        position="Auxiliar Contable",
        admission_date=date(2023, 1, 13),
        salary=3_044_000,
        issue_date=date(2026, 10, 29),
        city="Ciudad del Este",
        metadata={
            "contract_modality": "indefinido",
            "workplace": "Sucursal principal",
            "job_functions": "Registro de comprobantes, conciliaciones y archivo",
            "work_schedule": "Lunes a viernes, de 08:00 a 17:00",
            "weekly_rest": "Domingo",
            "payment_frequency": "Mensual",
            "contract_worker_gender": "No consignado",
            "contract_worker_civil_status": "Soltero/a",
            "contract_worker_nationality": "Paraguaya",
            "contract_payment_method": "Transferencia bancaria",
            "contract_benefits": "Uniforme de trabajo",
            "contract_additional_terms": "Entrega de equipos con inventario",
        },
    )
    assert title == "Contrato Individual de Trabajo"
    assert "artículo 46 de la Ley N.º 213/93" in body
    assert "PRIMERA — OBJETO, CARGO, FUNCIONES Y LUGAR DE PRESTACIÓN" in body
    assert "DÉCIMA — DOMICILIOS Y COMUNICACIONES" in body
    assert "DECIMOTERCERA — LECTURA, EJEMPLARES Y FIRMAS" in body
    assert "treinta días" in body and "sesenta días" in body
    assert "Transferencia bancaria" in body
    assert "Uniforme de trabajo" in body
    assert "no impone exclusividad automática" in body
    assert "no autoriza cambios irrestrictos" in body
    assert "26 años" in body


def test_contract_versions_save_custom_text_and_status_with_parent_link():
    with TestClient(app) as client:
        csrf = login(client)
        base_data = {
            "csrf_token": csrf,
            "company_id": "1",
            "employee_id": "1",
            "document_type": "contrato_trabajo",
            "city": "Ciudad del Este",
            "issue_date": "2026-10-29",
            "position": "Auxiliar Contable",
            "admission_date": "2023-01-13",
            "salary": "3044000",
            "contract_modality": "indefinido",
            "contract_end_date": "",
            "contract_cause": "",
            "workplace": "Oficina central",
            "job_functions": "Registro contable y conciliaciones",
            "work_schedule": "Lunes a viernes de 08:00 a 17:00",
            "weekly_rest": "Domingo",
            "payment_frequency": "Mensual",
            "contract_worker_gender": "No consignado",
            "contract_worker_civil_status": "Soltero/a",
            "contract_worker_nationality": "Paraguaya",
            "contract_payment_method": "Transferencia",
            "contract_benefits": "",
            "contract_additional_terms": "",
            "contract_text": "PRIMERA VERSIÓN EDITABLE — texto personalizado.",
            "intent": "save",
        }
        first_response = client.post("/app/certificates", data=base_data, follow_redirects=False)
        assert first_response.status_code == 303
        first_id = int(re.search(r"created=(\d+)", first_response.headers["location"]).group(1))

        db = SessionLocal()
        try:
            first = db.get(GeneratedCertificate, first_id)
            assert first is not None and first.status == "Borrador"
            assert first.body == "PRIMERA VERSIÓN EDITABLE — texto personalizado."
            first_metadata = decode_metadata(first.observations)
            assert first_metadata["contract_version"] == 1
            assert first_metadata["contract_root_id"] == first.id
        finally:
            db.close()

        edit_page = client.get(f"/app/certificates?edit_id={first_id}")
        assert edit_page.status_code == 200
        assert "Nueva versión del contrato" in edit_page.text
        assert "PRIMERA VERSIÓN EDITABLE" in edit_page.text

        second_data = {
            **base_data,
            "contract_parent_id": str(first_id),
            "contract_text": "SEGUNDA VERSIÓN EDITADA — lista para revisión.",
            "intent": "approve",
        }
        second_response = client.post("/app/certificates", data=second_data, follow_redirects=False)
        assert second_response.status_code == 303
        second_id = int(re.search(r"created=(\d+)", second_response.headers["location"]).group(1))

        db = SessionLocal()
        try:
            second = db.get(GeneratedCertificate, second_id)
            assert second is not None and second.status == "Aprobado"
            assert second.body == "SEGUNDA VERSIÓN EDITADA — lista para revisión."
            second_metadata = decode_metadata(second.observations)
            assert second_metadata["contract_version"] == 2
            assert second_metadata["contract_parent_id"] == first_id
            assert second_metadata["contract_root_id"] == first.id
        finally:
            db.close()

        history_page = client.get("/app/certificates")
        assert history_page.status_code == 200
        assert "Versión 2" in history_page.text
        assert f"/app/certificates?edit_id={second_id}" in history_page.text


def test_contract_signed_state_requires_explicit_signature_receipt_confirmation():
    with TestClient(app) as client:
        csrf = login(client)
        data = {
            "csrf_token": csrf,
            "company_id": "1",
            "employee_id": "1",
            "document_type": "contrato_trabajo",
            "city": "Ciudad del Este",
            "issue_date": "2026-10-29",
            "position": "Auxiliar",
            "admission_date": "2023-01-13",
            "salary": "3044000",
            "contract_modality": "indefinido",
            "workplace": "Oficina central",
            "job_functions": "Funciones administrativas",
            "work_schedule": "Lunes a viernes",
            "weekly_rest": "Domingo",
            "intent": "signed",
        }
        blocked = client.post("/app/certificates", data=data, follow_redirects=False)
        assert blocked.status_code == 400

        data["contract_signature_acknowledged"] = "on"
        accepted = client.post("/app/certificates", data=data, follow_redirects=False)
        assert accepted.status_code == 303
        document_id = int(re.search(r"created=(\d+)", accepted.headers["location"]).group(1))
        db = SessionLocal()
        try:
            item = db.get(GeneratedCertificate, document_id)
            assert item is not None and item.status == "Firmado"
            metadata = decode_metadata(item.observations)
            assert metadata["contract_state"] == "Firmado"
        finally:
            db.close()


def test_contract_generator_version_is_bumped():
    assert APP_VERSION == "2.6.46"
