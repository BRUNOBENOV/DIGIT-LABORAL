# REOP — Liquidación de Salarios en DIGIT-LABORAL

## Estado

Esta versión implementa un flujo de preparación y presentación manual asistida. El envío directo por API/Web Service del MTESS permanece deshabilitado.

La documentación pública del MTESS indica que las comunicaciones de liquidaciones pueden hacerse individualmente o mediante planillas Excel, y que los recibos electrónicos se generan en el propio REOP. No encontramos en las páginas públicas consultadas un contrato de API para terceros que especifique endpoints, autenticación y respuestas. Esto no descarta que exista un mecanismo privado de interoperabilidad: se debe solicitar la especificación y autorización al MTESS.

Fuentes oficiales:
- [Liquidaciones salariales y recibos electrónicos, MTESS (19/05/2025)](https://www.mtess.gov.py/?p=30018)
- [Comunicaciones REOP y campos requeridos](https://www.mtess.gov.py/?page_id=31365)
- [Modelos y estructura oficial de planillas](https://www.mtess.gov.py/?page_id=24021)
- [Guía práctica de liquidación salarial REOP (PDF)](https://www.mtess.gov.py/wp-content/uploads/2025/10/Guia-liquidacion-de-salarios-v1.pdf)

Contacto de REOP publicado por el Ministerio: reop@mtess.gov.py · (0986) 790 101.

## Flujo implementado

Desde Informes → Liquidación de Salarios → abrir recibo:

1. Solo prepara una comunicación desde un cálculo guardado en estado Aprobado o Validado; un cálculo anulado se bloquea.
2. Genera un snapshot inmutable de los valores guardados, con hash SHA-256 del cálculo fuente. No recalcula salario.
3. Solicita los datos complementarios que pueden faltar: fecha y forma de pago, días, horas y piezas/tareas o “No aplica”.
4. Genera un Excel de apoyo interno con hojas de datos, ingresos, descuentos, validaciones y trazabilidad. **No es la plantilla oficial de importación** y está identificado como tal. Antes de importar cualquier archivo, debe utilizarse el modelo vigente del MTESS.
5. Ejecuta controles locales de campos, período, número patronal y coherencia de importes. Esto no equivale a una validación legal ni a una aceptación del MTESS.
6. Permite aprobar internamente, descargar el archivo, presentar manualmente en el REOP oficial y registrar el resultado.
7. Admite referencia externa y carga del comprobante PDF, PNG o JPG emitido por REOP. El tipo de archivo se comprueba, pero no se certifica su autenticidad.
8. Conserva cada intento por separado. Observaciones o rechazos no sobrescriben el historial; el usuario corrige los datos y crea otro intento.

## Estados

```text
Generado → Validado → Presentado → Aceptado
                           ├──────→ Observado
                           └──────→ Rechazado

Observado / Rechazado → nuevo intento independiente
```

Validado significa aprobación local de DIGIT-LABORAL, no respuesta del MTESS. Presentado/Aceptado/Observado/Rechazado son estados que el usuario registra según lo que muestra REOP; en esta versión no los devuelve automáticamente una API de MTESS.

## Persistencia y seguridad

- Cada lote está asociado a empresa, estudio y al cálculo de origen.
- Los controles de empresa autorizada y los roles administrador/contador restringen las acciones.
- La política de doble aprobación se aplica cuando está habilitada.
- Se conservan snapshot JSON, archivo, SHA-256, estado, referencia externa, usuarios responsables, fechas y comprobante.
- No se almacenan PIN ni contraseñas del portal REOP.
- Mantener REOP_DIRECT_ENABLED=false hasta recibir especificación oficial, credenciales autorizadas y ambiente de homologación.

## Contrato propuesto para una API autorizada futura

El siguiente fragmento es una interfaz de diseño; no implica que esos endpoints existan ni que el conector directo funcione.

```python
from dataclasses import dataclass
from typing import Any, Protocol

@dataclass(frozen=True)
class OfficialSubmission:
    external_id: str
    status: str
    receipt_bytes: bytes | None = None
    receipt_content_type: str | None = None
    message: str = ""

class AuthorizedReopGateway(Protocol):
    def submit_salary(
        self, payload: dict[str, Any], *, idempotency_key: str
    ) -> OfficialSubmission:
        """Implementar solo con el contrato oficial homologado."""
        ...

    def get_submission(self, external_id: str) -> OfficialSubmission:
        """Consultar estado/recibo con el método definido por el MTESS."""
        ...
```

Una implementación futura debe fallar de forma segura cuando la bandera de integración directa está desactivada. No debe adivinar URLs ni automatizar el formulario de inicio de sesión. Después de obtener la especificación, adaptar autenticación, idempotencia, manejo de timeouts, códigos de error, firma y descarga del recibo oficial.

## Interfaz

La interfaz actual está en `app/templates/salary_settlement_detail.html`. Utiliza formularios del backend con CSRF para registrar datos complementarios, preparar el archivo de apoyo, validar, guardar la referencia y archivar el comprobante. No envía credenciales ni transmite datos de forma automática al portal.

## Para habilitar envío directo

Solicitar al MTESS:
- confirmación por escrito del mecanismo de interoperabilidad disponible para terceros;
- endpoints, esquemas, catálogos y ambiente de homologación;
- método de autenticación, representación del empleador y requisitos de firma;
- idempotencia, límites, timeouts, estados, errores y mecanismo de recuperación del recibo;
- autorización para tratar y presentar información de múltiples empleadores.

Solo después de homologación técnica y revisión de seguridad debe activarse REOP_DIRECT_ENABLED.
