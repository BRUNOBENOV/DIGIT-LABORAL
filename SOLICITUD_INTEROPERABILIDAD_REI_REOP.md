# Solicitud institucional de interoperabilidad — REI y REOP

## Finalidad

Este documento sirve como base para solicitar formalmente documentación técnica, homologación y autorización de interoperabilidad para Digit Laboral. No incluye ni solicita contraseñas de empleadores.

---

## Modelo de solicitud al IPS — Sistema REI

**Asunto:** Solicitud de información técnica para interoperabilidad autorizada con el Sistema REI

Señores
**Instituto de Previsión Social — Sistema REI**

Por medio de la presente, **Victor’s Contabilidad**, responsable del desarrollo de la plataforma **Digit Laboral**, solicita información institucional sobre los mecanismos autorizados de interoperabilidad con el Sistema REI.

Digit Laboral es una plataforma de gestión laboral destinada a estudios contables y empresas vinculadas. Su finalidad es organizar datos patronales, movimientos de trabajadores, declaraciones salariales, archivos de aportes, comprobantes y trazabilidad interna. La plataforma no pretende almacenar credenciales del portal ni automatizar su interfaz sin autorización.

Solicitamos informar:

1. Si el IPS dispone de API, web service, intercambio por lotes u otro mecanismo oficial para sistemas de terceros.
2. Requisitos jurídicos y técnicos de habilitación.
3. Documentación de endpoints, esquemas y catálogos.
4. Método de autenticación, firma y representación del empleador.
5. Ambiente de homologación o sandbox.
6. Reglas de idempotencia, reintentos, límites y tratamiento de errores.
7. Formato de comprobantes y respuestas de aceptación u observación.
8. Condiciones aplicables al tratamiento de datos de varios empleadores por un estudio contable.
9. Procedimiento de certificación, convenio o autorización institucional.

Datos del solicitante:

- Organización: Victor’s Contabilidad
- Plataforma: Digit Laboral
- Responsable: Bruno Alexander Benítez Oviedo
- Teléfono: 0983 102 220
- Correo institucional: [completar]
- RUC: [completar]
- Volumen estimado de empleadores y trabajadores: [completar]

Agradecemos las orientaciones para iniciar el proceso formal correspondiente.

---

## Modelo de solicitud al MTESS — Sistema REOP

**Asunto:** Solicitud de información técnica para interoperabilidad autorizada con el Sistema REOP

Señores
**Ministerio de Trabajo, Empleo y Seguridad Social — Registro Obrero Patronal**

Por medio de la presente, **Victor’s Contabilidad**, responsable del desarrollo de la plataforma **Digit Laboral**, solicita información institucional sobre los mecanismos autorizados de interoperabilidad con el Sistema REOP.

Digit Laboral organiza expedientes de empresas y trabajadores, comunicaciones laborales, liquidaciones, planillas, archivos de presentación, comprobantes y trazabilidad. Actualmente genera archivos de trabajo para revisión humana y carga manual. No almacena credenciales del REOP ni automatiza el portal.

Solicitamos informar:

1. Si el MTESS dispone de API, web service, intercambio por lotes u otro mecanismo autorizado para sistemas de terceros.
2. Requisitos para homologación y autorización.
3. Esquemas vigentes de comunicaciones, liquidaciones y planillas laborales.
4. Catálogos oficiales de ocupaciones, motivos, tipos de movimiento y establecimientos.
5. Método de autenticación, firma o declaración jurada.
6. Ambiente de pruebas.
7. Reglas de validación, idempotencia, reintentos y tratamiento de observaciones.
8. Formato de comprobantes y respuestas del organismo.
9. Tratamiento de empresas con múltiples sucursales y números patronales.
10. Condiciones para que un estudio contable opere datos de empresas vinculadas.

Datos del solicitante:

- Organización: Victor’s Contabilidad
- Plataforma: Digit Laboral
- Responsable: Bruno Alexander Benítez Oviedo
- Teléfono: 0983 102 220
- Correo institucional: [completar]
- RUC: [completar]
- Volumen estimado de empleadores y trabajadores: [completar]

Agradecemos las indicaciones para tramitar la autorización correspondiente.

---

## Anexo técnico sugerido

Adjuntar una ficha de una o dos páginas que describa:

- arquitectura de la aplicación;
- cifrado en tránsito y en reposo;
- separación de datos por estudio y empresa;
- roles y doble aprobación;
- auditoría, hash de archivos y comprobantes;
- copias de seguridad y recuperación;
- política de incidentes;
- ubicación de infraestructura;
- conservación y eliminación de datos;
- responsable técnico y responsable legal;
- diagrama del flujo de envío y recepción.

## Regla de seguridad

Hasta obtener respuesta escrita, especificación técnica y credenciales de homologación, mantener:

```text
REI_DIRECT_ENABLED=false
REOP_DIRECT_ENABLED=false
```

La integración operativa debe permanecer basada en exportación, validación humana, presentación manual y registro del comprobante.
