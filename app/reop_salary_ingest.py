"""Carga no destructiva de planillas oficiales REOP (32 columnas).

Los datos de origen se conservan como declaración IMPORTADA; no se considera
validación del MTESS, recepción oficial ni cálculo salarial aprobado.
"""
from __future__ import annotations

import io
import re
import zipfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256

from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel

from .approved_salary_import import REOP_PAYMENT_METHODS
from .official_salary_import import REOP_HEADERS

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 3000
MAX_AMOUNT = 2_147_483_647
INCOME_COLUMNS = tuple(range(9, 24))
DEDUCTION_COLUMNS = (24, 25, 26, 28, 30)
PAYMENT_COLUMNS = {26: 27, 28: 29, 30: 31}


def _digits(value) -> str:
    if value is None or isinstance(value, bool):
        return ""
    raw = str(value).strip()
    if re.fullmatch(r"\d+\.0+", raw):
        raw = raw.split(".")[0]
    return re.sub(r"\D", "", raw).lstrip("0") or ("0" if "0" in raw else "")


def _date(value, label: str, errors: list[str]) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return from_excel(value).date()
        except (OverflowError, ValueError, TypeError):
            pass
    if isinstance(value, str):
        value = value.strip()
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            pass
        match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", value)
        if match:
            first, second, year = map(int, match.groups())
            try:
                # La exportación REOP usa MES/DÍA/AÑO (p. ej. 10/01 = 1 de octubre).
                # Aceptar DÍA/MES/AÑO solo cuando el primer número > 12
                # y por tanto no puede ser un mes.
                if 1 <= first <= 12:
                    return date(year, first, second)
                if 1 <= second <= 12:
                    return date(year, second, first)
            except ValueError:
                pass
            errors.append(f"{label}: fecha REOP inválida {value} (formato MES/DÍA/AÑO).")
            return None
    errors.append(f"{label}: fecha vacía o inválida.")
    return None


def _amount(value, label: str, errors: list[str]) -> int:
    if value in (None, ""):
        return 0
    if isinstance(value, bool):
        errors.append(f"{label}: importe inválido.")
        return 0
    try:
        d = Decimal(str(value).strip())
        if not d.is_finite() or d < 0 or d > MAX_AMOUNT:
            raise ValueError
        return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (ValueError, TypeError, InvalidOperation):
        errors.append(f"{label}: el importe debe ser numérico y no negativo.")
        return 0


def _quantity(value, label: str, maximum: Decimal, errors: list[str], *,
              integer: bool = False) -> str:
    if value in (None, ""):
        errors.append(f"{label}: falta el valor.")
        return "0"
    try:
        d = Decimal(str(value))
        if not d.is_finite() or d < 0 or d > maximum or (integer and d != d.to_integral_value()):
            raise ValueError
        return format(d.normalize(), "f")
    except (ValueError, TypeError, InvalidOperation):
        errors.append(f"{label}: cantidad fuera de rango.")
        return "0"


def _income_rows(values: list[int], skip_night: bool) -> list[dict]:
    rows = []
    for index in INCOME_COLUMNS:
        if skip_night and index == 12:
            continue
        if values[index]:
            rows.append({"label": REOP_HEADERS[index], "amount": values[index],
                         "formula": "Importado del Excel REOP", "legal": ""})
    return rows


