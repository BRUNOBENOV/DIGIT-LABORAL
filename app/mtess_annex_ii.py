"""Anexo II oficial MTESS 195/2026: texto completo con autocompletado conservador.

Fuente: páginas 22-35 del PDF oficial incorporado en mtess_anexo_ii_source.txt.
El archivo fuente no se modifica. Los apartados del modelo se reproducen
siguiendo el mismo orden y se eliminan solo las instrucciones para quien
edita el modelo, las firmas del MTESS y los encabezados de la resolución.
La Resolución 564/2026 modifica la normativa: las referencias a 195/2026
aquí son las del anexo original, no una consolidación normativa.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from .document_export import format_date_long_es

SOURCE_FILE = Path(__file__).with_name("mtess_anexo_ii_source.txt")
PAGE_SEPARATOR = re.compile(r"--- ANEXO II PÁGINA (\d+) ---\s*\n")
SOURCE_PAGES = tuple(range(22, 36))
HEADING = "ANEXO II"
COVER_TITLE = (
    "MODELO ORIENTATIVO DE PROTOCOLO DE PREVENCIÓN, ATENCIÓN E "
    "INVESTIGACIÓN DE HECHOS DE DISCRIMINACIÓN, VIOLENCIA Y ACOSO "
    "EN EL MUNDO DEL TRABAJO."
)
EJE_TITLES = (
    "I. EJE DE PREVENCIÓN",
    "II. EJE DE IDENTIFICACIÓN Y DETECCIÓN DE CASOS",
    "III. EJE DE ATENCIÓN, MEDIDAS DE RESGUARDO Y MEDIDAS CORRECTIVAS",
    "IV. EJE DE SEGUIMIENTO Y EVALUACIÓN DEL PROTOCOLO",
)

# Los ejemplos de encuesta se reproducen por categorías, conservando todas
# las preguntas de las páginas 31-32. El origen también se conserva en source.
QUESTIONNAIRE = (
    ("Conocimiento y sensibilización", (
        "¿Sabe dónde encontrar nuestra política y código de conducta sobre el lugar de trabajo que abarca la violencia y el acoso?",
        "¿Hasta qué punto comprende nuestras políticas sobre el lugar de trabajo relacionadas con la prevención y eliminación de la violencia y el acoso?",
        "¿Ha recibido capacitación sobre la violencia y el acoso en el lugar de trabajo y cómo afrontarlos?",
        "¿En qué medida está preparado(a) para afrontar una situación de acoso o violencia?",
        "¿Sabe cómo informar sobre cualquier inquietud relacionada con la violencia y el acoso en el trabajo?",
    )),
    ("Seguridad y vigilancia", (
        "¿Ha sido alguna vez acosado o víctima de un incidente violento en el trabajo? En caso su respuesta sea afirmativa, ¿lo denunció?",
        "¿Ha sido alguna vez testigo de acoso o de un incidente violento en el lugar de trabajo? En caso su respuesta sea afirmativa, ¿lo denunció?",
        "¿En qué medida le preocupan la violencia y el acoso en nuestro lugar de trabajo?",
        "¿Se siente seguro en el trabajo?",
        "¿Cree que los riesgos de violencia y acoso en el lugar de trabajo han aumentado, han disminuido o se han mantenido igual en el último año?",
    )),
    ("Control de riesgos y medidas de mitigación", (
        "¿Cree que las medidas existentes para controlar y prevenir la violencia y el acoso en el trabajo son eficaces?",
        "En caso su respuesta sea negativa, ¿qué aspecto es ineficaz o qué tan ineficaces son las medidas?",
        "¿Qué otros pasos o medidas deberían adoptarse para hacer más seguro nuestro lugar de trabajo?",
    )),
    ("Cultura empresarial y liderazgo", (
        "¿En qué medida cree que la dirección está comprometida con prevenir y responder a la violencia y el acoso?",
        "¿Demuestran los altos directivos su compromiso con la lucha contra la violencia y el acoso?",
    )),
)
QUESTIONNAIRE_TOKEN = "[[CUESTIONARIO_ANEXO_II]]"


def source_pages() -> dict[int, str]:
    """Accede exclusivamente a la transcripción versionada, sin red externa."""
    raw = SOURCE_FILE.read_text(encoding="utf-8")
    pieces = PAGE_SEPARATOR.split(raw)
    pages = {int(pieces[i]): pieces[i + 1] for i in range(1, len(pieces), 2)}
    if sorted(pages) != list(SOURCE_PAGES):
        raise ValueError("La fuente Anexo II debe contener íntegramente las páginas 22 a 35")
    return pages


def _page_body(number: int, raw: str) -> str:
    # Encabezado institucional y pie numerado del PDF no forman parte del
    # protocolo para el empleador.
    found = re.search(r"Asunción,\s*marzo de 2026\.", raw)
    if not found:
        raise ValueError(f"Cabecera de origen no reconocida en página {number}")
    text = raw[found.end():]
    text = re.sub(rf"\s*Página\s+{number}\s+de\s+36\s*$", "", text)
    if number == 23:
        # El Anexo II pide expresamente excluir del protocolo definitivo las
        # instrucciones al editor y la bibliografía que sirve de ayuda.
        intro = re.search(r"La Empresa\s+\[Nombre de la empresa\], declara", text)
        if not intro:
            raise ValueError("No se encuentra el inicio del texto del modelo")
        text = text[intro.start():]
    if number == 35:
        # Firmas digitales de la Secretaria General y Ministra en la
        # resolución publicada: no son firmas de la empresa.
        text = re.split(r"\n\s*MARTA\s+Firmado", text, maxsplit=1)[0]
    return text.strip()


def _remove_editor_notes(source: str) -> str:
    text = source
    # Notas redactadas para quien personaliza la plantilla. Los párrafos
    # normativos y enumeraciones no se eliminan ni se sintetizan.
    patterns = (
        r"\[Ajustar según corresponda(?: al modelo de gestión adoptado)?\]",
        r"\[Determinar 1 instancia y ajustar según\s*corresponda\]",
        r"\[A continuación se presenta un ejemplo de la declaración de la política:\]",
        r"\[El empleador debe incluir las conductas.*?Resolución MTESS N°\s*XX solo define algunas de ellas\]",
        r"\[Se debe analizar igualmente el caso concreto.*?se podría ajustar la lista\]",
        r"\[Indicar otros temas de formación.*?indicar nombre y cargo\]",
        r"\[modelo que se proporciona orientado.*?necesidades de la\s*Empresa\]",
        r"\[La empresa podrá estandarizar un formato interno.*?los trabajadores\]",
        r"\[La Empresa deberá elaborar materiales de difusión.*?durante este\s*proceso\]",
        r"\[La Empresa deberá representar gráficamente el flujo del procedimiento interno, a fin de facilitar\s*la compresión de procesos y plazos por parte de todas las personas involucradas en un proceso\s*de investigación:",
        r"\[La Empresa completará la siguiente información, de acuerdo con el modelo organizativo que\s*elija:",
    )
    for expression in patterns:
        text = re.sub(expression, "", text, flags=re.I | re.S)
    text = re.sub(r"\[\s*Indicar el medio y la instancia habilitada.*?habilitado\]", "", text, flags=re.I | re.S)
    return text


def _replace_slots(source: str, *, company_name: str, ruc: str,
                   legal_representative: str, city: str, issued_on: date,
                   responsible: str, channel: str, hours: str,
                   rit_status: str) -> str:
    if rit_status in {"homologado", "no_homologado"}:
        integration = "y forma parte integrante del Reglamento Interno de Trabajo"
        approval = "por la autoridad administrativa, conforme al trámite de homologación del Reglamento Interno de Trabajo"
    else:
        integration = "y constituye un documento independiente de gestión interna"
        approval = "por la máxima autoridad de la Empresa"
    text = source
    text = re.sub(
        r"y forma parte integrante\s+del Reglamento Interno de Trabajo o del \[instrumento equivalente\]",
        integration, text, flags=re.I,
    )
    text = re.sub(
        r"\[por la autoridad administrativa\s*–\s*dentro del reglamento interno y/o por la máxima autoridad de la Empresa\s*–\s*sin obligación de\s*reglamento interno\]",
        approval, text, flags=re.I,
    )
    # Autocompletado de los únicos datos confirmados por el usuario o empresa.
    text = re.sub(r"\[\s*Nombre\s+de\s+la\s+empresa\s*\]", lambda _: company_name, text, flags=re.I)
    text = re.sub(r"\[\s*Nombre\s+de\s+la\s+empresa\s+RUC\s+de\s+la\s+empresa\s*\]",
                  lambda _: f"{company_name}\nRUC: {ruc}", text, flags=re.I)
    text = re.sub(r"\[nombre de la instancia\]", lambda _: responsible, text, flags=re.I)
    text = re.sub(r"\[Nombre\s+del\s+área,\s*comité\s*o\s*persona\s*responsable:\s*_+\]",
                  lambda _: f"Nombre del área, comité o persona responsable: {responsible}", text, flags=re.I)
    text = re.sub(r"\[Correo\s+institucional\s+o\s+canal\s+de\s+contacto:\s*_+\]",
                  lambda _: f"Correo institucional o canal de contacto: {channel}", text, flags=re.I)
    text = re.sub(r"\[Otros medios de contacto\s*\(teléfono interno, oficina física, horario de atención\):\s*_+\]",
                  lambda _: f"Horario de atención y otros medios de contacto: {hours or 'No especificado'}", text, flags=re.I)
    text = re.sub(r"\[indicar nombre y unidad, área o departamento en el que se\s*desempeña, y su cargo específico, y todos los detalles del canal de denuncias\.",
                  f"Responsable: {responsible}. Canal de denuncias: {channel}. Horario: {hours or 'Horario habitual de la empresa'}.",
                  text, flags=re.I)
    text = re.sub(r"\[indicar persona o teléfono o correo electrónico establecido para ello\]",
                  lambda _: f"{responsible}: {channel}", text, flags=re.I)
    text = re.sub(r"\[Indicar el medio y la vía\]",
                  "los medios internos establecidos por la empresa", text, flags=re.I)
    text = re.sub(r"\[Lugar\]", city, text, flags=re.I)
    text = re.sub(r"\[fecha\]", format_date_long_es(issued_on), text, flags=re.I)
    text = re.sub(r"\[Nombre y cargo de la máxima autoridad de la empresa\]",
                  legal_representative or "Firma del empleador o representante autorizado",
                  text, flags=re.I)
    text = re.sub(r"\[\s*Firma\s*\]", "____________________________________________", text, flags=re.I)
    text = re.sub(r"\[\s*…\s*\]\s*año\(s\)", "1 año", text)
    text = re.sub(r"\[POLÍTICA DE TOLERANCIA CERO FRENTE A LA DISCRIMINACIÓN, LA\s*VIOLENCIA Y EL ACOSO EN EL MUNDO DEL TRABAJO\]",
                  "POLÍTICA DE TOLERANCIA CERO FRENTE A LA DISCRIMINACIÓN, LA VIOLENCIA Y EL ACOSO EN EL MUNDO DEL TRABAJO",
                  text, flags=re.I)
    return text


def _clean_questionnaire(body: str) -> str:
    """Reproduce las 15 preguntas en tabla en los exportadores, no como texto desordenado."""
    # Se identifica por el título del cuadro de la fuente, y concluye al
    # inicio del eje siguiente. Su contenido se conserva en QUESTIONNAIRE.
    title = "Ejemplos de preguntas de encuesta relacionadas con el riesgo de violencia y acoso laboral"
    marker = re.search(re.escape(title), body, flags=re.I)
    if not marker:
        raise ValueError("No se halló el cuestionario orientativo del Anexo II")
    end = re.search(r"III\.\s+EJE DE ATENCIÓN", body[marker.start():], flags=re.I)
    if not end:
        raise ValueError("No se halló el final del cuestionario")
    start_index = marker.start()
    end_index = marker.start() + end.start()
    return (
        body[:start_index]
        + f"\n\n{title}\n{QUESTIONNAIRE_TOKEN}\n"
        + "Fuente: Violencia y acoso en el trabajo: Guía práctica para las empresas – OIT 2022.\n"
        + "Estas herramientas deberán aplicarse siempre de forma anónima y confidencial, y sus resultados se analizarán en forma agregada, sin intentar identificar personas específicas.\n\n"
        + body[end_index:]
    )


def _paragraphize(source: str) -> str:
    """Unifica las líneas partidas por el PDF sin cambiar el contenido."""
    output: list[str] = []
    buffer: list[str] = []
    def flush() -> None:
        nonlocal buffer
        if buffer:
            output.append(" ".join(buffer).strip())
            buffer = []
    for rawline in source.splitlines():
        line = rawline.strip()
        if not line:
            flush()
            continue
        is_title = bool(re.match(
            r"^(?:ANEXO II|MODELO ORIENTATIVO|PROTOCOLO DE PREVENCIÓN|"
            r"[IVX]+\.\s+EJE|[1-9]\.\s+[A-ZÁÉÍÓÚ]|"
            r"POLÍTICA DE TOLERANCIA CERO)", line
        ))
        bullet = line.startswith(("•", "– ", "- "))
        if is_title or bullet or line == QUESTIONNAIRE_TOKEN:
            flush()
            buffer.append(line)
            if is_title or line == QUESTIONNAIRE_TOKEN:
                flush()
            continue
        buffer.append(line)
    flush()
    result = "\n\n".join(x for x in output if x.strip())
    return re.sub(r"\n{3,}", "\n\n", result)


def build_annex_ii_body(
    *, company_name: str, ruc: str, legal_representative: str,
    city: str, issued_on: date, responsible: str, channel: str,
    hours: str, rit_status: str,
) -> str:
    pages = source_pages()
    parts = [_page_body(n, pages[n]) for n in SOURCE_PAGES]
    raw = "\n\n".join(parts)
    raw = _remove_editor_notes(raw)
    raw = _replace_slots(
        raw, company_name=company_name, ruc=ruc,
        legal_representative=legal_representative,
        city=city, issued_on=issued_on,
        responsible=responsible, channel=channel, hours=hours,
        rit_status=rit_status,
    )
    raw = _clean_questionnaire(raw)
    result = _paragraphize(raw)
    for title in EJE_TITLES:
        if title not in result:
            raise ValueError(f"Falta eje oficial: {title}")
    if "ANEXO II" not in result or "7. Flujograma orientativo" not in result:
        raise ValueError("La reproducción del Anexo II está incompleta")
    return result
