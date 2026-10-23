"""Catalog and lifecycle helpers for certificates issued by MTESS and IPS.

DIGIT-LABORAL tracks official documents and links to their official channels. It does
not recreate institutional certificates, signatures, QR codes or validation codes.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

MTESS_CERTIFICATE_INFO_URL = "https://www.mtess.gov.py/?page_id=24713"
IPS_AOP_URL = "https://servicios.ips.gov.py/constancias_aop/index.php"
IPS_COMPLIANCE_URL = "https://portal.ips.gov.py/sistemas/ipsportal/contenido.php?c=163"
IPS_PERSONAL_CERTIFICATES_URL = "https://portal.ips.gov.py/sistemas/ipsportal/comunicado.php?cod=258"

OFFICIAL_CERTIFICATE_TYPES: dict[str, dict[str, Any]] = {
    "mtess_certificado_laboral": {
        "institution": "MTESS",
        "label": "Certificado Laboral (REOP)",
        "scope": "empresa",
        "validity_days": 90,
        "source_url": MTESS_CERTIFICATE_INFO_URL,
        "portal_label": "Ver requisitos oficiales",
        "description": (
            "Certificado institucional que informa si el empleador registra multas pendientes "
            "en los conceptos certificados. Se solicita por RUC desde REOP con las credenciales "
            "de la empresa; DIGIT-LABORAL no lo emite."
        ),
        "requirements": (
            "RUC de la empresa y acceso autorizado al sistema REOP.",
            "Verificar inscripción patronal de matriz y sucursales, planillas, comunicaciones y multas antes de solicitarlo.",
            "Desde el 1 de junio de 2026, confirmar también los Libros de Información Laboral digitales mensuales exigidos para la expedición, según la información vigente del MTESS.",
            "Guardar aquí el PDF original descargado del MTESS.",
        ),
        "has_result": True,
    },
    "mtess_constancia_no_inscripto": {
        "institution": "MTESS",
        "label": "Constancia de no estar inscripto (REOP)",
        "scope": "empresa",
        "validity_days": None,
        "source_url": "https://www.mtess.gov.py/?page_id=24708",
        "portal_label": "Consultar servicios REOP",
        "description": (
            "Seguimiento documental de una constancia relacionada con la inscripción patronal. "
            "Confirmá la disponibilidad y el procedimiento vigente en el canal oficial antes de tramitar."
        ),
        "requirements": (
            "RUC y datos patronales que correspondan.",
            "Conservar el documento emitido por la institución, no una plantilla interna.",
        ),
        "has_result": False,
    },
    "ips_certificado_cumplimiento": {
        "institution": "IPS",
        "label": "Certificado de Cumplimiento del Seguro Social (AOP)",
        "scope": "empresa",
        "validity_days": None,
        "source_url": IPS_COMPLIANCE_URL,
        "verification_url": "https://servicios.ips.gov.py/constancia/",
        "portal_label": "Ver información del IPS",
        "description": (
            "Certificado para empresas al día con sus obligaciones frente al IPS. Su vigencia se "
            "extiende hasta el vencimiento del próximo pago; registrá la fecha exacta indicada o "
            "confirmada por la institución."
        ),
        "requirements": (
            "Verificar el estado de las obligaciones y aportes con IPS.",
            "Tener RUC y cédula del propietario o representante legal.",
            "Registrar el próximo vencimiento de pago como fecha de expiración cuando corresponda.",
        ),
        "has_result": False,
    },
    "ips_constancia_no_inscripto": {
        "institution": "IPS",
        "label": "Constancia de no estar inscripto (empleador)",
        "scope": "empresa",
        "validity_days": 30,
        "source_url": IPS_AOP_URL,
        "verification_url": "https://servicios.ips.gov.py/constancias_aop/?constancia=validarempleador",
        "portal_label": "Abrir Constancias AOP",
        "description": (
            "Constancia AOP para empleadores que no están registrados como patronales. "
            "El portal informa una validez de 30 días desde la expedición."
        ),
        "requirements": (
            "RUC de la empresa.",
            "Guardar el número de certificado que figura en el original para su validación.",
        ),
        "has_result": False,
    },
    "ips_consulta_empleador": {
        "institution": "IPS",
        "label": "Consulta de empleador (AOP)",
        "scope": "empresa",
        "validity_days": 30,
        "source_url": IPS_AOP_URL,
        "verification_url": "https://servicios.ips.gov.py/constancias_aop/?constancia=validarempleador",
        "portal_label": "Abrir Constancias AOP",
        "description": (
            "Consulta/constancia de empleador del portal AOP. Las constancias publicadas por el IPS "
            "tienen una validez informada de 30 días desde su expedición."
        ),
        "requirements": (
            "RUC de la empresa o identificación patronal según el trámite.",
            "Guardar el número de certificado que figura en el original para su validación.",
        ),
        "has_result": False,
    },
    "ips_constancia_no_asegurado": {
        "institution": "IPS",
        "label": "Constancia de no estar asegurado (AOP)",
        "scope": "persona",
        "validity_days": 30,
        "source_url": IPS_AOP_URL,
        "verification_url": "https://servicios.ips.gov.py/constancias_aop/?constancia=validarasegurado",
        "portal_label": "Abrir Constancias AOP",
        "description": (
            "Constancia individual disponible en el portal AOP. El portal informa una validez de "
            "30 días; requiere CI y el número de certificado para validación."
        ),
        "requirements": (
            "Cédula de identidad de la persona.",
            "Guardar el número de certificado que figura en el original.",
            "Validar el documento en el portal del IPS cuando sea necesario.",
        ),
        "has_result": False,
    },
    "ips_constancia_asegurado": {
        "institution": "IPS",
        "label": "Constancia de ser asegurado",
        "scope": "persona",
        "validity_days": None,
        "source_url": IPS_PERSONAL_CERTIFICATES_URL,
        "portal_label": "Consultar gestión y autorización",
        "description": (
            "Registro de seguimiento para un certificado personal emitido por el IPS. El canal, "
            "requisitos y vigencia deben confirmarse según el trámite y el documento original."
        ),
        "requirements": (
            "CI del titular.",
            "Si gestiona un tercero, verificar las autorizaciones y documentos exigidos por el IPS.",
            "Archivar el original emitido por la institución.",
        ),
        "has_result": False,
    },
    "ips_certificado_trabajo": {
        "institution": "IPS",
        "label": "Certificado de trabajo (IPS)",
        "scope": "persona",
        "validity_days": None,
        "source_url": IPS_PERSONAL_CERTIFICATES_URL,
        "portal_label": "Consultar gestión y autorización",
        "description": (
            "Seguimiento de un certificado personal del IPS. DIGIT-LABORAL conserva el estado y "
            "el original, pero no emite ni valida el certificado institucional."
        ),
        "requirements": (
            "CI del titular.",
            "Si gestiona un tercero, verificar la autorización expresa requerida por IPS.",
            "Archivar el original emitido por la institución.",
        ),
        "has_result": False,
    },
    "ips_certificado_jubilacion": {
        "institution": "IPS",
        "label": "Certificado de jubilación (IPS)",
        "scope": "persona",
        "validity_days": None,
        "source_url": IPS_PERSONAL_CERTIFICATES_URL,
        "portal_label": "Consultar gestión y autorización",
        "description": (
            "Seguimiento de un certificado personal de jubilación emitido por IPS. La vigencia "
            "y el procedimiento dependen de lo indicado por la institución."
        ),
        "requirements": (
            "CI del titular.",
            "Si gestiona un tercero, verificar la autorización expresa requerida por IPS.",
            "Archivar el original emitido por la institución.",
        ),
        "has_result": False,
    },
    "ips_computo_semanas": {
        "institution": "IPS",
        "label": "Cómputo de semanas consolidado (IPS)",
        "scope": "persona",
        "validity_days": None,
        "source_url": IPS_PERSONAL_CERTIFICATES_URL,
        "portal_label": "Consultar gestión y autorización",
        "description": (
            "Seguimiento del cómputo de semanas emitido por IPS. No se genera una constancia "
            "sustitutiva dentro de DIGIT-LABORAL."
        ),
        "requirements": (
            "CI del titular.",
            "Si gestiona un tercero, verificar la autorización expresa requerida por IPS.",
            "Archivar el original emitido por la institución.",
        ),
        "has_result": False,
    },
    "ips_constancia_jubilado": {
        "institution": "IPS",
        "label": "Constancia de jubilado (IPS)",
        "scope": "persona",
        "validity_days": None,
        "source_url": IPS_PERSONAL_CERTIFICATES_URL,
        "portal_label": "Consultar gestión y autorización",
        "description": (
            "Seguimiento de una constancia personal emitida por IPS. La vigencia debe revisarse "
            "en el original o confirmarse en el canal oficial."
        ),
        "requirements": (
            "CI del titular.",
            "Si gestiona un tercero, verificar la autorización expresa requerida por IPS.",
            "Archivar el original emitido por la institución.",
        ),
        "has_result": False,
    },
}


    "mtess_constancia_inscripcion_empleado": {
        "institution": "MTESS",
        "label": "Constancia de inscripción de empleado",
        "scope": "persona",
        "validity_days": None,
        "source_url": "https://www.paraguay.gov.py/carpeta-ciudadana",
        "portal_label": "Abrir Portal Único de Gobierno",
        "description": (
            "Constancia publicada dentro de los servicios de trabajo del Portal Único de Gobierno. "
            "Confirmá el canal de acceso y los requisitos vigentes antes de iniciar el trámite."
        ),
        "requirements": (
            "Cédula de identidad del trabajador.",
            "Verificar si el servicio requiere Identidad Electrónica.",
            "Archivar la constancia emitida por el MTESS, no una plantilla interna.",
        ),
        "has_result": False,
    },
    "ips_constancia_no_adeudar": {
        "institution": "IPS",
        "label": "Constancia de no adeudar (IPS)",
        "scope": "empresa",
        "validity_days": None,
        "source_url": "https://portal.ips.gov.py/sistemas/ipsportal/contenido.php?c=361",
        "portal_label": "Consultar servicios AOP del IPS",
        "description": (
            "Seguimiento de la constancia de no adeudar en los servicios AOP publicados por el IPS. "
            "La disponibilidad y cualquier condición de vigencia deben confirmarse en el canal oficial."
        ),
        "requirements": (
            "RUC y datos de identificación patronal.",
            "Confirmar el estado de las obligaciones ante IPS.",
            "Registrar la vigencia indicada por la institución cuando corresponda.",
        ),
        "has_result": False,
    },
    "ips_constancia_salario_asegurado": {
        "institution": "IPS",
        "label": "Constancia de salario de asegurado",
        "scope": "persona",
        "validity_days": None,
        "source_url": "https://www.paraguay.gov.py/carpeta-ciudadana",
        "portal_label": "Abrir Portal Único de Gobierno",
        "description": (
            "Constancia con información del salario declarado del asegurado, publicada entre los "
            "servicios del Portal Único de Gobierno. Revisá el documento emitido y su finalidad de uso."
        ),
        "requirements": (
            "Cédula de identidad del titular.",
            "Verificar el acceso mediante Identidad Electrónica y el alcance del documento.",
            "Conservar el original emitido por el sistema oficial.",
        ),
        "has_result": False,
    },

OFFICIAL_CERTIFICATE_STATUSES = ("Pendiente", "En trámite", "Emitido", "Observado", "Cancelado")
OFFICIAL_CERTIFICATE_RESULTS = ("", "CUMPLE", "NO CUMPLE", "No aplica")


def default_expiry_date(certificate_type: str, issue_date: date | None) -> date | None:
    """Infer a documented validity window only when the official source states one."""
    if not issue_date:
        return None
    info = OFFICIAL_CERTIFICATE_TYPES.get(certificate_type, {})
    validity_days = info.get("validity_days")
    if not isinstance(validity_days, int) or validity_days < 1:
        return None
    return issue_date + timedelta(days=validity_days)


def official_certificate_state(
    status: str,
    expiry_date: date | None,
    today: date | None = None,
) -> str:
    """Calculate the display state without overwriting the institution's record."""
    if status != "Emitido":
        return status
    if expiry_date is None:
        return "Emitido · vigencia por confirmar"
    current_day = today or date.today()
    days_remaining = (expiry_date - current_day).days
    if days_remaining < 0:
        return "Vencido"
    if days_remaining <= 15:
        return "Por vencer"
    return "Vigente"


def days_until_expiry(expiry_date: date | None, today: date | None = None) -> int | None:
    if expiry_date is None:
        return None
    return (expiry_date - (today or date.today())).days
