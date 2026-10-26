from __future__ import annotations

import logging
import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal, apply_session_tenant_context
from .models import Notification, NotificationDelivery, Studio, User

logger = logging.getLogger("digit.notifications")


def create_notification(
    db: Session,
    *,
    recipient: User,
    event_type: str,
    title: str,
    body: str,
    target_url: str,
    request_id: int | None = None,
    dedupe_key: str | None = None,
) -> tuple[Notification, NotificationDelivery | None, bool]:
    """Persist an in-app notice and queue email when SMTP is configured."""
    if dedupe_key:
        existing = db.scalar(select(Notification).where(Notification.dedupe_key == dedupe_key))
        if existing:
            return existing, None, False
    target = target_url if target_url.startswith("/") and not target_url.startswith("//") else "/app/notifications"
    notification = Notification(
        studio_id=recipient.studio_id,
        recipient_user_id=recipient.id,
        event_type=event_type[:80],
        title=title[:200],
        body=body,
        target_url=target[:500],
        related_request_id=request_id,
        dedupe_key=dedupe_key,
    )
    db.add(notification)
    db.flush()
    delivery = None
    if settings.smtp_host and settings.smtp_from_email and recipient.email:
        delivery = NotificationDelivery(
            studio_id=recipient.studio_id,
            notification_id=notification.id, channel="email", status="Pendiente", attempts=0,
        )
        db.add(delivery)
        db.flush()
    return notification, delivery, True


