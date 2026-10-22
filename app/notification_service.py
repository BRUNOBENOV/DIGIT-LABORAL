from __future__ import annotations

import logging
import smtplib
from datetime import UTC, datetime
from email.message import EmailMessage

from sqlalchemy import select
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
    """Deliver one queued email after the business transaction commits."""
    with SessionLocal() as db:
        db.info["studio_id"] = studio_id
        db.info["is_superadmin"] = False
        apply_session_tenant_context(db)
        delivery = db.get(NotificationDelivery, delivery_id)
        if not delivery or delivery.status == "Enviado" or delivery.status == "Enviando":
            return delivery is not None and delivery.status == "Enviado"
        if delivery.attempts >= 5:
            delivery.status = "Fallido"
            db.commit()
            return False
        notification = db.get(Notification, delivery.notification_id)
        recipient = db.get(User, notification.recipient_user_id) if notification else None
        if not notification or not recipient or not recipient.active or not recipient.email:
            delivery.status = "Fallido"
            delivery.last_error = "Destinatario o notificación no disponible."
            db.commit()
            return False
        if not settings.smtp_host or not settings.smtp_from_email:
            delivery.status = "Pendiente"
            delivery.last_error = "SMTP no está configurado."
            db.commit()
            return False
        delivery.status = "Enviando"
        delivery.attempts += 1
        delivery.updated_at = datetime.now(UTC)
        db.commit()
        recipient_email = recipient.email
        subject = f"Digit Laboral: {notification.title}"
        body = (
            f"{notification.title}\n\n{notification.body}\n\n"
            f"Abrí Digit Laboral para continuar: {settings.public_url}{notification.target_url}\n"
        )

    message = EmailMessage()
    message["Subject"] = subject[:200]
    message["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
    message["To"] = recipient_email
    message.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
    except Exception as exc:
        logger.warning("Notification email delivery failed: %s", str(exc)[:250], extra={"delivery_id": delivery_id})
        with SessionLocal() as db:
            db.info["studio_id"] = studio_id
            db.info["is_superadmin"] = False
            apply_session_tenant_context(db)
            delivery = db.get(NotificationDelivery, delivery_id)
            if delivery:
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
        if delivery:
            delivery.status = "Enviado"
            delivery.last_error = ""
            delivery.sent_at = datetime.now(UTC)
            delivery.updated_at = datetime.now(UTC)
            db.commit()
    return True


def dispatch_notification_outbox(limit: int = 100) -> dict[str, int]:
    """Retry pending or transiently failed SMTP messages across tenant scopes."""
    pending: list[tuple[datetime, int, int | None]] = []
    with SessionLocal() as db:
        # Studios are not row-level protected; set each tenant context before
        # touching tenant-scoped notification tables.
        studio_ids = list(db.scalars(select(Studio.id).order_by(Studio.id)))
        for studio_id in studio_ids:
            db.info["studio_id"] = studio_id
            db.info["is_superadmin"] = False
            apply_session_tenant_context(db)
            rows = list(db.scalars(
                select(NotificationDelivery)
                .where(NotificationDelivery.status.in_(("Pendiente", "Fallido")), NotificationDelivery.attempts < 5)
                .order_by(NotificationDelivery.created_at, NotificationDelivery.id)
                .limit(max(1, min(limit, 500)))
            ))
            pending.extend((item.created_at, item.id, studio_id) for item in rows)
    pending.sort(key=lambda row: (row[0], row[1]))
    pending = pending[:max(1, min(limit, 500))]
    sent = failed = 0
    for _, delivery_id, studio_id in pending:
        if send_notification_delivery(delivery_id, studio_id):
            sent += 1
        else:
            failed += 1
    return {"sent": sent, "failed": failed, "checked": len(pending)}
