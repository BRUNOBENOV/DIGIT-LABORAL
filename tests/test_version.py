from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_version_file_matches_health_and_visible_application_banner():
    version_file = Path(__file__).resolve().parents[1] / "VERSION"
    configured_version = os.getenv("DIGIT_APP_VERSION", "").strip() or version_file.read_text(encoding="utf-8").strip()

    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["version"] == configured_version
        assert re.fullmatch(r"\d+\.\d+\.\d+", health.json()["version"])

        login_page = client.get("/login")
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', login_page.text)
        assert login_page.status_code == 200 and csrf

        login_response = client.post(
            "/login",
            data={
                "email": "admin@digitlaboral.com.py",
                "password": settings.demo_admin_password,
                "csrf_token": csrf.group(1),
            },
            follow_redirects=False,
        )
        assert login_response.status_code == 303

        dashboard = client.get("/app")
        assert dashboard.status_code == 200
        assert 'class="app-version-indicator"' in dashboard.text
        assert f"<b>v{configured_version}</b>" in dashboard.text
        assert "BUILD" in dashboard.text
