# Integración REI y REOP — Diseño operativo v2.0

## Principio de integración

Digit Laboral separa cuatro acciones que no deben confundirse:

1. **Preparar:** reunir datos y crear un borrador.
2. **Validar:** comprobar campos, coherencia y respaldo.
3. **Exportar:** generar el archivo de trabajo y registrar su hash.
4. **Presentar:** ingresar al portal oficial, subir la información y conservar el comprobante.

La presentación oficial no se considera completada hasta que el usuario registra el comprobante y el resultado dentro de Digit Laboral.

## REI — IPS

Fuente oficial de referencia:

`https://portal.ips.gov.py/sistemas/ipsportal/contenido.php?c=119`

El portal oficial publica el acceso al REI, su manual y un formato Excel para aportes. El centro de cumplimiento de Digit Laboral prepara movimientos y declaraciones, pero no almacena el PIN o la contraseña del empleador.

Eventos cubiertos en v2.0:

- Entrada.
- Salida.
- Declaración salarial.
- Aportes.
- Reposo.

## REOP — MTESS

Fuentes oficiales de referencia:

- `https://www.mtess.gov.py/?page_id=24021`
- `https://www.mtess.gov.py/direccion-de-registro-obrero-patronal/planillas-laborales`
- `https://www.mtess.gov.py/direccion-de-registro-obrero-patronal/comunicaciones`

Eventos cubiertos en v2.0:

- Entrada.
- Salida.
- Permiso.
- Vacaciones.
- Amonestación.
- Ausencia.
- Suspensión.
- Preaviso.
- Accidente laboral.
- Liquidación salarial.
- Aguinaldo.

La versión 2.0 también administra números patronales y perfiles oficiales por sucursal. Cuando un trabajador está vinculado a un establecimiento, el archivo usa sus identificadores específicos y conserva la casa matriz como respaldo controlado.

Planillas de trabajo generadas:

- Empleados y Obreros.
- Sueldos y Jornales.
- Resumen General de Personas Ocupadas.

## Flujo de aprobación

```text
Borrador → Validado → Exportado → Presentado → Aceptado
                                      ├→ Observado
                                      └→ Rechazado
```

Solo administradores y contadores pueden cambiar estados de presentación o registrar comprobantes. La información declarativa debe revisarse antes de exportarse.

## Trazabilidad

Cada lote conserva:

- empresa, establecimiento y número patronal aplicable;
- autoridad;
- tipo de lote;
- periodo;
- cantidad de registros;
- nombre del archivo;
- hash SHA-256;
- usuario creador y aprobador;
- fecha de presentación;
- referencia externa;
- comprobante asociado;
- resultado.

## Conexión directa futura

Para desarrollar un conector directo se necesita, por cada organismo:

- confirmación formal de que existe un servicio de interoperabilidad;
- documentación de endpoints y esquemas;
- autenticación autorizada;
- ambiente de homologación;
- catálogos de códigos;
- reglas de idempotencia y reintentos;
- límites de uso;
- mecanismos de firma o declaración jurada;
- tratamiento de errores y comprobantes;
- autorización para operar datos de terceros.

Las variables `REI_DIRECT_ENABLED` y `REOP_DIRECT_ENABLED` deben permanecer en `false`. Activarlas sin una integración oficial genera una advertencia de producción.

## Solicitud técnica sugerida

Contactos publicados por los organismos:

- IPS/REI: `sistema.rei@ips.gov.py`
- MTESS/REOP: `reop@mtess.gov.py`

La solicitud debe describir a Digit Laboral, identificar al responsable legal, indicar el volumen estimado, explicar las medidas de seguridad y pedir documentación de interoperabilidad, sandbox y condiciones de homologación.


## Solicitud formal

El archivo `SOLICITUD_INTEROPERABILIDAD_REI_REOP.md` contiene modelos institucionales para solicitar API, web services, homologación, sandbox y condiciones de autorización.
