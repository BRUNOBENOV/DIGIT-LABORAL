"""Aguinaldo receipt with the reference model's exact sheet geometry.

Keeps the 595 x 678 pt original/copy layout, 319-pt repeat, original
colors, grid, spacing and signature areas. The REOP QR and official
issuing identity are NOT copied. DIGIT-LABORAL's real brand and internal
receipt number replace government issuance identifiers.
"""
from __future__ import annotations

import base64
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

# The uploaded model has a custom sheet height. Keeping its exact geometry
# is more faithful than resizing both vouchers to standard A4.
PAGE_SIZE = (595, 678)
WIDTH, HEIGHT = PAGE_SIZE
COPY_OFFSET = 319
NAVY = colors.Color(0.14118, 0.28235, 0.43137)
RED = colors.Color(0.55686, 0.09020, 0.06275)
PALE = colors.Color(0.93333, 0.93333, 0.93333)
WHITE = colors.white
BLACK = colors.black
MTESS_REFERENCE_LOGO_PATH = Path(__file__).resolve().parent / "assets" / "mtess_reference_logo.b64"


def _draw_rect(pdf, x, top, width, height, *, fill=WHITE, border=False):
    pdf.setFillColor(fill)
    if border:
        pdf.setStrokeColor(BLACK)
        pdf.setLineWidth(0.7)
    pdf.rect(x, HEIGHT - top - height, width, height, stroke=int(border), fill=1)


def _text(pdf, value, x, top, max_width, *, font="Helvetica", size=6,
          color=BLACK, align="left", min_size=4.4):
    """Fit UTF-8 names and identifiers within source-model column widths."""
    value = str(value if value is not None else "").replace("\r", " ").replace("\n", " ").strip()
    actual_size = size
    while value and actual_size > min_size and pdfmetrics.stringWidth(value, font, actual_size) > max_width:
        actual_size -= 0.2
    if pdfmetrics.stringWidth(value, font, actual_size) > max_width:
        while value and pdfmetrics.stringWidth(value + "...", font, actual_size) > max_width:
            value = value[:-1]
        value += "..."
    pdf.setFillColor(color)
    pdf.setFont(font, actual_size)
    baseline = HEIGHT - top - actual_size
    if align == "center":
        pdf.drawCentredString(x + max_width / 2, baseline, value)
    else:
        pdf.drawString(x, baseline, value)


def _heading(pdf, name, x, top, width, height=10):
    _draw_rect(pdf, x, top, width, height, fill=NAVY, border=True)
    _text(pdf, name, x + 4, top + 1, width - 8, font="Helvetica-Bold",
          size=6, color=WHITE, align="center")


def _value(pdf, value, x, top, width, height=10, *, bold=False):
    _draw_rect(pdf, x, top, width, height, border=True)
    _text(pdf, value, x + 2, top + 1, width - 4,
          font="Helvetica-Bold" if bold else "Helvetica", size=6)


@lru_cache(maxsize=1)
def _reference_logo_bytes():
    """User-supplied reference artwork; never a credential of official issuance."""
    return base64.b64decode(
        MTESS_REFERENCE_LOGO_PATH.read_text(encoding="ascii").strip(), validate=True
    )


def _logo(pdf, offset):
    """Place the MTESS reference artwork in the source model's exact slot."""
    pdf.drawImage(
        ImageReader(BytesIO(_reference_logo_bytes())),
        40, HEIGHT - offset - 88, width=129.04, height=51, mask="auto"
    )


def _money(value):
    return f"{int(value or 0):,}".replace(",", ".")


