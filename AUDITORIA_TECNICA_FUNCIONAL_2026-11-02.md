# Auditoría técnica y funcional de DIGIT-LABORAL — 02/11/2026

**Versión revisada:** v2.6.74 · **Versión correctiva sin migración:** v2.6.75  
**Metodología:** inspección del código fuente, estructura de modelos y migraciones, controles de seguridad, pruebas unitarias e integración con escenarios sintéticos, y consultas SQL exclusivamente de lectura sobre el esquema de producción.

> Este documento distingue **hechos verificados**, **correcciones en código** y **riesgos que todavía requieren validación externa**. No certifica el funcionamiento de la plataforma en el portal MTESS ni IPS y no reemplaza una auditoría externa de seguridad o una revisión jurídica.

## 1. Cobertura

| Área | Comprobación | Resultado |
|---|---|---|
| Cálculo / Salario | Versiones de `CalculationRecord`, aprobación, trazabilidad, entradas históricas | Revisado; dependencias entre origen histórico y profesional identificadas |
| Nóminas | Haberes, descuentos, IPS, cierre, líneas e importes agregados | Dos errores de integridad localizados y corregidos |
| REOP | Selección por empleado, últimas versiones, datos faltantes, validación previa y Excel | Correcciones de exclusiones/duplicados; limitaciones oficiales pendientes |
| REI | Estructura TXT, base IPS, nombres/apellidos y jornadas | Revisado; homologación con IPS pendiente |
| Empresas/Funcionarios | Tenencia y vinculación de registros; capacidad para decenas de miles | RLS y controles de empresa revisados en código |
| Documentos | Emisión de recibos y controles previos; PDF y reportes | Rutas y pruebas existentes inspeccionadas; sin prueba externa de impresión/firma |
| Seguridad | Roles, tenant, RLS, CSRF, comprobaciones de acceso | Controles presentes en código; no se efectuó pentest externo |
| Importación histórica | Reingresos, desvinculaciones, estado y migraciones | Código inspeccionado; no se alteraron registros masivos |
| UI | Formularios de exportación y mensajes | Selector de legajo y separación de avisos corregidos |
| Despliegue | CI GitHub, compilación, arranque sintético | Comprobación mediante CI; no equivale a una inspección autenticada en Render |

## 2. Datos de producción, lectura exclusivamente

Consulta agregada, sin extraer datos personales:

- Empresas: **950**.
- Funcionarios: **11.711**.
- Nóminas: **1**.
- Líneas de nómina: **1**.
- Registros de cálculo: **27**.
- Anexos `salary_import_details`: **0**.
- Lotes de exportación `integration_batches`: **0**.

Estos números corresponden a la consulta realizada durante esta auditoría, no al conjunto de registros que debiera comunicarse a REOP o REI. No se insertó, editó ni eliminó una sola fila de producción.

## 3. Hallazgos principales

### P1-01 — Declaraciones bloqueadas por borradores ajenos
El exportador de cálculos individuales aprobados trataba como errores globales los cálculos recientes `Borrador`/`Revisar`/`Anulado` de otros funcionarios. Se mostraba una fila aprobada, pero el resto bloqueaba la descarga.

**Corrección:** la última versión por legajo continúa controlando la elegibilidad; los excluidos aparecen por separado. La descarga **parcial** requiere confirmación positiva y conserva los IDs excluidos en el historial. Las exportaciones individuales no mezclan datos de otros legajos. No se restauran aprobaciones antiguas por encima de anulaciones o borradores posteriores.

### P1-02 — Aporte patronal IPS calculado con bruto en lugar de base
La edición de nómina calculaba `employer_ips` sobre `gross` incluso cuando `ips_base` era diferente. La retención obrera sí utilizaba `ips_base`. Esto provocaba importes patronales incompatibles con la base de cotización documentada.

**Corrección:** ambos cálculos utilizan la **base imponible guardada**, con tasa configurable, sin modificar importes históricos. Se añadió una regresión explícita con bruto de G. 3.500.000 y base de G. 3.000.000.

### P1-02b — Ruta efectiva de edición salarial diferente de la ruta principal
En el arranque `app.runtime` carga `app.ux_v24`, cuyo `_take_route` elimina la ruta `POST /app/payrolls/{payroll_id}/lines/{line_id}` de `main.py` y registra otra implementación. Esto explica por qué las correcciones anteriores del aporte patronal en `main.py` no cambiaban el comportamiento de la aplicación.

**Corrección:** se actualizó también la ruta activa `update_payroll_line_v24`: ahora conserva bases imponibles manuales documentadas, actualiza siempre el detalle de aporte patronal y utiliza la base IPS grabada. Se añadió una prueba de enrutamiento para detectar futuras sustituciones no previstas.

### P1-02c — Campos del formulario Salarios descartados por la ruta efectiva
La calculadora general de `main.py` había sido ampliada con `days_worked`, `hours_worked` y `payment_method`. Sin embargo, `ux_v24.py` reemplaza también la ruta `POST /app/calculations`; su implementación no guardaba esos campos aunque el formulario los enviara. Este es un motivo directo por el que el exportador solicitaba información previamente introducida.

