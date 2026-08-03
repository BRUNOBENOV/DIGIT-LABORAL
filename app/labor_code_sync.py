from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .models import LaborArticle

BASE_OFFICIAL_URL = "https://www.bacn.gov.py/leyes-paraguayas/2608/ley-n-213-establece-el-codigo-del-trabajo"
BASE_JUSTIA_URL = "https://paraguay.justia.com/nacionales/leyes/ley-213-oct-29-1993/gdoc/"
LAW_496_OFFICIAL_URL = "https://www.bacn.gov.py/leyes-paraguayas/2514/modifica-amplia-y-deroga-articulos-de-la-ley-21393-codigo-del-trabajo"
LAW_496_JUSTIA_URL = "https://paraguay.justia.com/nacionales/leyes/ley-496-aug-22-1995/gdoc/"
LAW_1416_OFFICIAL_URL = "https://www.bacn.gov.py/leyes-paraguayas/1619/ley-n-1416-modifica-el-articulo-385-de-la-ley-n-49694-que-modifica-amplia-y-deroga-articulos-de-la-ley-21393-codigo-del-trabajo-y-los-articulos-5-6-10-y-15-de-la-ley-n-88481-que-regula-las-condiciones-de-trabajo-en-el-transporte-automotor-terrestre"
LAW_1416_JUSTIA_URL = "https://paraguay.justia.com/nacionales/leyes/ley-1416-apr-16-1999/gdoc/"
LAW_3384_OFFICIAL_URL = "https://www.bacn.gov.py/leyes-paraguayas/3438/ley-n-3384-modifica-el-articulo-62-inciso-j-de-la-ley-n-21393-que-establece-el-codigo-del-trabajo"
LAW_5407_OFFICIAL_URL = "https://www.bacn.gov.py/leyes-paraguayas/4392/del-trabajo-domestico"
LAW_5764_OFFICIAL_URL = "https://www.bacn.gov.py/leyes-paraguayas/8310/ley-n-5764-modifica-el-art-culo-255-de-la-ley-n-213-93-que-establece-el-c-digo-del-trabajo-y-deroga-el-art-culo-256-del-mismo"
LAW_6470_OFFICIAL_URL = "https://www.bacn.gov.py/leyes-paraguayas/9119/ley-n-6470-modifica-el-art-culo-9-de-la-ley-n-213-1993-que-establece-el-c-digo-del-trabajo-modificado-por-la-ley-n-496-1995"

SOURCE_REGISTRY = (
    {"law": "Ley N.º 213/1993", "label": "Código del Trabajo", "url": BASE_OFFICIAL_URL},
    {"law": "Ley N.º 496/1995", "label": "Modificación general del Código", "url": LAW_496_OFFICIAL_URL},
    {"law": "Ley N.º 1416/1999", "label": "Modificación del artículo 385", "url": LAW_1416_OFFICIAL_URL},
    {"law": "Ley N.º 3384/2007", "label": "Modificación del artículo 62, inciso j)", "url": LAW_3384_OFFICIAL_URL},
    {"law": "Ley N.º 5407/2015", "label": "Trabajo doméstico y derogaciones", "url": LAW_5407_OFFICIAL_URL},
    {"law": "Ley N.º 5764/2016", "label": "Artículo 255 y derogación del 256", "url": LAW_5764_OFFICIAL_URL},
    {"law": "Ley N.º 6470/2020", "label": "Modificación del artículo 9", "url": LAW_6470_OFFICIAL_URL},
)

MODIFIED_496 = {
    2, 9, 17, 21, 26, 27, 36, 47, 74, 81, 84, 91, 105, 114, 119, 120,
    121, 122, 123, 124, 127, 128, 130, 131, 134, 135, 153, 156, 173, 181,
    182, 185, 188, 189, 194, 196, 198, 204, 205, 218, 229, 232, 254, 257,
    267, 283, 284, 291, 297, 300, 301, 318, 321, 322, 329, 333, 352, 362,
    363, 364, 366, 368, 376, 378, 379, 381, 385, 386, 388, 389, 398, 412,
}
PARTIAL_496 = {
    47: ("b",), 81: ("w",), 84: ("d",), 114: ("c",), 153: ("f", "g"),
    205: ("c", "d"), 232: ("a",), 291: ("c", "g"),
    297: ("b", "c", "d"), 352: ("e",), 376: ("c", "d", "e"),
}

