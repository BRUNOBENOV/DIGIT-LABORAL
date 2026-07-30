from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_employee_record_requires_login():
    with TestClient(app) as client:
        response = client.get('/app/employees/1', follow_redirects=False)
        assert response.status_code == 303
        assert response.headers['location'] == '/login'
