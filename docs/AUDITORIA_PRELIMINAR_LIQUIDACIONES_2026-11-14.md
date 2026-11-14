# Auditoría preliminar de liquidaciones laborales — 14/11/2026

**Alcance:** inspección estática del código del repositorio. **No se accedió a la base de datos productiva, no se ejecutaron cálculos con datos personales y no se certifica el funcionamiento integral.** Un estado `Aprobado` no es prueba de pago.

## Fuentes normativas

- Ley N.º 213/93, Código del Trabajo: https://www.bacn.gov.py/leyes-paraguayas/2608/ley-n-213-establece-el-codigo-del-trabajo
- Ley N.º 496/95, modificaciones, particularmente arts. 91 y 218: https://www.bacn.gov.py/leyes-paraguayas/2514/ley-n-496-modifica-amplia-y-deroga-articulos-
- MTESS, guía de REOP de liquidación de salarios (2025): https://www.mtess.gov.py/wp-content/uploads/2025/10/Guia-liquidacion-de-salarios-v1.pdf
- MTESS, vacaciones 06/01/2026 y Resolución N.º 1290/2024: https://www.mtess.gov.py/?p=34520
- MTESS, Resolución N.º 670/2026 y mínimo vigente desde 01/07/2026: https://www.mtess.gov.py/?p=36371
- MTESS, Guía de seguridad social: https://www.mtess.gov.py/wp-content/uploads/2025/10/Guia-de-Seguridad-Social-para-trabajadores-Asalariados-del-Sector-Privado-MTESS-MODIFICADO-FINAL.pdf

## Hallazgos verificables

| ID | Criticidad | Código | Hallazgo y criterio de aceptación |
| --- | --- | --- | --- |
| CAL-01 | Alta | `app/labor_calculator.py` (`calculate`, `kind=settlement`) y `app/calculator_fields.py` | La liquidación final fija `pay_basis=monthly`; el formulario no ofrece modalidad jornalera ni jornal real. **No aprobar liquidaciones de jornaleros sin corregir el circuito completo**, incluidos salario pendiente, vacaciones, promedio indemnizatorio y PDF. |
| CAL-02 | Alta | `app/payroll_average.py` | La propuesta automática de seis meses admite solo `salary_type=Mensual` y períodos mensuales completos. En jornaleros y meses parciales requiere respaldo, no completar con salario actual ni dividir de forma irreflexiva. |
| CAL-03 | Alta | `app/payroll_annual.py` | El aguinaldo puede recibir una suma parcial cuando faltan remuneraciones; `annotate_annual` activa resultado parcial. La revisión final debe impedir aprobación de totales incompletos y conciliar salarios guardados, mensualidades parciales y conceptos computables. |
| CAL-04 | Alta | `app/labor_calculator.py`, campos `pending_days`, `double_days`, `proportional_days` | Días de vacaciones de liquidación final son manuales. No existe conciliación obligatoria del período adquirido, usufructo/pago ya efectuado, saldo y duplicación legal. Debe evitarse pagar dos veces o tomar eventos históricos como saldo automático. |
| CAL-05 | Alta | `app/unified_labor_history.py`, `app/legacy_liq_import.py`, `app/payroll_annual.py` | Los registros antiguos LIQ se proyectan como eventos históricos con estado de visualización `Aprobado`, pero no equivalen necesariamente a `CalculationRecord` operativo ni acreditan pago. Una normalización única, idempotente y auditada debe validar integridad y evitar duplicados; no ejecutar una migración masiva sin prueba sobre copia de DB. |
| CAL-06 | Alta | `app/labor_calculator.py` | El motor solicita remuneración anual manual y comprueba solo que sea al menos la remuneración del egreso. Ello no demuestra que se incluyeron todos los salarios devengados. Requerir evidencia y clasificación para aprobar. |
| CAL-07 | Media | `app/labor_calculator.py`, `app/settlement_presets.py` | La propuesta de doble indemnización para antigüedad >= 10 años es condicionada; no se debe activar como monto definitivo por la sola antigüedad. Conservar confirmación documental, revisión de los arts. 94–99 y régimen de protección. |
| CAL-08 | Media | `app/labor_calculator.py`, `app/labor_rules.py` | La liquidación mensual usa divisor 30, el jornal pactado puede usar 26 días como referencia, y las reglas de vacaciones dependen de modalidad. Validar con casos en que el jornal es pactado y distinto del mínimo. |
| CAL-09 | Media | `app/labor_calculator.py` | Hasta 31 días declarados a jornal genera advertencia, no bloqueo. El reporte REOP distingue 26 jornadas a jornal y 30 para mensualizados en el período típico; exigir motivo y fuente cuando existan excepciones. |
| CAL-10 | Media | `app/labor_calculator.py` | IPS calcula 9% del trabajador y parametriza 16,5% patronal. Base del egreso obligatoriamente manual cuando se aplica; conciliar conceptos y no inventar base cero. |
| CAL-11 | Media | `app/labor_calculator.py` | Dobles vacaciones y egresos especiales requieren acreditación y revisión. La operación matemática simple no valida el derecho jurídico a duplicación. |
| CAL-12 | Media | `app/labor_rules.py` | `aguinaldo_amount` convierte a float antes del redondeo, a diferencia del motor de Decimal. Unificar manejo `Decimal` para evitar pérdida de precisión en importes grandes. |
| CAL-13 | Media | `app/liquidation_export.py`, rutas de informes | Verificar con tests de extremo a extremo que PDF, vista previa, informe y exportación usen exactamente el snapshot aprobado, sin recálculo involuntario, duplicados ni estados inconsistentes. |
| UX-01 | Resuelto en esta rama | `app/templates/labor_workbench.html` | Retirar el importador excepcional de la pantalla permanente. La ruta técnica permanece disponible para uso administrativo extraordinario. |
| UX-02 | Resuelto en esta rama | `app/unified_labor_history.py` | Suprimir sufijo `· LIQ` y etiquetas de origen en la consulta ordinaria. Conservar `origin`, `source` y el evento para auditoría. |

