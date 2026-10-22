from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import select

from .database import SessionLocal, apply_session_tenant_context
from .models import Company, CompanyRequest, RequestWorkflow, Studio, User
from .notification_service import create_notification, dispatch_notification_outbox

logger = logging.getLogger("digit.notification_worker")
CLOSED_STATUSES = {"Resuelta", "Rechazada", "Aplicada"}


def create_due_request_notifications(today: date | None = None) -> int:
    """Create one persistent notice per recipient and request deadline across studios."""
    today = today or date.today()
    horizon = today + timedelta(days=3)
    created = 0
    with SessionLocal() as db:
        studio_ids = list(db.scalars(select(Studio.id).order_by(Studio.id)))
        for studio_id in studio_ids:
            db.info["studio_id"] = studio_id
            db.info["is_superadmin"] = False
            apply_session_tenant_context(db)
            requests = list(db.scalars(
                select(CompanyRequest)
                .join(RequestWorkflow, RequestWorkflow.request_id == CompanyRequest.id)
                .where(
                    RequestWorkflow.due_date.is_not(None),
                    RequestWorkflow.due_date <= horizon,
                    CompanyRequest.status.notin_(tuple(CLOSED_STATUSES)),
                )
                .order_by(RequestWorkflow.due_date, CompanyRequest.id)
            ))
            for item in requests:
                workflow = db.scalar(select(RequestWorkflow).where(RequestWorkflow.request_id == item.id))
                company = db.get(Company, item.company_id)
                if not workflow or not company:
                    continue
                if workflow.assigned_user_id:
                    recipients = [db.get(User, workflow.assigned_user_id)]
                else:
                    recipients = list(db.scalars(select(User).where(
                        User.studio_id == company.studio_id,
                        User.active.is_(True),
                        User.role.in_(("administrador", "contador", "auxiliar")),
                    )))
                for recipient in recipients:
                    if not recipient or not recipient.active:
                        continue
                    due_date = workflow.due_date
                    title = f"{'Plazo vencido' if due_date < today else 'Solicitud próxima a vencer'} · #{item.id}"
                    body = (
                        f"El trámite «{item.subject or item.request_type}» "
                        f"{'venció' if due_date < today else 'vence'} el {due_date.strftime('%d/%m/%Y')}."
                    )
                    _, _, was_created = create_notification(
                        db,
                        recipient=recipient,
                        event_type="solicitud_vencimiento",
                        title=title,
                        body=body,
                        target_url=f"/app/requests/{item.id}",
                        request_id=item.id,
                        dedupe_key=f"request-deadline:{item.id}:{due_date.isoformat()}:{recipient.id}",
                    )
                    created += int(was_created)
        db.commit()
    return created


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    created = create_due_request_notifications()
    delivered = dispatch_notification_outbox()
    logger.info("Notification sweep done: created=%s deliveries=%s", created, delivered)


if __name__ == "__main__":
    main()
