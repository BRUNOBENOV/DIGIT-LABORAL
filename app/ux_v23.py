from __future__ import annotations

import io
import logging
import re
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .main import (
    app,
    company_allowed,
    get_db,
    get_or_create_branding,
    require_roles,
    smart_normalize_logo,
    write_audit,
)
from .models import CompanyBranding, User
from .logo_presentation import prepare_company_logo

logger = logging.getLogger("digit.logo_upload")
LOGO_UPLOAD_LIMIT = max(settings.max_logo_size, 8 * 1024 * 1024)
ALLOWED_LOGO_FORMATS = {"PNG", "JPEG", "WEBP"}


def _remove_route(path: str, method: str) -> None:
    method = method.upper()
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == path
            and method in (getattr(route, "methods", None) or set())
        )
    ]


def _logo_error(company_id: int, message: str) -> RedirectResponse:
    return RedirectResponse(
        f"/app/companies/{company_id}?logo_error={quote(message)}&open=brandingModal",
        status_code=303,
    )


def _validated_logo(content: bytes) -> tuple[bytes, str]:
    try:
        with Image.open(io.BytesIO(content)) as opened:
            source_format = (opened.format or "").upper()
            opened.verify()
    except Exception as exc:  # Pillow deliberately supplies format-specific exceptions.
        raise ValueError("El archivo no es una imagen válida.") from exc
    if source_format not in ALLOWED_LOGO_FORMATS:
        raise ValueError("Usá un logo PNG, JPG/JPEG o WEBP.")
    try:
        return smart_normalize_logo(content)
    except Exception as exc:
        raise ValueError("No se pudo preparar el logo. Probá con otra imagen.") from exc


_remove_route("/app/companies/{company_id}/logo", "GET")
_remove_route("/app/companies/{company_id}/logo", "POST")
_remove_route("/app/companies/{company_id}/branding", "POST")


@app.get("/app/companies/{company_id}/logo")
def company_logo_v23(
    company_id: int,
    user: User = Depends(require_roles("administrador", "contador", "auxiliar", "empresa", "abogado")),
    db: Session = Depends(get_db),
):
    company = company_allowed(db, user, company_id)
    branding = db.scalar(select(CompanyBranding).where(CompanyBranding.company_id == company.id))
    if not branding or not branding.logo_bytes:
        return Response(status_code=404)
    return Response(
        content=branding.logo_bytes,
        media_type=branding.logo_content_type or "image/png",
        headers={"Cache-Control": "private, no-cache, no-store, must-revalidate"},
    )


