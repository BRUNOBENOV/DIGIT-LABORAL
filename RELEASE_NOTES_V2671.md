# DIGIT-LABORAL v2.6.71 — Corrección HTTP 409 al aprobar salarios históricos

## Causa identificada
La columna `calculation_records.source` tiene el valor predeterminado histórico `Calculadora`. La ruta de aprobación únicamente reconocía `Cálculo automático` y `Centro laboral`; al encontrar `Calculadora`, rechazaba el registro con «No se puede validar el motor que generó este registro».

## Solución
- Reconocer `Calculadora` como origen histórico de los cálculos generales documentados (`salary`, `hours`, `aguinaldo`, `vacation`, `notice`).
- Reproducir las fórmulas utilizando el **input_json y result_json originales**, sin recalcular ni alterar importes persistidos.
- Para registros anteriores que no guardaron `ips_rate` en entradas, preferir la tasa guardada en el resultado; de faltar ambos, conservar el mecanismo previo de contraste estricto.
- Mantener HTTP 409 cuando los importes o conceptos no coincidan, falten datos reproducibles o el origen sea desconocido.
- Mejorar mensaje de diagnóstico cuando un motor de origen no sea reconocido.
- Incorporar pruebas de caso histórico correcto, tasa histórica, alteración de importe, alteración del aporte, origen desconocido y datos incompletos.

## Alcance
No modifica cálculos guardados, pagos, nóminas, ni exportaciones REOP/REI. Solo habilita la aprobación cuando la validación puede reproducir el cálculo correctamente.
