"""Pruebas de fidelidad estructural del recibo de salarios DIGIT-LABORAL."""
from __future__ import annotations

import io
from pathlib import Path

from pypdf import PdfReader

from app.salary_receipt_mtess_style import build_mtess_style_salary_pdf


def _model(**extra):
    model = {
        "code": "DL-LS-000021",
        "employer_name": "EMPRESA DE PRUEBA S.A.",
        "employer_ruc": "1234567-0",
        "employee_name": "TRABAJADOR DE PRUEBA",
        "employee_ci": "1234567",
        "period_from_display": "01/11/2026",
        "period_to_display": "30/11/2026",
        "payment_date_display": "05/12/2026",
        "payment_method": "Transferencia",
        "hours_worked_display": "208",
        "days_worked_display": "30",
        "pieces_or_tasks_display": "0",
        "earnings": [
            {"label": "Salario Básico", "amount": 3044000},
            {"label": "Bonificación", "amount": 100000},
        ],
        "deductions": [{"label": "Aporte Seg. Social", "amount": 273960}],
        "gross": 3144000,
        "discounts": 273960,
        "net": 2870040,
        "is_annulled": False,
    }
    model.update(extra)
    return model


def test_receipt_is_two_a4_copies_same_internal_number_without_qr():
    data = build_mtess_style_salary_pdf(_model())
    assert data.startswith(b"%PDF")
    pages = PdfReader(io.BytesIO(data)).pages
    assert len(pages) == 2
    texts = [page.extract_text() for page in pages]
    for page, text in zip(pages, texts):
        assert round(float(page.mediabox.width)) == 595
        assert round(float(page.mediabox.height)) == 842
        assert "DL-LS-000021" in text
        assert "LIQUIDACIÓN DE SALARIO" in text
        assert "FIRMA DEL EMPLEADOR" in text
        assert "FIRMA DEL EMPLEADO" in text
        assert "3.144.000" in text
        assert "273.960" in text
        assert "2.870.040" in text
        assert len(page.images) == 0
        assert "No constituye constancia oficial" in text
    assert "ORIGINAL" in texts[0]
    assert "DUPLICADO" in texts[1]


def test_annulled_receipt_is_marked_on_both_pages():
    pages = PdfReader(io.BytesIO(
        build_mtess_style_salary_pdf(_model(is_annulled=True))
    )).pages
    assert len(pages) == 2
    for page in pages:
        assert "ANULADO" in page.extract_text()


def test_browser_layout_uses_same_core_grid_as_downloaded_pdf():
    html = (Path(__file__).resolve().parents[1] /
            "app/templates/salary_settlement_detail.html").read_text(encoding="utf-8")
    assert 'rowspan="2">PERÍODO' in html
    assert '<th colspan="2">CONCEPTO</th>' in html
    assert '<colgroup><col style="width:17%">' in html
    assert "FIRMA DEL EMPLEADOR" in html
    assert "FIRMA DEL EMPLEADO" in html
    assert "DIGIT-LABORAL" in html
