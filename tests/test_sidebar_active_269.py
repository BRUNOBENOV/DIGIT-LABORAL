from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_sidebar_active_blue_styles_load_after_existing_theme_and_brand():
    base = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    order = [
        base.find("brand-identity.css"),
        base.find("sidebar-contrast-265.css"),
        base.find("brand-adjustments-267.css"),
        base.find("sidebar-active-269.css"),
    ]
    assert all(position >= 0 for position in order)
    assert order == sorted(order)
    assert "?v=20261028d" in base


def test_only_active_non_hovered_sidebar_links_change_to_white_and_blue():
    css = (ROOT / "app" / "static" / "sidebar-active-269.css").read_text(encoding="utf-8")
    assert ".workspace-home-link.active:not(:hover)" in css
    assert ".workspace-submenu .workspace-nav-link.active:not(:hover)" in css
    assert '.workspace-nav-link[aria-current="page"]:not(:hover)' in css
    assert "color:#2563EB!important" in css
    assert "background:#FFFFFF!important" in css
    assert "box-shadow:inset 4px 0 #2563EB!important" in css
    assert ":hover{" not in css
    assert ".workspace-nav-link:hover" not in css
    assert ".workspace-home-link:hover" not in css


def test_home_fix_targets_only_the_active_label_and_not_hover_or_inactive_states():
    css = (ROOT / "app" / "static" / "sidebar-active-269.css").read_text(encoding="utf-8")
    home_rule = (
        '.app-body .workspace-sidebar a.workspace-home-link[href="/app"].active:not(:hover) '
        '> span:not(.workspace-home-symbol)'
    )
    assert home_rule in css
    assert "color:#2563EB!important" in css
    assert ".workspace-home-link.active:not(:hover){\n  color:#2563EB" not in css
    assert ".workspace-home-link:hover" not in css
    assert ".workspace-home-link:not(.active)" not in css



def test_home_active_label_forces_visible_blue_text_only_without_hover():
    css = (ROOT / "app" / "static" / "sidebar-active-269.css").read_text(encoding="utf-8")
    selector = (
        ".workspace-home-link.active:not(:hover) "
        "> span:not(.workspace-home-symbol)"
    )
    start = css.index(selector)
    block = css[start:css.index("}", start) + 1]
    assert "color:#2563EB!important" in block
    assert "-webkit-text-fill-color:#2563EB!important" in block
    assert "opacity:1!important" in block
    assert "visibility:visible!important" in block
    assert "filter:none!important" in block
    assert ".workspace-home-link:hover" not in css


def test_home_text_visibility_rule_does_not_target_admin_home_link():
    css = (ROOT / "app" / "static" / "sidebar-active-269.css").read_text(encoding="utf-8")
    assert 'a.workspace-home-link[href="/app"].active:not(:hover)' in css
    assert 'a.workspace-home-link[href="/admin"].active:not(:hover)' not in css
