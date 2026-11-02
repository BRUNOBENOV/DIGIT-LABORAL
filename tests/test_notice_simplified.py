from urllib.parse import urlencode

import pytest
from bs4 import BeautifulSoup

from app.models import CompanyRequest, RequestWorkflow
from tests.test_notice_letter import notice_case
from tests.test_labor_suite import web_case


@pytest.mark.parametrize("role,allowed", [("contador", True), ("auxiliar", True), ("abogado", False)])
def test_notice_calculator_shortcut_respects_roles_and_keeps_the_employee(notice_case, role, allowed):
    client, db, box, company, employee, *_ = notice_case
    box["user"].role = role
    if role == "abogado":
        request = CompanyRequest(company_id=company.id, request_type="Consulta", detail="Caso sintético asignado")
        db.add(request)
        db.flush()
        db.add(RequestWorkflow(request_id=request.id, assigned_user_id=box["user"].id))
    db.commit()
    response = client.get("/app/certificates", params={"company_id": company.id, "employee_id": employee.id, "document_type": "notificacion_preaviso"})
    assert response.status_code == 200
    soup = BeautifulSoup(response.text, "html.parser")
    form = soup.select_one("#certificateForm")
    assert form["data-notice-can-register"] == str(allowed).lower()
    assert soup.select_one('script[src*="notice-simplified.js"]')
    calculator = client.get("/app/calculations?" + urlencode({"tipo": "notice", "company_id": company.id, "employee_id": employee.id}))
    assert calculator.status_code == (200 if allowed else 403)
    if allowed:
        target = BeautifulSoup(calculator.text, "html.parser")
        assert target.select_one('select[name="company_id"] option[selected]')["value"] == str(company.id)
        assert target.select_one('select[name="employee_id"] option[selected]')["value"] == str(employee.id)


def test_linked_notice_keeps_internal_calculation_details_out_of_observations(notice_case):
    client, _, _, company, employee, _, calculation = notice_case
    response = client.get("/app/certificates", params={"company_id": company.id, "employee_id": employee.id, "calculation_id": calculation.id, "document_type": "notificacion_preaviso"})
    assert response.status_code == 200
    soup = BeautifulSoup(response.text, "html.parser")
    assert soup.select_one('[name="observations"]').text == ""
    assert soup.select_one('[name="calculation_id"]')["value"] == str(calculation.id)
    assert soup.select_one('[name="employee_id"] option[selected]')["value"] == str(employee.id)
