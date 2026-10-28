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
    assert 'sidebar-contrast-265.css' in base
    assert "?v=20261028f" in base


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


def test_home_light_text_color_rule_excludes_active_and_hover_states():
    css = (ROOT / "app" / "static" / "sidebar-contrast-265.css").read_text(encoding="utf-8")
    base_rule = ".app-body .workspace-sidebar .workspace-home-link{"
    assert base_rule in css
    assert "font-size:.91rem!important;" in css
    assert "font-weight:700!important;" in css
    assert ".workspace-home-link:not(.active):not(:hover)" in css
    assert ".app-body .workspace-sidebar .workspace-home-link{\n  color:#F1F5F9!important;" not in css
    active_fix = (ROOT / "app" / "static" / "home-label-fix-2613.css").read_text(encoding="utf-8")
    assert 'a.workspace-home-link[href="/app"].active:not(:hover)' in active_fix
    assert "color: #2563EB !important;" in active_fix
