from __future__ import annotations

import base64
import hashlib
import hmac
import io
import secrets
import smtplib
import struct
import time
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from urllib.parse import quote

import qrcode
from qrcode.image.svg import SvgPathImage
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import PasswordResetToken, User, UserSecurity


def get_or_create_security(db: Session, user: User) -> UserSecurity:
    security = db.scalar(select(UserSecurity).where(UserSecurity.user_id == user.id))
    if security:
        return security
    security = UserSecurity(user_id=user.id)
    db.add(security)
    db.flush()
    return security


def is_locked(security: UserSecurity) -> bool:
    if not security.locked_until:
        return False
    locked_until = security.locked_until
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=UTC)
    return locked_until > datetime.now(UTC)


def record_failed_login(security: UserSecurity) -> None:
    security.failed_attempts += 1
    if security.failed_attempts >= settings.login_max_attempts:
        security.locked_until = datetime.now(UTC) + timedelta(minutes=settings.login_lock_minutes)


def reset_login_failures(security: UserSecurity) -> None:
    security.failed_attempts = 0
    security.locked_until = None


def build_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def totp_uri(user: User, secret: str) -> str:
    label = quote(f"Digit Laboral:{user.email}")
    issuer = quote("Digit Laboral")
    return f"otpauth://totp/{label}?secret={secret}&issuer={issuer}&algorithm=SHA1&digits=6&period=30"


def _totp_at(secret: str, counter: int) -> str:
    padded = secret + "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(padded.upper(), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{number % 1_000_000:06d}"


def verify_totp(secret: str, code: str) -> bool:
    normalized = "".join(character for character in (code or "") if character.isdigit())
    if not secret or len(normalized) != 6:
        return False
    counter = int(time.time() // 30)
    return any(hmac.compare_digest(_totp_at(secret, counter + drift), normalized) for drift in (-1, 0, 1))


def build_totp_qr_svg(user: User, secret: str) -> bytes:
    qr = qrcode.QRCode(version=None, box_size=8, border=2)
    qr.add_data(totp_uri(user, secret))
    qr.make(fit=True)
    image = qr.make_image(image_factory=SvgPathImage)
    output = io.BytesIO()
    image.save(output)
    return output.getvalue()


def hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_password_reset(db: Session, user: User, requested_ip: str) -> tuple[PasswordResetToken, str]:
    raw_token = secrets.token_urlsafe(32)
    item = PasswordResetToken(
        user_id=user.id,
        token_hash=hash_reset_token(raw_token),
        expires_at=datetime.now(UTC) + timedelta(minutes=settings.password_reset_minutes),
        requested_ip=requested_ip[:80],
    )
    db.add(item)
    db.flush()
    return item, raw_token


def validate_password_reset(db: Session, raw_token: str) -> PasswordResetToken | None:
    if not raw_token or len(raw_token) > 200:
        return None
    digest = hash_reset_token(raw_token)
    item = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == digest))
    if not item or item.used_at:
        return None
    expires = item.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires < datetime.now(UTC):
        return None
    return item


def password_strength_error(password: str) -> str | None:
    if len(password or "") < 10:
        return "La contraseña debe tener al menos 10 caracteres."
    classes = [
        any(char.islower() for char in password),
        any(char.isupper() for char in password),
        any(char.isdigit() for char in password),
        any(not char.isalnum() for char in password),
    ]
    if sum(classes) < 3:
        return "Usá una combinación de mayúsculas, minúsculas, números y símbolos."
    return None


def send_password_reset_email(recipient: str, reset_url: str) -> bool:
    if not settings.smtp_host or not settings.smtp_from_email:
        return False
    message = EmailMessage()
    message["Subject"] = "Restablecer contraseña de Digit Laboral"
    message["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
    message["To"] = recipient
    message.set_content(
        "Se solicitó restablecer la contraseña de tu cuenta en Digit Laboral.\n\n"
        f"Abrí este enlace: {reset_url}\n\n"
        f"El enlace vence en {settings.password_reset_minutes} minutos. "
        "Si no realizaste la solicitud, ignorá este mensaje."
    )
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)
    return True


def constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left or "", right or "")


def send_deadline_summary(recipient: str, studio_name: str, items: list[dict[str, str]]) -> bool:
    if not settings.smtp_host or not settings.smtp_from_email or not items:
        return False
    lines = [f"Agenda laboral de {studio_name}", ""]
    for item in items:
        lines.append(f"- {item['date']} · {item['title']} · {item['company']} · {item['status']}")
    lines.extend(["", "Ingresá a Digit Laboral para gestionar los vencimientos."])
    message = EmailMessage()
    message["Subject"] = f"Digit Laboral: {len(items)} vencimiento(s) para revisar"
    message["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
    message["To"] = recipient
    message.set_content("\n".join(lines))
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)
    return True
