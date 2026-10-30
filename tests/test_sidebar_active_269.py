from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_sidebar_states_are_owned_by_the_consolidated_theme():
    base = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    css = (ROOT / "app" / "static" / "theme-261.css").read_text(encoding="utf-8")
    for obsolete in (
        "sidebar-contrast-265.css",
        "sidebar-active-269.css",
        "home-label-fix-2613.css",
        "sidebar-brand-transparent-2617.css",
        "sidebar-brand-theme-2624.css",
    ):
        assert obsolete not in base
    assert '.workspace-home-link.active:not(:hover)' in css
    assert ".workspace-submenu .workspace-nav-link.active," in css
    assert ".workspace-submenu .workspace-nav-link[aria-current=\"page\"]{" in css
    assert ".workspace-submenu .workspace-nav-link.active:hover," in css
    assert "-webkit-text-fill-color:#0B2D78!important" in css
    assert ".workspace-submenu .workspace-nav-link.active:not(:hover)" not in css
    assert 'color:#0B2D78!important' in css
    assert 'background:#FFFFFF!important' in css
    assert 'box-shadow:inset 3px 0 #1D4ED8!important' in css


def test_home_label_rule_is_inline_and_uses_the_primary_brand_color():
    base = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    assert 'class="workspace-home-label">Inicio</span>' in base
    selector = 'body.app-body #modernMobileNav a.workspace-home-link[href="/app"].active:not(:hover)'
    start = base.find(selector)
    assert start >= 0
    block = base[start:base.find("}", start) + 1]
    assert "color:#1D4ED8!important" in block
    assert "-webkit-text-fill-color:#1D4ED8!important" in block
    assert "opacity:1!important" in block
    assert "visibility:visible!important" in block


def test_home_context_state_does_not_override_the_active_or_hovered_sidebar_item():
    base = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    assert "'home-in-section-context' if active_path.startswith('/app/') else ''" in base
    selector = 'a.workspace-home-link[href="/app"].home-in-section-context:not(:hover)'
    start = base.find(selector)
    assert start >= 0
    block = base[start:base.find("}", start) + 1]
    assert "> span.workspace-home-label" in block
    assert "color:#1D4ED8!important" in block
    assert "-webkit-text-fill-color:#1D4ED8!important" in block
    assert ":hover)" in block


def test_active_submodule_keeps_dark_text_when_hovered():
    css = (ROOT / "app" / "static" / "theme-261.css").read_text(encoding="utf-8")
    selected_rule = css[css.index(".app-body .workspace-sidebar .workspace-submenu .workspace-nav-link.active,"): ]
    selected_rule = selected_rule[:selected_rule.index("}")]
    assert "background:#FFFFFF!important" in selected_rule
    assert "color:#0B2D78!important" in selected_rule
    assert "-webkit-text-fill-color:#0B2D78!important" in selected_rule

    hover_rule_start = css.index(".app-body .workspace-sidebar .workspace-submenu .workspace-nav-link.active:hover,")
    hover_rule = css[hover_rule_start:css.index("}", hover_rule_start) + 1]
    assert "background:#FFFFFF!important" in hover_rule
    assert "color:#0B2D78!important" in hover_rule
    assert "-webkit-text-fill-color:#0B2D78!important" in hover_rule