**Corrección:** la ruta efectiva guarda los tres campos cuando se proporcionan, valida rangos y deja los registros antiguos intactos. No se imputan jornadas o medios de pago faltantes a snapshots históricos. Se añadieron pruebas HTTP de persistencia e invalidación.

### P1-03 — Riesgo de desbordamiento en totales de nóminas masivas
Los cuatro totales de `payrolls` usaban `INTEGER` de 32 bits en PostgreSQL. Una nómina con 1.000 salarios de G. 3.000.000 supera 2.147.483.647.

**Corrección pendiente de despliegue:** se preparó por separado una migración 0021 a `BigInteger` para las cuatro columnas agregadas. **Esta versión segura v2.6.75 no incluye esa migración** porque necesita respaldo recuperable y evaluación de ventana de mantenimiento. Sí incorpora el rechazo preventivo de líneas individuales fuera de rango.

### P2-04 — Avisos duplicados de jornadas y horas
La prevalidación de `CalculationRecord` ya indicaba ausencia de jornadas/horas, pero el exportador agregaba un segundo mensaje genérico sobre los mismos campos.

**Corrección:** deduplicación de los errores de prevalidación y presentación de una sola observación por dato faltante, conservando sus controles.

### P1-05 — Información histórica insuficiente para completar REOP sin intervención
`Calculadora v2.4` guardaba importes y bases, no siempre jornadas, horas ordinarias o forma de pago. No se pueden recuperar de una fórmula basada en 30 o 240.

**Tratamiento:** solo autocompletar datos existentes y vinculados al mismo cálculo/legajo. Los faltantes deben ingresarse una sola vez a través del anexo auditable, no inferirse desde otros trabajadores.

### P1-06 — Formatos externos todavía no homologados
El TXT REI proviene del instructivo de 2016 y la separación de nombres desde un campo libre puede ser incorrecta. El modelo de Excel REOP es el suministrado como referencia, no una certificación de aceptación vigente.

**Estado:** pendiente de cotejo operativo con el portal actual; no declarar los archivos como recibidos u oficiales hasta obtener comprobante del organismo.

### P2-07 — Seguridad y trazabilidad
Se constataron reglas de RLS para estudios, empresas, empleados y anexos; dependencias de roles y CSRF en rutas clave. Esto no prueba por sí solo ausencia de vulnerabilidades. Deben realizarse pruebas de penetración, restauración de backups y rotación de credenciales cuando corresponda.

### P2-08 — Arquitectura y mantenibilidad
`app/main.py` supera 500.000 caracteres. Los cálculos generales, la nómina mensual, los informes y las exportaciones mantienen rutas de origen distintas.

**Recomendación:** extraer progresivamente rutas y servicios separados; definir un modelo único de hechos salariales, conservar versiones y bloquear cualquier doble cálculo silencioso.

## 4. Pruebas añadidas

1. Borrador reciente y cálculo anterior aprobado: el anterior no se reutiliza silenciosamente.
2. Empresa con un cálculo aprobado y otro borrador: se permite la selección válida, con exclusión visible.
3. Confirmación obligatoria para descarga parcial y bloqueo de acceso a legajos de otra empresa.
4. No repetir errores de horas y jornadas.
5. Aporte patronal IPS sobre base imponible, no bruto.
6. Migración `INTEGER` a `BIGINT` desarrollada y probada en una rama separada; pendiente de respaldo para ejecutarla en producción.
7. Rechazo HTTP 422 a sumas de haberes individuales fuera del límite de almacenamiento.

Las pruebas sintéticas no modifican la base de datos real. La integración en GitHub solo procederá cuando compilación, suite automatizada y comprobaciones de arranque resulten correctas.

## 5. Controles pendientes para una certificación completa

- Despliegue real en Render, logs de producción y revisión de entorno autenticado; requiere conexión al workspace correspondiente.
- Prueba de importación efectiva REOP y REI con archivos de ejemplo y sus validaciones vigentes, sin enviar información real sin autorización.
- Prueba de rendimiento con volúmenes representativos de 11.711 legajos y cientos de empresas.
- Revisión jurídica exhaustiva de cada fórmula laboral con casos documentados por modalidad mensual/jornal.
- Prueba de restauración de backup y simulación de aislamiento multiestudio.
- Separación verificable de nombres y apellidos para REI.
- Revisión y consolidación de cálculos individuales en nóminas mensuales con control de versiones.

## 6. Criterio de publicación

No alterar `calculation_records` ni importes guardados. No forzar estados `Aprobado`. Rechazar inconsistencias contables, exigir selección y consentimiento en declaraciones parciales, registrar la fuente y hashes; **respaldar antes de migrar PostgreSQL**.

## 7. Separación deliberada de publicación

- **PR de correcciones seguras:** no incluye migración 0021 ni cambios de tipo a columnas agregadas; sí contiene correcciones de las rutas realmente activas, validación REOP/REI e IPS.
- **PR de ampliación BIGINT:** se conserva separado para aplicarlo después de verificar un respaldo externo recuperable y preparar recuperación ante fallos.
- **Riesgo de almacenamiento:** `render.yaml` declara plan `free` y `STORAGE_BACKEND=local`. Las rutas de archivos deben considerarse potencialmente efímeras; requerir un servicio de almacenamiento duradero antes de confiar en copias o recibos almacenados localmente.
