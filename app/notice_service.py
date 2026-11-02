"""Server-authoritative ordinary notice proposal and reproducible snapshots."""
from __future__ import annotations

import hashlib
import json
import re
from calendar import monthrange
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from .labor_calculator import CalculationError, amount, number
from .models import Employee, NoticeRuleSet, User
from .notice_scale import scale_days, service_tenure

AUTOMATION_VERSION = 1
SCOPE_NOTE = (
    "Referencia ordinaria para contrato indefinido y período de prueba cumplido. "
    "Revisá la procedencia y el promedio computable antes de aprobar; la antigüedad no acredita esos supuestos."
)


class NoticeError(ValueError):
    status_code = 422


class StaleNoticeError(NoticeError):
    status_code = 409


def reference_date_from(data) -> date:
    raw = str(data.get("reference_date") or "").strip()
    period = str(data.get("reference_period") or "").strip()
    try:
        if raw:
            result = date.fromisoformat(raw)
        elif re.fullmatch(r"\d{4}-\d{2}", period):
            year, month = map(int, period.split("-"))
            # Compatibility for old month-only clients: explicit month end,
            # never today's date. The selected date is saved in the snapshot.
            result = date(year, month, monthrange(year, month)[1])
        else:
            raise ValueError
        if not 1900 <= result.year <= 2100:
            raise ValueError
        return result
    except (ValueError, TypeError):
        raise NoticeError("Ingresá una fecha de referencia válida entre 1900 y 2100.") from None


def notice_proposal(db: Session, employee: Employee | None, reference: date) -> dict:
    if employee is None or not isinstance(employee.admission_date, date):
        raise NoticeError("Seleccioná un funcionario con fecha de ingreso registrada y aplicá la selección.")
    if reference < employee.admission_date:
        raise NoticeError("La fecha de referencia es anterior al ingreso del funcionario.")
    if employee.termination_date and reference > employee.termination_date:
        raise NoticeError("La fecha de referencia supera el egreso registrado. Revisá el período o el legajo.")
    rules = list(db.scalars(select(NoticeRuleSet).where(
        NoticeRuleSet.jurisdiction == "PY", NoticeRuleSet.active.is_(True),
        NoticeRuleSet.effective_from <= reference,
        or_(NoticeRuleSet.effective_to.is_(None), NoticeRuleSet.effective_to >= reference),
    ).options(selectinload(NoticeRuleSet.bands))))
    if len(rules) != 1:
        raise NoticeError("No hay una única escala de preaviso vigente para esa fecha. Revisá la configuración legal.")
    rule = rules[0]
    bands = [dict(position=b.position, max_service_months=b.max_service_months, notice_days=b.notice_days) for b in rule.bands]
    try:
        days = scale_days(employee.admission_date, reference, bands)
    except (ValueError, KeyError, TypeError) as exc:
        raise NoticeError(f"La escala de preaviso requiere revisión: {exc}") from None
    source = {
        "employee_id": employee.id, "company_id": employee.company_id,
        "admission_date": employee.admission_date.isoformat(),
        "termination_date": employee.termination_date.isoformat() if employee.termination_date else None,
        "contract_type": employee.contract_type, "payment_frequency": employee.payment_frequency,
        "reference_date": reference.isoformat(),
        "rule": {"code": rule.code, "effective_from": rule.effective_from.isoformat(),
                 "effective_to": rule.effective_to.isoformat() if rule.effective_to else None,
                 "legal_basis": rule.legal_basis, "source_url": rule.source_url, "bands": bands},
    }
    fingerprint = hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    warnings = []
    if (employee.contract_type or "").strip().casefold() != "tiempo indefinido":
        warnings.append("El contrato registrado no es por tiempo indefinido. Revisá el régimen aplicable; el plazo mostrado es una referencia ordinaria.")
    if (employee.payment_frequency or "").strip().casefold() != "mensual":
        warnings.append("La modalidad registrada no es mensual. La base mensual / 30 de esta estimación requiere revisión profesional.")
    tenure = service_tenure(employee.admission_date, reference)
    if tenure["years"] >= 10:
        warnings.append("Antigüedad de diez años o más: revisá la estabilidad laboral. Este cálculo de preaviso no autoriza el despido ni define la indemnización.")
    return dict(source, fingerprint=fingerprint, days=days, tenure=tenure, scope_note=SCOPE_NOTE, warnings=warnings)