ARTICLE_9_CURRENT = (
    "El trabajo es un derecho y un deber social y goza de protección del Estado. "
    "No debe ser considerado como una mercancía. Exige respeto para las libertades "
    "y dignidad de quienes lo prestan, y se efectuará en condiciones que aseguren "
    "la salud y un nivel económico compatible con las responsabilidades del trabajador "
    "padre o madre de familia.\n\nNo podrán establecerse discriminaciones relativas "
    "al trabajador por motivos étnicos, de nacionalidad, sexo, edad, religión, condición "
    "social, preferencias religiosas, políticas o sindicales.\n\nEl trabajo de las personas "
    "con discapacidad será especialmente amparado."
)

ARTICLE_255_CURRENT = (
    "La consideración del reajuste del salario mínimo será efectuada por el Poder Ejecutivo "
    "a propuesta del Consejo Nacional de Salarios Mínimos (CONASAM), sobre la base de la "
    "variación interanual del Índice de Precios al Consumidor (IPC) y su impacto en la economía "
    "nacional, al mes de junio de cada año.\n\nLa Autoridad Administrativa del Trabajo, cuando "
    "las conclusiones así lo indicaran, elevará al Poder Ejecutivo para su consideración y "
    "resolución, antes del 30 de junio de cada año, la propuesta de reajuste de salario mínimo, "
    "acompañada de las memorias correspondientes.\n\nEn los casos de profunda alteración de las "
    "condiciones macroeconómicas y financieras o de elevadas tasas de inflación, el Consejo "
    "Nacional de Salarios Mínimos podrá reunirse en un período distinto al indicado anteriormente, "
    "y considerará para la fijación del porcentaje del reajuste los informes sobre inflación y "
    "situación económica y financiera de los organismos competentes, así como las perspectivas "
    "o proyecciones inflacionarias y económicas respectivas."
)

ARTICLE_412_CURRENT = (
    "El derecho de asociación en sindicatos de los trabajadores del sector público, salvo las "
    "excepciones constitucionales previstas, se regirá por el Libro III, Título I, Capítulos I, "
    "II, III, IV, V y VI, y el Título Cuarto, Capítulo I del mismo Libro de este Código, hasta "
    "tanto una ley especial regule la materia."
)

ARTICLE_412_BIS = (
    "A partir de la vigencia del presente Código quedan derogadas las leyes contrarias y, "
    "especialmente, la Ley N.º 729 del 31 de diciembre de 1961; la Ley N.º 388 del 22 de "
    "diciembre de 1972; la Ley N.º 506 del 27 de diciembre de 1974; la Resolución N.º 521 del "
    "8 de agosto de 1982; la Ley N.º 1172 del 13 de diciembre de 1985; y la Ley N.º 49 del "
    "13 de octubre de 1992."
)

ARTICLE_62_J = (
    "Conceder, a solicitud del trabajador, tres días de licencia con goce de salario para "
    "contraer matrimonio, tres días en caso de nacimiento de un hijo/a y tres días en caso "
    "de fallecimiento del cónyuge, hijos, padres, abuelos o hermanos;"
)


@dataclass
class ParsedArticle:
    number: str
    book_code: str
    book_name: str
    title_code: str
    title_name: str
    chapter_code: str
    chapter_name: str
    body: str
    content_status: str = "Texto base"
    amendment_note: str = ""
    source_name: str = "BACN"
    source_url: str = BASE_OFFICIAL_URL

    @property
    def category(self) -> str:
        value = "|".join(filter(None, (self.book_code, self.title_code, self.chapter_code)))
        return value[:120]

    @property
    def heading(self) -> str:
        value = "|".join((self.book_name, self.title_name, self.chapter_name))
        return value[:220]


@dataclass
class SyncResult:
    article_count: int
    modified_count: int
    repealed_count: int
    source_used: str
    synced_at: date


class _VisibleTextParser(HTMLParser):
    BLOCK_TAGS = {"br", "p", "div", "li", "h1", "h2", "h3", "h4", "tr", "section", "article"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag.lower() in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def normalize_search(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in normalized if not unicodedata.combining(char)).lower()


def fetch_visible_text(url: str, timeout: int = 25) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; DigitLaboral/1.5; +https://digitlaboral.com.py)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "es-PY,es;q=0.9",
        },
    )
    with urlopen(request, timeout=timeout) as response:  # nosec B310 - fixed HTTPS sources
        raw = response.read(8 * 1024 * 1024)
        charset = response.headers.get_content_charset() or "utf-8"
    decoded = raw.decode(charset, errors="replace")
    parser = _VisibleTextParser()
    parser.feed(decoded)
    text = html.unescape("".join(parser.parts)).replace("\xa0", " ")
    lines = [re.sub(r"[\t ]+", " ", line).strip() for line in text.replace("\r", "\n").split("\n")]
    return "\n".join(line for line in lines if line)


