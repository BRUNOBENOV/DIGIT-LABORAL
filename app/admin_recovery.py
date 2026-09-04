from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select

from .auth import hash_password
from .config import settings
from .database import SessionLocal, apply_session_tenant_context
from .models import SecurityEvent, User, UserSecurity

logger = logging.getLogger("digit.admin_recovery")

RECOVERY_MARKER = "admin_recovery_2026_09_04_v1"
FALLBACK_EMAIL = "recuperacion@digitlaboral.com.py"


def _security_for(db, user: User) -> UserSecurity:
    security = db.scalar(select(UserSecurity).where(UserSecurity.user_id == user.id))
    if security:
        return security
    security = UserSecurity(user_id=user.id)
    db.add(security)
    db.flush()
    return security


def run_recovery() -> None:
    if settings.environment.lower() != "production":
        return

    configured_email = settings.initial_admin_email.strip().lower()
    configured_password = settings.initial_admin_password
    if not configured_email or not configured_password or len(configured_password) < 12:
        logger.warning("Admin recovery skipped: INITIAL_ADMIN_EMAIL/PASSWORD are not valid.")
        return

    with SessionLocal() as db:
        db.info["is_superadmin"] = True
        db.info["studio_id"] = None
        apply_session_tenant_context(db)

        already_done = db.scalar(
            select(SecurityEvent.id).where(SecurityEvent.event_type == RECOVERY_MARKER).limit(1)
        )
        if already_done:
            return

        superadmin = db.scalar(select(User).where(User.role == "superadmin").order_by(User.id.asc()))
        if superadmin is None:
            superadmin = User(
                full_name=settings.initial_admin_name.strip() or "Administrador General",
                email=configured_email,
                password_hash=hash_password(configured_password),
                role="superadmin",
                active=True,
                must_change_password=False,
            )
            db.add(superadmin)
            db.flush()

        conflict = db.scalar(
            select(User).where(User.email == configured_email, User.id != superadmin.id).limit(1)
        )
        target_email = configured_email
        if conflict:
            fallback_conflict = db.scalar(
                select(User).where(User.email == FALLBACK_EMAIL, User.id != superadmin.id).limit(1)
            )
            if fallback_conflict:
                logger.error("Admin recovery could not select a unique recovery email.")
                return
            target_email = FALLBACK_EMAIL
            logger.warning(
                "Configured INITIAL_ADMIN_EMAIL is already used by another account; recovery email set to %s.",
                target_email,
            )

        superadmin.email = target_email
        superadmin.password_hash = hash_password(configured_password)
        superadmin.role = "superadmin"
        superadmin.studio_id = None
        superadmin.company_id = None
        superadmin.active = True
        superadmin.must_change_password = False

        security = _security_for(db, superadmin)
        security.failed_attempts = 0
        security.locked_until = None
        security.totp_enabled = False
        security.totp_secret = ""
        security.session_version = int(security.session_version or 0) + 1
        security.password_changed_at = datetime.now(UTC)

        db.add(
            SecurityEvent(
                studio_id=None,
                user_id=superadmin.id,
                email=target_email,
                event_type=RECOVERY_MARKER,
                success=True,
                detail="One-time bootstrap recovery applied from Render INITIAL_ADMIN credentials.",
            )
        )
        db.commit()
        logger.warning("One-time admin recovery applied. Login email: %s", target_email)


if __name__ == "__main__":
    run_recovery()