## Casos de prueba de referencia (no ejecutados)

1. Mensualizado: salario Gs. 3.044.000, 30 días, 9% IPS, sin otros haberes/descuentos: bruto 3.044.000, IPS 273.960, neto 2.770.040, aporte patronal 502.260.
2. Mes parcial mensualizado: salario 3.044.000, 10 días: salario del período 1.014.667 según redondeo comercial.
3. Jornalero mínimo general diurno julio 2026: jornal 117.077, 26 jornales = 3.044.002. La diferencia Gs. 2 frente al mínimo mensual refleja redondeo del jornal oficial, no autoriza sustituir el jornal contractual.
4. Aguinaldo: 12 meses con remuneración computable 3.044.000 y sin adicionales = 36.528.000 / 12 = 3.044.000.
5. Antigüedad 4 años completos, promedio mensual 3.044.000, despido injustificado (sin tutela especial): 60 jornales indemnizatorios = 6.088.000; preaviso no cumplido 45 días = 4.566.000.
6. Escala vacaciones del art. 218 modificado: 12 días hasta 5 años, 18 con más de 5 hasta 10, 30 con más de 10 años.
7. Borde indemnizatorio del art. 91 modificado: la fracción debe ser **superior** a seis meses; probar seis meses exactos y seis meses más un día.
8. Protección por estabilidad: antigüedad de 10 años no implica automáticamente el pago doble; verificar el supuesto legal y su respaldo.

## Condiciones antes de afirmar «todos los cálculos son correctos»

- Ejecutar `pytest` y tests frontend en copia del proyecto, sin DB productiva.
- Cargar casos de cada modalidad y causa de egreso; comparar importes por concepto con cálculos independientes y resolución aplicable.
- Verificar integridad de las fuentes salariales por mes, reconcilación de ausencias, IPS, vacaciones pagadas y pendientes; prueba de regresión de informes.
- Probar importación **una sola vez** sobre una copia de base, con hash por fila, reintento idempotente, conteos antes/después, rollback y revisión de duplicados.
- Bloquear aprobaciones con incertidumbre legal o salarial sin respaldo documentado.

> Este documento es un inventario de hallazgos y pruebas pendientes, no una certificación contable o dictamen jurídico individual.
