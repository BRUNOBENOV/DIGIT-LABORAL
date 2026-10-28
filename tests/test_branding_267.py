from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_home_active_label_is_blue_without_changing_hover():
    css = (ROOT / "app" / "static" / "brand-adjustments-267.css").read_text(encoding="utf-8")
    assert ".workspace-home-link.active:not(:hover)" in css
    assert "color:#0B2D78!important" in css
    # Do not add a new hover rule for the Home link: the existing interaction is intentional.
    assert ".workspace-home-link:hover" not in css


def test_new_logo_is_used_across_app_and_auth_screens():
    base = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    login = (ROOT / "app" / "templates" / "login.html").read_text(encoding="utf-8")
    reset = (ROOT / "app" / "templates" / "reset_password.html").read_text(encoding="utf-8")
    forgot = (ROOT / "app" / "templates" / "forgot_password.html").read_text(encoding="utf-8")
    two_factor = (ROOT / "app" / "templates" / "login_2fa.html").read_text(encoding="utf-8")
    for text in (base, login, reset, forgot, two_factor):
        assert "digit-laboral-logo-267.webp?v=20261028a" in text
    assert "brand-adjustments-267.css" in base
    assert "digit-laboral-mark.svg?v=20261024a" not in base
