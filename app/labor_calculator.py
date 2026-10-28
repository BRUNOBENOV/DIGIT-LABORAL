"""Motor de liquidaciones PY. Importes en guaraníes, redondeo comercial por concepto."""
from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from .labor_wage_rules import minimum_wage_for_period

VERSION = "2026.10.2"
SOURCE = "Centro laboral"
TITLES = {"salary": "Liquidación de salario", "settlement": "Liquidación de haberes",
          "aguinaldo": "Aguinaldo", "vacation": "Vacaciones", "hours": "Horas y recargos"}
SOURCES = [
    ("Código del Trabajo · Ley N.º 213/93 · arts. 78, 84–94", "https://www.mtess.gov.py/wp-content/uploads/2026/01/Ley_213.pdf"),
    ("Aportes · IPS", "https://portal.ips.gov.py/sistemas/ipsportal/contenido.php?c=69"),
    ("Base de aporte · IPS", "https://portal.ips.gov.py/sistemas/ipsportal/contenido.php?c=59"),
    ("Vacaciones · MTESS", "https://www.mtess.gov.py/?p=34520"),
    ("Salario mínimo vigente · Resolución MTESS N.º 670/2026", "https://www.mtess.gov.py/?p=36371"),
    ("Salario mínimo anterior · Resolución MTESS N.º 677/2025", "https://www.mtess.gov.py/?p=30682"),
    ("Asignación familiar · Código del Trabajo, arts. 261–268", "https://www.mtess.gov.py/wp-content/uploads/2026/01/Ley_213.pdf"),
    ("Guía MTESS · Liquidación de salarios", "https://www.mtess.gov.py/wp-content/uploads/2025/10/Guia-liquidacion-de-salarios-v1.pdf"),
]
ZERO = Decimal(0)


class CalculationError(ValueError):
    def __init__(self, message, field=""):
        super().__init__(message)
        self.field = field


def amount(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def gs(value):
    return f"{amount(value):,}".replace(",", ".")


def clean(value, limit=300):
    return "".join(c for c in str(value or "") if c.isprintable()).strip()[:limit]


def checked(data, key):
    return str(data.get(key, "")).lower() in {"on", "true", "1", "yes"}


def number(data, key, label=None, *, default="0", maximum="100000000000", required=False, decimals=0):
    raw = str(data.get(key, "")).strip()
    label = label or key
    if not raw and required:
        raise CalculationError(f"Completá {label}.", key)
    try:
        value = Decimal(raw or default)
    except (InvalidOperation, ValueError):
        raise CalculationError(f"Revisá {label}: ingresá un número sin separadores de miles.", key)
    if not value.is_finite() or value < 0 or value > Decimal(maximum):
        raise CalculationError(f"Revisá {label}: el valor debe estar entre 0 y {maximum}.", key)
    if value != value.quantize(Decimal(1).scaleb(-decimals)):
        raise CalculationError(f"{label}: se admiten hasta {decimals} decimales.", key)
    return value


def positive(data, key, label=None):
    value = number(data, key, label, required=True)
    if value <= 0:
        raise CalculationError(f"{label or key} debe ser mayor que cero.", key)
    return value


def read_date(data, key):
    try:
        value = date.fromisoformat(str(data.get(key, "")))
        if not 1900 <= value.year <= 2100:
            raise ValueError
        return value
    except ValueError:
        raise CalculationError("Ingresá una fecha válida entre 1900 y 2100.", key)


def anniversary(start, years=0, months=0):
    index = start.year * 12 + start.month - 1 + years * 12 + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(start.day, monthrange(year, month)[1]))


def completed_years(start, end):
    years = end.year - start.year
    return max(0, years - int(end < anniversary(start, years)))


def notice_days(start, end):
    if end < start:
        raise CalculationError("El egreso no puede ser anterior al ingreso.", "end_date")
    for years, days in ((1, 30), (5, 45), (10, 60)):
        if end <= anniversary(start, years):
            return days
    return 90


def vacation_days(start, end):
    if end < anniversary(start, 1):
        return 0
    if end <= anniversary(start, 5):
        return 12
    return 18 if end <= anniversary(start, 10) else 30


