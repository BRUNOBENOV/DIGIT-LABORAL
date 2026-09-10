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

Validación del commit 08c5033a551916fde75af00edb7e5a77c09075a7: 41 pruebas aprobadas; PERSONA_QA_OK con 12.667 comprobaciones y cuatro perfiles; Dashboard smoke OK con ocho plantillas y 25 rutas críticas. Ejecución: https://github.com/BRUNOBENOV/DIGIT-LABORAL/actions/runs/34420394903.

El 10 de septiembre se renderizaron e inspeccionaron recibos A4 de salario y egreso con datos sintéticos: una página por copia, original y duplicado, sin recortes. Se incorporaron fuentes DejaVu con su licencia para evitar diferencias entre visores y se separaron las firmas en columnas. Las dos pruebas específicas de PDF volvieron a aprobarse.

La comprobación de interfaz y arranque de producción se realiza en Render después de desplegar. El navegador de revisión no permite abrir la dirección local del servidor. Los resultados de publicación y navegación se registran en la solicitud de cambios; este documento no afirma que el despliegue ya esté activo.
