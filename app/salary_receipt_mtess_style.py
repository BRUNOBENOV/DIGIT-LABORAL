"""Recibo salarial DIGIT-LABORAL: retícula del modelo MTESS, sin QR ni identidad oficial.

Presenta los importes persistidos sin recalcularlos y emite ORIGINAL / DUPLICADO
con una numeración interna compartida. No suplanta un comprobante REOP.
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

NAVY = colors.HexColor("#284B70")
DARK = colors.HexColor("#111111")
PALE = colors.HexColor("#F0F0F0")
BORDER = colors.HexColor("#111111")
MUTED = colors.HexColor("#111111")
W = 196 * mm
RED = colors.HexColor("#941D1C")


def _gs(amount):
    return f"{int(amount):,}".replace(",", ".")


def _text(value, fallback="—"):
    value = str(value) if value not in (None, "") else fallback
    return escape(value).replace("\n", "<br/>")


def build_mtess_style_salary_pdf(model: dict) -> bytes:
    """One complete A4 receipt for each copy. Layout follows reference categories."""
    stream = BytesIO()
    doc = SimpleDocTemplate(
        stream, pagesize=A4, leftMargin=7*mm, rightMargin=7*mm,
        topMargin=7*mm, bottomMargin=7*mm,
        title=f"Liquidación de salario {model['code']}",
        author="DIGIT-LABORAL",
    )
    body = ParagraphStyle(
        "DLReceiptBody", fontName="DLReceipt", fontSize=9,
        leading=12, textColor=DARK,
    )
    bold = ParagraphStyle(
        "DLReceiptBold", parent=body, fontName="DLReceipt-Bold", fontSize=9,
        leading=12,
    )
    white = ParagraphStyle(
        "DLReceiptWhite", parent=bold, textColor=colors.white, fontSize=8.6,
        leading=10.5,
    )
    centered = ParagraphStyle("DLReceiptCenter", parent=body, alignment=TA_CENTER)
    centered_bold = ParagraphStyle("DLReceiptCenterBold", parent=bold, alignment=TA_CENTER)
    centered_white = ParagraphStyle("DLReceiptCenterWhite", parent=white, alignment=TA_CENTER)
    right = ParagraphStyle("DLReceiptRight", parent=body, alignment=TA_RIGHT)
    right_bold = ParagraphStyle("DLReceiptRightBold", parent=bold, alignment=TA_RIGHT)
    small = ParagraphStyle(
        "DLReceiptSmall", parent=body, fontSize=7.5, leading=10, textColor=MUTED,
    )
    note = ParagraphStyle(
        "DLReceiptNote", parent=body, fontSize=8, leading=10.8, textColor=DARK,
    )

    def p(value, style=body):
        return Paragraph(_text(value), style)

    def table(rows, widths, *, head_rows=0, pads=3, special=None, row_heights=None):
        t = Table(rows, colWidths=widths, rowHeights=row_heights,
                  repeatRows=head_rows, hAlign="LEFT")
        commands = [
            ("BOX", (0, 0), (-1, -1), .75, BORDER),
            ("INNERGRID", (0, 0), (-1, -1), .55, BORDER),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), pads),
            ("RIGHTPADDING", (0, 0), (-1, -1), pads),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        if head_rows:
            commands.append(("BACKGROUND", (0, 0), (-1, head_rows-1), NAVY))
        if special:
            commands.extend(special)
        t.setStyle(TableStyle(commands))
        return t

    def copy_page(copy_label):
        story = []
        if model.get("is_annulled"):
            story.extend([
                table([[p("ANULADO · COPIA HISTÓRICA · NO UTILIZAR COMO RECIBO VIGENTE",
                          centered_white)]], [W],
                      special=[("BACKGROUND", (0, 0), (-1, -1), RED),
                               ("TOPPADDING", (0, 0), (-1, -1), 6),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]),
                Spacer(1, 3*mm),
            ])

        # Misma disposición del modelo de referencia: área gris a la izquierda,
        # franja roja superior, título azul y banda roja ORIGINAL/DUPLICADO.
        logo_style = ParagraphStyle(
            "DLReceiptLogo", parent=bold, fontSize=17, leading=20,
            alignment=TA_CENTER, textColor=colors.white,
        )
        title_style = ParagraphStyle(
            "DLReceiptTitle", parent=bold, fontSize=11, leading=13,
            textColor=colors.white,
        )
        header_note = ParagraphStyle(
            "DLReceiptHeaderNote", parent=body, fontSize=7.7, leading=9.5,
        )
        red_copy_style = ParagraphStyle(
            "DLReceiptCopy", parent=bold, fontSize=8, leading=10,
            textColor=colors.white,
        )
        left_heading = Table([
            [Paragraph("DL", logo_style),
             [p("DIGIT-LABORAL", bold),
              p("Sistema de gestión laboral", header_note),
              p("Liquidación de salarios · Paraguay", header_note)]],
        ], colWidths=[19*mm, 109*mm], rowHeights=[21*mm])
        left_heading.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), NAVY),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (0, 0), 4),
            ("RIGHTPADDING", (0, 0), (0, 0), 4),
            ("LEFTPADDING", (1, 0), (1, 0), 7),
            ("RIGHTPADDING", (1, 0), (1, 0), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ]))

        header_right = Table([
            [""],
            [[Paragraph("LIQUIDACIÓN DE SALARIO", title_style),
              p("N.º " + model["code"], white)]],
            [Paragraph(copy_label, red_copy_style)],
        ], colWidths=[64*mm], rowHeights=[4*mm, 14*mm, 5*mm])
        header_right.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), RED),
            ("BACKGROUND", (0, 1), (0, 1), NAVY),
            ("BACKGROUND", (0, 2), (0, 2), RED),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        header = Table([[left_heading, header_right]], colWidths=[132*mm, 64*mm],
                       rowHeights=[23*mm], hAlign="LEFT")
        header.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), PALE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.extend([header, Spacer(1, 3*mm)])

        story.append(table([
            [p("EMPLEADOR", centered_white), p("RUC N.º", centered_white)],
            [p(model["employer_name"]), p(model["employer_ruc"])],
        ], [150*mm, 46*mm], head_rows=1))
        story.append(Spacer(1, 3*mm))

        story.append(table([
            [p("NOMBRE Y APELLIDO DEL TRABAJADOR", centered_white),
             p("C.I. N.º", centered_white)],
            [p(model["employee_name"]), p(model["employee_ci"])],
        ], [150*mm, 46*mm], head_rows=1))
        story.append(Spacer(1, 3*mm))

        # El primer encabezado ocupa ambas filas, como en el recibo MTESS.
        story.append(table([
            [p("PERÍODO\nDE PAGO", white), p("DESDE", centered_white),
             p("HASTA", centered_white), p("FECHA", centered_white),
             p("FORMA DE PAGO", centered_white)],
            ["", p(model.get("period_from_mtess_display") or model.get("period_from_display") or "No registrado"),
             p(model.get("period_to_mtess_display") or model.get("period_to_display") or "No registrado"),
             p(model.get("payment_date_display") or "No registrada"),
             p(model.get("payment_method") or "No registrado")],
        ], [22*mm, 44*mm, 44*mm, 44*mm, 42*mm],
           special=[("SPAN", (0, 0), (0, 1)),
                    ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                    ("BACKGROUND", (0, 1), (0, 1), NAVY)]))
        story.append(Spacer(1, 3*mm))

        story.append(table([[
            p("HORAS\nTRABAJADAS", white),
            p(model.get("hours_worked_display") or "No registrado", centered),
            p("CANTIDAD DE DÍAS\nTRABAJADOS", white),
            p(model.get("days_worked_display") or "No registrado", centered),
            p("CANTIDAD DE\nPIEZAS O TAREAS", white),
            p(model.get("pieces_or_tasks_display") or "No registrado", centered),
        ]], [31*mm, 31*mm, 39*mm, 31*mm, 32*mm, 32*mm],
            special=[("BACKGROUND", (0, 0), (0, 0), NAVY),
                     ("BACKGROUND", (2, 0), (2, 0), NAVY),
                     ("BACKGROUND", (4, 0), (4, 0), NAVY),
                     ("TOPPADDING", (0, 0), (-1, 0), 8),
                     ("BOTTOMPADDING", (0, 0), (-1, 0), 8)]))
        story.append(Spacer(1, 3*mm))

        lines = [[p("CONCEPTO", centered_white), "",
                  p("MONTO EN GS.", centered_white),
                  p("MONTO EN GS.", centered_white)]]
        categories = []
        for category, values in (
            ("INGRESOS", model["earnings"]), ("EGRESOS", model["deductions"])
        ):
            valid = [row for row in values if int(row.get("amount") or 0) > 0]
            if not valid:
                valid = [{"label": "Sin conceptos registrados", "amount": 0}]
            for idx, row in enumerate(valid):
                categories.append(len(lines))
                lines.append([
                    p(category if idx == 0 else "", white),
                    p(row["label"]),
                    p(_gs(row["amount"])) if category == "INGRESOS" and row["amount"] else "",
                    p(_gs(row["amount"])) if category == "EGRESOS" and row["amount"] else "",
                ])
        story.append(table(lines, [33*mm, 94*mm, 34.5*mm, 34.5*mm],
                           head_rows=1,
                           special=[
                               ("SPAN", (0, 0), (1, 0)),
                               ("BACKGROUND", (0, 1), (0, -1), NAVY),
                               ("TOPPADDING", (0, 0), (-1, -1), 3),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                           ]))
        story.append(Spacer(1, 3*mm))

        story.append(table([
            [p("MONTO TOTAL DE INGRESO", white), p(_gs(model["gross"]))],
            [p("MONTO TOTAL DE EGRESO", white), p(_gs(model["discounts"]))],
            [p("MONTO TOTAL A COBRAR", white), p(_gs(model["net"]))],
        ], [101*mm, 95*mm], special=[
            ("BACKGROUND", (0, 0), (0, -1), NAVY),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(Spacer(1, 3*mm))

        # El QR del formulario oficial se elimina. Ambos casilleros de firma
        # ocupan el espacio disponible y mantienen el orden de la referencia.
        signatures = Table([
            ["", "", ""],
            [p("FIRMA DEL EMPLEADOR", white), "",
             p("FIRMA DEL EMPLEADO", white)],
        ], colWidths=[94*mm, 8*mm, 94*mm], rowHeights=[25*mm, 7*mm])
        signatures.setStyle(TableStyle([
            ("BOX", (0, 0), (0, 0), .75, BORDER),
            ("BOX", (2, 0), (2, 0), .75, BORDER),
            ("BACKGROUND", (0, 1), (0, 1), NAVY),
            ("BACKGROUND", (2, 1), (2, 1), NAVY),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(KeepTogether([signatures]))
        story.append(Spacer(1, 3*mm))

        disclaimer_style = ParagraphStyle(
            "DLReceiptDisclaimer", parent=note, fontSize=8,
            leading=10.5, fontName="DLReceipt",
        )
        story.append(Paragraph(
            "Este recibo fue generado electrónicamente por DIGIT-LABORAL con "
            "datos suministrados por el empleador bajo su responsabilidad. "
            "No constituye constancia oficial de presentación en REOP "
            "ni acredita por sí solo el pago efectivo.",
            disclaimer_style,
        ))
        story.append(Spacer(1, 1.7*mm))
        story.append(p("Original: Empleador. Duplicado: Trabajador.", bold))
        return story

    story = copy_page("ORIGINAL") + [PageBreak()] + copy_page("DUPLICADO")

    doc.build(story)
    return stream.getvalue()
