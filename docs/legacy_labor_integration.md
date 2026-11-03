# Integración progresiva de históricos DOS a DIGIT-LABORAL

## Política general
Los movimientos antiguos se importan primero como **evidencia histórica trazable**. No constituyen por sí solos una operación aprobada, un pago, una declaración oficial ni un saldo disponible. La conciliación profesional es independiente.

## Relaciones obligatorias

| Fuente | Enlace | Regla |
| --- | --- | --- |
| Empresas DOS | Company.legacy_code | CODEMP; empresa autorizada en el estudio |
| Trabajadores DOS | Employee.notes y código de empleado | CODEMP + CODTRA; contemplar reingresos |
| Vacaciones DOS LSVAC | EmployeeEvent, tipo Vacaciones históricas | Prefijo DIGIT_LSVAC_V1, legacy_key y source_hash |
| Próximo preaviso DOS | Pendiente de recibir el archivo | Verificar columnas y significado antes de modelar |

Cada vista y exportación verifica el estudio autorizado. Las huellas históricas, importes, fechas, archivo y fila de origen se mantienen, sin reinterpretación automática.

## Vacaciones: integración v2.6.83
- Vacaciones: filtrado, paginación, detalle del registro, CSV con origen y auditoría.
- Expediente: antecedentes históricos legibles y vinculados al funcionario.
- Histórico del Funcionario: sección documental, distinta del saldo operativo.
- Cálculo de Vacaciones: advertencia y consulta; no autocompleta días o importes.
- Informe integral PDF: antecedente con advertencia y muestra histórica.
- REOP/REI: las filas importadas no originan ninguna declaración oficial.

Los modelos Vacation y CalculationRecord conservan independencia. En una futura conciliación, cada saldo validado deberá registrar período, base jurídica, respaldo, usuario, fecha y controles contra duplicación.

## Próximo archivo: preaviso
1. Auditar encabezados, importes, fechas y archivos relacionados.
2. Relacionar CODEMP/CODTRA contra identidades ya migradas.
3. Distinguir aviso comunicado, preaviso cumplido e indemnización sustitutiva. Un cálculo no prueba que hubo pago o notificación.
4. Vista previa, duplicados, reingresos, conflictos y respaldo de origen.
5. Persistir como antecedentes de solo lectura con identificadores únicos antes de cualquier afectación operativa.
6. Integrar expediente, Histórico, Preaviso, Liquidación final e informes mediante enlaces y contexto, sin reclasificar automáticamente obligaciones.
7. Probar permisos, auditorías, exportaciones, exactitud y no alteración de nóminas o liquidaciones vigentes.
