from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from app.main import smart_normalize_logo


def test_smart_normalize_logo_outputs_balanced_png():
    image = Image.new('RGBA', (1800, 400), (255, 255, 255, 0))
    for x in range(250, 1550):
        for y in range(120, 280):
            image.putpixel((x, y), (20, 60, 140, 255))
    raw = io.BytesIO()
    image.save(raw, format='PNG')
    out, content_type = smart_normalize_logo(raw.getvalue())
    assert content_type == 'image/png'
    result = Image.open(io.BytesIO(out))
    assert result.size == (1100, 360)


def test_templates_include_improved_logo_and_legal_layout():
    root = Path(__file__).resolve().parents[1] / 'app' / 'templates'
    companies = (root / 'companies.html').read_text(encoding='utf-8')
    detail = (root / 'company_detail.html').read_text(encoding='utf-8')
    legal = (root / 'labor_code_v17.html').read_text(encoding='utf-8')
    assert 'company-logo-card-frame' in companies
    assert 'ajuste inteligente automático' in detail
    assert 'Ver Ley 213/93 del Código del Trabajo' in legal
    assert 'legal-reference-sheet' in legal
    assert 'Artículos visibles' in legal