@app.get("/app/companies/{company_id}/logo/print")
def company_logo_print_v23(
    company_id: int,
    user: User = Depends(require_roles("administrador", "contador", "auxiliar", "empresa", "abogado")),
    db: Session = Depends(get_db),
):
    """Serve the same presentation-ready logo used by Word/PDF for print previews."""
    company = company_allowed(db, user, company_id)
    branding = db.scalar(select(CompanyBranding).where(CompanyBranding.company_id == company.id))
    if not branding or not branding.logo_bytes:
        return Response(status_code=404)
    prepared = prepare_company_logo(
        branding.logo_bytes,
        fit=branding.logo_fit,
        scale=branding.logo_scale,
        alignment=branding.logo_alignment,
        background=branding.logo_background,
    )
    if not prepared:
        return Response(status_code=404)
    return Response(
        content=prepared,
        media_type="image/png",
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post("/app/companies/{company_id}/logo")
async def upload_company_logo_v23(
    company_id: int,
    logo: UploadFile = File(...),
    user: User = Depends(require_roles("administrador", "contador", "empresa")),
    db: Session = Depends(get_db),
):
    company = company_allowed(db, user, company_id)
    if not logo.filename:
        return _logo_error(company.id, "Seleccioná una imagen para continuar.")

    content = await logo.read(LOGO_UPLOAD_LIMIT + 1)
    if not content:
        return _logo_error(company.id, "El archivo seleccionado está vacío.")
    if len(content) > LOGO_UPLOAD_LIMIT:
        return _logo_error(company.id, f"El logo supera el máximo permitido de {LOGO_UPLOAD_LIMIT / (1024 * 1024):g} MB.")

    try:
        optimized_bytes, optimized_type = _validated_logo(content)
    except ValueError as exc:
        return _logo_error(company.id, str(exc))

    branding = get_or_create_branding(db, company)
    branding.logo_bytes = optimized_bytes
    branding.logo_content_type = optimized_type
    clean_name = re.sub(r"[^A-Za-z0-9._-]+", "_", logo.filename.rsplit("/", 1)[-1]).strip("._")
    base_name = clean_name.rsplit(".", 1)[0] if "." in clean_name else clean_name
    branding.logo_filename = f"{base_name or 'logo'}-normalizado.png"
    branding.updated_at = datetime.now(UTC)
    write_audit(db, user, "actualizar", "logo_empresa", str(company.id), company.legal_name)
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Could not persist company logo (company_id=%s)", company.id)
        return _logo_error(company.id, "No se pudo guardar el logo. Intentá nuevamente; si vuelve a fallar, avisá al administrador.")
    logger.info("Company logo saved (company_id=%s, size_bytes=%s)", company.id, len(optimized_bytes))
    return RedirectResponse(f"/app/companies/{company.id}?logo_saved=1", status_code=303)


@app.post("/app/companies/{company_id}/branding")
def update_company_branding_v23(
    company_id: int,
    primary_color: Annotated[str, Form()] = "#173B86",
    secondary_color: Annotated[str, Form()] = "#0B1F48",
    document_footer: Annotated[str, Form()] = "Generado por Digit Laboral",
    signature_name: Annotated[str, Form()] = "",
    signature_title: Annotated[str, Form()] = "Representante legal",
    document_prefix: Annotated[str, Form()] = "DL",
    show_ruc: Annotated[str | None, Form()] = None,
    show_contact: Annotated[str | None, Form()] = None,
    logo_fit: Annotated[str, Form()] = "contain",
    logo_scale: Annotated[int, Form()] = 100,
    logo_alignment: Annotated[str, Form()] = "center",
    logo_background: Annotated[str, Form()] = "white",
    user: User = Depends(require_roles("administrador", "contador", "empresa")),
    db: Session = Depends(get_db),
):
    company = company_allowed(db, user, company_id)
    branding = get_or_create_branding(db, company)
    color_pattern = re.compile(r"^#[0-9A-Fa-f]{6}$")
    branding.primary_color = primary_color if color_pattern.fullmatch(primary_color) else "#173B86"
    branding.secondary_color = secondary_color if color_pattern.fullmatch(secondary_color) else "#0B1F48"
    branding.document_footer = (document_footer or "").strip()[:240] or "Generado por Digit Laboral"
    branding.signature_name = (signature_name or "").strip()[:180]
    branding.signature_title = (signature_title or "").strip()[:140] or "Representante legal"
    branding.document_prefix = re.sub(r"[^A-Za-z0-9]", "", (document_prefix or "").upper())[:12] or "DL"
    branding.show_ruc = show_ruc == "on"
    branding.show_contact = show_contact == "on"
    branding.logo_fit = logo_fit if logo_fit in {"contain", "cover"} else "contain"
    branding.logo_scale = max(60, min(140, int(logo_scale or 100)))
    branding.logo_alignment = logo_alignment if logo_alignment in {"left", "center", "right"} else "center"
    branding.logo_background = logo_background if logo_background in {"white", "transparent", "soft", "navy"} else "white"
    branding.updated_at = datetime.now(UTC)
    write_audit(db, user, "actualizar", "identidad_visual", str(company.id), company.legal_name)
    db.commit()
    return RedirectResponse(f"/app/companies/{company.id}?branding_saved=1", status_code=303)
