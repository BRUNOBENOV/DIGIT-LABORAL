from __future__ import annotations

from pathlib import Path

from app.labor_code_sync import article_sort_key, parse_code_articles


def test_branding_modal_is_inside_content_block():
    template = Path(__file__).resolve().parents[1] / "app" / "templates" / "company_detail.html"
    text = template.read_text(encoding="utf-8")
    assert text.index('{% block content %}') < text.index('id="brandingModal"')
    assert 'id="companyLogoInput"' in text
    assert 'data-logo-dropzone' in text


def test_labor_code_template_has_structure_and_sources():
    root = Path(__file__).resolve().parents[1]
    template = (root / "app" / "templates" / "labor_code_v17.html").read_text(encoding="utf-8")
    base = (root / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    assert "ÍNDICE GENERAL" in template
    assert "Libro" in template and "Título" in template and "Capítulo" in template
    assert "Fuente jurídica" in template
    assert "v17.css" in base and "v17.js" in base


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
