from __future__ import annotations

import csv
import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, PageBreak, KeepTogether

from .labor_calculator import gs

GREEN = colors.HexColor("#193b31")


def build_liquidation_pdf(result):
    stream = io.BytesIO()
    doc = SimpleDocTemplate(stream, pagesize=A4, leftMargin=17*mm, rightMargin=17*mm,
                            topMargin=16*mm, bottomMargin=18*mm,
                            title=result["title"], author="Digit Laboral")
    body = ParagraphStyle("body", fontName="Helvetica", fontSize=8.4, leading=11, spaceAfter=4)
    small = ParagraphStyle("small", parent=body, fontSize=7.1, leading=9)
    heading = ParagraphStyle("heading", parent=body, fontName="Helvetica-Bold", fontSize=19, leading=22, textColor=GREEN)
    right = ParagraphStyle("right", parent=body, alignment=TA_RIGHT)
    def p(value, style=body):
        text = str(value or "").replace("−", "-").replace("—", "-").replace("–", "-")
        return Paragraph(escape(text), style)
    flow = []
    for copy in range(result.get("copies", 1)):
        if copy:
            flow.append(PageBreak())
        flow += [p("DIGIT LABORAL · ORIGINAL / EMPLEADOR" if copy == 0 else "DIGIT LABORAL · DUPLICADO / TRABAJADOR", small),
                 p(result["title"], heading), p(result["status"], small), Spacer(1, 3*mm)]
        identity = result["identity"]
        data = [[p("Empleador: " + (identity.get("employer") or "________________")),
                 p("RUC: " + (identity.get("ruc") or "________________"))],
                [p("Trabajador: " + (identity.get("employee") or "________________")),
                 p("Documento: " + (identity.get("ci") or "________________"))],
                [p("Cargo: " + identity.get("position", "")),
                 p("Fecha: " + result["issued_date"])],
                [p("Período: " + result.get("period", "")),
                 p("Referencia: " + identity.get("reference", ""))]]
        flow.append(Table(data, colWidths=[104*mm, 72*mm], style=TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#f0f4f1")),
            ("VALIGN", (0,0), (-1,-1), "TOP"), ("BOTTOMPADDING", (0,0), (-1,-1), 6)])))
        flow.append(Spacer(1, 3*mm))
        for fact in result.get("facts", []):
            flow.append(p(fact["label"] + ": " + fact["value"], small))
        table = [[p("Concepto", small), p("Base / cálculo", small), p("Haberes · Gs.", small), p("Descuentos · Gs.", small)]]
        for direction in ("earnings", "deductions"):
            for row in result[direction]:
                label = row["label"] + (f" ({row['legal']})" if row.get("legal") else "")
                table.append([p(label), p(row.get("formula", ""), small),
                              p(gs(row["amount"]) if direction == "earnings" else "", right),
                              p(gs(row["amount"]) if direction == "deductions" else "", right)])
        table.append([p("Totales"), "", p(gs(result["gross"]), right), p(gs(result["discounts"]), right)])
        flow += [Spacer(1, 2*mm), Table(table, colWidths=[61*mm, 59*mm, 28*mm, 28*mm], repeatRows=1,
                    style=TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),
                        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#e3ece6")),
                        ("LINEBELOW",(0,0),(-1,0),.6,GREEN),
                        ("LINEBELOW",(0,1),(-1,-1),.3,colors.HexColor("#dbe3de")),
                        ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6)])),
                 Spacer(1, 3*mm), p(f"{result['net_label']}: Gs. {gs(result['net'])}", heading), Spacer(1, 3*mm)]
        if result.get("employer_cost") is not None:
            flow.append(p(f"Aporte patronal: Gs. {gs(result['employer_contribution'])} · Costo del empleador: Gs. {gs(result['employer_cost'])}. El aporte patronal no se descuenta del neto.", small))
        for note in result.get("warnings", []) + result.get("notes", []):
            flow.append(p(note, small))
        for title, url in result.get("sources", []):
            flow.append(p(title + ": " + url, small))
        signature = [
            Spacer(1, 8*mm),
            p("______________________________                    ______________________________"),
            p("Firma del empleador / representante                           Firma del trabajador", small),
            p("Fecha y constancia efectiva de pago: ______________________________", small),
            p("Medio de pago previsto: " + identity.get("payment_method", "") + " · Preparado por: " + identity.get("prepared_by", ""), small),
            p("La generación de este documento no acredita pago ni firma y no implica renuncia de derechos.", small)]
        flow.append(KeepTogether(signature))
    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#52645b"))
        canvas.drawString(17*mm, 10*mm, f"Digit Laboral · Motor {result['engine_version']} · Borrador para revisión")
        canvas.drawRightString(193*mm, 10*mm, f"Página {document.page}")
        canvas.restoreState()
    doc.build(flow, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()


def build_liquidation_csv(result):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=";")
    def row(*values):
        safe = []
        for value in values:
            text = str(value)
            if text.lstrip().startswith(("=", "+", "-", "@")):
                text = "'" + text
            safe.append(text)
        writer.writerow(safe)
    row("Digit Laboral", result["title"], result["status"], result["engine_version"])
    for key, value in result["identity"].items():
        row(key, value)
    row("Fecha", result["issued_date"], "Período", result.get("period", ""))
    row("Concepto", "Fórmula", "Referencia", "Haberes Gs.", "Descuentos Gs.")
    for direction in ("earnings", "deductions"):
        for item in result[direction]:
            row(item["label"], item.get("formula",""), item.get("legal",""),
                item["amount"] if direction == "earnings" else "",
                item["amount"] if direction == "deductions" else "")
    row("Total haberes", result["gross"])
    row("Total descuentos", result["discounts"])
    row(result["net_label"], result["net"])
    if result.get("employer_cost") is not None:
        row("Aporte patronal", result["employer_contribution"])
        row("Costo empleador", result["employer_cost"])
    for fact in result.get("facts", []):
        row(fact["label"], fact["value"])
    for note in result.get("warnings", []) + result.get("notes", []):
        row("Observación", note)
    return ("\ufeff" + stream.getvalue()).encode("utf-8")