def _first_available(urls: Iterable[str]) -> tuple[str, str]:
    errors: list[str] = []
    for url in urls:
        try:
            text = fetch_visible_text(url)
            if len(text) > 20_000 and "Artículo" in text:
                return text, url
            errors.append(f"{url}: contenido insuficiente")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError("No fue posible descargar el Código del Trabajo. " + " | ".join(errors))


def _roman_label(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().upper())


def _join_body(lines: list[str]) -> str:
    paragraphs: list[str] = []
    current = ""
    item_pattern = re.compile(r"^(?:[a-zñ]\)|\d+\)|[-–—])\s*", re.IGNORECASE)
    for line in lines:
        clean = re.sub(r"\s+", " ", line).strip().strip('“”"')
        if not clean:
            continue
        if item_pattern.match(clean):
            if current:
                paragraphs.append(current.strip())
            current = clean
        elif current:
            current += " " + clean
        else:
            current = clean
    if current:
        paragraphs.append(current.strip())
    return "\n".join(paragraphs).strip()


def parse_code_articles(text: str) -> list[ParsedArticle]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    start = next((i for i, line in enumerate(lines) if re.search(r"LEY\s+N[°º(]?\s*213", line, re.I)), 0)
    lines = lines[start:]

    article_re = re.compile(
        r"^(?:Artículo|Art\.)\s*(\d+)\s*(?:[°ºo|])?\s*(?:\(?(Bis)\)?)?\s*[.\-:|]*\s*(.*)$",
        re.IGNORECASE,
    )
    heading_re = re.compile(r"^(LIBRO|T[IÍ]TULO|CAP[IÍ]TULO)\s+(.+)$", re.IGNORECASE)

    book_code = book_name = title_code = title_name = chapter_code = chapter_name = ""
    pending_heading: tuple[str, str] | None = None
    current_number = ""
    current_body: list[str] = []
    articles: list[ParsedArticle] = []

    def flush() -> None:
        nonlocal current_number, current_body
        if not current_number:
            return
        body = _join_body(current_body)
        if body:
            articles.append(
                ParsedArticle(
                    number=current_number,
                    book_code=book_code,
                    book_name=book_name,
                    title_code=title_code,
                    title_name=title_name,
                    chapter_code=chapter_code,
                    chapter_name=chapter_name,
                    body=body,
                )
            )
        current_number = ""
        current_body = []

    for line in lines:
        heading_match = heading_re.match(line)
        article_match = article_re.match(line)
        if heading_match:
            flush()
            kind = normalize_search(heading_match.group(1))
            code = f"{heading_match.group(1).upper()} {_roman_label(heading_match.group(2))}"
            pending_heading = (kind, code)
            continue
        if pending_heading and not article_match:
            kind, code = pending_heading
            if kind == "libro":
                book_code, book_name = code, line
                title_code = title_name = chapter_code = chapter_name = ""
            elif kind == "titulo":
                title_code, title_name = code, line
                chapter_code = chapter_name = ""
            else:
                chapter_code, chapter_name = code, line
            pending_heading = None
            continue
        if article_match:
            flush()
            number = article_match.group(1)
            if article_match.group(2):
                number += " Bis"
            current_number = number
            first = article_match.group(3).strip()
            current_body = [first] if first else []
            continue
        if current_number:
            if re.match(r"^(?:Justia|Find a Lawyer|Ask a Lawyer|Research the Law)$", line, re.I):
                continue
            current_body.append(line)
    flush()

    unique: dict[str, ParsedArticle] = {}
    for article in articles:
        unique.setdefault(article.number, article)
    result = sorted(unique.values(), key=lambda item: article_sort_key(item.number))
    if len([item for item in result if item.number.isdigit()]) < 400:
        raise RuntimeError(f"La fuente devolvió solamente {len(result)} artículos; se esperaba el Código completo.")
    return result


def article_sort_key(number: str) -> tuple[int, int, str]:
    match = re.match(r"(\d+)(.*)", number or "")
    if not match:
        return (99999, 9, number)
    suffix = normalize_search(match.group(2))
    return (int(match.group(1)), 1 if "bis" in suffix else 0, suffix)


