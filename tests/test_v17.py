from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

from app.labor_code_sync import article_sort_key, parse_code_articles


def test_branding_modal_is_inside_content_block():
    template = Path(__file__).resolve().parents[1] / "app" / "templates" / "company_detail.html"
    text = template.read_text(encoding="utf-8")
    assert text.index('{% block content %}') < text.index('id="brandingModal"')
    assert 'id="companyLogoInput"' in text
    assert 'data-logo-dropzone' in text


def test_labor_code_template_has_structure_and_sources():
    templates = Path(__file__).resolve().parents[1] / "app" / "templates"
    env = Environment(autoescape=True, loader=ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}"}),
        FileSystemLoader(templates),
    ]))
    env.filters["fecha"] = str
    articles = [
        {"number": number, "book_code": "LIBRO PRIMERO", "title_code": "TITULO PRIMERO",
         "chapter_code": code, "heading": name, "body": "Texto del artículo", "source_url": "https://example.org/ley"}
        for number, code, name in [("1", "CAPITULO I", "Objeto"), ("2", "CAPITULO I", "Objeto"),
                                   ("3 Bis", "CAPITULO II", "Garantías")]
    ]
    html = env.get_template("labor_code_v17.html").render(
        user={"role": "contador"}, csrf_token="test", q="jornada & descanso",
        articles=articles, page=1, pages=2, result_start=1, result_end=3, total=4,
        article_query="", selected_book="", selected_title="", selected_chapter="", status_filter="modificado",
        stats={"books": 1, "total": 4, "modified": 4, "repealed": 0},
        source_registry=[{"law": "Ley N.º 213/1993", "url": "https://example.org/ley"}],
    )
    soup = BeautifulSoup(html, "html.parser")
    assert [heading.get_text(strip=True) for heading in soup.select("h1")] == ["Código del Trabajo"]
    assert len(soup.select(".legal-outline")) == 1
    assert [heading.get_text(strip=True) for heading in soup.select(".legal-chapter-head h3")] == ["Objeto", "Garantías"]
    assert soup.select_one("#articulo-3-Bis h4").get_text(strip=True) == "Artículo 3 Bis"
    assert soup.select_one(".legal-official-link")["href"] == "https://example.org/ley"
    assert soup.select_one("#articulo-1 footer a").get_text(strip=True).startswith("Fuente jurídica")
    assert soup.select_one('form[action="/app/labor-code/sync"] input[name="csrf_token"]')["value"] == "test"
    next_page = urlsplit(soup.select_one('a[rel="next"]')["href"])
    assert next_page.fragment == "resultados"
    assert parse_qs(next_page.query) == {"q": ["jornada & descanso"], "status_filter": ["modificado"], "page": ["2"]}


def test_parser_orders_complete_synthetic_code():
    parts = ["LEY N° 213", "LIBRO PRIMERO", "Disposiciones", "TITULO PRIMERO", "General", "CAPITULO I", "Objeto"]
    for number in range(1, 413):
        parts.append(f"Artículo {number}°.- Texto legal del artículo {number}.")
    parsed = parse_code_articles("\n".join(parts))
    assert len(parsed) == 412
    assert parsed[0].number == "1"
    assert parsed[-1].number == "412"
    assert article_sort_key("9") < article_sort_key("9 Bis") < article_sort_key("10")


def test_amendments_add_final_article_412_bis():
    from app.labor_code_sync import ParsedArticle, apply_amendments
    articles = [
        ParsedArticle(str(number), "LIBRO QUINTO", "Disposiciones", "TÍTULO", "Final", "CAPÍTULO", "Final", f"Texto {number}")
        for number in range(1, 413)
    ]
    apply_amendments(articles)
    mapped = {item.number: item for item in articles}
    assert "412 Bis" in mapped
    assert "incorporado" in mapped["412 Bis"].content_status.lower()
    assert "modificado" in mapped["412"].content_status.lower()
