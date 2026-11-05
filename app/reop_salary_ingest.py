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
            x, y, year = map(int, match.groups())
            if x > 12 and y <= 12:
                return date(year, y, x)
            if y > 12 and x <= 12:
                return date(year, x, y)
            errors.append(f"{label}: fecha ambigua {value}; usá fecha real de Excel o AAAA-MM-DD.")
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
                        correct_swapped_start: bool = False,
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
                    date_swap_proposal = {"original": start.isoformat(), "suggested": corrected.isoformat()}
                    if correct_swapped_start:
                        warnings.append(f"Fecha DESDE corregida expresamente de {start.isoformat()} a {corrected.isoformat()}.")
                        start = corrected
                    else:
                        errors.append(
                            f"DESDE {start.strftime('%d/%m/%Y')} no coincide con HASTA; "
                            "posible inversión día/mes. Autorizá la corrección en la pantalla."
                        )
                else:
                    errors.append("DESDE y HASTA corresponden a meses distintos.")
            if start and end and (end < start or (end - start).days > 30):
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
                      "night_column_is_total": night_column_is_total},
        }
    finally:
        book.close()
