from fastapi.testclient import TestClient

from app.main import app


def test_health_and_security_headers():
    with TestClient(app) as client:
        response = client.get('/health')
        assert response.status_code == 200
        payload = response.json()
        assert payload['status'] == 'ok'
        assert payload['version'] == '1.1.0-preview'
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert response.headers['x-frame-options'] == 'SAMEORIGIN'
        assert 'default-src' in response.headers['content-security-policy']


def test_public_pages_render():
    with TestClient(app) as client:
        for path in ('/', '/login', '/activacion'):
            response = client.get(path)
            assert response.status_code == 200
            assert 'Digit Laboral' in response.text
