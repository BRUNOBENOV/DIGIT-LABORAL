# Versión 2.6.29 — Liquidación de Salarios

## Funcionalidad

- Acceso dedicado desde Informes: `/app/reports/liquidaciones-salarios`.
- Busca los cálculos de salario ya guardados en Cálculo, tanto del motor clásico como del motor profesional.
- Filtra por empresa, funcionario, período, estado y texto.
- Presenta empleador, número patronal, datos del funcionario, período, conceptos de haberes, descuentos, total bruto, total descontado y neto guardado.
- Incluye observaciones, validaciones de consistencia, fechas y espacios para las firmas del empleador y del trabajador.
- Imprime desde el navegador o descarga PDF A4.
- Muestra registros anteriores del mismo funcionario y período como versiones históricas sin sobrescribir los importes anteriores.
- Registra las reimpresiones y descargas PDF en Auditoría.
- Restringe cada consulta a las empresas visibles para el usuario de la sesión y bloquea la reimpresión de cálculos anulados.

## Alcance contable y documental

El informe reproduce el resultado persistido del cálculo: no modifica conceptos, importes ni el neto para hacerlos coincidir. Cuando hay datos incompletos o totales que no concuerdan, muestra avisos que deben revisarse antes de firmar. Los cálculos anteriores se presentan como versiones históricas del período; no se crean importes ficticios ni se certifica un pago efectivo.

El recibo es un documento interno de DIGIT-LABORAL, no un formulario oficial expedido por MTESS o IPS. Debe comprobarse la normativa aplicable, la base imponible y el pago antes de su uso formal.
