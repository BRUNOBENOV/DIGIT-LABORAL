from datetime import date

from fastapi.testclient import TestClient

from app.main import app, build_certificate_body


def test_calculations_and_certificates_render_after_login():
    with TestClient(app) as client:
        login = client.post(
            "/login",
            data={"email": "admin@digitlaboral.com.py", "password": "demo123"},
            follow_redirects=False,
        )
        assert login.status_code == 303
        for path, marker in (("/app/calculations", "Cálculo"), ("/app/certificates", "Certificados")):
            response = client.get(path)
            assert response.status_code == 200
            assert marker in response.text


def test_certificate_body_uses_snapshot_data():
    title, body = build_certificate_body(
        "certificado_trabajo_a",
        "Empresa Demo S.A.",
        "Juan Pérez",
        "1.234.567",
        "Auxiliar",
        date(2024, 2, 1),
        3_044_000,
        "Presentación ante entidad bancaria.",
    )
    assert title == "Certificado de Trabajo A"
    assert "Empresa Demo S.A." in body
    assert "Juan Pérez" in body
    assert "3.044.000" in body
    assert "entidad bancaria" in body
