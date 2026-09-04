from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .main import (
    app,
    apply_session_tenant_context,
    get_db,
    get_or_create_security,
    hash_password,
    password_strength_error,
    render,
    require_roles,
    reset_login_failures,
    write_audit,
)
from .models import ActivationRequest, Company, Studio, StudioPayment, User, UserSecurity

logger = logging.getLogger("digit.production_entry")

ADMIN_VERSION = "2.1.0"
ALLOWED_PLANS = {"Inicial", "Profesional", "Estudio Plus"}
ALLOWED_PAYMENT_STATUS = {"Activo", "Pendiente", "Suspendido"}
ALLOWED_ACTIVATION_STATUS = {"Pendiente", "Contactado", "Aprobado", "Rechazado"}
ALLOWED_PAYMENT_RECORD_STATUS = {"Confirmado", "Pendiente", "Anulado"}


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


for _path, _method in (
    ("/admin", "GET"),
    ("/admin/studios", "POST"),
    ("/admin/studios/{studio_id}/status", "POST"),
    ("/admin/studios/{studio_id}/payments", "POST"),
    ("/admin/activation/{request_id}/status", "POST"),
):
    _remove_route(_path, _method)


def _admin_scope(db: Session) -> None:
    """Force the privileged RLS context for the complete admin transaction."""
    db.info["studio_id"] = None
    db.info["is_superadmin"] = True
    apply_session_tenant_context(db)


def _redirect_error(message: str, *, modal: str = "") -> RedirectResponse:
    target = f"/admin?error={quote(message)}"
    if modal:
        target += f"&open={quote(modal)}"
    return RedirectResponse(target, status_code=303)


def _redirect_success(code: str) -> RedirectResponse:
    return RedirectResponse(f"/admin?success={quote(code)}", status_code=303)


def _clean_email(value: str) -> str:
    return (value or "").strip().lower()


def _valid_email(value: str) -> bool:
    return bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value or ""))


def _month_bounds(reference: date) -> tuple[date, date]:
    start = reference.replace(day=1)
    if start.month == 12:
        end = date(start.year + 1, 1, 1)
    else:
        end = date(start.year, start.month + 1, 1)
    return start, end


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard_v21(
    request: Request,
    user: User = Depends(require_roles("superadmin")),
    db: Session = Depends(get_db),
):
    _admin_scope(db)
    studios = list(db.scalars(select(Studio).order_by(Studio.created_at.desc(), Studio.id.desc())))
    studio_ids = [item.id for item in studios]

    owners_by_studio: dict[int, User] = {}
    locked_user_ids: set[int] = set()
    company_counts: dict[int, int] = {}

    if studio_ids:
        owners = list(
            db.scalars(
                select(User)
                .where(User.studio_id.in_(studio_ids), User.role == "administrador")
                .order_by(User.studio_id, User.id)
            )
        )
        for owner in owners:
            owners_by_studio.setdefault(owner.studio_id, owner)

        owner_ids = [item.id for item in owners]
        if owner_ids:
            security_items = list(db.scalars(select(UserSecurity).where(UserSecurity.user_id.in_(owner_ids))))
            now = datetime.now(UTC)
            for security in security_items:
                locked_until = security.locked_until
                if locked_until and locked_until.tzinfo is None:
                    locked_until = locked_until.replace(tzinfo=UTC)
                if locked_until and locked_until > now:
                    locked_user_ids.add(security.user_id)

        rows = db.execute(
            select(Company.studio_id, func.count(Company.id)).where(Company.studio_id.in_(studio_ids)).group_by(Company.studio_id)
        ).all()
        company_counts = {int(studio_id): int(count) for studio_id, count in rows}

    requests_list = list(
        db.scalars(select(ActivationRequest).order_by(ActivationRequest.created_at.desc(), ActivationRequest.id.desc()).limit(100))
    )
    total_companies = db.scalar(select(func.count(Company.id))) or 0
    total_users = db.scalar(select(func.count(User.id))) or 0
    payments = list(
        db.scalars(
            select(StudioPayment)
            .order_by(StudioPayment.payment_date.desc(), StudioPayment.id.desc())
            .limit(100)
        )
    )
    month_start, month_end = _month_bounds(date.today())
    monthly_revenue = db.scalar(
        select(func.coalesce(func.sum(StudioPayment.amount), 0)).where(
            StudioPayment.payment_date >= month_start,
            StudioPayment.payment_date < month_end,
            StudioPayment.status == "Confirmado",
        )
    ) or 0

    active_studios = sum(1 for item in studios if item.active and item.payment_status == "Activo")
    attention_studios = sum(1 for item in studios if not item.active or item.payment_status != "Activo")
    pending_requests = sum(1 for item in requests_list if item.status == "Pendiente")

    diagnostics: list[dict[str, str]] = []
    for studio in studios:
        owner = owners_by_studio.get(studio.id)
        count = company_counts.get(studio.id, 0)
        if owner is None:
            diagnostics.append({"level": "danger", "text": f"{studio.name}: no tiene administrador principal."})
        elif owner.id in locked_user_ids:
            diagnostics.append({"level": "warning", "text": f"{studio.name}: el administrador está bloqueado temporalmente."})
        if count > studio.company_limit:
            diagnostics.append({"level": "warning", "text": f"{studio.name}: supera su límite de empresas ({count}/{studio.company_limit})."})

    logger.info(
        "Admin v%s rendered: studios=%s companies=%s users=%s diagnostics=%s",
        ADMIN_VERSION,
        len(studios),
        total_companies,
        total_users,
        len(diagnostics),
    )
    return render(
        request,
        "admin.html",
        db,
        user,
        studios=studios,
        owners_by_studio=owners_by_studio,
        locked_user_ids=locked_user_ids,
        company_counts=company_counts,
        requests_list=requests_list,
        total_companies=total_companies,
        total_users=total_users,
        payments=payments,
        monthly_revenue=int(monthly_revenue),
        active_studios=active_studios,
        attention_studios=attention_studios,
        pending_requests=pending_requests,
        diagnostics=diagnostics,
        admin_version=ADMIN_VERSION,
    )


