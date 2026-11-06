"""A4 aguinaldo receipt: original + employee copy, based on the supplied model.

The MTESS/REOP logo, QR and government folio are deliberately not reproduced:
this is an internal Digit Laboral receipt, not an official REOP issuance.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

FONT_ROOT = Path(__file__).resolve().parent / "assets" / "fonts"
NAVY = colors.HexColor("#294A6C")
DARK = colors.HexColor("#132F4F")
RED = colors.HexColor("#A52D2D")
PALE = colors.HexColor("#F1F4F8")
WHITE = colors.white
GREY = colors.HexColor("#46566C")
BLACK = colors.HexColor("#171E2A")


def _fonts():
    if "DL-DejaVu" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DL-DejaVu", str(FONT_ROOT / "DejaVuSans.ttf")))
    if "DL-DejaVu-Bold" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DL-DejaVu-Bold", str(FONT_ROOT / "DejaVuSans-Bold.ttf")))


def _money(value):
    return f"{int(value or 0):,}".replace(",", ".")


def _text(c, text, x, y, width, *, font="DL-DejaVu", size=8.3, color=BLACK):
    """Fit long names and IDs without running through the neighboring column."""
    value = str(text or "—").replace("\n", " ").replace("\r", " ").strip()
    chosen = size
    while chosen > 5.5 and pdfmetrics.stringWidth(value, font, chosen) > width - 5:
        chosen -= .2
    if pdfmetrics.stringWidth(value, font, chosen) > width - 5:
        while value and pdfmetrics.stringWidth(value + "…", font, chosen) > width - 5:
            value = value[:-1]
        value += "…"
    c.setFillColor(color)
    c.setFont(font, chosen)
    c.drawString(x + 3, y, value)


def _band(c, x, y, w, h, caption):
    c.setFillColor(NAVY)
    c.rect(x, y, w, h, stroke=0, fill=1)
    _text(c, caption, x + 4, y + (h - 9) / 2 + 2, w - 8,
          font="DL-DejaVu-Bold", size=7.3, color=WHITE)


def _box(c, x, y, w, h, text, *, bold=False):
    c.setFillColor(WHITE)
    c.setStrokeColor(colors.HexColor("#243851"))
    c.setLineWidth(.5)
    c.rect(x, y, w, h, stroke=1, fill=1)
    _text(c, text, x + 4, y + (h - 9) / 2 + 2, w - 8,
          font="DL-DejaVu-Bold" if bold else "DL-DejaVu", size=8.3)


def _copy(c, model, top, label):
    x, w = 25, A4[0] - 50
    split = x + w * .77
    left_w = split - x
    right_w = w - left_w
    # The reference uses two compact copies on one A4 page.
    c.setFillColor(PALE)
    c.rect(x, top - 64, w, 64, stroke=0, fill=1)
    _text(c, "Digit Laboral", x + 8, top - 25, 205, font="DL-DejaVu-Bold", size=15, color=NAVY)
    _text(c, "RECIBO INTERNO · DATOS REGISTRADOS", x + 8, top - 43, 230, size=7.1, color=GREY)
    title_x = x + 284
    c.setFillColor(NAVY)
    c.rect(title_x, top - 64, w - (title_x - x), 64, stroke=0, fill=1)
    _text(c, "LIQUIDACIÓN DE AGUINALDO", title_x + 7, top - 24, w - 300,
          font="DL-DejaVu-Bold", size=11, color=WHITE)
    _text(c, model["code"], title_x + 7, top - 43, 170, size=8.5, color=WHITE)
    _text(c, f'Estado: {model["status"]}', title_x + 7, top - 56, 180, size=7.3, color=WHITE)
    c.setFillColor(RED)
    c.rect(x + w - 134, top - 81, 134, 17, stroke=0, fill=1)
    _text(c, label, x + w - 120, top - 76, 115, font="DL-DejaVu-Bold", size=8, color=WHITE)

    # Employer identity and RUC.
    _band(c, x, top - 100, left_w, 17, "EMPLEADOR")
    _band(c, split, top - 100, right_w, 17, "RUC N.º")
    _box(c, x, top - 124, left_w, 24, model["employer_name"])
    _box(c, split, top - 124, right_w, 24, model["employer_ruc"])

    # Employee identity and document.
    _band(c, x, top - 140, left_w, 16, "NOMBRE Y APELLIDO DEL TRABAJADOR")
    _band(c, split, top - 140, right_w, 16, "C.I. N.º")
    _box(c, x, top - 164, left_w, 24, model["employee_name"])
    _box(c, split, top - 164, right_w, 24, model["employee_ci"])

    # Payment details are never invented from the annual calculation.
    middle = x + w * .55
    _band(c, x, top - 180, middle - x, 16, "FORMA DE PAGO")
    _band(c, middle, top - 180, x + w - middle, 16, "FECHA DE PAGO")
    method = model["payment_method"] or "NO REGISTRADA"
    payment_date = model["payment_date"].strftime("%d/%m/%Y") if model["payment_date"] else "NO REGISTRADA"
    _box(c, x, top - 203, middle - x, 23, method)
    _box(c, middle, top - 203, x + w - middle, 23, payment_date)

    # Concept + amount in the same two-column structure as the reference.
    _band(c, x, top - 219, w * .70, 16, "CONCEPTO")
    _band(c, x + w * .70, top - 219, w * .30, 16, "MONTO EN GS.")
    exercise = model["exercise"] if model["exercise"] is not None else "NO INFORMADO"
    concept = f"Aguinaldo correspondiente al ejercicio {exercise}"
    _band(c, x, top - 244, 86, 25, "INGRESOS")
    _box(c, x + 86, top - 244, w * .70 - 86, 25, concept)
    _box(c, x + w * .70, top - 244, w * .30, 25, _money(model["amount"]), bold=True)

    _band(c, x, top - 266, w * .70, 21, "MONTO TOTAL DE INGRESOS")
    _box(c, x + w * .70, top - 266, w * .30, 21, _money(model["amount"]), bold=True)

    # Signature spaces: intentionally no fabricated signatures or REOP QR.
    sig_w = (w - 20) / 2
    for idx, title in enumerate(("FIRMA DEL EMPLEADOR", "FIRMA DEL TRABAJADOR")):
        sx = x + idx * (sig_w + 20)
        c.setStrokeColor(GREY)
        c.setLineWidth(.7)
        c.rect(sx, top - 345, sig_w, 60, stroke=1, fill=0)
        _band(c, sx, top - 362, sig_w, 17, title)

    if model["annulled"]:
        c.setFillColor(RED)
        c.setFont("DL-DejaVu-Bold", 11)
        c.drawCentredString(x + w / 2, top - 279, "ANULADO · COPIA HISTÓRICA")
    _text(c, "Generado por DIGIT-LABORAL con datos del empleador.", x, top - 378, w, size=7.1, color=GREY)
    _text(c, "No acredita pago efectivo ni emisión o presentación ante REOP/MTESS.", x, top - 391, w, size=7.1, color=GREY)


def build_aguinaldo_receipt_pdf(model):
    """Exactly one A4 page containing employer original and worker copy."""
    _fonts()
    stream = BytesIO()
    c = canvas.Canvas(stream, pagesize=A4, pageCompression=1)
    c.setTitle(f"Liquidación de aguinaldo {model['code']} | Digit Laboral")
    c.setAuthor("DIGIT-LABORAL")
    _copy(c, model, 827, "ORIGINAL · EMPLEADOR")
    _copy(c, model, 417, "COPIA · TRABAJADOR")
    c.showPage()
    c.save()
    return stream.getvalue()
