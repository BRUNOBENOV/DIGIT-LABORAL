from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_corporate_sidebar_uses_the_consolidated_navy_surface():
    base = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    css = (ROOT / "app" / "static" / "theme-261.css").read_text(encoding="utf-8")
    assert "sidebar-contrast-265.css" not in base
    assert ".app-body .modern-mobile-nav.workspace-sidebar{" in css
    assert "background:#05256D!important;" in css
    assert "color:#F8FAFC!important;" in css
    assert ".workspace-sidebar-label" in css
    assert "color:#C9D8FF!important" in css


def test_sidebar_normal_hover_and_active_states_have_sufficient_visual_separation():
    css = (ROOT / "app" / "static" / "theme-261.css").read_text(encoding="utf-8")
    assert ".workspace-submenu .workspace-nav-link" in css
    assert "color:#EDF2FF!important" in css
    assert "background:#143B88!important" in css
    assert ".workspace-nav-link.active:not(:hover)," in css
    assert ".workspace-nav-link[aria-current=\"page\"]:not(:hover)" in css
    assert "-webkit-text-fill-color:#0B2D78!important" in css
    assert ".workspace-nav-link.active:hover," in css
    assert "-webkit-text-fill-color:#FFFFFF!important" in css
    assert "background:#FFFFFF!important" in css
    assert "background:#143B88!important" in css
    assert "transition:background-color .16s ease,color .16s ease" in css
    assert "box-shadow:inset 3px 0 #1D4ED8!important" in css


def test_mobile_sidebar_keeps_the_same_brand_color():
    css = (ROOT / "app" / "static" / "theme-261.css").read_text(encoding="utf-8")
    assert "@media(max-width:860px)" in css
    mobile = css[css.index("@media(max-width:860px)"):]
    assert ".app-body .modern-mobile-nav.workspace-sidebar{background:#05256D!important;" in mobile
