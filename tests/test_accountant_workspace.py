
def test_accountant_workbench_keeps_operational_tools_and_request_approval() -> None:
    with TestClient(app) as client:
        email, password, accountant_id, company_id = _new_user("contador")
        csrf = _login(client, email, password)

        home = client.get("/app")
        assert home.status_code == 200
        assert "Mantenimientos" in home.text
        assert "Cálculo" in home.text
        assert 'href="/app/calculations?tipo=salary"' in home.text
        assert 'href="/app/payrolls"' in home.text

        for path in (
            "/app/payrolls",
            "/app/calculations",
            "/app/compliance",
            "/app/reports",
            "/app/certificates",
        ):
            response = client.get(path)
            assert response.status_code == 200, path

        assert "Revisar con IA" in client.get("/app/certificates").text
        queue = client.get("/app/requests")
        assert queue.status_code == 200
        assert 'name="status_filter"' in queue.text
        assert 'name="assigned_filter"' in queue.text

        with SessionLocal() as db:
            item = CompanyRequest(
                company_id=company_id,
                request_type="Otra consulta",
                subject=f"QA-ACCOUNTANT-{uuid.uuid4().hex[:10]}",
                detail="Solicitud de prueba para la revisión del contador.",
                requested_by_user_id=accountant_id,
                priority="Normal",
                status="Pendiente",
            )
            db.add(item)
            db.commit()
            request_id = item.id

        approved = client.post(
            f"/app/requests/{request_id}/review",
            data={
                "csrf_token": csrf,
                "status": "Aprobada",
                "response": "Revisión contable finalizada.",
                "assigned_to": "",
                "assigned_user_id": "",
            },
            follow_redirects=False,
        )
        assert approved.status_code == 303
        with SessionLocal() as db:
            item = db.get(CompanyRequest, request_id)
            assert item is not None and item.status == "Aprobada"