def calculate(data):
    kind = data.get("kind", "salary")
    if kind not in TITLES:
        raise CalculationError("Elegí un tipo de cálculo válido.", "kind")
    issued = read_date(data, "issued_date")
    identity = {key: clean(data.get(key), 180) for key in
                ("employer", "ruc", "employee", "ci", "position", "prepared_by", "payment_method", "reference")}
    result = dict(kind=kind, title=TITLES[kind], engine_version=VERSION, identity=identity,
                  issued_date=issued.strftime("%d/%m/%Y"), period="", earnings=[], deductions=[],
                  facts=[], warnings=[], notes=[], sources=SOURCES, partial=False,
                  status="Borrador · pendiente de revisión, pago y firma",
                  copies=2 if checked(data, "two_copies") else 1, employer_contribution=0)
    earnings, deductions = result["earnings"], result["deductions"]

    def add(label, value, formula="", legal="", deduction=False):
        value = amount(value)
        if value:
            (deductions if deduction else earnings).append(
                dict(label=label, amount=value, formula=formula, legal=legal))

    def fact(label, value):
        result["facts"].append(dict(label=label, value=str(value)))

    protected = 0
    proposed_ips_base = 0
    salary = ZERO
    if kind in {"salary", "settlement", "vacation"}:
        salary = positive(data, "salary", "salario mensual")
    if kind in {"salary", "settlement"}:
        days = number(data, "days_paid", "días a liquidar", required=True, maximum="30")
        add("Salario del período", salary / 30 * days, f"Gs. {gs(salary)} / 30 × {days} días", "Base mensual")
        fact("Días a liquidar (base 30)", days)
        if kind == "salary":
            period = str(data.get("month", ""))
            try:
                if len(period) != 7:
                    raise ValueError
                date.fromisoformat(period + "-01")
            except ValueError:
                raise CalculationError("Seleccioná el mes liquidado.", "month")
            result["period"] = period
            if str(data.get("days_worked", "")).strip():
                fact("Jornadas trabajadas", number(data, "days_worked", maximum="31"))
            else:
                result["warnings"].append("Completá las jornadas trabajadas antes de firmar el recibo (art. 235).")
        if kind == "salary":
            period_categories = str(data.get("minimum_wage_category") or "general_day")
            overtime_components = (
                ("night_premium_hours", "Recargo nocturno ordinario (30 % adicional)", Decimal("0.30"), "day", "premium"),
                ("day_extra_hours", "Horas extraordinarias diurnas (mínimo 50 %)", Decimal("1.50"), "day", "full"),
                ("night_extra_hours", "Horas extraordinarias nocturnas (100 %)", Decimal("2.00"), "night", "full"),
                ("holiday_hours", "Recargo por trabajo en feriado (100 % adicional)", Decimal("1.00"), "day", "premium"),
            )
            quantities = {
                key: number(data, key, label, maximum="744", decimals=2)
                for key, label, _factor, _base_type, _payment_type in overtime_components
            }
            total_component_hours = sum(quantities.values(), ZERO)
            manual_overtime = number(data, "overtime", "ajuste manual de horas extras")
            if total_component_hours and manual_overtime:
                raise CalculationError(
                    "Elegí cargar las horas por tipo o registrar un importe manual excepcional; no se pueden combinar porque duplicarían haberes.",
                    "overtime"
                )
            has_day_components = any(quantities[key] for key, _label, _factor, base_type, _payment_type in overtime_components if base_type == "day")
            has_night_components = any(quantities[key] for key, _label, _factor, base_type, _payment_type in overtime_components if base_type == "night")
            raw_day_base = str(data.get("overtime_day_hourly_base", "")).strip()
            raw_night_base = str(data.get("overtime_night_hourly_base", "")).strip()
            day_base = None
            night_base = None
            if has_day_components:
                if raw_day_base:
                    day_base = number(data, "overtime_day_hourly_base", "valor de hora diurna", decimals=4)
                elif period_categories == "general_day":
                    day_base = salary / Decimal("240")
                elif period_categories == "general_night":
                    day_base = salary / (Decimal("1.30") * Decimal("240"))
                else:
                    raise CalculationError(
                        "Para esta escala salarial debés ingresar la base horaria diurna revisada en «Bases horarias y ajustes excepcionales».",
                        "overtime_day_hourly_base"
                    )
                if day_base <= ZERO:
                    raise CalculationError("La base horaria diurna debe ser mayor que cero.", "overtime_day_hourly_base")
                fact("Base horaria diurna aplicada", f"Gs. {day_base:.4f}")
            if has_night_components:
                if raw_night_base:
                    night_base = number(data, "overtime_night_hourly_base", "valor de hora nocturna", decimals=4)
                elif period_categories == "general_day":
                    night_base = salary * Decimal("1.30") / Decimal("210")
                elif period_categories == "general_night":
                    night_base = salary / Decimal("210")
                else:
                    raise CalculationError(
                        "Para esta escala salarial debés ingresar la base horaria nocturna revisada en «Bases horarias y ajustes excepcionales».",
                        "overtime_night_hourly_base"
                    )
                if night_base <= ZERO:
                    raise CalculationError("La base horaria nocturna debe ser mayor que cero.", "overtime_night_hourly_base")
                fact("Base horaria nocturna aplicada", f"Gs. {night_base:.4f}")
            if quantities["night_premium_hours"] and period_categories == "general_night":
                raise CalculationError(
                    "El salario de la escala nocturna ya incorpora el recargo nocturno ordinario. No lo sumes de nuevo; revisá la base salarial antes de cambiar la escala.",
                    "night_premium_hours"
                )
            if total_component_hours:
                for key, label, factor, base_type, payment_type in overtime_components:
                    quantity = quantities[key]
                    if not quantity:
                        continue
                    hourly_base = day_base if base_type == "day" else night_base
                    description = (
                        "Solo adicional sobre el salario mensual" if payment_type == "premium"
                        else "Pago de la hora extraordinaria, incluida su remuneración ordinaria"
                    )
                    add(
                        label, hourly_base * quantity * factor,
                        f"Gs. {hourly_base} × {quantity} × {factor}",
                        description + "; verificar jornada, base, solapamientos y régimen aplicable."
                    )
                if quantities["holiday_hours"] and (
                    quantities["night_premium_hours"] or quantities["day_extra_hours"] or quantities["night_extra_hours"]
                ):
                    result["warnings"].append(
                        "Se cargaron horas feriadas junto con otras categorías horarias. Verificá que no representen las mismas horas y revisá la acumulación legal de recargos antes de aprobar."
                    )
            elif manual_overtime:
                add("Horas extras (importe manual)", manual_overtime, "Importe manual informado")
                result["warnings"].append(
                    "Se utilizó un importe manual de horas extras por compatibilidad o excepción. Verificá su respaldo y que no duplique horas incorporadas en otro concepto."
                )
        else:
            add("Horas extras", number(data, "overtime"), "Importe informado")
        for key, label in (("commissions", "Comisiones"),
                           ("bonuses", "Bonificaciones remunerativas"),
                           ("other_income", "Otros haberes remunerativos")):
            add(label, number(data, key), "Importe informado")
        proposed_ips_base = sum(row["amount"] for row in earnings)
        if kind == "salary":
            category = str(data.get("minimum_wage_category") or "general_day")
            manual_minimum = number(data, "minimum_wage_manual", "mínimo mensual especial")
            wage_rule = minimum_wage_for_period(period, category, manual_minimum)
            minimum = wage_rule.get("amount")

            if minimum:
                fact("Escala de mínimo legal", wage_rule["label"])
                fact("Mínimo legal mensual de referencia", "Gs. " + gs(minimum))
                if wage_rule.get("effective_from"):
                    fact("Vigencia del mínimo usado", wage_rule["effective_from"].strftime("%d/%m/%Y"))
                if salary < minimum:
                    difference = int(minimum) - int(salary)
                    fact("Diferencia de la base frente al mínimo", "Gs. " + gs(difference))
                    result["warnings"].append(
                        f"La base mensual ingresada (Gs. {gs(salary)}) está por debajo del mínimo de referencia "
                        f"(Gs. {gs(minimum)}; diferencia Gs. {gs(difference)}). Verificá la jornada, la categoría "
                        "legal, la escala de la actividad y el período antes de emitir el recibo."
                    )
            elif wage_rule.get("reason") == "manual_required":
                result["warnings"].append(
                    "La actividad seleccionada requiere un mínimo especial. Abrí «Mínimo legal especial» e ingresá "
                    "el importe mensual vigente para esa actividad antes de validar el salario."
                )
            elif wage_rule.get("reason") == "historical_scale_unavailable":
                result["warnings"].append(
                    "No hay una escala automática de salario mínimo cargada para este período anterior a julio de 2025. "
                    "Verificá manualmente la resolución vigente antes de emitir el recibo."
                )
            elif wage_rule.get("reason") == "unknown_category":
                raise CalculationError("Elegí una escala de salario mínimo reconocida.", "minimum_wage_category")

            family_children = number(data, "family_children", "cantidad de hijos con derecho", maximum="20")
            family_manual = number(data, "family", "bonificación familiar manual")
            family_verified = checked(data, "family_right_verified")
            if family_children:
                if not family_verified:
                    result["warnings"].append(
                        "Se declararon hijos para la asignación familiar, pero no se confirmó el derecho, la "
                        "documentación y la comunicación escrita al empleador. No se agregó la asignación automática."
                    )
                    if family_manual:
                        result["warnings"].append(
                            "El importe manual de bonificación familiar no se aplicó porque hay hijos declarados "
                            "sin confirmación documental."
                        )
                elif family_manual:
                    raise CalculationError(
                        "Usá la cantidad de hijos para calcular la asignación familiar automática o el importe manual "
                        "para una excepción, pero no ambos.", "family"
                    )
                elif minimum is None:
                    result["warnings"].append(
                        "No se calculó automáticamente la asignación familiar porque no se pudo determinar el mínimo "
                        "legal mensual de referencia para este período y categoría."
                    )
                elif Decimal(proposed_ips_base) > Decimal(minimum) * 2:
                    result["warnings"].append(
                        "No se agregó automáticamente la asignación familiar: la base mensual supera el límite de "
                        "dos salarios mínimos indicado en el artículo 263. Verificá la remuneración y el régimen aplicable."
                    )
                else:
                    per_child = amount(Decimal(minimum) * Decimal("0.05"))
                    family_total = per_child * int(family_children)
                    add("Bonificación familiar", family_total,
                        f"Gs. {gs(minimum)} × 5% × {int(family_children)} hijo(s)",
                        "Arts. 261–268; derecho y comunicación documental confirmados por el liquidador")
                    fact("Hijos con derecho a asignación familiar", int(family_children))
                    fact("Asignación familiar por hijo", "Gs. " + gs(per_child))
            elif family_manual:
                add("Bonificación familiar manual", family_manual,
                    "Importe ingresado por el liquidador; revisar derecho, vigencia y soporte documental",
                    "Arts. 261–268; revisión manual")
                result["warnings"].append(
                    "La bonificación familiar fue ingresada manualmente. Verificá el salario mínimo aplicable, "
                    "el límite de remuneración, la comunicación escrita, la documentación y el derecho por cada hijo."
                )
            add("Reintegro de gastos documentados", number(data, "reimbursements"), "Importe informado")

    if kind == "settlement":
        start, end = read_date(data, "start_date"), read_date(data, "end_date")
        if end < start:
            raise CalculationError("El egreso no puede ser anterior al ingreso.", "end_date")
        years = completed_years(start, end)
        months = 0
        while months < 11 and anniversary(start, years, months + 1) <= end:
            months += 1
        tenure_anchor = anniversary(start, years, months)
        tenure_days = (end - tenure_anchor).days
        reason = data.get("reason", "")
        reason_labels = {
            "dismissal": "Despido sin causa",
            "resignation": "Renuncia voluntaria",
            "justified": "Despido con causa invocada por el empleador",
            "worker_justified": "Retiro justificado por causa imputable al empleador",
            "fixed_term_expiration": "Vencimiento de contrato a plazo / fin de obra",
            "mutual_consent": "Mutuo consentimiento",
            "death": "Fallecimiento del trabajador",
            "other": "Otra causa o caso especial",
        }
        if reason not in reason_labels:
            raise CalculationError("Elegí el motivo de egreso.", "reason")
        result["period"] = end.isoformat()
        fact("Ingreso", start.strftime("%d/%m/%Y"))
        fact("Egreso", end.strftime("%d/%m/%Y"))
        fact("Años completos", years)
        fact("Antigüedad exacta", f"{years} {('año' if years == 1 else 'años')}, {months} {('mes' if months == 1 else 'meses')} y {tenure_days} {('día' if tenure_days == 1 else 'días')}")
        fact("Días calendario del vínculo", (end - start).days + 1)
        fact("Motivo declarado", reason_labels[reason])

        # Las causales especiales no deben quedar presentadas como una liquidación definitiva.
        special_severance_regime = (
            years >= 10 or checked(data, "protected") or not checked(data, "indefinite")
        )
        within_probation = (
            reason in {"dismissal", "worker_justified"} and not checked(data, "trial_completed")
        )
        result["partial"] = (
            special_severance_regime
            or within_probation
            or reason in {"justified", "worker_justified", "fixed_term_expiration", "mutual_consent", "death", "other"}
        )

        if special_severance_regime:
            result["warnings"].append(
                "Subtotal parcial: el caso activa estabilidad de diez años, protección especial o contrato no indefinido. "
                "No se agrega automáticamente indemnización ordinaria ni preaviso; verificá el régimen aplicable y la documentación."
            )
            if years >= 10:
                result["warnings"].append(
                    "Con diez años de antigüedad o más debe revisarse la estabilidad laboral (artículo 94) y sus excepciones antes de emitir."
                )
            if checked(data, "protected"):
                result["warnings"].append(
                    "Se declaró protección laboral especial. Revisá la tutela aplicable; este motor no determina si el despido es válido."
                )
            if not checked(data, "indefinite"):
                result["warnings"].append(
                    "El vínculo no está marcado como indefinido. Verificá la modalidad y el vencimiento contractual; se omitió la fórmula ordinaria."
                )
        elif reason in {"dismissal", "worker_justified"} and checked(data, "trial_completed"):
            average = positive(data, "average_salary", "promedio salarial de los últimos seis meses o menor tiempo de servicio")
            last_anniversary = anniversary(start, years)
            units = years + int(end > anniversary(last_anniversary, months=6))
            severance = amount(average / 30 * 15 * units)
            severance_legal = "Arts. 85, 91 y 92" if reason == "worker_justified" else "Arts. 91 y 92"
            add(
                "Indemnización ordinaria por antigüedad", severance,
                f"Gs. {gs(average)} / 30 × 15 × {units}", severance_legal
            )
            due = notice_days(start, end)
            served = number(data, "notice_served", "días de preaviso cumplidos", maximum=str(due))
            notice = amount(average / 30 * (due - served))
            notice_legal = "Arts. 85, 87, 90 y 92" if reason == "worker_justified" else "Arts. 87, 90 y 92"
            add(
                "Indemnización por preaviso no cumplido", notice,
                f"Gs. {gs(average)} / 30 × {Decimal(due) - served}", notice_legal
            )
            protected += severance + notice
            fact("Preaviso legal de referencia", f"{due} días")
            result["notes"].append(
                "La indemnización ordinaria utiliza el promedio salarial de los últimos seis meses o el menor tiempo trabajado. "
                "La fracción adicional se considera si supera seis meses; revisá los conceptos computables y cualquier régimen especial."
            )
            if reason == "worker_justified":
                result["warnings"].append(
                    "Escenario condicionado: el retiro justificado exige acreditar una causa imputable al empleador prevista en el artículo 84. "
                    "La procedencia de las indemnizaciones de los artículos 85 y 187 requiere revisión profesional y, si hay controversia, puede depender de decisión competente."
                )
        elif reason in {"dismissal", "worker_justified"}:
            result["warnings"].append(
                "No se calcularon indemnización ni preaviso ordinarios porque no se confirmó la conclusión del período de prueba. "
                "Verificá las fechas, la categoría laboral y el régimen aplicable antes de aprobar."
            )
        elif reason == "resignation":
            result["notes"].append(
                "La renuncia voluntaria no activa por sí sola la indemnización ordinaria por despido. "
                "No se descuenta automáticamente una eventual compensación por falta de preaviso del trabajador."
            )
        elif reason == "justified":
            result["warnings"].append(
                "El empleador invoca una causa de despido. El motor no declara probada esa causa ni resuelve controversias; "
                "el resultado es un subtotal sujeto a revisión del artículo 82 y del expediente."
            )
        elif reason == "fixed_term_expiration":
            result["warnings"].append(
                "Verificá la validez del contrato a plazo/obra, el vencimiento pactado y si hubo terminación anticipada. "
                "Una terminación injustificada anterior al vencimiento puede requerir determinación judicial (artículo 83)."
            )
        elif reason == "mutual_consent":
            result["warnings"].append(
                "El mutuo consentimiento debe cumplir la forma prevista en el artículo 78(b). El cálculo no acredita el acuerdo, su formalización ni el pago."
            )
        elif reason == "death":
            result["warnings"].append(
                "El fallecimiento requiere verificar herederos, beneficiarios y la indemnización especial prevista por el artículo 91. "
                "No se estima automáticamente esa prestación."
            )
        elif reason == "other":
            result["warnings"].append(
                "La causal no está parametrizada como supuesto ordinario. El resultado queda como subtotal hasta documentar y revisar el régimen aplicable."
            )

        simple = number(data, "pending_days", "vacaciones pendientes simples", maximum="365", decimals=2)
        double = number(data, "double_days", "vacaciones pendientes dobles", maximum="365", decimals=2)
        proportional = number(data, "proportional_days", "vacaciones proporcionales", maximum="30", decimals=2)
        add("Vacaciones pendientes", salary / 30 * simple, f"Gs. {gs(salary)} / 30 × {simple}", "Arts. 218 y 221")
        add("Vacaciones pendientes con pago doble", salary / 30 * double * 2, f"Gs. {gs(salary)} / 30 × {double} × 2", "Art. 223; procedencia revisada")
        add("Vacaciones proporcionales", salary / 30 * proportional, f"Gs. {gs(salary)} / 30 × {proportional}", "Art. 221; causal y días reconocidos por el liquidador")
        fact("Escala anual orientativa", f"{vacation_days(start, end)} días hábiles")
        result["notes"].append(
            "Los días de vacaciones simples, dobles y proporcionales se ingresan por separado y solo una vez. "
            "La proporcionalidad y duplicación dependen de la causal, los períodos adquiridos y los plazos de goce; verificá el derecho antes de aprobar."
        )
    if kind in {"settlement", "aguinaldo"}:
        annual = number(data, "annual_remuneration", "remuneraciones computables del año", required=True)
        if kind == "settlement" and annual < proposed_ips_base:
            raise CalculationError("La base anual debe incluir los haberes remunerativos de este egreso.", "annual_remuneration")
        accrued = amount(annual / 12)
        paid = number(data, "aguinaldo_paid", "aguinaldo ya abonado")
        if paid > accrued:
            raise CalculationError("El aguinaldo ya abonado supera el devengado.", "aguinaldo_paid")
        add("Aguinaldo devengado", accrued, f"Gs. {gs(annual)} / 12", "Arts. 243 y 244")
        add("Aguinaldo ya abonado", paid, "Pago previo informado", deduction=True)
        protected += accrued - int(paid)
        if kind == "aguinaldo":
            year = number(data, "year", "año", required=True, maximum="2100")
            if year < 1900:
                raise CalculationError("Ingresá un año entre 1900 y 2100.", "year")
            result["period"] = str(year)
        result["notes"].append("La base anual comprende remuneraciones computables; el aguinaldo se calcula antes de descuentos y no lleva aporte IPS.")
    if kind == "vacation":
        minimum = positive(data, "legal_minimum", "mínimo legal aplicable al período y actividad")
        base = max(salary, minimum)
        days = number(data, "vacation_quantity", "días hábiles", required=True, maximum="365", decimals=2)
        factor = 2 if checked(data, "vacation_double") else 1
        add("Remuneración de vacaciones", base / 30 * days * factor,
            f"Gs. {gs(base)} / 30 × {days} × {factor}", "Arts. 218, 220 y 223")
        fact("Días hábiles", days)
        result["notes"].append("Importe bruto a pagar por adelantado. Verificá el derecho y la duplicación; no sumes otra vez estos días a un salario mensual ya pagado. Los aportes se concilian en la nómina.")
    if kind == "hours":
        base = number(data, "hourly_base", "valor de la hora ordinaria", required=True, decimals=4)
        if base <= 0:
            raise CalculationError("El valor de la hora debe ser mayor que cero.", "hourly_base")
        quantity = number(data, "hours", "horas", required=True, maximum="744", decimals=2)
        mode = data.get("hour_type", "")
        modes = {"day_extra": ("Extra diurna", "1.5", "hora ordinaria diurna"),
                 "night": ("Ordinaria nocturna", "1.3", "hora ordinaria diurna"),
                 "night_extra": ("Extra nocturna", "2", "hora ordinaria nocturna"),
                 "holiday": ("Feriado", "2", "hora ordinaria aplicable")}
        if mode not in modes:
            raise CalculationError("Elegí el tipo de hora.", "hour_type")
        label, factor, basis = modes[mode]
        add(label, base * quantity * Decimal(factor), f"Gs. {base} × {quantity} × {factor}", "Art. 234")
        fact("Base que debés ingresar", basis)
        result["notes"].append("Total bruto por esas horas, incluida la parte ordinaria. Evitá duplicarla si ya está incluida en el salario. No determina límites de jornada ni legalidad del horario.")

    if kind in {"salary", "settlement"}:
        if checked(data, "apply_ips"):
            rate = number(data, "ips_rate", "tasa IPS del trabajador", default="9", maximum="100", decimals=2)
            employer_rate = number(data, "employer_rate", "tasa IPS patronal", default="16.5", maximum="100", decimals=2)
            raw_base = str(data.get("ips_base", "")).strip()
            if kind == "settlement" and not raw_base:
                raise CalculationError("Ingresá la base IPS revisada para este egreso, incluso si es cero.", "ips_base")
            base = number(data, "ips_base") if raw_base else Decimal(proposed_ips_base)
            basis_note = clean(data.get("ips_reason"))
            if (kind == "settlement" or base != proposed_ips_base) and not basis_note:
                raise CalculationError("Explicá el criterio utilizado para la base IPS.", "ips_reason")
            add("Aporte IPS del trabajador", base * rate / 100, f"Gs. {gs(base)} × {rate}%", "Régimen y base declarados", deduction=True)
            fact("Base IPS", f"Gs. {gs(base)}")
            if basis_note:
                result["notes"].append("Criterio IPS: " + basis_note)
            if kind == "salary":
                result["employer_contribution"] = amount(base * employer_rate / 100)
            else:
                result["warnings"].append("La base IPS del egreso fue ingresada manualmente. Revisar qué conceptos integran el salario cotizado según el régimen.")
        advances = number(data, "advances", "anticipos")
        other = number(data, "other_discount", "otros descuentos")
        reason = clean(data.get("discount_reason"))
        if (advances or other) and not reason:
            raise CalculationError("Describí el respaldo y motivo de los descuentos.", "discount_reason")
        # No compensar créditos del empleador contra aguinaldo, preaviso o indemnización protegidos.
        available = sum(r["amount"] for r in earnings) - sum(r["amount"] for r in deductions) - protected
        if kind == "settlement" and advances + other > max(0, available):
            raise CalculationError("Los descuentos adicionales afectarían conceptos protegidos; revisalos por separado.", "other_discount")
        add("Anticipos documentados", advances, reason, deduction=True)
        add("Otros descuentos autorizados", other, reason, deduction=True)

    result["gross"] = sum(row["amount"] for row in earnings)
    result["discounts"] = sum(row["amount"] for row in deductions)
    result["net"] = result["gross"] - result["discounts"]
    if result["net"] < 0:
        raise CalculationError("Los descuentos superan los haberes. Revisá los importes; no se reemplaza un saldo negativo por cero.")
    result["net_label"] = ("Subtotal parcial" if result["partial"] else
                           "Total bruto" if kind in {"vacation", "hours"} else "Neto a percibir")
    result["employer_cost"] = result["gross"] + result["employer_contribution"] if kind == "salary" else None
    if kind in {"salary", "settlement"} and str(data.get("reported_net", "")).strip():
        reported = int(number(data, "reported_net", "neto informado en el recibo"))
        difference = result["net"] - reported
        result["receipt_review"] = dict(reported=reported, difference=difference)
        fact("Neto informado en el recibo", "Gs. " + gs(reported))
        fact("Diferencia (calculado menos informado)", "Gs. " + gs(difference))
        result["notes"].append("La diferencia compara los importes según los datos ingresados; no acredita un pago ni determina por sí sola una deuda. Revisá período, conceptos y comprobantes.")
    if any(not identity[key] for key in ("employer", "ruc", "employee", "ci")):
        result["warnings"].append("Completá empleador, RUC, trabajador y documento antes de emitir un recibo para firma.")
    if note := clean(data.get("notes"), 600):
        result["notes"].append(note)
    result["notes"].append("Redondeo comercial a guaraníes enteros por concepto; el total suma los importes mostrados.")
    return result
