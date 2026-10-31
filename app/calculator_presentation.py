"""Presentation of the existing calculator; no financial formulas live here."""
from .calculator_fields import GROUPS


def quick_steps(kind):
    if kind not in {"salary", "settlement"}:
        return []
    groups = {group["title"]: group for group in GROUPS[kind]}
    if kind == "settlement":
        relationship = groups["Relación laboral"]
        contract_names = {"indefinite", "trial_completed", "protected"}
        base = dict(relationship, fields=[f for f in relationship["fields"] if f["name"] not in contract_names])
        contract = dict(relationship, title="Modalidad del vínculo", fields=[
            f for f in relationship["fields"] if f["name"] in contract_names])
        sections = [
            ("Datos base", "Salario, fechas y motivo", [base]),
            ("Indemnización y preaviso", "Días automáticos y régimen revisado", [contract, groups["Indemnización y preaviso"]]),
            ("Vacaciones y aguinaldo", "Días reconocidos y remuneración anual", [groups["Vacaciones pendientes"], groups["Aguinaldo"]]),
            ("Aportes y descuentos", "IPS, otros haberes y retenciones", [groups["Otros haberes"], groups["Aportes y descuentos"]]),
        ]
    else:
        sections = [
            ("Datos base", "Período, salario y días", [groups["Salario del período"]]),
            ("Horas y recargos", "Nocturnas, extras y feriados", [groups["Horas nocturnas, extras y feriados"], groups["Bases horarias y ajustes excepcionales"]]),
            ("Otros haberes", "Comisiones, bonificaciones y asignación familiar", [groups[t] for t in ("Haberes adicionales", "Asignación familiar", "Mínimo legal especial", "Conceptos separados")]),
            ("Aportes y descuentos", "Base IPS y retenciones", [groups["Aportes y descuentos"]]),
        ]
    sections.append(("Confirmación y documento", "Identificación, revisión y descarga", [groups["Revisar un recibo"], groups["Datos del documento"]]))
    return [dict(number=i, title=title, hint=hint, groups=items)
            for i, (title, hint, items) in enumerate(sections, 1)]


def calculation_summary(result):
    """Only summarize amounts the authoritative engine has already calculated."""
    values = dict(salary=0, aguinaldo=0, vacations=0, severance=0, notice=0, other=0, ips=0, other_discounts=0)
    for row in result["earnings"]:
        label = row["label"]
        key = ("salary" if label == "Salario del período" else
               "aguinaldo" if label == "Aguinaldo devengado" else
               "vacations" if label.startswith("Vacaciones ") else
               "notice" if label == "Indemnización por preaviso no cumplido" else
               "severance" if label.startswith("Indemnización ") else "other")
        values[key] += row["amount"]
    for row in result["deductions"]:
        values["ips" if row["label"] == "Aporte IPS del trabajador" else "other_discounts"] += row["amount"]
    return dict(values=values, net=result["net"], gross=result["gross"], discounts=result["discounts"],
                partial=result["partial"], label="Subtotal parcial" if result["partial"] else "Total a cobrar",
                warnings=result["warnings"], status=result["status"])
