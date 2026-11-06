"""Recibo DIGIT-LABORAL sobre plantilla visual del MTESS aportada por el usuario.

La plantilla no contiene identidad de terceros, QR ni numeración oficial.
Cada página identifica expresamente la emisión interna; nunca es comprobante REOP.
"""
from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from typing import Any

import fitz

BASE = Path(__file__).resolve().parent / "assets" / "mtess_salary_receipt_blank.b64"
NAVY = (40 / 255, 74 / 255, 107 / 255)
RED = (151 / 255, 30 / 255, 27 / 255)
BLACK = (0, 0, 0)
WHITE = (1, 1, 1)


def _gs(n: Any) -> str:
    return f"{int(n or 0):,}".replace(",", ".")


def _put(page, text, rect, *, size=9.5, color=BLACK, center=False, bold=False):
    if text is None or not str(text).strip():
        return
    value = str(text)
    bounds = fitz.Rect(rect)
    font = "hebo" if bold else "helv"
    current = size
    while current > 6.0 and fitz.get_text_length(value, fontname=font, fontsize=current) > bounds.width - 4:
        current -= 0.3
    width = fitz.get_text_length(value, fontname=font, fontsize=current)
    left = bounds.x0 + (max(0, bounds.width - width) / 2 if center else 2)
    page.insert_text((left, bounds.y0 + (bounds.height + current) / 2 - 1),
                     value, fontsize=current, fontname=font, color=color, overlay=True)


def _positive(values):
    return [r for r in (values or []) if isinstance(r, dict) and int(r.get("amount") or 0) > 0]


def _append_concept_annex(result, model):
    """Preserve every saved itemized component when a category exceeds one row."""
    items = [("INGRESOS", r) for r in model.get("earnings", []) if isinstance(r, dict)]
    items += [("EGRESOS", r) for r in model.get("deductions", []) if isinstance(r, dict)]
    page = None
    y = 0
    for i, (kind, row) in enumerate(items):
        if page is None or y > 755:
            page = result.new_page(width=595, height=842)
            page.draw_rect(fitz.Rect(20, 20, 575, 68), fill=NAVY, color=None)
            _put(page, "ANEXO DE CONCEPTOS · DIGIT-LABORAL", (25, 27, 570, 48), size=13, color=WHITE, bold=True)
            _put(page, f"N.º {model.get('code', '')} · DOCUMENTO INTERNO NO OFICIAL",
                 (25, 47, 570, 64), size=9, color=WHITE)
            _put(page, "Detalle asociado al Original y Duplicado. Importes del cálculo guardado.",
                 (25, 75, 570, 96), size=9)
            if model.get("is_annulled"):
                page.draw_rect(fitz.Rect(20, 98, 575, 116), color=None, fill=RED)
                _put(page, "ANULADO · COPIA HISTÓRICA · NO UTILIZAR COMO RECIBO VIGENTE",
                     (24, 98, 571, 116), size=10, color=WHITE, center=True, bold=True)
                y = 128
            else:
                y = 112
        page.draw_rect(fitz.Rect(20, y, 575, y + 25), color=BLACK, width=.55)
        page.draw_line(fitz.Point(95, y), fitz.Point(95, y + 25), color=BLACK, width=.55)
        page.draw_line(fitz.Point(450, y), fitz.Point(450, y + 25), color=BLACK, width=.55)
        _put(page, kind, (22, y + 3, 92, y + 23), size=8, bold=True)
        _put(page, str(row.get("label") or "Concepto"), (98, y + 3, 447, y + 23), size=9)
        _put(page, _gs(row.get("amount")), (453, y + 3, 572, y + 23), size=9)
        y += 25
    if page is not None:
        y += 12
        for label, value in (("TOTAL INGRESOS", "gross"), ("TOTAL EGRESOS", "discounts"), ("NETO", "net")):
            _put(page, label, (25, y, 255, y + 17), size=9, bold=True)
            _put(page, _gs(model.get(value)), (451, y, 570, y + 17), size=9)
            y += 18


