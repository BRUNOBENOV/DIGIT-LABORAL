from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .config import settings


@dataclass(frozen=True)
class AIResult:
    text: str
    provider: str
    model: str
    used_external_ai: bool


def _rule_based_review(purpose: str, context: dict[str, Any], instruction: str) -> str:
    company = context.get("company") or {}
    employee = context.get("employee") or {}
    calculations = context.get("calculations") or []
    missing: list[str] = []
    for label, value in {
        "RUC de la empresa": company.get("ruc"),
        "dirección de la empresa": company.get("address"),
        "representante legal": company.get("legal_representative"),
        "cédula del funcionario": employee.get("document_number"),
        "cargo": employee.get("position"),
        "fecha de ingreso": employee.get("admission_date"),
        "salario base": employee.get("base_salary"),
    }.items():
        if value in (None, "", 0):
            missing.append(label)

    lines = ["Revisión automática de Digit Laboral:"]
    if missing:
        lines.append("• Faltan datos para una emisión completa: " + ", ".join(missing) + ".")
    else:
        lines.append("• Los datos principales del expediente están completos.")
    if calculations:
        latest = calculations[0]
        lines.append(
            f"• Cálculo vinculado más reciente: {latest.get('type', 'sin tipo')}, "
            f"monto Gs. {int(latest.get('amount') or 0):,}.".replace(",", ".")
        )
    else:
        lines.append("• No hay cálculos guardados para vincular automáticamente.")
    lines.append("• Verificá fechas, causa, periodo y parámetros vigentes antes de emitir o firmar.")
    if purpose == "documento":
        lines.append("• Recomendación: generar primero la vista previa y luego descargar Word o PDF.")
    elif purpose == "control":
        lines.append("• Recomendación: completar logo, firma autorizada y datos patronales de la empresa.")
    elif purpose == "calculo":
        lines.append("• Recomendación: guardar el cálculo para que pueda reutilizarse en certificados e informes.")
    if instruction.strip():
        lines.append(f"• Solicitud registrada: {instruction.strip()[:400]}")
    lines.append("Resultado orientativo: requiere revisión humana y profesional.")
    return "\n".join(lines)


def generate_assistance(
    *,
    purpose: str,
    context: dict[str, Any],
    instruction: str,
    allow_external: bool = False,
) -> AIResult:
    """Genera ayuda sin ejecutar decisiones jurídicas ni modificar datos automáticamente."""
    if not allow_external or not settings.ai_enabled or not settings.openai_api_key:
        return AIResult(
            text=_rule_based_review(purpose, context, instruction),
            provider="Motor interno",
            model="Reglas v1.4",
            used_external_ai=False,
        )

    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        safe_context = json.dumps(context, ensure_ascii=False, default=str)[:16000]
        response = client.responses.create(
            model=settings.openai_model,
            store=settings.ai_store_responses,
            instructions=(
                "Sos un asistente de gestión laboral para Paraguay dentro de Digit Laboral. "
                "No tomes decisiones jurídicas, no inventes artículos ni parámetros, no reemplaces la revisión profesional. "
                "Analizá únicamente los datos proporcionados. Marcá faltantes, inconsistencias y próximos pasos. "
                "Respondé en español claro, con secciones breves: Resumen, Alertas, Recomendaciones y Datos a verificar."
            ),
            input=(
                f"Propósito: {purpose}\n"
                f"Solicitud del usuario: {instruction.strip() or 'Revisar y sugerir mejoras'}\n"
                f"Contexto estructurado: {safe_context}"
            ),
        )
        text = (response.output_text or "").strip()
        if not text:
            raise RuntimeError("Respuesta vacía")
        return AIResult(text=text, provider="OpenAI", model=settings.openai_model, used_external_ai=True)
    except Exception:
        return AIResult(
            text=_rule_based_review(purpose, context, instruction)
            + "\n• La IA externa no estuvo disponible; se utilizó el motor interno.",
            provider="Motor interno",
            model="Reglas v1.4",
            used_external_ai=False,
        )
