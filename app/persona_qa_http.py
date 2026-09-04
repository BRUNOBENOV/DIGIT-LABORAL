from __future__ import annotations

from fastapi.testclient import TestClient

from .runtime import app


def expect_status(check, response, allowed: set[int], label: str) -> None:  # noqa: ANN001
    check(response.status_code in allowed, f'{label}: HTTP {response.status_code}, esperado {sorted(allowed)}')


def login(check, client: TestClient, email: str, password: str) -> None:
    response = client.post('/login', data={'email': email, 'password': password}, follow_redirects=False)
    expect_status(check, response, {303}, f'login {email}')


def logout(check, client: TestClient) -> None:
    response = client.post('/logout', follow_redirects=False)
    expect_status(check, response, {303}, 'logout')


def run_http_personas(check, password: str) -> None:  # noqa: ANN001
    from .persona_qa_workflow import run_admin_workflow
    from .persona_qa_roles import run_role_and_legal_checks
    with TestClient(app) as client:
        context = run_admin_workflow(check, client, password)
        run_role_and_legal_checks(check, client, password, context)