def build_mtess_style_salary_pdf(model: dict[str, Any]) -> bytes:
    template_data = base64.b64decode(BASE.read_text(encoding="ascii").strip(), validate=True)
    source = fitz.open(stream=template_data, filetype="pdf")
    result = fitz.open()
    try:
        for label in ("ORIGINAL", "DUPLICADO"):
            result.insert_pdf(source, from_page=0, to_page=0)
            page = result[-1]
            if label == "DUPLICADO":
                # Remove the embedded ORIGINAL word (not merely cover it visually).
                page.add_redact_annot(fitz.Rect(399, 82, 580, 102), fill=RED)
                page.apply_redactions(images=0, graphics=0, text=0)
                _put(page, label, (404, 84, 515, 100), size=8, color=WHITE, bold=True)
            # The source already excludes the QR. Remove any residual third-box border.
            page.add_redact_annot(fitz.Rect(447, 456, 579, 572), fill=WHITE)
            page.apply_redactions(images=0, graphics=0, text=0)
            _put(page, str(model.get("code") or ""), (430, 54.5, 570, 75), size=10, color=WHITE)
            _put(page, model.get("employer_name"), (20, 122.5, 438, 143), size=10)
            _put(page, model.get("employer_ruc"), (439, 122.5, 571, 143), size=10)
            _put(page, model.get("employee_name"), (20, 172.5, 438, 193), size=10)
            _put(page, model.get("employee_ci"), (439, 172.5, 571, 193), size=10)
            for key, box in [
                ("period_from_mtess_display", (79, 222.5, 199, 243)),
                ("period_to_mtess_display", (199, 222.5, 319, 243)),
                ("payment_date_display", (319, 222.5, 439, 243)),
                ("payment_method", (439, 222.5, 573, 243)),
            ]:
                fallback = model.get(key.replace("_mtess", ""))
                _put(page, model.get(key) or fallback or "No registrado", box, size=9)
            for key, box in [
                ("hours_worked_display", (106, 253, 192, 303)),
                ("days_worked_display", (301, 253, 383, 303)),
                ("pieces_or_tasks_display", (482, 253, 574, 303)),
            ]:
                _put(page, model.get(key) or "No registrado", box, size=10, center=True)
            for kind, rect, amount_box, total in [
                ("earnings", (101, 333, 300, 353), (301, 333, 428, 353), "gross"),
                ("deductions", (101, 353, 300, 373), (430, 353, 571, 373), "discounts"),
            ]:
                rows = _positive(model.get(kind))
                if not rows:
                    _put(page, "Sin conceptos registrados", rect, size=8.4)
                elif len(rows) == 1:
                    _put(page, rows[0].get("label"), rect, size=9)
                    _put(page, _gs(rows[0].get("amount")), amount_box, size=9)
                else:
                    _put(page, f"{len(rows)} conceptos (detalle en anexo)", rect, size=8)
                    _put(page, _gs(model.get(total)), amount_box, size=9)
            for key, rect in [
                ("gross", (300, 383, 569, 402)),
                ("discounts", (300, 403, 569, 422)),
                ("net", (300, 423, 569, 442)),
            ]:
                _put(page, _gs(model.get(key)), rect, size=10)
            page.insert_text((20, 588),
                             "Este recibo fue generado por DIGIT-LABORAL con datos suministrados por el empleador.",
                             fontsize=9, fontname="heit", color=BLACK)
            page.insert_text((20, 603),
                             "No es comprobante emitido por el MTESS ni acredita presentación en REOP o pago efectivo.",
                             fontsize=8.5, fontname="heit", color=BLACK)
            if model.get("is_annulled"):
                page.draw_rect(fitz.Rect(20, 633, 572, 650), fill=RED, color=None)
                _put(page, "ANULADO · COPIA HISTÓRICA · NO UTILIZAR COMO RECIBO VIGENTE",
                     (26, 633, 566, 650), size=10, color=WHITE, center=True, bold=True)

        # Only make annex pages when the original reference has insufficient rows.
        if len(_positive(model.get("earnings"))) > 1 or len(_positive(model.get("deductions"))) > 1:
            _append_concept_annex(result, model)
        return result.tobytes(garbage=4, deflate=True)
    finally:
        result.close()
        source.close()
