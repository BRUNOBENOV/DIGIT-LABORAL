# DIGIT-LABORAL v2.6.73 — Validación de resultados históricos (HTTP 409)

## Causa confirmada en la base de datos
Siete registros de salario creados con el origen `Calculadora v2.4` guardaron estos **cinco campos económicos** en `result_json`:
- `gross_computable`
- `ips_base`
- `ips_employee`
- `discounts`
- `net`

La tasa `ips_rate` sí está en `input_json`, pero **no está en `result_json`**.
El validador actual agrega `ips_rate` en su nuevo resultado y comparaba diccionarios completos; por eso devolvía HTTP 409 incluso cuando todos los importes coincidían.

Una verificación SQL de lectura comprobó que los siete registros históricos salariales mantienen consistentes bruto, aporte IPS y neto. No se modificó ninguna fila.

## Corrección
- Reproducción estricta con el motor vigente usando las entradas históricas.
- Para **`Calculadora v2.4` + `salary` solamente**, admitir la diferencia **exclusiva** del campo adicional `ips_rate` del nuevo resultado.
- Comparar uno a uno los cinco campos económicos y el importe de `calculation_records.amount`.
- Otros campos extra, conceptos ausentes, valores modificados, orígenes desconocidos o diferencias numéricas siguen bloqueados.
- No modifica liquidaciones, nóminas, archivos REOP/REI ni bases de datos.

## Pruebas de regresión
- Snapshots auténticos en estructura (sin datos identificables) con IPS habilitado y deshabilitado.
- Alteraciones en bruto, IPS, descuentos y neto.
- Ausencia de campos monetarios y campos desconocidos.
- Verificación de que otros orígenes no obtengan la excepción.