def parse_reop_workbook(content: bytes, filename: str, *,
                        correct_swapped_start: bool = True,
                        night_column_is_total: bool = False) -> dict:
    """Validación estricta; jamás infiere correcciones sin opción explícita."""
    if not filename or not filename.lower().endswith(".xlsx"):
        raise ValueError("Seleccioná una planilla REOP .xlsx.")
    if not content or len(content) > MAX_FILE_BYTES:
        raise ValueError("El archivo debe tener entre 1 byte y 5 MB.")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            if len(members) > 500 or sum(x.file_size for x in members) > 35 * 1024 * 1024:
                raise ValueError("El archivo XLSX contiene demasiados datos internos.")
            if any(x.file_size > 30 * 1024 * 1024 for x in members):
                raise ValueError("El archivo XLSX supera el límite seguro de descompresión.")
        book = load_workbook(io.BytesIO(content), read_only=True, data_only=True, keep_links=False)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("No se pudo leer el archivo Excel REOP.") from exc
    try:
        if len(book.worksheets) != 1:
            raise ValueError("El modelo REOP debe tener una sola hoja de salarios.")
        sheet = book.worksheets[0]
        if sheet.max_row > MAX_ROWS + 1:
            raise ValueError(f"Máximo {MAX_ROWS} trabajadores por importación.")
        headers = [str(cell.value or "").strip() for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
        if len(headers) != len(REOP_HEADERS) or tuple(headers) != REOP_HEADERS:
            raise ValueError("Las 32 columnas no coinciden con el modelo REOP de DIGIT-LABORAL.")
        prepared = []
        seen: set[tuple[str, str, str]] = set()
        for sheet_row, cells in enumerate(sheet.iter_rows(min_row=2, values_only=True), 2):
            raw = list(cells)
            if not any(x not in ("", None) for x in raw):
                continue
            errors: list[str] = []
            warnings: list[str] = []
            if len(raw) != 32:
                errors.append("La fila no tiene 32 campos.")
                raw = (raw + [None] * 32)[:32]
            patronal = _digits(raw[0])
            ci = _digits(raw[1])
            if not patronal or not ci:
                errors.append("N.º patronal y C.I. son obligatorios.")
            start = _date(raw[2], "DESDE", errors)
            end = _date(raw[3], "HASTA", errors)
            original_start = start.isoformat() if start else ""
            date_swap_proposal = None
            if start and end and (start.year, start.month) != (end.year, end.month):
                corrected = None
                if start.day <= 12 and start.month <= 12:
                    corrected = date(start.year, start.day, start.month)
                if corrected and (corrected.year, corrected.month) == (end.year, end.month) and corrected <= end:
                    date_swap_proposal = {
                        "original": start.isoformat(), "suggested": corrected.isoformat(),
                        "original_display": start.strftime("%d/%m/%Y"),
                        "suggested_display": corrected.strftime("%d/%m/%Y"),
                        "format": "REOP MM/DD/YYYY",
                    }
                    if correct_swapped_start:
                        warnings.append(
                            f"Fecha DESDE normalizada automáticamente al formato REOP MES/DÍA/AÑO: "
                            f"{start.strftime('%d/%m/%Y')} → {corrected.strftime('%d/%m/%Y')}."
                        )
                        start = corrected
                    else:
                        errors.append(
                            f"DESDE {start.strftime('%d/%m/%Y')} no coincide con HASTA; "
                            "posible inversión día/mes; la fecha no pudo normalizarse con seguridad."
                        )
                else:
                    errors.append("DESDE y HASTA corresponden a meses distintos.")
            if start and end and (end < start or (end - start).days > 30) and not (
                date_swap_proposal and not correct_swapped_start
            ):
                errors.append("El rango DESDE/HASTA no es válido para una liquidación mensual.")
            period = start.strftime("%Y-%m") if start and end and start.year == end.year and start.month == end.month else ""
            payment_code = _quantity(raw[4], "Forma de pago", Decimal(4), errors, integer=True)
            if payment_code not in REOP_PAYMENT_METHODS:
                errors.append("Forma de pago: código REOP válido de 1 a 4.")
            days = _quantity(raw[5], "Días trabajados", Decimal(31), errors, integer=True)
            pieces = _quantity(raw[6], "Piezas o tareas", Decimal(100_000_000), errors, integer=True)
            hours = _quantity(raw[7], "Horas ordinarias", Decimal(744), errors)
            extra_hours = _quantity(raw[8], "Horas extraordinarias", Decimal(744), errors)
            amounts = [0] * len(REOP_HEADERS)
            for index in (*INCOME_COLUMNS, *DEDUCTION_COLUMNS):
                amounts[index] = _amount(raw[index], REOP_HEADERS[index], errors)
            others = sum(amounts[i] for i in INCOME_COLUMNS if i != 12)
            suspected_gross = bool(amounts[12] and others and amounts[12] == others)
            if suspected_gross:
                if not night_column_is_total:
                    errors.append(
                        "«Recargo horario Nocturno» coincide con todos los demás ingresos: "
                        "parece un TOTAL BRUTO duplicado. Confirmá el tratamiento antes de importar."
                    )
                else:
                    warnings.append("El valor duplicado de Recargo nocturno se trató como total de control, no como otro ingreso.")
            earnings = _income_rows(amounts, suspected_gross and night_column_is_total)
            deductions = [
                {"label": REOP_HEADERS[index], "amount": amounts[index],
                 "formula": "Importado del Excel REOP", "legal": ""}
                for index in (24, 25) if amounts[index]
            ]
            for amount_column, concept_column in PAYMENT_COLUMNS.items():
                concept = str(raw[concept_column] or "").strip()
                if amounts[amount_column] and not concept:
                    errors.append(f"{REOP_HEADERS[amount_column]} requiere su concepto descriptivo.")
                if amounts[amount_column] and concept:
                    deductions.append({"label": concept[:160], "amount": amounts[amount_column],
                                       "formula": "Importado del Excel REOP", "legal": ""})
            gross = sum(row["amount"] for row in earnings)
            discounts = sum(row["amount"] for row in deductions)
            if not gross:
                errors.append("No hay haberes positivos.")
            if discounts > gross:
                errors.append("Los egresos superan los ingresos.")
            if gross > MAX_AMOUNT:
                errors.append("El bruto supera el límite admitido por el sistema.")
            net = gross - discounts
            key = (patronal, ci, period)
            if period and key in seen:
                errors.append("Trabajador/mes duplicado dentro del archivo.")
            seen.add(key)
            # No se inventa una fecha de pago: el archivo solo contiene la forma.
            prepared.append({
                "source_row": sheet_row, "patronal": patronal, "ci": ci,
                "period": period, "period_hint": end.strftime("%Y-%m") if end else "",
                "period_start": start.isoformat() if start else "",
                "source_period_start": original_start,
                "date_swap_proposal": date_swap_proposal,
                "date_auto_normalized": bool(date_swap_proposal and correct_swapped_start),
                "night_total_proposal": amounts[12] if suspected_gross else None,
                "period_end": end.isoformat() if end else "",
                "payment_code": payment_code, "payment_method": REOP_PAYMENT_METHODS.get(payment_code, ""),
                "days_worked": days, "pieces_or_tasks": pieces,
                "hours_worked": hours, "extra_hours": extra_hours,
                "earnings": earnings, "deductions": deductions,
                "gross": gross, "discounts": discounts, "net": net,
                "night_total_control": amounts[12] if suspected_gross else None,
                "errors": errors, "warnings": warnings,
            })
        if not prepared:
            raise ValueError("La planilla no contiene trabajadores.")
        return {
            "filename": filename[:160], "sha256": sha256(content).hexdigest(),
            "rows": prepared, "source_rows": len(prepared),
            "flags": {"correct_swapped_start": correct_swapped_start,
                      "reop_date_format": "MM/DD/YYYY",
                      "night_column_is_total": night_column_is_total},
        }
    finally:
        book.close()


def validate_imported_reop_salary_for_approval(db, item, inputs: dict, saved: dict) -> None:
    """Revalidar el snapshot del Excel, sin sustituirlo por un cálculo nuevo.

    La importación preserva haberes declarados, no un cálculo reproducible por
    nuestro motor. La aprobación aquí es INTERNA y exige consistencia exacta,
    identidad vinculada, patronal vigente y ausencia de otro salario aprobado.
    """
    from calendar import monthrange
    from sqlalchemy import select
    from .models import Branch, BranchComplianceProfile, CalculationRecord, Company, Employee

    def refuse(reason: str) -> None:
        raise ValueError("No se puede aprobar el salario REOP importado: " + reason)

    if item.source != "Importación Excel REOP" or item.calculation_type != "suite_salary":
        refuse("tipo u origen incorrecto.")
    company = db.get(Company, item.company_id)
    employee = db.get(Employee, item.employee_id) if item.employee_id else None
    if not company or not employee or employee.company_id != company.id:
        refuse("empresa o funcionario vinculado no coincide con el registro.")
    if inputs.get("kind") != "salary" or saved.get("kind") != "salary":
        refuse("falta el tipo de liquidación salarial en los datos guardados.")
    period = str(item.reference_period or "")
    if not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", period):
        refuse("el período registrado no es válido.")
    if str(inputs.get("month") or "") != period or str(saved.get("period") or "") != period:
        refuse("el período no coincide entre los datos guardados.")
    try:
        start = date.fromisoformat(str(inputs.get("period_start") or ""))
        end = date.fromisoformat(str(inputs.get("period_end") or ""))
        year, month = (int(v) for v in period.split("-"))
        if not date(year, month, 1) <= start <= end <= date(year, month, monthrange(year, month)[1]):
            refuse("las fechas DESDE/HASTA no pertenecen al período.")
    except ValueError:
        refuse("las fechas de la liquidación no son válidas.")

    source_hash = str(inputs.get("reop_import_sha256") or "")
    if not re.fullmatch(r"[a-f0-9]{64}", source_hash):
        refuse("falta la huella SHA-256 del Excel original.")
    try:
        source_row = int(inputs.get("reop_import_source_row"))
    except (ValueError, TypeError):
        source_row = 0
    if source_row < 2:
        refuse("falta la fila de origen verificable.")
    if _digits(inputs.get("ci")) != _digits(employee.document_number):
        refuse("la C.I. vinculada no coincide con la declarada.")
    identity = saved.get("identity")
    if not isinstance(identity, dict) or _digits(identity.get("ci")) != _digits(employee.document_number):
        refuse("la identidad del recibo no coincide con el legajo.")
    patronal = _digits(inputs.get("reop_employer_number"))
    allowed = {_digits(company.mtess_employer_number)}
    branch_query = select(BranchComplianceProfile.mtess_employer_number).join(
        Branch, Branch.id == BranchComplianceProfile.branch_id,
    ).where(Branch.company_id == company.id)
    allowed.update(_digits(value) for value in db.scalars(branch_query))
    allowed.discard("")
    if not patronal or patronal not in allowed:
        refuse("el número patronal del Excel no coincide con la empresa registrada.")

    def integer_amount(value, name: str) -> int:
        if type(value) is not int or not 0 <= value <= MAX_AMOUNT:
            refuse(f"el importe de {name} no es un número entero válido.")
        return value

    def amounts(section: str) -> int:
        rows = saved.get(section)
        if not isinstance(rows, list) or len(rows) > 100:
            refuse(f"los conceptos de {section} no son válidos.")
        total = 0
        for index, row in enumerate(rows, 1):
            if not isinstance(row, dict) or not str(row.get("label") or "").strip():
                refuse(f"falta la descripción del concepto {index} en {section}.")
            total += integer_amount(row.get("amount"), f"{section} #{index}")
        return total

    incomes = amounts("earnings")
    deductions = amounts("deductions")
    gross = integer_amount(saved.get("gross"), "total ingresos")
    discounts = integer_amount(saved.get("discounts"), "total egresos")
    net = integer_amount(saved.get("net"), "total a cobrar")
    if gross <= 0 or incomes != gross or deductions != discounts or gross < discounts:
        refuse("los conceptos no suman exactamente los totales declarados.")
    if gross - discounts != net or net != item.amount:
        refuse("el importe neto no coincide con el cálculo guardado.")
    try:
        days = Decimal(str(inputs.get("days_worked")))
        hours = Decimal(str(inputs.get("hours_worked")))
        pieces = Decimal(str(inputs.get("pieces_or_tasks")))
        if not all(x.is_finite() for x in (days, hours, pieces)):
            raise ValueError
        if not (0 <= days <= 31 and days == days.to_integral_value()
                and 0 <= hours <= 744
                and 0 <= pieces <= 100000000 and pieces == pieces.to_integral_value()):
            raise ValueError
    except (InvalidOperation, TypeError, ValueError):
        refuse("los días, horas o piezas declarados no son válidos.")
    if inputs.get("payment_method") not in REOP_PAYMENT_METHODS.values():
        refuse("la forma de pago no coincide con el modelo REOP.")
    original_nocturnal_total = inputs.get("reop_original_night_total_control")
    if original_nocturnal_total not in (None, 0) and not (
        isinstance(inputs.get("reop_import_options"), dict)
        and inputs["reop_import_options"].get("night_column_is_total") is True
    ):
        refuse("el tratamiento del total nocturno duplicado no está documentado.")
    existing = db.scalar(select(CalculationRecord.id).where(
        CalculationRecord.company_id == item.company_id,
        CalculationRecord.employee_id == item.employee_id,
        CalculationRecord.reference_period == period,
        CalculationRecord.calculation_type.in_(("salary", "suite_salary")),
        CalculationRecord.status.in_(("Aprobado", "Validado")),
        CalculationRecord.id != item.id,
    ).limit(1))
    if existing is not None:
        refuse("ya hay otra liquidación aprobada para este trabajador y período.")
