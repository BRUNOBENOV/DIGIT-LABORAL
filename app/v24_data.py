from __future__ import annotations

from datetime import date

from sqlalchemy import select

from . import seed as seed_module
from .database import SessionLocal
from .models import LaborArticle

SOURCE_213 = "https://www.bacn.gov.py/leyes-paraguayas/2608/ley-n-213-establece-el-codigo-del-trabajo"
SOURCE_496 = "https://www.bacn.gov.py/leyes-paraguayas/2514/ley-n-496-modifica-amplia-y-deroga-articulos-de-la-ley-21393-codigo-del-trabajo"
SOURCE_5764 = "https://www.bacn.gov.py/leyes-paraguayas/8310/ley-n-5764-modifica-el-art-culo-255-de-la-ley-n-213-93-que-establece-el-c-digo-del-trabajo-y-deroga-el-art-culo-256-del-mismo"

# These are deliberately concise fallback summaries. The full library synchronizer
# remains the source of the complete official wording when an online sync is run.
CRITICAL_FALLBACKS: dict[str, tuple[str, str, str, str, str]] = {
    "87": ("Plazos de preaviso", "Terminación laboral", "Después del período de prueba, el preaviso varía según la antigüedad: 30, 45, 60 o 90 días en los tramos previstos por la ley.", SOURCE_496, "Modificado por Ley N.º 496/1995"),
    "89": ("Licencia durante el preaviso", "Terminación laboral", "Durante el preaviso comunicado por el empleador, el trabajador dispone del tiempo legal previsto para buscar nueva ocupación sin reducción salarial.", SOURCE_213, ""),
    "90": ("Omisión del preaviso", "Terminación laboral", "La omisión del preaviso produce las consecuencias económicas previstas por el Código para empleador o trabajador, según quién lo omita.", SOURCE_496, "Modificado por Ley N.º 496/1995"),
    "91": ("Indemnización por despido injustificado", "Terminación laboral", "El despido sin justa causa genera la indemnización legal calculada por años de servicio o fracción computable, conforme a la base establecida por el Código.", SOURCE_496, "Modificado por Ley N.º 496/1995"),
    "92": ("Base para indemnizaciones", "Terminación laboral", "Para las indemnizaciones y el preaviso se utiliza la base remuneratoria promedio legal del período establecido por el Código.", SOURCE_496, "Modificado por Ley N.º 496/1995"),
    "93": ("Certificado de trabajo", "Terminación laboral", "Al terminar el contrato, el empleador debe expedir la constancia laboral con los datos mínimos exigidos por la ley.", SOURCE_213, ""),
    "213": ("Descanso semanal", "Descansos y vacaciones", "Todo trabajador tiene derecho al descanso semanal obligatorio en los términos del Código del Trabajo.", SOURCE_213, ""),
    "218": ("Vacaciones anuales", "Descansos y vacaciones", "La escala general de vacaciones anuales es de 12, 18 o 30 días según la antigüedad alcanzada en el servicio, conforme al artículo 218.", SOURCE_496, "Modificado por Ley N.º 496/1995"),
    "220": ("Remuneración de vacaciones", "Descansos y vacaciones", "La remuneración de vacaciones debe calcularse sobre la base legal aplicable y pagarse conforme al artículo 220.", SOURCE_213, ""),
    "222": ("Época y aviso de vacaciones", "Descansos y vacaciones", "El empleador fija la época de vacaciones dentro del plazo legal y debe comunicarla por escrito con la anticipación establecida.", SOURCE_213, ""),
    "223": ("Vacaciones fuera de plazo", "Descansos y vacaciones", "El retraso imputable al empleador en conceder las vacaciones produce las consecuencias económicas previstas por el artículo 223, sin sustituir el descanso.", SOURCE_213, ""),
    "227": ("Concepto de salario", "Salarios", "Salario es la remuneración debida por el empleador al trabajador en virtud del contrato de trabajo.", SOURCE_213, ""),
    "240": ("Descuentos sobre salarios", "Salarios", "Los descuentos y retenciones sobre el salario solo proceden en los casos autorizados por la ley.", SOURCE_213, ""),
    "242": ("Amortización de deudas", "Salarios", "Las deudas u otros pagos anticipados a favor del empleador se amortizan dentro de los límites y condiciones previstos por el artículo 242.", SOURCE_213, ""),
    "243": ("Aguinaldo", "Aguinaldo", "El aguinaldo equivale a la doceava parte de las remuneraciones computables devengadas durante el año calendario y debe abonarse en el plazo legal.", SOURCE_213, ""),
    "244": ("Aguinaldo proporcional", "Aguinaldo", "Al terminar la relación antes de fin de año corresponde el aguinaldo proporcional sobre las remuneraciones computables devengadas.", SOURCE_213, ""),
    "245": ("Protección del aguinaldo", "Aguinaldo", "El aguinaldo cuenta con la protección legal especial prevista por el artículo 245.", SOURCE_213, ""),
    "255": ("Reajuste del salario mínimo", "Salario mínimo", "La consideración del reajuste del salario mínimo se realiza conforme al mecanismo vigente del artículo 255 y sus modificaciones.", SOURCE_5764, "Modificado por Ley N.º 5764/2016"),
    "268": ("Asignación familiar y salario", "Asignación familiar", "La asignación familiar no integra el salario para los efectos expresamente previstos por el Código, incluido el cálculo indicado en el artículo 268.", SOURCE_213, ""),
}


def _patched_seed_articles():
    existing = [row for row in seed_module.ARTICLES if str(row[0]) not in {"154", "218", "243"}]
    for number, (heading, category, body, source, amendment) in CRITICAL_FALLBACKS.items():
        existing = [row for row in existing if str(row[0]) != number]
        existing.append((number, heading, category, body, source, amendment))
    return existing


seed_module.ARTICLES = _patched_seed_articles()


def apply_v24_data_fixes() -> None:
    """Fix only known inaccurate legacy seed rows; never overwrite synced full text."""
    with SessionLocal() as db:
        for wrong_number, wrong_heading in (("154", "Descanso semanal"), ("218", "Concepto de salario"), ("243", "Salario mínimo")):
            item = db.scalar(select(LaborArticle).where(LaborArticle.article_number == wrong_number))
            if item and item.heading.strip() == wrong_heading:
                if wrong_number == "154":
                    db.delete(item)
                else:
                    heading, category, body, source, amendment = CRITICAL_FALLBACKS[wrong_number]
                    item.heading = heading
                    item.category = category
                    item.body = body
                    item.source_url = source
                    item.source_name = "BACN"
                    item.amendment_note = amendment
                    item.content_status = "Síntesis de respaldo; verificar texto oficial"
                    item.reviewed_at = date.today()

        for number, (heading, category, body, source, amendment) in CRITICAL_FALLBACKS.items():
            current = db.scalar(select(LaborArticle).where(LaborArticle.article_number == number))
            if current is None:
                db.add(LaborArticle(
                    article_number=number,
                    heading=heading,
                    category=category,
                    body=body,
                    source_url=source,
                    source_name="BACN",
                    amendment_note=amendment,
                    content_status="Síntesis de respaldo; verificar texto oficial",
                    reviewed_at=date.today(),
                ))
        db.commit()
