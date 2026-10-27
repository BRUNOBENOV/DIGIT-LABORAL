# Digit Laboral 2.5.9 — Salarios por período

## Cambios funcionales

- Se incorpora un resolver común basado en SalaryHistory.effective_from para saber qué salario corresponde sugerir en una fecha determinada.
- El Centro Profesional precarga el salario según el inicio del período en la calculadora salarial y según la fecha de egreso en la liquidación de haberes.
- Si el usuario cambia el mes salarial o la fecha de egreso, el formulario actualiza la sugerencia usando el historial fechado.
- Las nóminas nuevas utilizan el salario vigente al comienzo del mes. Para un trabajador ingresado dentro del período, se toma la vigencia registrada a la fecha de ingreso.
- Los cambios salariales intra-mes y las altas a mitad de período se documentan como alertas de revisión manual en las observaciones; no se realiza un prorrateo automático sin una regla expresamente validada.
- Los funcionarios con fecha de ingreso posterior al cierre del período no se incluyen en una nómina nueva de ese período.
- No se modifican cálculos guardados, nóminas anteriores, fórmulas legales ni conectores oficiales.

## Pruebas

Se incorporan pruebas para la selección de salario por fecha, cambios de salario futuros, legajos legados sin historial, cambios dentro de un mes y altas de personal a mitad de período.

## Alcance

La precarga es una propuesta revisable. El profesional responsable debe revisar salarios, días efectivamente trabajados, altas/bajas y todo cambio salarial ocurrido dentro del período antes de cerrar y emitir la nómina.
