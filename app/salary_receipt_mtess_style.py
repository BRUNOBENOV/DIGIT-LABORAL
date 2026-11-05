"""Recibo interno de salarios inspirado en la distribución del modelo MTESS.

No usa escudos, QR ni números de comprobante oficial. Emite ORIGINAL y DUPLICADO
a partir de un cálculo persistido, sin recálculo de salarios.
"""
from __future__ import annotations

from html import escape
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

FONT_PATH = Path(__file__).resolve().parent / "assets" / "fonts"
pdfmetrics.registerFont(TTFont("DLReceipt", str(FONT_PATH / "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("DLReceipt-Bold", str(FONT_PATH / "DejaVuSans-Bold.ttf")))

NAVY = colors.HexColor("#284C70")
DARK = colors.HexColor("#17314B")
PALE = colors.HexColor("#EAF0F7")
BORDER = colors.HexColor("#A8B8C8")
MUTED = colors.HexColor("#5D6F83")
W = 180 * mm


def _gs(amount):
    return f"{int(amount):,}".replace(",", ".")


def _text(value, fallback="—"):
    value = str(value) if value not in (None, "") else fallback
    return escape(value).replace("\n", "<br/>")


def build_mtess_style_salary_pdf(model: dict) -> bytes:
    """One complete A4 receipt for each copy. Layout follows reference categories."""
    stream = BytesIO()
    doc = SimpleDocTemplate(
        stream, pagesize=A4, leftMargin=15*mm, rightMargin=15*mm,
        topMargin=14*mm, bottomMargin=17*mm,
        title=f"Liquidación de salario {model['code']}",
        author="DIGIT-LABORAL",
    )
    body = ParagraphStyle(
        "DLReceiptBody", fontName="DLReceipt", fontSize=7.8,
        leading=10.6, textColor=DARK,
    )
    bold = ParagraphStyle(
        "DLReceiptBold", parent=body, fontName="DLReceipt-Bold", fontSize=8,
        leading=10.8,
    )
    white = ParagraphStyle(
        "DLReceiptWhite", parent=bold, textColor=colors.white, fontSize=7.3,
        leading=10,
    )
    centered = ParagraphStyle("DLReceiptCenter", parent=body, alignment=TA_CENTER)
    centered_bold = ParagraphStyle("DLReceiptCenterBold", parent=bold, alignment=TA_CENTER)
    centered_white = ParagraphStyle("DLReceiptCenterWhite", parent=white, alignment=TA_CENTER)
    right = ParagraphStyle("DLReceiptRight", parent=body, alignment=TA_RIGHT)
    right_bold = ParagraphStyle("DLReceiptRightBold", parent=bold, alignment=TA_RIGHT)
    small = ParagraphStyle(
        "DLReceiptSmall", parent=body, fontSize=6.8, leading=9.1, textColor=MUTED,
    )
    note = ParagraphStyle(
        "DLReceiptNote", parent=body, fontSize=6.6, leading=9.3, textColor=DARK,
    )

    def p(value, style=body):
        return Paragraph(_text(value), style)

    def table(rows, widths, *, head_rows=0, pads=5, special=None):
        t = Table(rows, colWidths=widths, repeatRows=head_rows, hAlign="LEFT")
        commands = [
            ("BOX", (0,0), (-1,-1), .65, DARK),
            ("INNERGRID", (0,0), (-1,-1), .35, BORDER),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("LEFTPADDING", (0,0), (-1,-1), pads),
            ("RIGHTPADDING", (0,0), (-1,-1), pads),
            ("TOPPADDING", (0,0), (-1,-1), 5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ]
        if head_rows:
            commands.append(("BACKGROUND", (0,0), (-1,head_rows-1), NAVY))
        if special:
            commands.extend(special)
        t.setStyle(TableStyle(commands))
        return t

    def strip(label, heading):
        return table([[p(label, white), p(heading, white)]], [135*mm, 45*mm],
                     special=[("BACKGROUND", (0,0), (-1,-1), NAVY)])

    def copy_page(copy_label):
        story = []
        head_left = [
            p("DIGIT-LABORAL", ParagraphStyle(
                "DLBrand", parent=bold, fontSize=15, leading=19, textColor=NAVY,
            )),
            p("Liquidaciones y recibos laborales", small),
            p("Documento generado desde el cálculo salarial guardado", small),
        ]
        head_right = [
            p("LIQUIDACIÓN DE SALARIO", white),
            p(f"N.º {model['code']}", white),
            p(copy_label, white),
        ]
        header = Table([[head_left, head_right]], colWidths=[104*mm, 76*mm])
        header.setStyle(TableStyle([
            ("BACKGROUND", (1,0), (1,0), NAVY),
            ("BOX", (1,0), (1,0), .6, DARK),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("LEFTPADDING", (0,0), (0,0), 0),
            ("LEFTPADDING", (1,0), (1,0), 14),
            ("TOPPADDING", (0,0), (-1,-1), 9),
            ("BOTTOMPADDING", (0,0), (-1,-1), 9),
        ]))
        story.extend([header, Spacer(1, 5*mm)])

        story.append(table([
            [p("EMPLEADOR", white), p("RUC N.º", white)],
            [p(model["employer_name"], bold), p(model["employer_ruc"], bold)],
        ], [139*mm, 41*mm], head_rows=1))
        story.append(Spacer(1, 3*mm))
        story.append(table([
            [p("NOMBRE Y APELLIDO DEL TRABAJADOR", white), p("C.I. N.º", white)],
            [p(model["employee_name"], bold), p(model["employee_ci"], bold)],
        ], [139*mm, 41*mm], head_rows=1))
        story.append(Spacer(1, 3*mm))

        period_from = model.get("period_from_display") or "No registrado"
        period_to = model.get("period_to_display") or "No registrado"
        payment_date = model.get("payment_date_display") or "No registrada"
        story.append(table([
            [p("PERÍODO DE PAGO", white), p("DESDE", white), p("HASTA", white),
             p("FECHA DE PAGO", white), p("FORMA DE PAGO", white)],
            [p(model.get("period_display"), centered), p(period_from, centered),
             p(period_to, centered), p(payment_date, centered), p(model.get("payment_method"), centered)],
        ], [30*mm, 39*mm, 39*mm, 37*mm, 35*mm], head_rows=1))
        story.append(Spacer(1, 3*mm))
        story.append(table([
            [p("HORAS TRABAJADAS", centered_white), p("CANTIDAD DE DÍAS TRABAJADOS", centered_white),
             p("CANTIDAD DE PIEZAS O TAREAS", centered_white)],
            [p(model.get("hours_worked_display") or "No registrado", centered_bold),
             p(model.get("days_worked_display") or "No registrado", centered_bold),
             p(model.get("pieces_or_tasks_display") or "No registrado", centered_bold)],
        ], [60*mm, 60*mm, 60*mm], head_rows=1,
            special=[("TOPPADDING",(0,1),(-1,1),9),("BOTTOMPADDING",(0,1),(-1,1),9)]))
        story.append(Spacer(1, 3*mm))

        lines = [[p("", white), p("CONCEPTO", white), p("INGRESOS EN GS.", centered_white),
                  p("EGRESOS EN GS.", centered_white)]]
        for category, values in (("INGRESOS", model["earnings"]), ("EGRESOS", model["deductions"])):
            valid = [r for r in values if int(r.get("amount") or 0) > 0]
            for index, row in enumerate(valid):
                lines.append([
                    p(category if index == 0 else "", bold),
                    p(row["label"]),
                    p(_gs(row["amount"]), right) if category == "INGRESOS" else p("", right),
                    p(_gs(row["amount"]), right) if category == "EGRESOS" else p("", right),
                ])
            if not valid:
                lines.append([p(category, bold), p("Sin conceptos registrados", small), p(""), p("")])
        story.append(table(lines, [27*mm, 91*mm, 31*mm, 31*mm], head_rows=1, pads=4))
        story.append(Spacer(1, 3*mm))

        totals = [
            [p("MONTO TOTAL DE INGRESOS", white), p(f"Gs. {_gs(model['gross'])}", right_bold)],
            [p("MONTO TOTAL DE EGRESOS", white), p(f"Gs. {_gs(model['discounts'])}", right_bold)],
            [p("MONTO TOTAL A COBRAR", white), p(f"Gs. {_gs(model['net'])}", right_bold)],
        ]
        story.append(table(totals, [118*mm, 62*mm], pads=7,
                           special=[("BACKGROUND", (0,0), (0,-1), NAVY),
                                    ("TOPPADDING", (0,2), (-1,2), 8),
                                    ("BOTTOMPADDING", (0,2), (-1,2), 8)]))
        story.append(Spacer(1, 5*mm))

        signature_boxes = Table([
            [p("", centered), p("", centered)],
            [p("FIRMA DEL EMPLEADOR", centered_white), p("FIRMA DEL TRABAJADOR", centered_white)],
            [p(model.get("representative") or "Empleador / representante legal", small),
             p(model.get("employee_name"), small)],
        ], colWidths=[90*mm, 90*mm], rowHeights=[23*mm, 8*mm, 10*mm])
        signature_boxes.setStyle(TableStyle([
            ("BOX", (0,0), (-1,-1), .65, DARK),
            ("INNERGRID", (0,0), (-1,-1), .35, BORDER),
            ("BACKGROUND", (0,1), (-1,1), NAVY),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("LEFTPADDING", (0,0), (-1,-1), 6),
        ]))
        story.append(KeepTogether([signature_boxes]))
        story.append(Spacer(1, 4*mm))
        story.append(p(
            f"Documento interno generado por DIGIT-LABORAL. Referencia {model['code']}. "
            "No es un recibo emitido por el MTESS, ni constituye una constancia de presentación "
            "o aceptación en REOP. Original: empleador. Duplicado: trabajador.",
            note,
        ))
        if model.get("warnings"):
            story.append(Spacer(1, 2*mm))
            story.append(p("Observaciones del cálculo guardado:", small))
            for warning in model["warnings"][:3]:
                story.append(p("• " + str(warning), small))
        return story

    story = copy_page("ORIGINAL · EMPLEADOR") + [PageBreak()] + copy_page("DUPLICADO · TRABAJADOR")

    def footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(BORDER)
        canvas.line(15*mm, 11*mm, 195*mm, 11*mm)
        canvas.setFont("DLReceipt", 6.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(15*mm, 7*mm, f"DIGIT-LABORAL · {model['code']} · Documento interno")
        canvas.drawRightString(195*mm, 7*mm, f"Página {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()