@app.post("/admin/studios")
def admin_create_studio_v21(
    name: Annotated[str, Form()],
    owner_name: Annotated[str, Form()],
    owner_email: Annotated[str, Form()],
    temporary_password: Annotated[str, Form()],
    plan_name: Annotated[str, Form()] = "Inicial",
    company_limit: Annotated[int, Form()] = 5,
    phone: Annotated[str, Form()] = "",
    user: User = Depends(require_roles("superadmin")),
    db: Session = Depends(get_db),
):
    _admin_scope(db)
    clean_name = (name or "").strip()
    clean_owner_name = (owner_name or "").strip()
    clean_owner_email = _clean_email(owner_email)
    clean_phone = (phone or "").strip()

    if len(clean_name) < 2:
        return _redirect_error("Ingresá un nombre válido para el estudio.", modal="studioModal")
    if len(clean_owner_name) < 2:
        return _redirect_error("Ingresá el nombre del administrador.", modal="studioModal")
    if not _valid_email(clean_owner_email):
        return _redirect_error("El correo del administrador no es válido.", modal="studioModal")
    if plan_name not in ALLOWED_PLANS:
        return _redirect_error("El plan seleccionado no es válido.", modal="studioModal")
    company_limit = max(1, min(int(company_limit or 1), 500))

    strength_error = password_strength_error(temporary_password)
    if strength_error:
        return _redirect_error(strength_error, modal="studioModal")

    existing_studio = db.scalar(select(Studio).where(func.lower(Studio.name) == clean_name.lower()))
    if existing_studio:
        return _redirect_error("Ya existe un estudio con ese nombre.", modal="studioModal")
    existing_user = db.scalar(select(User).where(func.lower(User.email) == clean_owner_email))
    if existing_user:
        return _redirect_error(
            "Ese correo ya pertenece a otro usuario. Usá un correo distinto para el administrador del estudio.",
            modal="studioModal",
        )

    studio = Studio(
        name=clean_name,
        phone=clean_phone,
        plan_name=plan_name,
        company_limit=company_limit,
        payment_status="Activo",
        active=True,
    )
    db.add(studio)
    try:
        db.flush()
        owner = User(
            studio_id=studio.id,
            full_name=clean_owner_name,
            email=clean_owner_email,
            password_hash=hash_password(temporary_password),
            role="administrador",
            active=True,
            must_change_password=False,
        )
        db.add(owner)
        db.flush()
        security = get_or_create_security(db, owner)
        reset_login_failures(security)
        security.totp_enabled = False
        security.totp_secret = ""
        security.password_changed_at = datetime.now(UTC)
        write_audit(db, user, "crear", "estudio", str(studio.id), f"{studio.name} · {owner.email}")
        db.commit()
    except IntegrityError:
        db.rollback()
        return _redirect_error(
            "No se pudo crear el estudio porque el nombre o el correo ya están registrados.",
            modal="studioModal",
        )
    except Exception:
        db.rollback()
        logger.exception("Unexpected error while creating studio")
        return _redirect_error("No se pudo crear el estudio. La operación fue revertida sin perder datos.", modal="studioModal")

    logger.info("Studio created: id=%s name=%s owner=%s", studio.id, studio.name, clean_owner_email)
    return _redirect_success("studio_created")


