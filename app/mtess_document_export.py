"""Salida formal de documentos MTESS, sin membretes ni etiquetas del sistema.

La declaración se construye siguiendo el texto y la distribución del Anexo III
de la Resolución 195/2026. Los datos de empresa, lugar y fecha son los únicos
campos autocompletados en ella; la firma queda para su suscripción real.
"""
from __future__ import annotations

import io
from html import escape
from datetime import date
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Mm, Pt
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, KeepTogether

from .document_export import ExportData, format_date_long_es
from .mtess_annex_ii import QUESTIONNAIRE, protocol_blocks

DECLARATION_TYPE = "mtess_declaracion_tolerancia_cero"
PROTOCOL_TYPE = "mtess_protocolo_acoso_laboral"
NOTICE_TYPE = "mtess_cartel_denuncias"
RECEIPT_TYPE = "mtess_constancia_recepcion"

ANEXO_III_HEADING = (
    "ANEXO III",
    "MODELO ORIENTATIVO DE DECLARACIÓN DE TOLERANCIA CERO",
    "FRENTE A LA DISCRIMINACIÓN, LA VIOLENCIA Y EL ACOSO EN EL",
    "MUNDO DEL TRABAJO",
)
ANEXO_III_SIGNATURE_LABEL = "Firma"
_SIGNATURE_WIDTH_MM = 65
_SIGNATURE_SPACE_MM = 12

# Cada párrafo se representa como fragmentos [texto, negrita].
# Esto permite mantener exactamente las mismas negritas en la vista previa,
# en Word y en PDF.
def annex_three_paragraphs(company_name: str) -> list[list[dict[str, Any]]]:
    name = company_name.strip()
    return [
        [
            {"text": name + ', en adelante “la Empresa”, reconoce el derecho de todas las personas que '
                     "trabajan a desenvolverse en un entorno laboral seguro, digno y respetuoso, libre de "
                     "discriminación, violencia y acoso en el mundo del trabajo.", "bold": False},
        ],
        [
            {"text": "En este sentido, la Empresa ", "bold": False},
            {"text": "declara expresamente su política de tolerancia cero", "bold": True},
            {"text": " frente a toda forma de discriminación, violencia y acoso en el mundo del "
                     "trabajo, incluidos aquellos de carácter psicológico, físico y sexual.", "bold": False},
        ],
        [
            {"text": "Estas conductas son inaceptables, no serán permitidas bajo ninguna circunstancia "
                     "y se consideran incompatibles con los valores y objetivos de " + name + ".", "bold": False},
        ],
        [
            {"text": "Esta declaración se aplica a todas las personas que prestan servicios para la Empresa, "
                     "cualquiera sea su modalidad de contratación o la naturaleza de su vínculo, así como "
                     "a quienes interactúan con ella en razón del trabajo [clientes, usuarios, pacientes, "
                     "proveedores, contratistas, subcontratistas y público en general].", "bold": False},
        ],
        [
            {"text": "En caso de denuncias, la Empresa ", "bold": False},
            {"text": "aplicará los procedimientos establecidos por el Ministerio de Trabajo, Empleo "
                     "y Seguridad Social (MTESS)", "bold": True},
            {"text": " para la atención, análisis e investigación de los casos, ajustándose "
                     "a los lineamientos vigentes.", "bold": False},
        ],
        [
            {"text": "La Empresa manifiesta que ", "bold": False},
            {"text": "no admitirá represalias", "bold": True},
            {"text": " contra aquellas personas que formulen denuncias, planteen consultas, participen "
                     "como testigos o colaboren en la gestión de situaciones relacionadas "
                     "con discriminación, violencia o acoso.", "bold": False},
        ],
        [
            {"text": "Todas las personas que integran " + name + " deberán observar esta política "
                     "de tolerancia cero, basando sus relaciones laborales en el respeto, el buen trato, "
                     "la igualdad y la protección de la dignidad de las personas.", "bold": False},
        ],
    ]


def annex_three_location(city: str, issue_date: date) -> str:
    return f"{city}, {format_date_long_es(issue_date)}"


def build_annex_three_body(company_name: str, city: str, issue_date: date) -> str:
    """Snapshot del texto fiel, sin RUC, leyendas, canales, advertencias ni marcas."""
    return "\n\n".join([
        "\n".join(ANEXO_III_HEADING),
        *("".join(part["text"] for part in paragraph)
          for paragraph in annex_three_paragraphs(company_name)),
        annex_three_location(city, issue_date) + "\n[Firma]",
    ])


