from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import main as core
from .calculator_fields import GROUPS
from .calculator_routes import HEADERS, context, download
from .labor_calculator import CalculationError, SOURCE, TITLES, calculate, checked, clean
from .labor_examples import example_values
from .models import CalculationRecord, Employee, Payroll, User

router = APIRouter()
PROFILES = {
    "empresa": dict(label="Empresas", title="De los datos del equipo al recibo.",
        intro="Prepará salarios, revisá el costo de cada persona y organizá el trabajo mensual con tu estudio.",
        tasks=[("Calcular un salario", "Haberes, descuentos, neto y costo patronal.", "/herramientas?tipo=salary"),
               ("Organizar mi empresa", "Expedientes, funcionarios, documentos e historial según los permisos de tu cuenta.", "/app/guia"),
               ("Comparar costos", "Revisá dos propuestas salariales con los mismos conceptos.", "/herramientas/comparar?tipo=salary")],
        prepare=["Período, salarios y jornadas trabajadas.", "Horas extras, anticipos y respaldo de descuentos.", "Datos de la empresa y de cada trabajador."]),
    "contador": dict(label="Contadores", title="Un recorrido para cada cierre mensual.",
        intro="Trabajá por empresa y funcionario, conservá los cálculos y recuperá los recibos desde el historial.",
        tasks=[("Preparar mi espacio", "Empresas, funcionarios y primer cálculo guardado.", "/app/guia"),
               ("Liquidar la nómina", "Prepará el período y descargá los recibos guardados.", "/app/payrolls"),
               ("Abrir historial de cálculos", "Recuperá resultados y usalos como base del siguiente período.", "/app/liquidaciones")],
        prepare=["Listado de empresas y funcionarios actualizado.", "Novedades del período y conceptos revisados.", "Bases y tasas del régimen aplicable."]),
    "abogado": dict(label="Abogados", title="Compará supuestos con el detalle a la vista.",
        intro="Analizá bases, fechas y conceptos; distinguí un cálculo completo de un subtotal que requiere revisión.",
        tasks=[("Comparar dos escenarios", "Cambios de fechas, bases o causa de egreso con desglose A y B.", "/herramientas/comparar?tipo=settlement"),
               ("Analizar una liquidación final", "Salarios pendientes, aguinaldo, vacaciones y conceptos de egreso.", "/herramientas?tipo=settlement"),
               ("Consultar fuentes oficiales", "Cada resultado enlaza las fuentes y muestra los criterios del cálculo.", "/herramientas?tipo=settlement")],
        prepare=["Fechas de ingreso y egreso y documentación de la relación.", "Salarios, remuneraciones del año y pagos acreditados.", "Causa invocada, preaviso, vacaciones y posibles protecciones especiales."]),
    "empleado": dict(label="Empleados", title="Entendé y revisá tu liquidación.",
        intro="Consultá sin cuenta. Podés ingresar importes sin completar tu nombre o documento y ver cómo se forma el resultado.",
        tasks=[("Revisar mi recibo", "Ingresá los conceptos y el neto informado para ver la diferencia.", "/herramientas?tipo=salary#f-reported_net"),
               ("Consultar mi aguinaldo", "Calculá según las remuneraciones computables y lo ya abonado.", "/herramientas?tipo=aguinaldo"),
               ("Revisar mi liquidación final", "Identificá las bases, conceptos y observaciones del egreso.", "/herramientas?tipo=settlement")],
        prepare=["Recibo del período que querés revisar.", "Salario, jornadas, haberes y descuentos del mismo período.", "Neto informado en el recibo; una diferencia requiere revisar los datos y respaldos."]),
}


@router.get("/empezar")
def getting_started(request: Request, perfil: str = "empresa"):
    if perfil not in PROFILES:
        raise HTTPException(404, "Perfil no encontrado.")
    response = core.render(request, "labor_guide.html", None, profiles=PROFILES, profile=perfil,
                           guide=PROFILES[perfil], private=False)
    response.headers.update(HEADERS)
    return response


