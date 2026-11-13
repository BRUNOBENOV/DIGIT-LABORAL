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
from docx.shared import Cm, Pt
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer

from .document_export import ExportData, format_date_long_es

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


def build_mtess_docx_bytes(data: ExportData) -> bytes:
    """PDF y Word MTESS sin branding supletorio, pie ni leyenda de borrador."""
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
        sign = doc.add_paragraph(annex_three_location(data.city, data.issue_date))
        sign.alignment = WD_ALIGN_PARAGRAPH.LEFT
        sign.paragraph_format.space_after = Pt(0)
        doc.add_paragraph("[Firma]")
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
    signature = ParagraphStyle(
        "MtessSignature", parent=main, alignment=TA_LEFT, spaceAfter=0,
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
        story.append(Spacer(1, 1 * mm))
        story.append(Paragraph(escape(annex_three_location(data.city, data.issue_date)), signature))
        story.append(Paragraph("[Firma]", signature))
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