def _docx_logo(doc: Document, logo_bytes: bytes | None) -> None:
    # Sin imagen real, no crear siquiera el párrafo contenedor.
    if not logo_bytes:
        return
    paragraph = doc.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = paragraph.add_run()
    run.add_picture(io.BytesIO(logo_bytes), width=Cm(3.0))
    paragraph.paragraph_format.space_after = Pt(4)


def _docx_annex_three_signature(doc: Document, location: str) -> None:
    place_and_date = doc.add_paragraph(location)
    place_and_date.paragraph_format.space_after = Pt(0)
    place_and_date.paragraph_format.keep_with_next = True

    signature = doc.add_paragraph()
    borders = OxmlElement("w:pBdr")
    top = OxmlElement("w:top")
    top.set(qn("w:val"), "single")
    top.set(qn("w:sz"), "4")
    top.set(qn("w:space"), "3")
    top.set(qn("w:color"), "000000")
    borders.append(top)
    signature._p.get_or_add_pPr().append(borders)

    section = doc.sections[-1]
    signature.paragraph_format.right_indent = (
        section.page_width - section.left_margin - section.right_margin - Mm(_SIGNATURE_WIDTH_MM)
    )
    signature.paragraph_format.space_before = Mm(_SIGNATURE_SPACE_MM)
    signature.paragraph_format.space_after = Pt(0)
    signature.alignment = WD_ALIGN_PARAGRAPH.CENTER
    signature.add_run(ANEXO_III_SIGNATURE_LABEL).font.size = Pt(10)


def build_mtess_docx_bytes(data: ExportData) -> bytes:
    """PDF y Word MTESS sin branding supletorio, pie ni leyenda de borrador."""
    if data.document_type == PROTOCOL_TYPE:
        return build_annex_two_docx_bytes(data)
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.top_margin, section.bottom_margin = Cm(1.8), Cm(1.8)
    section.left_margin, section.right_margin = Cm(2.2), Cm(2.2)
    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(11)
    normal.paragraph_format.line_spacing = 1.12
    normal.paragraph_format.space_after = Pt(12)

    _docx_logo(doc, data.logo_bytes)

    if data.document_type == DECLARATION_TYPE:
        for line in ANEXO_III_HEADING:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.keep_with_next = True
            r = p.add_run(line)
            r.bold = True
            r.font.name = "Times New Roman"
            r.font.size = Pt(11.5)
        doc.paragraphs[-1].paragraph_format.space_after = Pt(14)
        for segments in annex_three_paragraphs(data.company_name):
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            for segment in segments:
                r = p.add_run(segment["text"])
                r.bold = segment["bold"]
        _docx_annex_three_signature(doc, annex_three_location(data.city, data.issue_date))
    else:
        paragraphs = data.body.strip().split("\n\n")
        for index, block in enumerate(paragraphs):
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER if index == 0 else WD_ALIGN_PARAGRAPH.JUSTIFY
            if index == 0:
                p.paragraph_format.space_after = Pt(14)
            for k, line in enumerate(block.split("\n")):
                if k:
                    p.add_run().add_break()
                run = p.add_run(line)
                run.bold = index == 0

    # No añadir footer, página, logo genérico, "DOCUMENTO LABORAL" ni BORRADOR.
    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()


def _pdf_logo(story: list, logo_bytes: bytes | None) -> None:
    if not logo_bytes:
        return  # Sin imagen no hay bloque ni espacio sobrante.
    from reportlab.lib.utils import ImageReader
    reader = ImageReader(io.BytesIO(logo_bytes))
    w, h = reader.getSize()
    if not w or not h:
        return
    ratio = min(80 / w, 40 / h)
    story.append(Image(io.BytesIO(logo_bytes), width=w * ratio, height=h * ratio))
    story.append(Spacer(1, 4 * mm))