def notice_results(base: Decimal, days: int, legal_basis: str) -> dict:
    return {"daily_value": amount(base / 30), "days": days,
            "total": amount(base * days / 30), "legal_basis": legal_basis}


def prepare_notice(db: Session, employee: Employee | None, user: User, data) -> tuple[dict, dict]:
    reference = reference_date_from(data)
    proposal = notice_proposal(db, employee, reference)
    if str(data.get("notice_automation_version") or "") not in {"", str(AUTOMATION_VERSION)}:
        raise NoticeError("La versión del formulario no es compatible. Actualizá la pantalla.")
    fingerprint = str(data.get("notice_fingerprint") or "")
    if data.get("notice_automation_version") and fingerprint != proposal["fingerprint"]:
        raise StaleNoticeError("El legajo, la fecha o la escala cambiaron. Aplicá la selección para actualizar el cálculo.")
    try:
        base = number(data, "salary", "el promedio mensual revisado", maximum="2147483647", required=True, decimals=2)
    except CalculationError as exc:
        raise NoticeError(str(exc)) from None
    days, override = proposal["days"], None
    if data.get("notice_override") == "on":
        if user.role != "administrador":
            # Caller distinguishes an authorization failure from bad inputs.
            raise PermissionError("Solo un administrador puede registrar una excepción de preaviso.")
        reason = str(data.get("notice_override_reason") or "").strip()
        if not 10 <= len(reason) <= 2000:
            raise NoticeError("Describí el fundamento de la excepción de preaviso (entre 10 y 2000 caracteres).")
        try:
            manual = number(data, "days", "los días excepcionales", maximum="365", required=True)
        except CalculationError as exc:
            raise NoticeError(str(exc)) from None
        days = int(manual)
        override = {"days": days, "reason": reason, "user_id": user.id,
                    "user_email": user.email, "role": user.role}
    # Posted 'days' is deliberately ignored in automatic mode, including zero.
    inputs = {"calculation_type": "notice", "notice_automation_version": AUTOMATION_VERSION,
              "monthly_average_base": str(base), "days": days, "reference_date": reference.isoformat(),
              "notice_proposal": proposal, "notice_override": override}
    return inputs, notice_results(base, days, proposal["rule"]["legal_basis"])


def verify_notice_snapshot(db: Session, item, inputs: dict, results: dict) -> None:
    """Replay without mutating inputs or reinterpreting old calculator records."""
    try:
        if inputs["notice_automation_version"] != AUTOMATION_VERSION or item.calculation_type != "notice":
            raise ValueError
        proposal = inputs["notice_proposal"]
        reference = reference_date_from(inputs)
        if item.reference_period != reference.strftime("%Y-%m"):
            raise ValueError
        if (proposal["employee_id"], proposal["company_id"], proposal["reference_date"]) != (item.employee_id, item.company_id, reference.isoformat()):
            raise ValueError
        # Already approved historical documents retain their recorded sources.
        if item.status not in {"Aprobado", "Validado"}:
            current = notice_proposal(db, db.get(Employee, item.employee_id), reference)
            if current != proposal:
                raise NoticeError("El legajo o la escala cambiaron desde el cálculo. Volvé a calcular antes de aprobar.")
        automatic = scale_days(date.fromisoformat(proposal["admission_date"]), reference, proposal["rule"]["bands"])
        if automatic != proposal["days"]:
            raise ValueError
        override = inputs.get("notice_override")
        expected_days = automatic
        if override is not None:
            if (not isinstance(override, dict) or override.get("role") != "administrador"
                    or not override.get("user_id") or not override.get("user_email")
                    or not 10 <= len(override.get("reason", "")) <= 2000
                    or type(override.get("days")) is not int or not 0 <= override["days"] <= 365):
                raise ValueError
            expected_days = override["days"]
        if type(inputs["days"]) is not int or inputs["days"] != expected_days:
            raise ValueError
        base = number({"base": inputs["monthly_average_base"]}, "base", maximum="2147483647", required=True, decimals=2)
        expected = notice_results(base, expected_days, proposal["rule"]["legal_basis"])
        if expected != results or item.amount != expected["total"]:
            raise ValueError
    except NoticeError:
        raise
    except (KeyError, ValueError, TypeError, InvalidOperation, CalculationError):
        raise NoticeError("El preaviso guardado no coincide con sus fuentes e importes. Volvé a calcular antes de aprobar.") from None