@app.post("/admin/studios/{studio_id}/status")
def admin_studio_status_v21(
    studio_id: int,
    name: Annotated[str, Form()],
    active: Annotated[str, Form()],
    payment_status: Annotated[str, Form()],
    company_limit: Annotated[int, Form()],
    plan_name: Annotated[str, Form()] = "Inicial",
    phone: Annotated[str, Form()] = "",
    user: User = Depends(require_roles("superadmin")),
    db: Session = Depends(get_db),
):
    _admin_scope(db)
    studio = db.get(Studio, studio_id)
    if not studio:
        raise HTTPException(404, "Estudio no encontrado.")

    clean_name = (name or "").strip()
    if len(clean_name) < 2:
        return _redirect_error("El nombre del estudio no es válido.")
    if payment_status not in ALLOWED_PAYMENT_STATUS:
        return _redirect_error("Estado de pago inválido.")
    if plan_name not in ALLOWED_PLANS:
        return _redirect_error("Plan inválido.")
    duplicate = db.scalar(
        select(Studio).where(func.lower(Studio.name) == clean_name.lower(), Studio.id != studio.id)
    )
    if duplicate:
        return _redirect_error("Ya existe otro estudio con ese nombre.")

    studio.name = clean_name
    studio.phone = (phone or "").strip()
    studio.plan_name = plan_name
    studio.active = active == "true"
    studio.payment_status = payment_status
    studio.company_limit = max(1, min(int(company_limit or 1), 500))
    write_audit(
        db,
        user,
        "actualizar",
        "estudio",
        str(studio.id),
        f"{studio.name} · {studio.plan_name} · {studio.payment_status} · límite {studio.company_limit}",
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _redirect_error("No se pudo guardar porque hay datos duplicados.")
    return _redirect_success("studio_updated")


@app.post("/admin/studios/{studio_id}/access")
def admin_studio_access_v21(
    studio_id: int,
    owner_name: Annotated[str, Form()],
    owner_email: Annotated[str, Form()],
    new_password: Annotated[str, Form()] = "",
    reset_2fa: Annotated[str | None, Form()] = None,
    user: User = Depends(require_roles("superadmin")),
    db: Session = Depends(get_db),
):
    _admin_scope(db)
    studio = db.get(Studio, studio_id)
    if not studio:
        raise HTTPException(404, "Estudio no encontrado.")

    clean_name = (owner_name or "").strip()
    clean_email = _clean_email(owner_email)
    if len(clean_name) < 2:
        return _redirect_error("Ingresá el nombre del administrador.")
    if not _valid_email(clean_email):
        return _redirect_error("El correo del administrador no es válido.")

    owner = db.scalar(
        select(User)
        .where(User.studio_id == studio.id, User.role == "administrador")
        .order_by(User.id.asc())
    )
    conflict = db.scalar(
        select(User).where(func.lower(User.email) == clean_email, User.id != (owner.id if owner else -1))
    )
    if conflict:
        return _redirect_error("Ese correo ya está siendo utilizado por otra cuenta.")

    if new_password:
        strength_error = password_strength_error(new_password)
        if strength_error:
            return _redirect_error(strength_error)
    elif owner is None:
        return _redirect_error("El estudio no tiene administrador. Para crearlo, ingresá también una contraseña nueva.")

    if owner is None:
        owner = User(
            studio_id=studio.id,
            full_name=clean_name,
            email=clean_email,
            password_hash=hash_password(new_password),
            role="administrador",
            active=True,
            must_change_password=False,
        )
        db.add(owner)
        db.flush()
    else:
        owner.full_name = clean_name
        owner.email = clean_email
        owner.active = True
        owner.role = "administrador"
        owner.studio_id = studio.id
        owner.company_id = None
        if new_password:
            owner.password_hash = hash_password(new_password)
            owner.must_change_password = False

    security = get_or_create_security(db, owner)
    reset_login_failures(security)
    if new_password:
        security.password_changed_at = datetime.now(UTC)
        security.session_version = int(security.session_version or 0) + 1
    if reset_2fa == "on":
        security.totp_enabled = False
        security.totp_secret = ""
        security.session_version = int(security.session_version or 0) + 1

    studio.active = True
    if studio.payment_status == "Suspendido":
        studio.payment_status = "Pendiente"

    write_audit(db, user, "restablecer_acceso", "estudio", str(studio.id), owner.email)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _redirect_error("No se pudo actualizar el acceso porque el correo ya existe.")
    return _redirect_success("access_updated")


@app.post("/admin/studios/{studio_id}/payments")
def admin_add_payment_v21(
    studio_id: int,
    amount: Annotated[int, Form()],
    period: Annotated[str, Form()],
    payment_date: Annotated[date, Form()],
    method: Annotated[str, Form()] = "Transferencia",
    reference: Annotated[str, Form()] = "",
    status_value: Annotated[str, Form(alias="status")] = "Confirmado",
    notes: Annotated[str, Form()] = "",
    user: User = Depends(require_roles("superadmin")),
    db: Session = Depends(get_db),
):
    _admin_scope(db)
    studio = db.get(Studio, studio_id)
    if not studio:
        raise HTTPException(404, "Estudio no encontrado.")
    if int(amount or 0) <= 0:
        return _redirect_error("El monto del pago debe ser mayor a cero.", modal="paymentModal")
    clean_period = (period or "").strip()
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", clean_period):
        return _redirect_error("El periodo debe tener formato AAAA-MM, por ejemplo 2026-09.", modal="paymentModal")
    if status_value not in ALLOWED_PAYMENT_RECORD_STATUS:
        return _redirect_error("Estado de pago inválido.", modal="paymentModal")

    item = StudioPayment(
        studio_id=studio.id,
        amount=int(amount),
        period=clean_period,
        payment_date=payment_date,
        method=(method or "Transferencia").strip()[:60],
        reference=(reference or "").strip()[:120],
        status=status_value,
        notes=(notes or "").strip(),
    )
    db.add(item)
    if status_value == "Confirmado":
        studio.payment_status = "Activo"
        studio.active = True
    write_audit(db, user, "registrar", "pago_estudio", str(studio.id), f"Gs. {item.amount:,} · {item.period}")
    db.commit()
    return _redirect_success("payment_created")


@app.post("/admin/activation/{request_id}/status")
def admin_activation_status_v21(
    request_id: int,
    status_value: Annotated[str, Form(alias="status")],
    user: User = Depends(require_roles("superadmin")),
    db: Session = Depends(get_db),
):
    _admin_scope(db)
    item = db.get(ActivationRequest, request_id)
    if not item:
        raise HTTPException(404, "Solicitud no encontrada.")
    if status_value not in ALLOWED_ACTIVATION_STATUS:
        return _redirect_error("Estado de solicitud inválido.")
    item.status = status_value
    write_audit(db, user, "actualizar", "solicitud_activacion", str(item.id), status_value)
    db.commit()
    return _redirect_success("request_updated")


logger.warning("Digit Laboral production admin v%s loaded", ADMIN_VERSION)
