"""Exportación salarial REOP (32 columnas) y REI (TXT de referencia 2016).

Las nóminas se LEEN; nunca se recalculan ni se actualizan. La validación local
no constituye homologación, declaración o recepción de los portales oficiales.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from xml.sax.saxutils import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    BranchComplianceProfile, Employee, EmployeeComplianceProfile,
    Payroll, PayrollComplianceDetail, PayrollLine,
)

REOP_HEADERS = (
    "numero_patronal", "nro_ci", "periodo_pago_desde", "periodo_pago_hasta",
    "forma_de_pago", "canti_dias_trabajados", "canti_piezas_tareas",
    "horas_ordinarias", "horas_extraordinarias", "Salario Básico",
    "Comisiones", "Horas extras diurnas(50%)", "Recargo horario Nocturno",
    "Horas extras nocturnas(100%)", "Premios", "Salario en especie (Max 30%)",
    "Regalias", "Gratificaciones", "Grado Académico", "Feriados",
    "Dietas", "Complemento Salarial", "Bonificacion Familiar",
    "Antigüedad", "Anticipos de salario", "Aporte Seg. Social",
    "Descuentos 1", "Concepto descuentos 1", "Descuentos 2",
    "Concepto descuentos 2", "Descuentos 3", "Concepto descuentos 3",
)
REOP_OTHER_COLUMNS = {
    "premios": 14,
    "regalias": 16,
    "gratificaciones": 17,
    "grado": 18,
    "dietas": 20,
    "complemento": 21,
    "antiguedad": 23,
}
REI_FIELDS_2016 = (
    "numero_patronal", "numero_asegurado", "ci", "apellido", "nombre",
    "categoria", "dias_trabajados", "salario_imponible",
    "mes_anio_pago", "codigo_actividad", "salario_real",
)
MIME_REOP = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MIME_REI = "text/plain; charset=windows-1252"


class SalaryImportError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = list(dict.fromkeys(errors))
        super().__init__("; ".join(self.errors))


def _number(value, label: str, errors: list[str]) -> int:
    if not isinstance(value, int) or value < 0:
        errors.append(f"{label}: debe ser un importe entero no negativo guardado.")
        return 0
    return value


def _text(value) -> str:
    return str(value or "").strip().replace("\t", " ").replace("\r", " ").replace("\n", " ")


def _patronal(db: Session, company, employee: Employee, authority: str) -> str:
    field = "mtess_employer_number" if authority == "REOP" else "ips_employer_number"
    if employee.branch_id:
        profile = db.scalar(select(BranchComplianceProfile).where(
            BranchComplianceProfile.branch_id == employee.branch_id
        ))
        if profile and _text(getattr(profile, field, "")):
            return _text(getattr(profile, field))
    return _text(getattr(company, field, ""))


def _source(db: Session, company, period: str):
    if not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", period or ""):
        raise SalaryImportError(["Ingresá un período válido AAAA-MM."])
    payroll = db.scalar(select(Payroll).where(
        Payroll.company_id == company.id, Payroll.period == period
    ))
    if payroll is None:
        raise SalaryImportError(["No existe una nómina guardada para ese período y empresa."])
    if payroll.status != "Cerrada" or not payroll.closed_at:
        raise SalaryImportError(["La nómina debe estar cerrada y tener constancia de cierre antes de exportarse."])
    records = db.execute(
        select(PayrollLine, Employee, PayrollComplianceDetail)
        .join(Employee, Employee.id == PayrollLine.employee_id)
        .outerjoin(PayrollComplianceDetail, PayrollComplianceDetail.payroll_line_id == PayrollLine.id)
        .where(PayrollLine.payroll_id == payroll.id, Employee.company_id == company.id)
        .order_by(Employee.full_name, Employee.id)
    ).all()
    if not records:
        raise SalaryImportError(["La nómina cerrada no contiene trabajadores."])
    return payroll, records


def prepare_import(db: Session, company, period: str, authority: str, *,
                   payment_code: str = "", other_category: str = "",
                   rei_category: str = "", name_order: str = "",
                   source_type: str = "payroll", employee_id: int | None = None) -> tuple[list[list], list[str]]:
    """Preflight integral: devuelve filas y TODOS los errores; el archivo se bloquea ante cualquier error."""
    if authority not in {"REOP", "REI"}:
        raise SalaryImportError(["Sistema de destino inválido."])
    from .approved_salary_import import approved_salary_records, choose_salary_source, salary_export_employee_eligible
    if not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", period or ""):
        raise SalaryImportError(["Ingresá un período válido AAAA-MM."])
    try:
        effective_source = choose_salary_source(db, company.id, period, source_type, employee_id=employee_id,
                                                authority=authority)
    except ValueError as exc:
        raise SalaryImportError([str(exc)]) from exc
    if effective_source == "approved":
        records, source_errors, _details = approved_salary_records(
            db, company, period, authority=authority, employee_id=employee_id,
            payment_code=payment_code if authority == "REOP" else "",
        )
    elif effective_source == "mov":
        from .historical_mov_salary_export import mov_salary_records
        records, source_errors, _details = mov_salary_records(
            db, company, period, authority=authority, employee_id=employee_id,
            payment_code=payment_code if authority == "REOP" else "",
        )
    else:
        _payroll, records = _source(db, company, period)
        if employee_id is not None:
            records = [record for record in records if record[1].id == employee_id]
        source_errors = []
    # Filtro de seguridad para AMBOS orígenes y organismos.
    # Nunca armar filas REOP/REI con trabajadores marcados IPS No.
    records = [
        (line, employee, detail) for line, employee, detail in records
        if salary_export_employee_eligible(employee, authority)
    ]
    start = date.fromisoformat(period + "-01")
    end = date(start.year, start.month, monthrange(start.year, start.month)[1])
    errors: list[str] = list(source_errors)
    rows: list[list] = []
    if authority == "REOP":
        if payment_code not in {"1", "2", "3", "4"}:
            errors.append("REOP: seleccioná el código de forma de pago que corresponda al modelo vigente (1-4).")
        if other_category and other_category not in REOP_OTHER_COLUMNS:
            errors.append("REOP: clasificación de otros ingresos inválida.")
        methods = {_text(d.payment_method).casefold() for _, _, d in records
                   if d is not None and _text(d.payment_method)}
        if len(methods) > 1:
            errors.append("REOP: la nómina contiene distintas formas de pago. No se puede usar un único código para todos; revisá cada detalle.")
        elif methods and next(iter(methods)).isdigit() and payment_code != next(iter(methods)):
            errors.append("REOP: el código de forma de pago elegido difiere del registrado en la nómina.")
    else:
        if name_order not in {"apellido_primero", "nombre_primero"}:
            errors.append("REI: confirmá cómo están ordenados los nombres en el legajo.")
        if rei_category and not re.fullmatch(r"[A-Za-z0-9]{1,3}", rei_category):
            errors.append("REI: categoría de asegurado inválida.")
    for line, employee, detail in records:
        context = f"{employee.full_name} (legajo {employee.employee_code or employee.id})"
        err: list[str] = []
        patronal = _patronal(db, company, employee, authority)
        if not patronal or not re.fullmatch(r"[0-9]{1,20}", patronal):
            err.append("falta número patronal numérico del organismo")
        ci = _text(employee.document_number)
        if not ci or not re.fullmatch(r"[0-9A-Za-z-]{2,40}", ci):
            err.append("documento de identidad ausente o con formato inválido")
        gross = _number(line.gross, "Bruto", err)
        discounts = _number(line.total_discounts, "Descuentos", err)
        net = _number(line.net, "Neto", err)
        amounts = [line.base_salary, line.overtime, line.commissions, line.bonuses, line.other_income]
        deductions = [line.absences_discount, line.advances, line.other_discount, line.ips_employee]
        for val in [*amounts, *deductions]:
            _number(val, "Concepto de nómina", err)
        if all(isinstance(v, int) and v >= 0 for v in [*amounts, *deductions]):
            if sum(amounts) != gross:
                err.append("los haberes desglosados no suman el bruto registrado")
            if sum(deductions) != discounts or gross - discounts != net:
                err.append("los descuentos o el neto no concuerdan con el recibo cerrado")
        if gross <= 0:
            err.append("no hay remuneración positiva que comunicar en el período")
        if line.ips_base is None:
            if authority == "REI" or line.ips_employee:
                err.append("falta base imponible IPS guardada")
        else:
            base = _number(line.ips_base, "Base IPS", err)
            if line.ips_rate is None:
                if line.ips_employee:
                    err.append("falta la tasa IPS guardada")
            else:
                rate = Decimal(str(line.ips_rate))
                if not rate.is_finite() or rate < 0 or rate > 100:
                    err.append("tasa IPS inválida")
                elif int((Decimal(base) * rate / Decimal(100)).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )) != line.ips_employee:
                    err.append("la base IPS y el aporte obrero guardados son inconsistentes")
        if detail is None:
            err.append("falta el detalle de días, horas y período del trabajador")
            days, hours, dstart, dend = 0, Decimal(0), start, end
        else:
            days = detail.days_worked
            try:
                hours = Decimal(str(detail.hours_worked or 0))
                hours_invalid = not hours.is_finite() or hours < 0 or hours > 744
            except (ValueError, TypeError, ArithmeticError):
                hours, hours_invalid = Decimal(0), True
            dstart = detail.period_start or start
            dend = detail.period_end or end
            if (detail.period_start is None) != (detail.period_end is None):
                err.append("el período del detalle está incompleto")
            if dstart < start or dend > end or dend < dstart:
                err.append("las fechas del detalle no pertenecen al período")
            if employee.admission_date > dstart:
                err.append("el período comienza antes de la fecha de ingreso")
            if employee.termination_date and employee.termination_date < dend:
                err.append("el período termina después del egreso")
            if not isinstance(days, int) or days > 31:
                err.append("cantidad de jornadas trabajadas fuera del rango 0-31")
            elif days < 0 and effective_source != "approved":
                err.append("cantidad de jornadas trabajadas fuera del rango 0-31")
            # For approved individual calculations, an absent day count (-1)
            # has already been reported in the source preflight.
            if hours_invalid:
                err.append("cantidad de horas trabajadas inválida")
                hours = Decimal(0)
        if authority == "REI":
            if not employee.ips_contributor:
                err.append("funcionario no identificado como aportante IPS")
            profile = db.scalar(select(EmployeeComplianceProfile).where(
                EmployeeComplianceProfile.employee_id == employee.id
            ))
            cat = _text(profile.position_category if profile else "") or rei_category.upper()
            if not re.fullmatch(r"[A-Za-z0-9]{1,3}", cat):
                err.append("falta categoría IPS verificada (por empleado o en el formulario)")
            parts = _text(employee.full_name).split()
            if len(parts) < 2:
                err.append("nombre completo insuficiente para separar nombre y apellido")
                surname = given = ""
            elif name_order == "apellido_primero":
                boundary = 2 if len(parts) > 2 else 1
                surname, given = " ".join(parts[:boundary]), " ".join(parts[boundary:])
            else:
                boundary = -2 if len(parts) > 2 else -1
                given, surname = " ".join(parts[:boundary]), " ".join(parts[boundary:])
            # REI informa los días remunerados guardados, que pueden incluir
            # vacaciones pagadas; no reutilizar las jornadas efectivas REOP.
            rei_days = getattr(detail, "days_rei", days) if detail is not None else days
            fields = [
                patronal, "", ci, surname, given, cat, rei_days,
                line.ips_base if line.ips_base is not None else 0,
                f"{start.month}{start.year}", "",
                gross,
            ]
            if any("\t" in str(v) or "\n" in str(v) for v in fields):
                err.append("el texto contiene separadores no permitidos")
            try:
                "\t".join(str(v) for v in fields).encode("cp1252")
            except UnicodeEncodeError:
                err.append("contiene caracteres no compatibles con el TXT Windows-1252")
        else:
            if detail is None:
                err.append("no se pueden clasificar los haberes sin detalle")
                continue_row = [None] * len(REOP_HEADERS)
            else:
                overtime_day = _number(detail.overtime_day, "Horas extras diurnas", err)
                overtime_night = _number(detail.overtime_night, "Horas extras nocturnas", err)
                if overtime_day + overtime_night != line.overtime:
                    err.append("las horas extras diurnas/nocturnas no concuerdan con el total guardado")
                extra_hours = getattr(detail, "extra_hours", Decimal("0"))
                if line.overtime and not getattr(detail, "extra_hours_documented", False):
                    err.append("faltan cantidades reales de horas extraordinarias (no solo montos) en el registro")
                if line.overtime and (not extra_hours.is_finite() or extra_hours <= 0 or extra_hours > 744):
                    err.append("horas extraordinarias guardadas fuera del rango válido")
                if detail.vacation_pay:
                    err.append("el pago vacacional debe revisarse en su comunicación específica")
                complements = [
                    _number(detail.night_surcharge, "Recargo nocturno", err),
                    _number(detail.holidays, "Feriados", err),
                    _number(detail.family_allowance, "Bonificación familiar", err),
                    _number(detail.other_income_detail, "Otros ingresos detallados", err),
                ]
                pool = line.bonuses + line.other_income
                remainder = pool - sum(complements)
                if remainder < 0:
                    err.append("los beneficios detallados superan bonos y otros ingresos del cálculo")
                allocations = []
                if effective_source == "approved":
                    bonus_value = int(getattr(detail, "other_amount_bonus", 0))
                    income_value = int(getattr(detail, "other_amount_income", 0))
                    if bonus_value + income_value != remainder:
                        err.append("el desglose de bonos/otros ingresos no coincide con el cálculo aprobado")
                    allocations = [
                        (bonus_value, getattr(detail, "other_category_bonus", "") or other_category, "bonificaciones"),
                        (income_value, getattr(detail, "other_category_income", "") or other_category, "otros ingresos"),
                    ]
                elif remainder:
                    allocations = [(remainder, other_category, "otros ingresos de nómina")]
                for value, category, label in allocations:
                    if value and category not in REOP_OTHER_COLUMNS:
                        err.append(f"{label}: otros ingresos no clasificados; elegí la clasificación REOP respaldada para este funcionario")
                if not 0 < hours <= 744 and effective_source != "approved":
                    # Approved-source preflight already emits this same issue
                    # with the calculation ID and worker context.
                    err.append("faltan horas ordinarias efectivamente trabajadas")
                # Las 32 columnas corresponden a la plantilla proporcionada por el usuario.
                continue_row = [
                    patronal, ci, dstart, dend, int(payment_code) if payment_code in {"1", "2", "3", "4"} else 0,
                    getattr(detail, "days_reop", days), 0,
                    int(hours) if hours == int(hours) else float(hours),
                    int(extra_hours) if extra_hours == int(extra_hours) else float(extra_hours),
                    line.base_salary, line.commissions, overtime_day,
                    complements[0], overtime_night, 0, 0, 0, 0, 0,
                    complements[1], 0, complements[3], complements[2], 0,
                    line.advances, line.ips_employee,
                    line.absences_discount,
                    "Ausencias" if line.absences_discount else None,
                    line.other_discount,
                    _text(line.other_discount_note) or "Otros descuentos" if line.other_discount else None,
                    0, None,
                ]
                for value, category, _label in allocations:
                    if value and category in REOP_OTHER_COLUMNS:
                        continue_row[REOP_OTHER_COLUMNS[category]] += value
                if sum(int(continue_row[i] or 0) for i in range(9, 24)) != gross:
                    err.append("los conceptos de ingreso REOP no concuerdan con el bruto guardado")
                if (continue_row[24] + continue_row[25] + continue_row[26] + continue_row[28]) != discounts:
                    err.append("los descuentos REOP no concuerdan con el total guardado")
            fields = continue_row
        if err:
            errors.extend(f"{context}: {problem}." for problem in err)
        rows.append(fields)
    if not rows:
        errors.append(
            "REI: no hay salarios guardados de funcionarios activos con IPS marcado Sí para "
            "esta empresa, período y origen seleccionados."
            if authority == "REI" else
            "REOP: no hay salarios guardados de funcionarios con IPS marcado Sí "
            "para esta empresa, período y origen seleccionados."
        )
    return rows, list(dict.fromkeys(errors))


def _excel_column(index: int) -> str:
    result = ""
    while index:
        index, r = divmod(index - 1, 26)
        result = chr(65 + r) + result
    return result


def build_reop_xlsx(rows: list[list]) -> bytes:
    """XLSX de una sola hoja, encabezados EXACTOS; fechas como números Excel."""
    def cell(value, col: int, row: int) -> str:
        coord = f"{_excel_column(col)}{row}"
        if value is None:
            return ""
        if isinstance(value, date):
            serial = (value - date(1899, 12, 30)).days
            return f'<c r="{coord}" s="1"><v>{serial}</v></c>'
        if isinstance(value, (int, float)):
            return f'<c r="{coord}"><v>{value}</v></c>'
        val = _text(value)
        return f'<c r="{coord}" t="inlineStr"><is><t>{escape(val)}</t></is></c>'
    xmlrows = []
    for row_index, original_values in enumerate([list(REOP_HEADERS), *rows], start=1):
        if len(original_values) != len(REOP_HEADERS):
            raise SalaryImportError(["La estructura REOP requiere exactamente 32 columnas."])
        values = list(original_values)
        if row_index > 1:
            # REOP interpreta incluso un 0 como monto consignado. Si el
            # descuento opcional no existe, ambas celdas deben quedar VACÍAS;
            # escribir 0 junto al concepto vacío provoca CONCEPTO_VACIO.
            for amount_idx, concept_idx in ((26, 27), (28, 29), (30, 31)):
                amount, concept = values[amount_idx], values[concept_idx]
                if amount in (None, "", 0):
                    values[amount_idx] = None
                    values[concept_idx] = None
                elif not _text(concept):
                    raise SalaryImportError([
                        f"Fila {row_index}: {REOP_HEADERS[amount_idx]} tiene importe "
                        f"pero falta {REOP_HEADERS[concept_idx]}."
                    ])
        xmlrows.append('<row r="%d">%s</row>' % (
            row_index, "".join(cell(v, i, row_index) for i, v in enumerate(values, 1))
        ))
    sheet = ('<?xml version="1.0" encoding="utf-8"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             '<sheetData>' + "".join(xmlrows) + '</sheetData></worksheet>')
    parts = {
        "[Content_Types].xml": '''<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>''',
        "_rels/.rels": '''<?xml version="1.0" encoding="utf-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>''',
        "xl/workbook.xml": '''<?xml version="1.0" encoding="utf-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="Hoja1" sheetId="1" r:id="rId1"/></sheets></workbook>''',
        "xl/_rels/workbook.xml.rels": '''<?xml version="1.0" encoding="utf-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>''',
        "xl/styles.xml": '''<?xml version="1.0" encoding="utf-8"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="1"><numFmt numFmtId="164" formatCode="dd/mm/yyyy"/></numFmts>
<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>
<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>
</styleSheet>''',
        "xl/worksheets/sheet1.xml": sheet,
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, data in parts.items():
            archive.writestr(path, data)
    return output.getvalue()


def build_rei_txt(rows: list[list]) -> bytes:
    """TXT tabulado sin encabezados, codificación ANSI/Windows como Excel 2016."""
    out = io.StringIO(newline="")
    writer = csv.writer(out, delimiter="\t", lineterminator="\r\n",
                        quoting=csv.QUOTE_MINIMAL)
    for row in rows:
        if len(row) != len(REI_FIELDS_2016):
            raise SalaryImportError(["La estructura REI 2016 necesita 11 campos."])
        writer.writerow(row)
    return out.getvalue().encode("cp1252")
