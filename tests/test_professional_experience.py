from pathlib import Path


def test_professional_experience_assets_are_loaded():
    root = Path(__file__).resolve().parents[1]
    base = (root / "app/templates/base.html").read_text(encoding="utf-8")
    css = root / "app/static/experience.css"
    js = root / "app/static/experience.js"

    assert css.is_file()
    assert js.is_file()
    assert "path='experience.css'" in base
    assert "path='experience.js'" in base


def test_professional_list_filters_are_explicitly_local():
    root = Path(__file__).resolve().parents[1]
    script = (root / "app/static/experience.js").read_text(encoding="utf-8")

    assert 'installCardFilter(".request-grid"' in script
    assert 'installCardFilter(".notification-list"' in script
    assert "experience-filter-item-hidden" in script or "experience-filter-item-hidden" in (root / "app/static/experience.css").read_text(encoding="utf-8")
