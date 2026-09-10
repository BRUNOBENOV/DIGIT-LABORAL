"""Campos compartidos por el formulario público y el profesional."""
def field(name, label, kind="number", value="", help="", required=False, **attrs):
    if kind == "number":
        attrs = {"min": "0", "max": "100000000000", "step": "1", **attrs}
    return dict(name=name, label=label, type=kind, value=value, help=help, required=required, attrs=attrs)

def group(title, fields, advanced=False):
    return dict(title=title, fields=fields, advanced=advanced)

SALARY = field("salary", "Salario mensual · Gs.", required=True, min="1")
DAYS = field("days_paid", "Días a liquidar", value="30", max="30",
             help="Para remuneración mensual se utiliza base de 30 días.", required=True)
EXTRAS = group("Otros haberes", [
    field("overtime", "Horas extras liquidadas · Gs."), field("commissions", "Comisiones · Gs."),
    field("bonuses", "Bonificaciones remunerativas · Gs."), field("other_income", "Otros haberes remunerativos · Gs.")], True)
IPS = group("Aportes y descuentos", [
    field("apply_ips", "Aplicar aporte IPS", "checkbox", "on"),
    field("ips_rate", "IPS trabajador · %", value="9", max="100", step="0.01"),
    field("employer_rate", "IPS empleador · %", value="16.5", max="100", step="0.01",
          help="El aporte patronal no se descuenta al trabajador."),
    field("ips_base", "Base IPS revisada · Gs.", help="Salario: vacío propone haberes remunerativos. Egreso: completar siempre, incluso cero. Verificá la base mínima y el régimen."),
    field("ips_reason", "Criterio de la base IPS", "text", help="Obligatorio en egresos o si cambiás la base propuesta.", maxlength="300"),
    field("advances", "Anticipos · Gs."), field("other_discount", "Otros descuentos · Gs."),
    field("discount_reason", "Motivo y respaldo de descuentos", "text", maxlength="300")])
ANNUAL = group("Aguinaldo", [
    field("annual_remuneration", "Remuneraciones computables del año · Gs.", required=True,
          help="Incluí lo devengado hasta el egreso, antes de descuentos. No ingreses solo el último sueldo."),
    field("aguinaldo_paid", "Aguinaldo ya abonado · Gs.")])
IDENTITY = group("Datos del documento", [
    field("employer", "Empleador / razón social", "text", maxlength="180"),
    field("ruc", "RUC del empleador", "text", maxlength="40"),
    field("employee", "Nombre del trabajador", "text", maxlength="180"),
    field("ci", "Cédula / documento", "text", maxlength="40"),
    field("position", "Cargo", "text", maxlength="140"),
    field("prepared_by", "Preparado por", "text", maxlength="180"),
    field("payment_method", "Medio de pago previsto", "text", maxlength="80"),
    field("reference", "Referencia del documento", "text", maxlength="80"),
    field("issued_date", "Fecha del documento", "date", required=True),
    field("notes", "Observaciones", "textarea", maxlength="600"),
    field("two_copies", "PDF con original y duplicado", "checkbox", "on")])
GROUPS = {
    "salary": [
        group("Salario del período", [field("month", "Mes liquidado", "month", required=True), SALARY, DAYS,
            field("days_worked", "Jornadas efectivamente trabajadas", max="31",
                  help="Dato del recibo. Distinto de la base mensual de 30 días.")]),
        EXTRAS, group("Conceptos separados", [
            field("family", "Bonificación familiar · Gs.", help="Ingresá el importe cuyo derecho verificaste."),
            field("reimbursements", "Reintegros documentados · Gs.")], True), IPS, IDENTITY],
    "settlement": [
        group("Relación laboral", [SALARY, field("days_paid", "Días de salario pendientes", value="0", max="30", required=True),
            field("start_date", "Fecha de ingreso", "date", required=True),
            field("end_date", "Fecha de egreso", "date", required=True),
            field("reason", "Motivo de egreso", "select", "dismissal", options=[
                ("dismissal", "Despido sin causa"), ("resignation", "Renuncia"),
                ("justified", "Despido con causa invocada"), ("other", "Otra causa")]),
            field("indefinite", "Contrato por tiempo indefinido", "checkbox", "on"),
            field("trial_completed", "Período de prueba cumplido", "checkbox", "on"),
            field("protected", "Existe protección especial (maternidad, fuero u otra)", "checkbox"),
            field("average_salary", "Promedio salarial para indemnización y preaviso · Gs.",
                  help="Últimos seis meses o menor tiempo trabajado; obligatorio para despido ordinario fuera de prueba."),
            field("notice_served", "Días de preaviso cumplidos", max="90")]),
        EXTRAS, group("Vacaciones pendientes", [
            field("pending_days", "Días pendientes con pago simple", max="365", step="0.01"),
            field("double_days", "Días pendientes con pago doble", max="365", step="0.01",
                  help="Solo cuando proceda legalmente. No repetir días simples."),
            field("proportional_days", "Días proporcionales reconocidos", max="30", step="0.01",
                  help="Ingresá el derecho verificado según causa y período.")]), ANNUAL, IPS, IDENTITY],
    "aguinaldo": [group("Período", [field("year", "Año liquidado", min="1900", max="2100", required=True)]), ANNUAL, IDENTITY],
    "vacation": [group("Remuneración de vacaciones", [SALARY,
        field("legal_minimum", "Mínimo legal de la actividad y período · Gs.", min="1", required=True,
              help="Consultar la escala aplicable. No se presupone que todas las actividades tengan el mismo mínimo."),
        field("vacation_quantity", "Días hábiles reconocidos", max="365", step="0.01", required=True),
        field("vacation_double", "Corresponde pago doble, según revisión del caso", "checkbox")]), IDENTITY],
    "hours": [group("Horas y recargos", [
        field("hour_type", "Tipo de hora", "select", "day_extra", options=[
            ("day_extra", "Extra diurna · 1,5 × hora diurna"), ("night", "Ordinaria nocturna · 1,3 × hora diurna"),
            ("night_extra", "Extra nocturna · 2 × hora nocturna"), ("holiday", "Feriado · 2 × hora ordinaria")]),
        field("hourly_base", "Valor de la hora ordinaria · Gs.", min="0.0001", step="0.0001", required=True,
              help="Extra nocturna: ingresá la hora ordinaria nocturna. En los otros casos, la base indicada en el selector."),
        field("hours", "Cantidad de horas", max="744", step="0.01", required=True)]), IDENTITY],
}
