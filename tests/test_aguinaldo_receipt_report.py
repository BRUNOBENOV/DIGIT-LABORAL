"""Aguinaldo report: original/copy preview, scoped reads, audited payment fields."""
import io
from datetime import date

from pypdf import PdfReader
from sqlalchemy import func, select

from app.models import Aguinaldo, AguinaldoReceiptDetail, AuditLog, CalculationRecord
from tests.test_labor_suite import token, web_case

ROOT = "/app/reports/liquidaciones-aguinaldo"


def create_records(db, company, employee, other):
    annual = Aguinaldo(employee_id=employee.id, year=2026, total_remunerations=36000000,
                       calculated_amount=3000000, status="Aprobado", notes="Registro sintético")
    calc = CalculationRecord(company_id=company.id, employee_id=employee.id, calculation_type="aguinaldo",
                             reference_period="2026", amount=1000000, status="Borrador",
                             source="Calculadora", input_json='{"total_remunerations":12000000}',
                             result_json='{"total_remunerations":12000000,"aguinaldo":1000000}')
    outsider = Aguinaldo(employee_id=other.id, year=2025, total_remunerations=1200000,
                         calculated_amount=100000, status="Aprobado")
    db.add_all([annual, calc, outsider])
    db.commit()
    return annual, calc, outsider


def test_aguinaldo_report_index_and_existing_catalog_link(web_case):
    client, db, _, company, employee, other = web_case
    annual, calc, outsider = create_records(db, company, employee, other)
    redirect = client.get("/app/reports/liquidacion-aguinaldo?year=2026", follow_redirects=False)
    assert redirect.status_code == 303
    assert redirect.headers["location"] == ROOT + "?year=2026"
    page = client.get(ROOT)
    assert page.status_code == 200
    assert page.headers["cache-control"] == "private, no-store"
    assert f"DL-AG-A{annual.id:06d}" in page.text
    assert f"DL-AG-C{calc.id:06d}" in page.text
    assert "3.000.000" in page.text
    assert "1.000.000" in page.text
    assert f"DL-AG-A{outsider.id:06d}" not in page.text or outsider.id == annual.id
    assert client.get(ROOT + "?year=2025").text.count("/calculo/") == 0
    assert f"/app/reports/liquidaciones-aguinaldo/registro/{annual.id}" in client.get("/app/aguinaldo").text


def test_aguinaldo_pdf_preview_download_are_same_one_page_two_copies(web_case):
    client, db, _, company, employee, other = web_case
    annual, calc, _ = create_records(db, company, employee, other)
    for kind, record in (("registro", annual), ("calculo", calc)):
        url = f"{ROOT}/{kind}/{record.id}/pdf"
        preview = client.get(url + "?vista=1")
        assert preview.status_code == 200, preview.text
        assert preview.headers["content-type"].startswith("application/pdf")
        assert preview.headers["content-disposition"].startswith("inline;")
        assert preview.content[:4] == b"%PDF"
        pdf = PdfReader(io.BytesIO(preview.content))
        assert len(pdf.pages) == 1
        text = pdf.pages[0].extract_text()
        assert "LIQUIDACIÓN DE AGUINALDO" in text
        assert "ORIGINAL" in text and "COPIA" in text
        assert "NO REGISTRADA" in text
        assert "Persona sintética" in text
        assert "REOP/MTESS" in text
        assert "2.848.679" not in text  # no amounts copied from the user-supplied example
        assert "3.000.000" in text if kind == "registro" else "1.000.000" in text
        assert db.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == "descarga_pdf_liquidacion_aguinaldo")) == 0 if kind == "registro" else 1
        download = client.get(url)
        assert download.status_code == 200
        assert download.headers["content-disposition"].startswith("attachment;")
        assert download.content == preview.content or PdfReader(io.BytesIO(download.content)).pages[0].extract_text() == text


def test_payment_metadata_is_separate_audited_and_can_be_cleared(web_case):
    client, db, box, company, employee, other = web_case
    annual, calc, _ = create_records(db, company, employee, other)
    target = f"{ROOT}/registro/{annual.id}"
    page = client.get(target)
    assert page.status_code == 200
    assert "NO REGISTRADA" in PdfReader(io.BytesIO(client.get(target+"/pdf?vista=1").content)).pages[0].extract_text()
    assert 'name="payment_method"' in page.text
    csrf = token(client)
    invalid = client.post(target + "/payment", data={
        "csrf_token": csrf, "payment_method": "Efectivo", "payment_date": "",
    })
    assert invalid.status_code == 422
    valid = client.post(target + "/payment", data={
        "csrf_token": csrf, "payment_method": "Transferencia bancaria", "payment_date": "2026-10-30",
    }, follow_redirects=False)
    assert valid.status_code == 303
    db.expire_all()
    assert db.get(Aguinaldo, annual.id).calculated_amount == 3000000
    detail = db.scalar(select(AguinaldoReceiptDetail).where(AguinaldoReceiptDetail.source_id == annual.id,
                                                            AguinaldoReceiptDetail.source_kind == "registro"))
    assert detail.payment_date == date(2026,10,30)
    assert detail.payment_method == "Transferencia bancaria"
    text = PdfReader(io.BytesIO(client.get(target+"/pdf?vista=1").content)).pages[0].extract_text()
    assert "Transferencia bancaria" in text and "30/10/2026" in text
    assert db.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == "actualizar_datos_recibo_aguinaldo")) == 1
    cleared = client.post(target + "/payment", data={"csrf_token":csrf,"payment_method":"","payment_date":""},follow_redirects=False)
    assert cleared.status_code == 303
    db.expire_all()
    assert db.get(Aguinaldo,annual.id).calculated_amount == 3000000
    assert db.scalar(select(AguinaldoReceiptDetail).where(AguinaldoReceiptDetail.source_id == annual.id)).payment_date is None


def test_pdf_access_is_tenant_scoped_and_annulment_preserved(web_case):
    client, db, box, company, employee, other = web_case
    annual, calc, outsider = create_records(db, company, employee, other)
    assert client.get(f"{ROOT}/registro/{outsider.id}").status_code == 404
    assert client.get(f"{ROOT}/registro/{outsider.id}/pdf").status_code == 404
    assert client.get(f"{ROOT}/calculo/{annual.id}").status_code == 404
    assert client.get(f"{ROOT}/registro/{annual.id + 90000}").status_code == 404
    assert client.get(ROOT + "?company_id=9999999").status_code == 404
    db.get(Aguinaldo,annual.id).status="Anulado"
    db.commit()
    text=PdfReader(io.BytesIO(client.get(f"{ROOT}/registro/{annual.id}/pdf?vista=1").content)).pages[0].extract_text()
    assert "ANULADO" in text
    assert client.post(f"{ROOT}/registro/{annual.id}/payment",data={
        "csrf_token":token(client),"payment_method":"Efectivo","payment_date":"2026-10-30"}).status_code == 409
    box["user"].role = "auxiliar"
    db.commit()
    assert client.get(f"{ROOT}/registro/{annual.id}").status_code == 200
    assert client.post(f"{ROOT}/registro/{annual.id}/payment",data={
        "csrf_token":token(client),"payment_method":"Efectivo","payment_date":"2026-10-30"}).status_code == 403
