"""Regresiones del recibo construido sobre la plantilla exacta aportada."""
from __future__ import annotations

import base64
import io
import zlib
from pathlib import Path

import fitz
from pypdf import PdfReader

from app.salary_receipt_mtess_style import BASE, build_mtess_style_salary_pdf


def _model(**extra):
    model = {
        "code": "DL-LS-000021",
        "employer_name": "EMPRESA DE PRUEBA S.A.",
        "employer_ruc": "1234567-0",
        "employee_name": "TRABAJADOR DE PRUEBA",
        "employee_ci": "1234567",
        "period_from_mtess_display": "01 de noviembre de 2026",
        "period_to_mtess_display": "30 de noviembre de 2026",
        "payment_date_display": "05/12/2026",
        "payment_method": "Transferencia",
        "hours_worked_display": "208",
        "days_worked_display": "30",
        "pieces_or_tasks_display": "0",
        "earnings": [{"label": "Salario Básico", "amount": 3144000}],
        "deductions": [{"label": "Aporte Seg. Social", "amount": 273960}],
        "gross": 3144000,
        "discounts": 273960,
        "net": 2870040,
        "is_annulled": False,
    }
    model.update(extra)
    return model


def test_template_is_identical_to_validated_sanitized_source():
    raw = base64.b64decode(BASE.read_text(encoding="ascii"), validate=True)
    assert len(raw) == 10037
    assert zlib.crc32(raw) == 0x22D8DF2C
    assert raw.startswith(b"%PDF")


def test_receipt_a4_two_copies_with_ministry_logo_but_no_qr():
    data = build_mtess_style_salary_pdf(_model())
    assert data.startswith(b"%PDF")
    reader = PdfReader(io.BytesIO(data))
    assert len(reader.pages) == 2
    for idx, page in enumerate(reader.pages):
        text = page.extract_text()
        assert round(float(page.mediabox.width)) == 595
        assert round(float(page.mediabox.height)) == 842
        for fragment in [
            "DL-LS-000021", "MINISTERIO DE TRABAJO",
            "LIQUIDACIÓN DE SALARIO", "FIRMA DEL EMPLEADOR",
            "FIRMA DEL EMPLEADO", "3.144.000", "273.960",
            "2.870.040", "DOCUMENTO INTERNO NO OFICIAL", "REOP",
        ]:
            assert fragment in text
        assert "ORIGINAL" in text if idx == 0 else "DUPLICADO" in text
        # The only embedded image is the letterhead's MTESS logo, not a QR.
        assert len(page.images) == 1

    with fitz.open(stream=data, filetype="pdf") as document:
        for page in document:
            for item in page.get_images(full=True):
                assert all(box.y1 < 108 for box in page.get_image_rects(item[0]))
        assert "ORIGINAL" not in document[1].get_text()


def test_annulled_record_is_marked_on_both_copies():
    doc = PdfReader(io.BytesIO(build_mtess_style_salary_pdf(_model(is_annulled=True))))
    assert len(doc.pages) == 2
    for page in doc.pages:
        assert "ANULADO" in page.extract_text()


def test_many_saved_concepts_are_not_silently_omitted():
    model = _model(
        earnings=[
            {"label": "Salario Básico", "amount": 3044000},
            {"label": "Bonificación", "amount": 100000},
        ],
    )
    pages = PdfReader(io.BytesIO(build_mtess_style_salary_pdf(model))).pages
    assert len(pages) == 3
    assert "detalle en anexo" in pages[0].extract_text().lower()
    annex = pages[2].extract_text()
    assert "Salario Básico" in annex
    assert "Bonificación" in annex
    assert "Aporte Seg. Social" in annex
    assert "3.144.000" in annex


def test_browser_uses_pdf_not_a_separate_html_replica():
    html = (Path(__file__).resolve().parents[1] /
            "app/templates/salary_settlement_detail.html").read_text(encoding="utf-8")
    assert 'id="salary-mtess-pdf"' in html
    assert 'src="/app/reports/liquidaciones-salarios/{{ item.id }}/pdf?vista=1' in html
    assert "createObjectURL" not in html  # CSP default-src self impide blob: en iframe.
    assert "Abrir visor en otra pestaña" in html
    assert "ANULADO · COPIA HISTÓRICA" in html
