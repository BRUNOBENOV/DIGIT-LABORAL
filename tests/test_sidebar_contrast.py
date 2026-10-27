from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_sidebar_contrast_styles_load_after_the_shared_ui_layer():
    base = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    links = [
        "theme-261.css",
        "ui-system-264.css",
        "sidebar-contrast-265.css",
    ]
    positions = [base.find(name) for name in links]
    assert all(position >= 0 for position in positions)
    assert positions == sorted(positions)
    assert 'path=\'static\', path=\'sidebar-contrast-265.css\'' not in base
    assert "?v=20261027e" in base


def test_sidebar_subitems_have_high_contrast_normal_hover_and_active_states():
    css = (ROOT / "app" / "static" / "sidebar-contrast-265.css").read_text(encoding="utf-8")
    for token in (
        ".workspace-submenu .workspace-nav-link",
        "color:#F1F5F9!important",
        "background:#213D59!important",
        ".workspace-nav-link.active",
        "background:#2563EB!important",
        "color:#FFFFFF!important",
        "box-shadow:inset 4px 0 #BFDBFE!important",
        ".workspace-group-chevron",
        "outline:3px solid #BFDBFE!important",
        "@media(max-width:860px)",
    ):
        assert token in css
