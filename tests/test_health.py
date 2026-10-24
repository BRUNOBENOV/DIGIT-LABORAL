from fastapi.testclient import TestClient

from app.main import APP_VERSION, app


def test_health_and_security_headers():
    with TestClient(app) as client:
        response = client.get('/health')
        assert response.status_code == 200
        payload = response.json()
        assert payload['status'] == 'ok'
        assert payload['version'] == APP_VERSION
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert response.headers['x-frame-options'] == 'SAMEORIGIN'
        assert 'default-src' in response.headers['content-security-policy']


def test_public_pages_render():
    with TestClient(app) as client:
        for path in ('/', '/login', '/activacion'):
            response = client.get(path)
            assert response.status_code == 200
            assert 'Digit Laboral' in response.text



def test_health_endpoints_report_the_same_runtime_version():
    with TestClient(app) as client:
        for path in ("/health", "/health/live", "/health/ready"):
            response = client.get(path)
            assert response.status_code == 200, (path, response.text[:200])
            assert response.json()["version"] == APP_VERSION
