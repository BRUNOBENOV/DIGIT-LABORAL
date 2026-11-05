"""Conciliación de planillas contables contra reglas de salarios/REOP/REI.

Vista previa informativa, sin escrituras ni altas automáticas: las planillas
contables no contienen C.I., asistencia, fechas ni bases de declaración REI.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO
import re
import zipfile

from openpyxl import load_workbook

MAX_UPLOAD = 2 * 1024 * 1024
MAX_EXPANDED = 20 * 1024 * 1024
MAX_ROWS = 5000


class AccountingPayrollError(ValueError):
    pass


def _amount(value, *, cents=False):
    if value is None or value == "":
        return Decimal(0)
    if isinstance(value, bool):
        raise ValueError("importe booleano")
    if isinstance(value, str):
        val = value.strip().replace("Gs.", "").replace("₲", "").replace(" ", "")
        # Soporta importes simples de Excel, no interpreta textos ambiguos.
        if re.fullmatch(r"-?[0-9]{1,3}(?:\.[0-9]{3})+(?:,[0-9]{1,2})?", val):
            val = val.replace(".", "").replace(",", ".")
        elif re.fullmatch(r"-?[0-9]+,[0-9]{1,2}", val):
            val = val.replace(",", ".")
        value = val
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("importe no numérico") from exc
    if not amount.is_finite() or amount < 0 or amount > Decimal("1000000000000"):
        raise ValueError("importe negativo, no finito o fuera de rango")
    if not cents and amount != amount.to_integral_value():
        raise ValueError("salario o haber con centavos; expresá guaraníes enteros")
    return amount


def _rounded(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _name(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:180]


def reconcile_accounting_payroll(payload: bytes, *, period: str = "") -> dict:
    if not 0 < len(payload) <= MAX_UPLOAD:
        raise AccountingPayrollError("El archivo XLSX debe tener como máximo 2 MB.")
    if period and not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", period):
        raise AccountingPayrollError("Ingresá un mes válido en formato AAAA-MM.")
    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            if len(archive.infolist()) > 200 or sum(i.file_size for i in archive.infolist()) > MAX_EXPANDED:
                raise AccountingPayrollError("La planilla excede el tamaño descomprimido permitido.")
            if any(i.filename.startswith("/") or ".." in i.filename.split("/") for i in archive.infolist()):
                raise AccountingPayrollError("La planilla contiene rutas inválidas.")
        workbook = load_workbook(BytesIO(payload), data_only=True, read_only=True)
    except AccountingPayrollError:
        raise
    except (ValueError, OSError, zipfile.BadZipFile, KeyError, TypeError) as exc:
        raise AccountingPayrollError("El archivo no es un Excel XLSX válido.") from exc

    groups = []
    current = None
    title = ""
    count_rows = 0
    general_warnings = []
    try:
        for ws in workbook:
            if ws.max_row > MAX_ROWS or ws.max_column > 100:
                raise AccountingPayrollError("La planilla excede 5.000 filas o 100 columnas.")
            for row_index, cells in enumerate(ws.iter_rows(min_row=1, max_col=25, values_only=True), start=1):
                cells = list(cells) + [None] * max(0, 9 - len(cells))
                b, c, d, e, f, g, h, i = cells[1:9]
                if isinstance(b, str) and "COMISION" in b.upper() and "CONTABIL" in b.upper():
                    title = _name(b.split(" - ")[0])
                    continue
                if isinstance(b, str) and "EMPLEADOS" in b.upper() and isinstance(d, str) and "SALARIO" in d.upper():
                    current = {"name": title or f"Empresa por identificar · {ws.title}", "sheet": ws.title,
                               "rows": [], "warnings": [], "totals": {"salary": 0, "commissions": 0,
                                 "overtime": 0, "gross": 0, "ips_worker": 0, "ips_employer": 0}}
                    groups.append(current)
                    continue
                if current is None or not isinstance(b, (int, float)) or isinstance(b, bool):
                    continue
                # Filas numeradas con el nombre a continuación: no son subtotales.
                name = _name(c)
                if not name:
                    continue
                count_rows += 1
                if count_rows > MAX_ROWS:
                    raise AccountingPayrollError("El archivo contiene demasiados trabajadores.")
                row_errors, row_warnings = [], []
                amounts = {}
                for field, value in (
                    ("salary", d), ("commissions", e), ("overtime", f), ("gross", g),
                    ("ips_worker", h), ("ips_employer", i),
                ):
                    try:
                        amounts[field] = _amount(value, cents=field.startswith("ips_"))
                    except ValueError as exc:
                        row_errors.append(f"{field}: {exc}")
                        amounts[field] = Decimal(0)
                salary, commissions, overtime, gross = (
                    amounts["salary"], amounts["commissions"], amounts["overtime"], amounts["gross"]
                )
                calculated_gross = salary + commissions + overtime
                expected_worker = gross * Decimal("0.09")
                expected_employer = gross * Decimal("0.165")
                if gross != calculated_gross:
                    row_errors.append("Bruto diferente de salario + comisiones + horas extras")
                if abs(amounts["ips_worker"] - expected_worker) > Decimal("1"):
                    row_errors.append(f"IPS obrero: planilla Gs. {_rounded(amounts['ips_worker']):,}; "
                                      f"referencia 9% Gs. {_rounded(expected_worker):,}")
                if abs(amounts["ips_employer"] - expected_employer) > Decimal("1"):
                    row_errors.append(f"IPS patronal: planilla Gs. {_rounded(amounts['ips_employer']):,}; "
                                      f"referencia 16,5% Gs. {_rounded(expected_employer):,}")
                if gross == 0:
                    row_warnings.append("Sin remuneración: confirmar causal y comunicación; no crear declaración cero automáticamente")
                if salary and commissions >= salary * 3:
                    row_warnings.append("Comisiones elevadas respecto al sueldo: comprobar respaldos e imponibilidad")
                if overtime:
                    row_warnings.append("La planilla tiene importe de horas extras, pero no indica cantidad ni tipo (diurnas/nocturnas)")
                if salary + commissions + overtime:
                    row_warnings.append("Sin C.I., período efectivo, asistencia ni medio de pago: no puede exportarse directamente")
                for key, value in amounts.items():
                    current["totals"][key] += _rounded(value) if key.startswith("ips_") else int(value)
                current["rows"].append({
                    "excel_row": row_index, "name": name,
                    "salary": int(salary), "commissions": int(commissions),
                    "overtime": int(overtime), "gross": int(gross),
                    "ips_worker": _rounded(amounts["ips_worker"]),
                    "ips_employer": _rounded(amounts["ips_employer"]),
                    "expected_ips_worker": _rounded(expected_worker),
                    "expected_ips_employer": _rounded(expected_employer),
                    "errors": row_errors, "warnings": row_warnings,
                })
    finally:
        workbook.close()

    if not groups or not any(group["rows"] for group in groups):
        raise AccountingPayrollError(
            "No encontré el formato contable con empleados, sueldo, comisiones, horas extras e IPS. "
            "Esta herramienta solo analiza esa estructura y no importa otros modelos arbitrarios."
        )
    for group in groups:
        if not group["rows"]:
            group["warnings"].append("Bloque sin trabajadores identificados.")
    result = {
        "period": period, "groups": groups,
        "companies": len(groups), "workers": sum(len(g["rows"]) for g in groups),
        "workers_paid": sum(sum(r["gross"] > 0 for r in g["rows"]) for g in groups),
        "gross": sum(g["totals"]["gross"] for g in groups),
        "errors": sum(len(r["errors"]) for g in groups for r in g["rows"]),
        "warnings": sum(len(r["warnings"]) for g in groups for r in g["rows"]),
        "general_warnings": [
            "Es una conciliación contable, no una importación de empleados ni declaración REOP/REI.",
            "Faltan cédulas, códigos patronales, jornadas, horas efectivas y fechas/forma de pago: vinculá los legajos antes de exportar.",
            "Los porcentajes de referencia (9% y 16,5%) corresponden al régimen general IPS; revisar regímenes especiales.",
            "Importes IPS con fracciones de guaraní se muestran redondeados; validar la regla de redondeo antes de declararlos.",
        ],
    }
    return result
