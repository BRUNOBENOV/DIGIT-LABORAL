# DIGIT-LABORAL v2.6.72 — Corrección de aprobación histórica (409)

## Diagnóstico
La versión 2.6.71 reconocía el origen `Calculadora`, pero la base también contiene cálculos de origen `Calculadora v2.4`. Su aprobación devolvía HTTP 409 antes de intentar validar los importes.

## Cambio
- Se reconoce de forma **explícita** el origen histórico `Calculadora v2.4` junto a `Calculadora` y `Cálculo automático`, sin aceptar versiones desconocidas por prefijo.
- Solo se permite aprobar tipos conocidos de la calculadora general con reproducción exacta de los conceptos guardados, el neto y, cuando aplique, la tasa IPS histórica.
- Los resultados incompletos o inconsistentes siguen bloqueados con HTTP 409.
- No se transforman ni alteran registros existentes; tampoco se ejecutan migraciones.

## Pruebas
Se añadieron regresiones para `Calculadora v2.4` con tasa IPS presente y ausente en los inputs, importes modificados, datos inválidos y versiones de origen desconocidas.
