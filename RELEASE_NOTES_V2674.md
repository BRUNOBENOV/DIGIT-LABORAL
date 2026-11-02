# DIGIT-LABORAL v2.6.74 — Datos de cálculo y exportación REOP/REI

## Diagnóstico real
El cálculo salarial histórico aprobado de referencia (octubre de 2026) proviene de `Calculadora v2.4`. Su `input_json` registra los haberes, la base IPS y la tasa, pero **no contiene `days_worked`, `hours_worked` ni `payment_method`**. Es imposible recuperarlos automáticamente de ese registro sin inventar información.

Se detectó también que otros legajos tenían borradores profesionales del mismo período, generando observaciones en una exportación iniciada para un trabajador concreto. No deben confundirse los campos de un legajo con los de otro.

## Mejoras
- Enlace **Exportar REOP/REI** de cada cálculo salarial aprobado filtra por su propio legajo.
- Vista de exportación informa «Exportación individual», con opción para volver a todos los trabajadores.
- API GET/POST del exportador propaga el filtro `employee_id` y comprueba que el empleado pertenezca a la empresa accesible al usuario.
- Archivo e historial registran alcance individual o por empresa, sin mezclar legajos ni añadir importes ajenos.
- REI: elimina validaciones innecesarias de horas ordinarias y forma de pago; se requieren solo las jornadas realmente registradas y los demás campos del instructivo correspondiente.
- Formulario REI acepta guardar solo jornadas reales sin borrar horas ni medio de pago REOP previamente ingresados en el anexo.
- REOP: sigue exigiendo jornadas, horas ordinarias reales, forma de pago y validación contable.
- La base IPS para cálculos antiguos conserva la tasa histórica de `input_json` cuando `result_json` no la tenía y respeta `apply_ips=false` sin fingir un descuento de 9%.
- El formulario aclara que los datos no guardados en una liquidación histórica no pueden inferirse de días pagados, divisor de 240 horas u otros trabajadores.

## Límites
No cambia importes históricos ni fabrica jornadas. Los datos complementarios que no existían requieren confirmación una vez, se registran en tabla independiente y serán reutilizados por exportaciones siguientes. El formato TXT REI procede de instructivo de 2016 y continúa pendiente de verificar frente al importador IPS vigente.

## Pruebas
Regresiones sobre tasas IPS históricas, ausencia de horas/forma de pago en REI, exigencia REOP, filtro de empleados y preservación del historial del cálculo.
