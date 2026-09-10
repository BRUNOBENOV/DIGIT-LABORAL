# Centro laboral: cálculo, documento e historial

Propósito: ayudar a empresas, contadores, abogados y empleados de Paraguay a calcular, comprender, documentar y gestionar obligaciones laborales.

## Cambios preparados

- Inicio orientado a tareas y a los cuatro públicos, con calculadoras sin cuenta y acceso profesional.
- Salario mensual, egreso, aguinaldo, vacaciones, horas y recargos.
- Desglose de bases, fórmulas, haberes, descuentos, neto y costo patronal.
- PDF A4 con original y duplicado, CSV protegido contra fórmulas y vista de impresión.
- Guardado por empresa y funcionario con una copia del resultado y controles de acceso por estudio.
- Recibos de las nóminas existentes; descarga por funcionario o lote ZIP.
- Base y tasa IPS persistidas, incluido cero, sin reconstruir la historia con parámetros actuales.
- Rechazo de importes negativos, descuentos superiores a haberes y cierre de nóminas inconsistentes.
- Corrección de escalas de preaviso y vacaciones al día siguiente del aniversario.

## Criterios laborales

Fuentes revisadas el 9 de septiembre de 2026:

- Código del Trabajo: https://www.mtess.gov.py/wp-content/uploads/2026/01/Ley_213.pdf
- Edición concordada OIT: https://www.ilo.org/sites/default/files/wcmsp5/groups/public/@americas/@ro-lima/@sro-santiago/documents/publication/wcms_709389.pdf
- Aportes IPS: https://portal.ips.gov.py/sistemas/ipsportal/contenido.php?c=69
- Base IPS: https://portal.ips.gov.py/sistemas/ipsportal/contenido.php?c=59
- Vacaciones: https://www.mtess.gov.py/?p=34520
- Salarios mínimos 2026: https://www.mtess.gov.py/?p=36371

Las tasas generales sugeridas son 9% trabajador y 16,5% empleador. Se verifica la base y régimen del caso. El egreso exige base IPS manual y explicación; no presupone exención de todos sus conceptos. El mínimo de vacaciones es un dato obligatorio del período y la actividad, no una constante universal.

La indemnización ordinaria usa 15 salarios diarios por año o fracción estrictamente superior a seis meses. La estabilidad desde diez años, los fueros, los contratos no indefinidos y otras causas generan un subtotal parcial para revisión. No se determina la legitimidad de un despido ni se descuenta automáticamente preaviso a cargo del trabajador.

Los documentos se emiten como borradores para revisión, pago y firma. Su creación no acredita pago ni implica renuncia de derechos.

## Migración y conservación

0006 agrega columnas a payroll_lines. No reescribe importes históricos. Las bases o tasas históricas desconocidas quedan nulas; al editar, el responsable debe revisarlas. Los recibos exportan los importes de la nómina guardada.

Los cálculos del centro usan la tabla CalculationRecord ya existente y guardan datos de entrada, resultado y versión. Los cambios futuros de parámetros no recalculan los documentos del historial.

## Validación

El flujo labor-suite.yml ejecuta casos de límites por fecha, redondeo, IPS cero, haberes protegidos, PDF/CSV, validación de formularios, CSRF, aislamiento por estudio, historial inmutable, guardado de nómina y migración sin alterar importes. Consultar los resultados de GitHub Actions del commit; la presencia del archivo de pruebas no acredita su ejecución.

Primera ejecución: 40 pruebas aprobadas en el commit 7004768efd7bcaed03804014d70c7b9500c472eb. Se añaden los controles de arranque y personas utilizados por el Dockerfile, sobre una base temporal y datos sintéticos.

Pendientes antes de una publicación final: comprobar el arranque en Render con su configuración de producción, inspección visual en escritorio y móvil, revisión de paginación de PDFs renderizados y comprobación en Render. El entorno local anterior quedó inaccesible antes de completar estas verificaciones. Esta rama reconstruye los cambios a partir de la revisión realizada; no recupera archivos inaccesibles ni afirma que estén publicados.
