# DIGIT-LABORAL v2.6.69 — Exportación salarial REOP / REI

## Alcance
- Nueva pantalla en Cumplimiento para seleccionar empresa y período de una nómina **cerrada**.
- REOP: Excel de **32 columnas exactas** siguiendo la plantilla `recibo_salarios (1).xlsx` entregada como referencia. Una sola hoja Hoja1, fechas Excel reales, sin pestañas extra.
- REI: TXT tabulado sin encabezados, codificación Windows-1252, conforme a la **referencia visual del instructivo IPS fechado 06/05/2016**; incluye 11 campos identificados. **Pendiente de homologación operativa actual con IPS.**
- Validaciones de base/aporte IPS, bruto, descuentos y neto; detalle de días, horas, fechas, número patronal y clasificación de ingresos.
- Solicita revisión explícita de códigos de pago REOP y orden de nombres/categoría REI. No adivina horas extraordinarias por sus montos: las bloquea cuando falta el conteo.
- Historial auditable por lote, hash SHA-256, empresa, período, fecha, usuario y cantidad de trabajadores; el archivo se conserva con la extensión y tipo MIME apropiados.
- Descargas manuales, sin presentación automatizada, ni sustitución del comprobante del organismo.

## Limitaciones deliberadas
1. La plantilla REOP referida es la proporcionada en esta implementación. Comprobar que coincida con el modelo vigente del portal antes de presentar.
2. Los códigos de medio de pago REOP deben verificarse contra la configuración del portal. Si hay métodos distintos en una nómina, se bloquea un único código global.
3. Las nóminas sin detalle o con importes inconsistentes deben corregirse mediante procedimientos de nómina; no se modifican resultados cerrados.
4. REI: el PDF de 2016 no es la planilla Excel original de IPS y no acredita aceptación del formato en 2026. Revisar layout y valores de categoría, nombres, número de asegurado y código de actividad antes de usar el TXT.
5. No se activan API externas ni automatización de accesos a portales.

## Pruebas añadidas
`tests/test_official_salary_import.py`: columnas exactas, fechas Excel, TXT tabulado, rechazo de base IPS inconsistente y de salarios incompletos o sin clasificar.