def build_mtess_pdf_bytes(data: ExportData) -> bytes:
    if data.document_type == PROTOCOL_TYPE:
        return build_annex_two_pdf_bytes(data)
    stream = io.BytesIO()
    document = SimpleDocTemplate(
        stream, pagesize=A4, topMargin=17*mm, bottomMargin=18*mm,
        leftMargin=20*mm, rightMargin=20*mm,
        title=data.title, author=data.company_name,
    )
    main = ParagraphStyle(
        "MtessNormal", fontName="Times-Roman", fontSize=11,
        leading=14, alignment=TA_JUSTIFY, textColor=colors.black,
        spaceAfter=12,
    )
    title = ParagraphStyle(
        "MtessAnexoTitle", parent=main, fontName="Times-Bold", fontSize=11.5,
        leading=13.6, alignment=TA_CENTER, spaceAfter=0,
    )
    story = []
    _pdf_logo(story, data.logo_bytes)
    if data.document_type == DECLARATION_TYPE:
        for line in ANEXO_III_HEADING:
            story.append(Paragraph(escape(line), title))
        story.append(Spacer(1, 5*mm))
        for segments in annex_three_paragraphs(data.company_name):
            markup = "".join(
                f"<b>{escape(segment['text'])}</b>" if segment["bold"] else escape(segment["text"])
                for segment in segments
            )
            story.append(Paragraph(markup, main))
        location = ParagraphStyle("MtessLocation", parent=main, alignment=TA_LEFT, spaceAfter=0)
        signature = ParagraphStyle("MtessSignature", parent=location, alignment=TA_CENTER, fontSize=10)
        signature_line = Table(
            [[Paragraph(ANEXO_III_SIGNATURE_LABEL, signature)]],
            colWidths=[_SIGNATURE_WIDTH_MM * mm],
            hAlign="LEFT",
            style=[
                ("LINEABOVE", (0, 0), (0, 0), 0.5, colors.black),
                ("TOPPADDING", (0, 0), (0, 0), 3),
                ("BOTTOMPADDING", (0, 0), (0, 0), 0),
            ],
        )
        story.append(KeepTogether([
            Spacer(1, 1 * mm),
            Paragraph(escape(annex_three_location(data.city, data.issue_date)), location),
            Spacer(1, _SIGNATURE_SPACE_MM * mm),
            signature_line,
        ]))
    else:
        for index, block in enumerate(data.body.strip().split("\n\n")):
            markup = "<br/>".join(escape(line) for line in block.split("\n"))
            if index == 0:
                story.append(Paragraph(markup, title))
                story.append(Spacer(1, 5*mm))
            else:
                story.append(Paragraph(markup, main))

    # Sin onFirstPage/onLaterPages: no pie de página, páginas numeradas ni borrador.
    document.build(story)
    return stream.getvalue()



def _docx_questionnaire(doc: Document) -> None:
    """Tabla original de cuatro categorías y quince preguntas."""
    table = doc.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    table.columns[0].width = Cm(4.8)
    table.columns[1].width = Cm(11.7)
    for category, questions in QUESTIONNAIRE:
        cells = table.add_row().cells
        cells[0].width = Cm(4.8)
        cells[1].width = Cm(11.7)
        cells[0].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        cells[1].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        label = cells[0].paragraphs[0]
        label.alignment = WD_ALIGN_PARAGRAPH.LEFT
        run = label.add_run(category)
        run.bold = True
        run.font.name = "Times New Roman"
        run.font.size = Pt(9.4)
        for i, question in enumerate(questions):
            paragraph = cells[1].paragraphs[0] if i == 0 else cells[1].add_paragraph()
            paragraph.paragraph_format.space_after = Pt(3)
            paragraph.paragraph_format.left_indent = Cm(.2)
            paragraph.add_run("• " + question).font.size = Pt(9.2)


def build_annex_two_docx_bytes(data: ExportData) -> bytes:
    """Protocolo completo, orden oficial, con tablas y campos de empresa."""
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.top_margin, section.bottom_margin = Cm(1.9), Cm(1.7)
    section.left_margin, section.right_margin = Cm(2.15), Cm(2.15)
    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(11)
    normal.paragraph_format.space_after = Pt(9)
    normal.paragraph_format.line_spacing = 1.12
    _docx_logo(doc, data.logo_bytes)
    for item in protocol_blocks(data.body):
        kind, content = item["kind"], item["text"]
        if kind == "questionnaire":
            _docx_questionnaire(doc)
            continue
        paragraph = doc.add_paragraph()
        paragraph.alignment = (
            WD_ALIGN_PARAGRAPH.CENTER
            if kind in {"annex", "cover", "axis", "policy"}
            else WD_ALIGN_PARAGRAPH.LEFT if kind == "bullet"
            else WD_ALIGN_PARAGRAPH.JUSTIFY
        )
        if kind in {"annex", "cover", "axis", "policy", "heading"}:
            paragraph.paragraph_format.space_before = Pt(10 if kind in {"axis", "policy"} else 3)
            paragraph.paragraph_format.keep_with_next = True
        if kind == "bullet":
            paragraph.paragraph_format.left_indent = Cm(.35)
            paragraph.paragraph_format.first_line_indent = Cm(-.15)
            paragraph.paragraph_format.space_after = Pt(4)
        for i, line in enumerate(content.splitlines()):
            if i:
                paragraph.add_run().add_break()
            run = paragraph.add_run(line)
            run.font.name = "Times New Roman"
            run.font.size = Pt(11)
            run.bold = kind in {"annex", "cover", "axis", "policy", "heading"}
    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()


