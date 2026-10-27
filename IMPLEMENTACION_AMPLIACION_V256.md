# Plan de implementación ampliada — DigIT Laboral v2.5.6

## Estado de auditoría inicial

Fecha: 2026-10-27  
Base revisada: rama `main`, versión declarada `2.5.5`.

### Capacidades existentes confirmadas en el repositorio

- El motor laboral `app/labor_calculator.py` declara una versión propia de reglas y produce desglose, advertencias y fuentes.
- `CalculationRecord` conserva empresa, funcionario, tipo, período, entradas y resultado serializados, importe, estado, origen, autor y fecha.
- `app/calculator_routes.py` permite guardar cálculos, consultar el historial, abrir un cálculo guardado para copiar sus entradas y exportar resultados.
- `app/compliance_service.py` ya contiene eventos REI/REOP, validación de datos, prevención de duplicados por clave de origen y estados de flujo.
- `REI_REOP_INTEGRATION.md` especifica el flujo de preparación, validación, exportación y registro manual de comprobante. Los conectores directos deben permanecer desactivados hasta contar con autorización y especificaciones oficiales.
- Hay migraciones Alembic, pruebas automatizadas y documentación de seguridad/producción existentes.

## Objetivo de la siguiente entrega

No duplicar tablas ni rehacer módulos que ya existen. Completar las brechas verificadas mediante cambios incrementales.

### A. Cálculos laborales

1. Auditar los formularios y las funciones de cálculo por tipo antes de modificar fórmulas.
2. Añadir una capa de diagnóstico de períodos: períodos esperados, períodos con datos confirmados, períodos faltantes y origen de cada dato.
3. Reutilizar datos salariales históricos únicamente cuando estén vinculados al mismo trabajador, empresa y período; nunca extrapolar automáticamente un salario sin marcarlo como sugerencia.
4. Mostrar las novedades que afectan al cálculo y exigir aprobación para ajustes sensibles.
5. Mantener los registros guardados como snapshots inmutables. Una corrección crea un registro nuevo que referencia el anterior.
6. Guardar de manera explícita la versión del motor y de las reglas normativas aplicadas.
7. Crear pruebas de regresión con resultados revisados por especialistas paraguayos antes de cambiar las fórmulas vigentes.

### B. REOP y REI

1. Conservar el flujo actual de preparación, validación y exportación.
2. Añadir panel unificado de vencimientos con filtros por empresa, organismo, tipo de evento y responsable.
3. Calcular vencimientos únicamente desde reglas documentadas y versionadas; registrar la fuente y la fecha de vigencia de cada regla.
4. No marcar un trámite como presentado o aceptado sin comprobante o respuesta verificable.
5. Mantener apagados los conectores directos hasta disponer de confirmación escrita, documentación, credenciales autorizadas y entorno de homologación de MTESS/IPS.
6. No almacenar PIN ni contraseñas de portales oficiales ni automatizar sesiones personales como sustituto de una API autorizada.

### C. Firma cualificada

1. Crear una interfaz interna de proveedor para evitar acoplar el sistema a un único prestador.
2. No implementar un proveedor ficticio ni marcar documentos como firmados sin respuesta verificable.
3. Solicitar a proveedores candidatos documentación de API/SDK, sandbox, identificación, validación de certificados, evidencia y costos.
4. Mantener el original firmado en almacenamiento privado y conservar huella criptográfica, transacción, datos de validación y auditoría.
5. Exigir aprobación explícita del contenido y acto personal de firma; nunca almacenar PIN ni claves privadas de los firmantes.

## Criterios de aceptación

- Las calculadoras existentes continúan pasando las pruebas de regresión.
- La aplicación conserva aislamiento entre empresas y controles de roles.
- Los reintentos de operaciones externas no duplican trámites ni documentos.
- Los estados oficiales distinguen borrador, validado, exportado, presentado, aceptado, observado y rechazado.
- Un error externo no bloquea la consulta de expedientes ni los cálculos locales.
- La firma solo se considera validada cuando se verifica el resultado del proveedor.
- Migraciones probadas en una copia de base de datos y procedimiento de reversión documentado.
- Ningún secreto, archivo de producción ni dato personal real se incorpora al repositorio.

## Orden de trabajo

1. Revisar los cálculos y sus pruebas actuales; documentar brechas exactas.
2. Implementar diagnóstico de cobertura de períodos sin cambiar las fórmulas.
3. Implementar panel de obligaciones sobre los modelos existentes.
4. Validar formatos REOP/REI con archivos de prueba y mantener presentación humana hasta autorización oficial.
5. Integrar firma en sandbox con un proveedor confirmado.
6. Ejecutar regresión, pruebas de permisos, restauración y despliegue gradual.

## Límite de esta entrega

Este documento registra el plan técnico derivado de la auditoría inicial. No representa una API oficial habilitada, un envío real a MTESS/IPS ni una firma electrónica cualificada implementada. Esas funciones requieren validación técnica y autorizaciones externas.
