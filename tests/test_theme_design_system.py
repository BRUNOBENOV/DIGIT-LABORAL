from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_corporate_theme_loads_after_workspace_foundation_styles():
    base = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    links = [
        "app.css",
        "modern.css",
        "brand-identity.css",
        "certificate-premium.css",
        "theme-261.css",
        "ui-system-264.css",
    ]
    positions = [base.find(name) for name in links]
    assert all(position >= 0 for position in positions)
    assert positions == sorted(positions)
    assert 'content="#05256D"' in base


def test_blue_theme_defines_the_corporate_palette_and_accessible_focus():
    css = (ROOT / "app" / "static" / "theme-261.css").read_text(encoding="utf-8")
    for token in (
        "--navy:#05256D",
        "--blue:#0B2D78",
        "--bright:#1D4ED8",
        "--soft:#F2F5FA",
        "--ink:#111827",
        "--muted:#6B7280",
        "--input-bg:#FFFFFF",
        "background:#05256D!important",
        "background:#1D4ED8!important",
        ":focus-visible",
        "prefers-reduced-motion:reduce",
    ):
        assert token in css
    assert "body.app-body" in css
    assert ".app-body .dl" in css
    assert "--accent:#0B2D78" in css
