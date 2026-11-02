# DIGIT-LABORAL v2.6.70 — Conciliación de Salarios y exportaciones

## Problema resuelto
Una empresa podía tener múltiples cálculos de Salario aprobados en `calculation_records`, pero el exportador REOP / REI solo leía `payrolls` cerradas y mostraba «No existe nómina».

## Cambios
- Origen **Automático**: elige la nómina cerrada cuando existe; en caso contrario examina los últimos cálculos salariales por legajo. También permite seleccionar manualmente uno de los dos orígenes.
- Versión por funcionario: el último cálculo controla el período. Los cálculos anulados o «Revisar» no reactivan aprobaciones anteriores. Nunca se mezclan fuentes en un mismo archivo.
- Vista previa y explicación de faltantes por funcionario.
- Jornadas, horas ordinarias reales, intervalo y medio de pago se pueden guardar como anexos declarativos trazables mediante `SalaryImportDetail`; se vinculan al hash del cálculo de origen y nunca modifican importes de salarios.
- Cálculo → Salarios (calculadora básica): campos opcionales de jornadas, horas efectivamente trabajadas y forma de pago, guardados en el snapshot.
- Cálculos guardados aprobados tienen acceso directo al exportador.
- Los importes de REOP y bases imponibles IPS del REI siguen siendo validados contra valores guardados; no se infieren horas reales desde el divisor horario.
- Si un concepto del motor profesional no tiene correspondencia comprobada con REOP/REI, se bloquea su exportación.
- Historial de lotes conserva la fuente elegida.

## Seguridad y límites
- Cambios de datos auxiliares requieren rol administrador o contador y confirmación.
- La migración `0020_salary_import_details` crea una tabla independiente; no transforma cálculo ni nómina.
- El formato REI proviene de una guía de 2016; requiere cotejarlo con el portal actual del IPS.
- El Excel REOP utiliza la estructura entregada como referencia; la validación local no equivale a aceptación oficial.
- Si una nómina todavía está en Borrador, no puede exportarse como cerrada. Solo se utilizan cálculos individuales aprobados cuando el origen lo permite.

## Pruebas
Regresión para ausencia de nómina, cálculos aprobados, documentos incompletos, versiones anuladas, hash de anexos y base IPS inmutable.