def _pdf_questionnaire() -> Table:
    """Tabla visual equivalente a la del Anexo II (páginas 31-32)."""
    category_style = ParagraphStyle(
        "AnexoIIQCategory", fontName="Times-Bold", fontSize=9.5,
        leading=12, textColor=colors.black, spaceAfter=0,
    )
    question_style = ParagraphStyle(
        "AnexoIIQuestion", fontName="Times-Roman", fontSize=9.2,
        leading=11.6, textColor=colors.black, spaceAfter=4,
    )
    rows = []
    for category, questions in QUESTIONNAIRE:
        rows.append([
            Paragraph(escape(category), category_style),
            [Paragraph("&#8226; " + escape(question), question_style) for question in questions],
        ])
    tab = Table(rows, colWidths=[43*mm, 124*mm], hAlign="CENTER", repeatRows=0)
    tab.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), .35, colors.HexColor("#aaaaaa")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return tab


def build_annex_two_pdf_bytes(data: ExportData) -> bytes:
    """A4 sin marca de agua, página, membrete ficticio ni pie automático."""
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=21*mm, leftMargin=21*mm,
        topMargin=17*mm, bottomMargin=18*mm,
        title=data.title, author=data.company_name,
    )
    styles = {
        "paragraph": ParagraphStyle(
            "AnexoIIParagraph", fontName="Times-Roman", fontSize=10.9,
            leading=14.1, alignment=TA_JUSTIFY, spaceAfter=9,
            textColor=colors.black,
        ),
        "annex": ParagraphStyle(
            "AnexoIICoverNumber", fontName="Times-Bold", fontSize=12,
            leading=16, alignment=TA_CENTER, spaceAfter=12, textColor=colors.black,
        ),
        "cover": ParagraphStyle(
            "AnexoIICover", fontName="Times-Bold", fontSize=11.5,
            leading=14, alignment=TA_CENTER, spaceAfter=10, textColor=colors.black,
        ),
        "axis": ParagraphStyle(
            "AnexoIIAxis", fontName="Times-Bold", fontSize=11.3,
            leading=15, alignment=TA_CENTER, spaceBefore=12, spaceAfter=12,
            textColor=colors.black, keepWithNext=True,
        ),
        "policy": ParagraphStyle(
            "AnexoIIPolicy", fontName="Times-Bold", fontSize=11,
            leading=14, alignment=TA_CENTER, spaceBefore=9, spaceAfter=11,
            textColor=colors.black, keepWithNext=True,
        ),
        "heading": ParagraphStyle(
            "AnexoIIHeading", fontName="Times-Bold", fontSize=11,
            leading=14, alignment=TA_LEFT, spaceBefore=7, spaceAfter=4,
            textColor=colors.black, keepWithNext=True,
        ),
        "bullet": ParagraphStyle(
            "AnexoIIBullet", fontName="Times-Roman", fontSize=10.8,
            leading=14, alignment=TA_JUSTIFY, leftIndent=9, firstLineIndent=-7,
            spaceAfter=5, textColor=colors.black,
        ),
    }
    story = []
    _pdf_logo(story, data.logo_bytes)
    for item in protocol_blocks(data.body):
        kind, content = item["kind"], item["text"]
        if kind == "questionnaire":
            story.append(_pdf_questionnaire())
        else:
            markup = "<br/>".join(escape(line) for line in content.splitlines())
            story.append(Paragraph(markup, styles.get(kind, styles["paragraph"])))
    document.build(story)
    return buffer.getvalue()
