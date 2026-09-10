"""Motor de liquidaciones PY. Importes en guaraníes, redondeo comercial por concepto."""
from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

VERSION = "2026.09.1"
SOURCE = "Centro laboral"
TITLES = {"salary": "Liquidación de salario", "settlement": "Liquidación de haberes",
          "aguinaldo": "Aguinaldo", "vacation": "Vacaciones", "hours": "Horas y recargos"}
SOURCES = [
    ("Código del Trabajo · MTESS", "https://www.mtess.gov.py/wp-content/uploads/2026/01/Ley_213.pdf"),
    ("Aportes · IPS", "https://portal.ips.gov.py/sistemas/ipsportal/contenido.php?c=69"),
    ("Base de aporte · IPS", "https://portal.ips.gov.py/sistemas/ipsportal/contenido.php?c=59"),
    ("Vacaciones · MTESS", "https://www.mtess.gov.py/?p=34520"),
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
        for key, label in (("overtime", "Horas extras"), ("commissions", "Comisiones"),
                           ("bonuses", "Bonificaciones remunerativas"), ("other_income", "Otros haberes remunerativos")):
            add(label, number(data, key), "Importe informado")
        proposed_ips_base = sum(row["amount"] for row in earnings)
        if kind == "salary":
            add("Bonificación familiar", number(data, "family"), "Importe y derecho verificados por el liquidador")
            add("Reintegro de gastos documentados", number(data, "reimbursements"), "Importe informado")

    if kind == "settlement":
        start, end = read_date(data, "start_date"), read_date(data, "end_date")
        if end < start:
            raise CalculationError("El egreso no puede ser anterior al ingreso.", "end_date")
        years = completed_years(start, end)
        reason = data.get("reason", "")
        if reason not in {"dismissal", "resignation", "justified", "other"}:
            raise CalculationError("Elegí el motivo de egreso.", "reason")
        result["period"] = end.isoformat()
        fact("Ingreso", start.strftime("%d/%m/%Y"))
        fact("Egreso", end.strftime("%d/%m/%Y"))
        fact("Años completos", years)
        fact("Motivo declarado", {"dismissal": "Despido sin causa", "resignation": "Renuncia",
                                 "justified": "Despido con causa invocada", "other": "Otra causa"}[reason])
        result["partial"] = (years >= 10 or checked(data, "protected") or
                             not checked(data, "indefinite") or reason == "other")
        if result["partial"]:
            result["warnings"].append("Subtotal parcial: estabilidad, protección especial, contrato a plazo u otra causa requieren analizar el régimen aplicable. No se calculan automáticamente indemnización ni preaviso.")
        elif reason == "dismissal" and checked(data, "trial_completed"):
            average = positive(data, "average_salary", "promedio salarial de los últimos seis meses o menor tiempo de servicio")
            last_anniversary = anniversary(start, years)
            units = years + int(end > anniversary(last_anniversary, months=6))
            severance = amount(average / 30 * 15 * units)
            add("Indemnización ordinaria", severance, f"Gs. {gs(average)} / 30 × 15 × {units}", "Arts. 91 y 92")
            due = notice_days(start, end)
            served = number(data, "notice_served", "días de preaviso cumplidos", maximum=str(due))
            notice = amount(average / 30 * (due - served))
            add("Preaviso omitido por el empleador", notice, f"Gs. {gs(average)} / 30 × {Decimal(due) - served}", "Arts. 87, 90 y 92")
            protected += severance + notice
            fact("Preaviso legal", f"{due} días")
            result["notes"].append("Indemnización: la fracción restante cuenta solamente si supera seis meses. Revisar conceptos del promedio y beneficios más favorables.")
        elif reason == "resignation":
            result["notes"].append("La eventual compensación por falta de preaviso del trabajador requiere análisis separado; no se descuenta automáticamente.")
        elif reason == "justified":
            result["warnings"].append("La causa invocada debe estar acreditada. Este cálculo no determina si el despido fue justificado.")
        elif not checked(data, "trial_completed"):
            result["warnings"].append("No se incluyeron preaviso ni indemnización ordinaria: verificá la vigencia del período de prueba.")
        simple = number(data, "pending_days", "vacaciones pendientes simples", maximum="365", decimals=2)
        double = number(data, "double_days", "vacaciones pendientes dobles", maximum="365", decimals=2)
        proportional = number(data, "proportional_days", "vacaciones proporcionales", maximum="30", decimals=2)
        add("Vacaciones pendientes", salary / 30 * simple, f"Gs. {gs(salary)} / 30 × {simple}", "Art. 221")
        add("Vacaciones pendientes con pago doble", salary / 30 * double * 2, f"Gs. {gs(salary)} / 30 × {double} × 2", "Arts. 221 y 223; procedencia revisada")
        add("Vacaciones proporcionales", salary / 30 * proportional, f"Gs. {gs(salary)} / 30 × {proportional}", "Art. 221; procedencia revisada")
        fact("Escala anual orientativa", f"{vacation_days(start, end)} días hábiles")
        result["notes"].append("Los días de vacaciones se ingresan una sola vez: simples, dobles o proporcionales. La proporcionalidad y duplicación dependen de la causa, los períodos adquiridos y los plazos de goce.")
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
    if any(not identity[key] for key in ("employer", "ruc", "employee", "ci")):
        result["warnings"].append("Completá empleador, RUC, trabajador y documento antes de emitir un recibo para firma.")
    if note := clean(data.get("notes"), 600):
        result["notes"].append(note)
    result["notes"].append("Redondeo comercial a guaraníes enteros por concepto; el total suma los importes mostrados.")
    return result
