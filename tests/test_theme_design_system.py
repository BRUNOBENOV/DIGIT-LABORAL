from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_global_blue_theme_is_loaded_after_existing_workspace_styles():
    base = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    links = [
        "app.css",
        "modern.css",
        "brand-identity.css",
        "certificate-premium.css",
        "theme-261.css",
    ]
    positions = [base.find(name) for name in links]
    assert all(position >= 0 for position in positions)
    assert positions == sorted(positions)
    assert 'content="#0D1B2A"' in base


def test_blue_theme_defines_requested_palette_and_accessible_focus():
    css = (ROOT / "app" / "static" / "theme-261.css").read_text(encoding="utf-8")
    for token in (
        "--navy:#0D1B2A",
        "--blue:#1E40AF",
        "--bright:#2563EB",
        "--soft:#F9FAFB",
        "--ink:#111827",
        "--muted:#6B7280",
        "--input-bg:#FFFFFF",
        "background:#0D1B2A!important",
        "background:#2563EB!important",
        "outline:3px solid rgba(37,99,235,.45)!important",
        "prefers-reduced-motion:reduce",
    ):
        assert token in css
    assert "body.app-body" in css