def send_notification_delivery(delivery_id: int, studio_id: int | None = None) -> bool:
    """Deliver one queued email with an atomic claim to prevent concurrent sends."""
    now = datetime.now(UTC)
    with SessionLocal() as db:
        db.info["studio_id"] = studio_id
        db.info["is_superadmin"] = False
        apply_session_tenant_context(db)
        delivery = db.get(NotificationDelivery, delivery_id)
        if not delivery:
            return False
        if delivery.status == "Enviado":
            return True
        if delivery.status == "Enviando":
            # An active worker owns this delivery. A scheduled sweep recovers it
            # only after it has remained in this state past the stale threshold.
            return False
        if delivery.attempts >= 5:
            delivery.status = "Fallido"
            delivery.last_error = delivery.last_error or "Se agotaron los intentos de entrega."
            delivery.updated_at = now
            db.commit()
            return False

        notification = db.get(Notification, delivery.notification_id)
        recipient = db.get(User, notification.recipient_user_id) if notification else None
        if not notification or not recipient or not recipient.active or not recipient.email:
            delivery.status = "Fallido"
            delivery.last_error = "Destinatario o notificación no disponible."
            delivery.updated_at = now
            db.commit()
            return False
        if not settings.smtp_host or not settings.smtp_from_email:
            delivery.status = "Pendiente"
            delivery.last_error = "SMTP no está configurado."
            delivery.updated_at = now
            db.commit()
            return False

        # Claim only if the row is still eligible. Concurrent workers attempting
        # the same ID cannot both transition it from Pendiente/Fallido to Enviando.
        claim = db.execute(
            update(NotificationDelivery)
            .where(
                NotificationDelivery.id == delivery_id,
                NotificationDelivery.status.in_(("Pendiente", "Fallido")),
                NotificationDelivery.attempts < 5,
            )
            .values(
                status="Enviando",
                attempts=NotificationDelivery.attempts + 1,
                last_error="",
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if claim.rowcount != 1:
            db.rollback()
            current = db.get(NotificationDelivery, delivery_id)
            return bool(current and current.status == "Enviado")
        db.commit()

        recipient_email = recipient.email
        subject = f"Digit Laboral: {notification.title}"
        body = (
            f"{notification.title}\n\n{notification.body}\n\n"
            f"Abrí Digit Laboral para continuar: {settings.public_url}{notification.target_url}\n"
        )
        smtp_host = settings.smtp_host
        smtp_port = settings.smtp_port
        smtp_use_tls = settings.smtp_use_tls
        smtp_username = settings.smtp_username
        smtp_password = settings.smtp_password
        smtp_from_email = settings.smtp_from_email
        smtp_from_name = settings.smtp_from_name

    message = EmailMessage()
    message["Subject"] = subject[:200]
    message["From"] = f"{smtp_from_name} <{smtp_from_email}>"
    message["To"] = recipient_email
    message.set_content(body)
    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as smtp:
            if smtp_use_tls:
                smtp.starttls()
            if smtp_username:
                smtp.login(smtp_username, smtp_password)
            smtp.send_message(message)
    except Exception as exc:
        logger.warning(
            "Notification email delivery failed: %s",
            str(exc)[:250],
            extra={"delivery_id": delivery_id},
        )
        with SessionLocal() as db:
            db.info["studio_id"] = studio_id
            db.info["is_superadmin"] = False
            apply_session_tenant_context(db)
            delivery = db.get(NotificationDelivery, delivery_id)
            if delivery and delivery.status == "Enviando":
                delivery.status = "Fallido" if delivery.attempts >= 5 else "Pendiente"
                delivery.last_error = str(exc)[:1000]
                delivery.updated_at = datetime.now(UTC)
                db.commit()
        return False

    with SessionLocal() as db:
        db.info["studio_id"] = studio_id
        db.info["is_superadmin"] = False
        apply_session_tenant_context(db)
        delivery = db.get(NotificationDelivery, delivery_id)
        if delivery and delivery.status == "Enviando":
            delivery.status = "Enviado"
            delivery.last_error = ""
            delivery.sent_at = datetime.now(UTC)
            delivery.updated_at = datetime.now(UTC)
            db.commit()
    return True


def dispatch_notification_outbox(limit: int = 100) -> dict[str, int]:
    """Recover interrupted sends, then dispatch eligible notifications across tenants."""
    pending: list[tuple[datetime, int, int | None]] = []
    now = datetime.now(UTC)
    stale_before = now - timedelta(minutes=15)
    per_tenant_limit = max(1, min(limit, 500))
    with SessionLocal() as db:
        # Studios are not row-level protected; set each tenant context before
        # touching tenant-scoped notification tables.
        studio_ids = list(db.scalars(select(Studio.id).order_by(Studio.id)))
        for studio_id in studio_ids:
            db.info["studio_id"] = studio_id
            db.info["is_superadmin"] = False
            apply_session_tenant_context(db)

            # A worker may be terminated while its email is being sent. Recover
            # only claims that have been untouched for 15 minutes; keep attempt
            # counts so repeated process crashes eventually stop retrying.
            stale = list(db.scalars(
                select(NotificationDelivery).where(
                    NotificationDelivery.status == "Enviando",
                    NotificationDelivery.updated_at < stale_before,
                )
            ))
            for item in stale:
                item.updated_at = now
                if item.attempts >= 5:
                    item.status = "Fallido"
                    item.last_error = "El envío quedó interrumpido y agotó los intentos permitidos."
                else:
                    item.status = "Pendiente"
                    item.last_error = "El envío anterior quedó interrumpido; se reintentará."
            db.commit()

            rows = list(db.scalars(
                select(NotificationDelivery)
                .where(
                    NotificationDelivery.status.in_(("Pendiente", "Fallido")),
                    NotificationDelivery.attempts < 5,
                )
                .order_by(NotificationDelivery.created_at, NotificationDelivery.id)
                .limit(per_tenant_limit)
            ))
            pending.extend((item.created_at, item.id, studio_id) for item in rows)
    pending.sort(key=lambda row: (row[0], row[1]))
    pending = pending[:per_tenant_limit]
    sent = failed = 0
    for _, delivery_id, studio_id in pending:
        if send_notification_delivery(delivery_id, studio_id):
            sent += 1
        else:
            failed += 1
    return {"sent": sent, "failed": failed, "checked": len(pending)}