@router.get("/app/guia")
def workspace_guide(request: Request, user: User = Depends(core.require_user), db: Session = Depends(core.get_db)):
    ids = core.company_ids_for_user(db, user)
    employee_count = db.scalar(select(func.count(Employee.id)).where(Employee.company_id.in_(ids))) or 0
    calculation_count = db.scalar(select(func.count(CalculationRecord.id)).where(
        CalculationRecord.company_id.in_(ids), CalculationRecord.source == SOURCE)) or 0
    payroll_count = db.scalar(select(func.count(Payroll.id)).where(Payroll.company_id.in_(ids))) or 0
    steps = [
        dict(title="Empresas", count=len(ids), href="/app/companies", description="Revisá razón social, RUC y datos del expediente."),
        dict(title="Funcionarios", count=employee_count, href="/app/employees", description="Comprobá fechas, salarios y régimen de aporte."),
        dict(title="Liquidaciones guardadas", count=calculation_count, href="/app/liquidaciones", description="Calculá, revisá el desglose y recuperá el PDF desde el historial."),
    ]
    if user.role != "empresa":
        steps.append(dict(title="Nóminas", count=payroll_count, href="/app/payrolls", description="Guardá los cambios de cada funcionario antes de descargar los recibos."))
    response = core.render(request, "labor_guide.html", db, user, private=True, steps=steps,
                           profiles=PROFILES, profile="empresa" if user.role == "empresa" else "contador")
    response.headers.update(HEADERS)
    return response


def comparison_page(request, kind, scenarios=None, results=None, labels=None, errors=None, example=False):
    defaults = context(kind)["values"]
    scenarios = scenarios or {side: dict(defaults) for side in ("a", "b")}
    labels = labels or {"a": "Escenario A", "b": "Escenario B"}
    errors = errors or {}
    changes = []
    if results:
        for group in GROUPS[kind]:
            for field in group["fields"]:
                def display(data):
                    value = data.get(field["name"], "")
                    if field["type"] == "checkbox":
                        return "Sí" if checked(data, field["name"]) else "No"
                    if field["type"] == "select":
                        return dict(field["attrs"]["options"]).get(value, value)
                    return value or "Sin informar"
                a, b = display(scenarios["a"]), display(scenarios["b"])
                if a != b:
                    changes.append(dict(label=field["label"], a=a, b=b))
    response = core.render(request, "labor_compare.html", None, kind=kind, titles=TITLES,
                           groups=GROUPS[kind], scenarios=scenarios, results=results, labels=labels,
                           errors=errors, changes=changes, example=example)
    response.headers.update(HEADERS)
    if errors:
        response.status_code = 422
    return response


async def comparison_values(request):
    if len(await request.body()) > 64000:
        raise HTTPException(413, "Formulario demasiado grande.")
    form = await request.form(max_files=0, max_fields=200)
    kind = str(form.get("kind", ""))
    if kind not in TITLES:
        raise HTTPException(422, "Tipo de cálculo inválido.")
    scenarios = {}
    for side in ("a", "b"):
        scenarios[side] = {field["name"]: str(form.get(side + "_" + field["name"], ""))
                           for group in GROUPS[kind] for field in group["fields"]}
        scenarios[side]["kind"] = kind
    labels = {side: clean(form.get("label_" + side), 70) or "Escenario " + side.upper() for side in ("a", "b")}
    return kind, scenarios, labels


@router.get("/herramientas/comparar")
def comparison_start(request: Request, tipo: str = "settlement", ejemplo: bool = False):
    defaults = context(tipo)["values"]
    scenarios = labels = None
    if ejemplo and tipo in {"salary", "settlement"}:
        scenarios = {side: example_values(tipo, defaults) for side in ("a", "b")}
        if tipo == "salary":
            scenarios["b"]["salary"] = "4000000"
        else:
            scenarios["b"]["reason"] = "resignation"
        labels = {"a": "Ejemplo A", "b": "Ejemplo B"}
    return comparison_page(request, tipo, scenarios, labels=labels, example=bool(scenarios))


@router.post("/herramientas/comparar")
async def compare(request: Request):
    kind, scenarios, labels = await comparison_values(request)
    results, errors = {}, {}
    for side in ("a", "b"):
        try:
            results[side] = calculate(scenarios[side])
        except CalculationError as exc:
            errors[side] = dict(message=str(exc), field=exc.field)
    return comparison_page(request, kind, scenarios, results if not errors else None, labels, errors)


@router.post("/herramientas/comparar/exportar/{side}/{fmt}")
async def comparison_export(request: Request, side: str, fmt: str):
    if side not in {"a", "b"} or fmt not in {"pdf", "csv"}:
        raise HTTPException(404, "Documento no encontrado.")
    kind, scenarios, labels = await comparison_values(request)
    try:
        result = calculate(scenarios[side])
    except CalculationError as exc:
        return comparison_page(request, kind, scenarios, labels=labels,
                               errors={side: dict(message=str(exc), field=exc.field)})
    # Names distinguish both files even when the identity and period coincide.
    result["identity"]["reference"] = clean(labels[side] + " · " + result["identity"].get("reference", ""), 180)
    response = await download(result, fmt)
    response.headers["Content-Disposition"] = response.headers["Content-Disposition"].replace("digit-laboral-", "digit-laboral-escenario-" + side + "-", 1)
    return response


core.app.include_router(router)