def _copy(pdf, model, offset: int, name: str):
    """Geometry transcribed from the supplied model, without REOP QR."""
    # Header: the red strip, navy title and light grey background stay in
    # exactly the same positions as the source document.
    _draw_rect(pdf, 30, offset + 42, 560, 45, fill=PALE)
    _draw_rect(pdf, 410, offset + 40, 180, 53, fill=RED)
    _draw_rect(pdf, 400, offset + 46, 190, 34, fill=NAVY)
    _logo(pdf, offset)
    # Contact block restored to the exact wording, font size and baseline of
    # the supplied official-form reference. The footer identifies Digit as issuer.
    _text(pdf, "MINISTERIO DE TRABAJO, EMPLEO Y SEGURIDAD SOCIAL",
          180, offset + 53, 220, size=5)
    _text(pdf, "Dirección: Luis A. de Herrera e/ Paraguarí",
          180, offset + 59, 220, size=5)
    _text(pdf, "Teléfono: (+595 21) 729 - 0100",
          180, offset + 65, 220, size=5)
    _text(pdf, "Horario de atención: de 07:00hs a 15:00hs",
          180, offset + 71, 220, size=5)
    _text(pdf, "LIQUIDACIÓN DE AGUINALDO", 410, offset + 51, 174,
          size=11, color=WHITE)
    _text(pdf, f"N° {model['code']}", 410, offset + 67, 175, size=8,
          color=WHITE)
    _text(pdf, name, 415, offset + 81, 160, font="Helvetica-Bold",
          size=8, color=WHITE)

    # Source's original 10-pt-high double-column employer/worker grid.
    for top, left_head, right_head, left_value, right_value in (
        (94, "EMPLEADOR", "RUC N°", model["employer_name"], model["employer_ruc"]),
        (114, "NOMBRE Y APELLIDO DEL TRABAJADOR", "C.I. N°",
         model["employee_name"], model["employee_ci"]),
    ):
        _heading(pdf, left_head, 30, offset + top, 420)
        _heading(pdf, right_head, 450, offset + top, 130)
        _value(pdf, left_value, 30, offset + top + 10, 420)
        _value(pdf, right_value, 450, offset + top + 10, 130)

    _heading(pdf, "FORMA DE PAGO", 30, offset + 134, 280)
    _heading(pdf, "FECHA DE PAGO", 310, offset + 134, 270)
    payment_method = model["payment_method"] or "NO REGISTRADA"
    payment_date = (model["payment_date"].strftime("%d/%m/%Y")
                    if model["payment_date"] else "NO REGISTRADA")
    _value(pdf, payment_method, 30, offset + 144, 280)
    _value(pdf, payment_date, 310, offset + 144, 270)

    _heading(pdf, "CONCEPTO", 30, offset + 154, 280)
    _heading(pdf, "MONTO EN GS.", 310, offset + 154, 270)
    _heading(pdf, "INGRESOS", 30, offset + 164, 80)
    exercise = model["exercise"] if model["exercise"] is not None else "NO INFORMADO"
    _value(pdf, f"Pago de aguinaldo - Periodo {exercise}", 110, offset + 164, 200)
    _value(pdf, _money(model["amount"]), 310, offset + 164, 270)

    _heading(pdf, "MONTO TOTAL DE INGRESO", 30, offset + 184, 280)
    _value(pdf, _money(model["amount"]), 310, offset + 184, 270)

    # Two signing boxes and labels retain the model's original measurements;
    # the QR at x460..576 has been removed and is never generated.
    for x, width, title in (
        (30, 204, "FIRMA DEL EMPLEADOR"),
        (250, 200, "FIRMA DEL EMPLEADO"),
    ):
        _draw_rect(pdf, x, offset + 204, width, 60, border=True)
        _draw_rect(pdf, x, offset + 274, width, 19, fill=NAVY, border=True)
        _text(pdf, title, x + 2, offset + 276, width - 4,
              font="Helvetica-Bold", size=6, color=WHITE)

    # The legal attribution is internal, not a simulated REOP issuance.
    _text(pdf, "Este recibo fue generado electrónicamente por DIGIT-LABORAL con datos proveídos por el Empleador.",
          30, offset + 295, 550, size=8)
    _text(pdf, "DOCUMENTO INTERNO. No emitido por el MTESS ni presentado ante REOP.",
          30, offset + 303, 550, size=6.7)
    _text(pdf, "Original: Empleador." if name == "ORIGINAL" else "Duplicado: Trabajador",
          30, offset + 311, 300, font="Helvetica-Bold", size=8)

    if model.get("annulled"):
        pdf.saveState()
        pdf.setFillColor(RED)
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(460, HEIGHT - offset - 248, "ANULADO")
        pdf.restoreState()


def build_aguinaldo_receipt_pdf(model):
    """The preview, download and print links consume these identical bytes."""
    stream = BytesIO()
    pdf = canvas.Canvas(stream, pagesize=PAGE_SIZE, pageCompression=1, invariant=1)
    pdf.setTitle(f"Liquidación de aguinaldo N° {model['code']} | Digit Laboral")
    pdf.setAuthor("DIGIT-LABORAL")
    _copy(pdf, model, 0, "ORIGINAL")
    _copy(pdf, model, COPY_OFFSET, "COPIA")
    pdf.showPage()
    pdf.save()
    return stream.getvalue()