def _extract_replacement_blocks(text: str, allowed_numbers: set[int]) -> dict[int, str]:
    normalized = text.replace("\r", "\n")
    marker = re.search(r"quedan\s+redactados\s+como\s+sigue", normalized, re.I)
    if marker:
        normalized = normalized[marker.end():]
    end = re.search(r"\nArtículo\s+2[°ºo|]?\s*[.\-]+\s*Der[oó]ganse", normalized, re.I)
    if end:
        normalized = normalized[:end.start()]
    match_re = re.compile(
        r"(?im)^[\"“”]?\s*Art(?:ículo)?\.?\s*(\d+)\s*(?:[°ºo|])?\s*(?:\(?(Bis)\)?)?\s*([^\n]*?)\s*[.\-:]+\s*(.*)$"
    )
    matches = list(match_re.finditer(normalized))
    replacements: dict[int, str] = {}
    for index, match in enumerate(matches):
        number = int(match.group(1))
        if number not in allowed_numbers:
            continue
        tail = (match.group(3) or "").strip()
        if "inc" in normalize_search(tail):
            continue
        end_pos = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        body = match.group(4) + "\n" + normalized[match.end():end_pos]
        body = _join_body(body.splitlines())
        body = re.sub(r"\nArtículo\s+[234][°ºo|]?.*$", "", body, flags=re.I | re.S).strip(' “”"')
        if len(body) > 20:
            replacements[number] = body
    return replacements


def _replace_inciso(body: str, letter: str, new_text: str) -> str:
    pattern = re.compile(
        rf"(?is)(^|\n|\s){re.escape(letter)}\)\s*.*?(?=(?:\n|\s)[a-zñ]\)\s|$)"
    )
    replacement = f"\n{letter}) {new_text.strip()}"
    if pattern.search(body):
        return pattern.sub(replacement, body, count=1).strip()
    return (body.rstrip() + replacement).strip()


def _article_map(articles: list[ParsedArticle]) -> dict[str, ParsedArticle]:
    return {article.number: article for article in articles}


def apply_amendments(articles: list[ParsedArticle], law_496_text: str | None = None, law_1416_text: str | None = None) -> None:
    mapped = _article_map(articles)

    if law_496_text:
        replacements = _extract_replacement_blocks(law_496_text, MODIFIED_496)
        for number, body in replacements.items():
            article = mapped.get(str(number))
            if not article or number in PARTIAL_496:
                continue
            article.body = body
            article.content_status = "Vigente · modificado"
            article.amendment_note = "Texto modificado por la Ley N.º 496/1995."
            article.source_url = LAW_496_OFFICIAL_URL
        # La Ley 496 contiene reformas parciales por inciso. Se conservan el artículo
        # completo y una advertencia cuando no es posible reconstruir con seguridad
        # todo el inciso desde la fuente remota.
        for number, letters in PARTIAL_496.items():
            article = mapped.get(str(number))
            if article:
                article.content_status = "Vigente · modificación parcial"
                article.amendment_note = (
                    f"Modificación parcial por Ley N.º 496/1995, incisos {', '.join(letters)}. "
                    "Verificar el texto consolidado en la fuente oficial."
                )
                article.source_url = LAW_496_OFFICIAL_URL

    for number in (287, 325):
        article = mapped.get(str(number))
        if article:
            article.content_status = "Derogado"
            article.amendment_note = "Derogado por el artículo 2 de la Ley N.º 496/1995."
            article.source_url = LAW_496_OFFICIAL_URL

    article_412 = mapped.get("412")
    if article_412:
        article_412.body = ARTICLE_412_CURRENT
        article_412.content_status = "Vigente · modificado"
        article_412.amendment_note = "Texto modificado por la Ley N.º 496/1995."
        article_412.source_url = LAW_496_OFFICIAL_URL
    if "412 Bis" not in mapped:
        reference = article_412 or articles[-1]
        article_412_bis = ParsedArticle(
            number="412 Bis",
            book_code=reference.book_code,
            book_name=reference.book_name,
            title_code=reference.title_code,
            title_name=reference.title_name,
            chapter_code=reference.chapter_code,
            chapter_name="Disposición final",
            body=ARTICLE_412_BIS,
            content_status="Vigente · incorporado",
            amendment_note="Artículo incorporado por la Ley N.º 496/1995.",
            source_url=LAW_496_OFFICIAL_URL,
        )
        articles.append(article_412_bis)
        mapped["412 Bis"] = article_412_bis

    article_9 = mapped.get("9")
    if article_9:
        article_9.body = ARTICLE_9_CURRENT
        article_9.content_status = "Vigente · modificado"
        article_9.amendment_note = "Texto vigente según Ley N.º 6470/2020."
        article_9.source_url = LAW_6470_OFFICIAL_URL

    article_62 = mapped.get("62")
    if article_62:
        article_62.body = _replace_inciso(article_62.body, "j", ARTICLE_62_J)
        article_62.content_status = "Vigente · modificación parcial"
        article_62.amendment_note = "Inciso j) modificado por Ley N.º 3384/2007."
        article_62.source_url = LAW_3384_OFFICIAL_URL

    article_255 = mapped.get("255")
    if article_255:
        article_255.body = ARTICLE_255_CURRENT
        article_255.content_status = "Vigente · modificado"
        article_255.amendment_note = "Texto vigente según Ley N.º 5764/2016."
        article_255.source_url = LAW_5764_OFFICIAL_URL

    article_256 = mapped.get("256")
    if article_256:
        article_256.content_status = "Derogado"
        article_256.amendment_note = "Derogado por el artículo 3 de la Ley N.º 5764/2016."
        article_256.source_url = LAW_5764_OFFICIAL_URL

    article_44 = mapped.get("44")
    if article_44:
        article_44.content_status = "Vigente · derogación parcial"
        article_44.amendment_note = "El inciso a) fue derogado por la Ley N.º 5407/2015 de trabajo doméstico."
        article_44.source_url = LAW_5407_OFFICIAL_URL

    for number in range(148, 157):
        article = mapped.get(str(number))
        if article:
            article.content_status = "Derogado"
            article.amendment_note = "Derogado por la Ley N.º 5407/2015 de trabajo doméstico."
            article.source_url = LAW_5407_OFFICIAL_URL

    if law_1416_text:
        replacements = _extract_replacement_blocks(law_1416_text, {385})
        if 385 in replacements and "385" in mapped:
            mapped["385"].body = replacements[385]
    article_385 = mapped.get("385")
    if article_385:
        article_385.content_status = "Vigente · modificado"
        article_385.amendment_note = "Modificado por Ley N.º 1416/1999."
        article_385.source_url = LAW_1416_OFFICIAL_URL


def sync_labor_code(db: Session, *, force: bool = False) -> SyncResult:
    existing_count = db.scalar(select(func.count(LaborArticle.id))) or 0
    if existing_count >= 400 and not force:
        modified = db.scalar(
            select(func.count(LaborArticle.id)).where(LaborArticle.content_status.ilike("%modific%"))
        ) or 0
        repealed = db.scalar(
            select(func.count(LaborArticle.id)).where(LaborArticle.content_status.ilike("%derogad%"))
        ) or 0
        return SyncResult(existing_count, modified, repealed, "Base existente", date.today())

    base_text, source_used = _first_available((BASE_OFFICIAL_URL, BASE_JUSTIA_URL))
    parsed = parse_code_articles(base_text)

    law_496_text = None
    law_1416_text = None
    try:
        law_496_text, _ = _first_available((LAW_496_OFFICIAL_URL, LAW_496_JUSTIA_URL))
    except RuntimeError:
        pass
    try:
        law_1416_text, _ = _first_available((LAW_1416_OFFICIAL_URL, LAW_1416_JUSTIA_URL))
    except RuntimeError:
        pass

    apply_amendments(parsed, law_496_text=law_496_text, law_1416_text=law_1416_text)
    parsed.sort(key=lambda item: article_sort_key(item.number))

    db.execute(delete(LaborArticle))
    for item in parsed:
        db.add(
            LaborArticle(
                law_number="Ley N.º 213/1993",
                article_number=item.number,
                heading=item.heading,
                category=item.category,
                body=item.body,
                content_status=item.content_status,
                amendment_note=item.amendment_note,
                source_name="BACN" if "bacn.gov.py" in item.source_url else "Fuente de respaldo",
                source_url=item.source_url,
                reviewed_at=date.today(),
            )
        )
    db.commit()

    modified_count = sum("modific" in normalize_search(item.content_status) for item in parsed)
    repealed_count = sum("derogad" in normalize_search(item.content_status) for item in parsed)
    return SyncResult(len(parsed), modified_count, repealed_count, source_used, date.today())
