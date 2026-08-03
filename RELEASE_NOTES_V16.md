# Digit Laboral v1.4 Preview

## Automatización empresarial

- Nueva configuración de identidad visual por empresa.
- Carga de logo PNG o JPG de hasta 2 MB.
- La empresa vinculada puede actualizar su propio logo y membrete sin modificar el expediente laboral.
- Colores principal y secundario, firma autorizada, cargo del firmante, pie de documento y prefijo de numeración.
- Indicador de integridad del expediente y alertas de datos faltantes.

## Cálculos conectados

- Los cálculos se guardan en la base de datos con empresa, funcionario, periodo, entradas, resultados, monto, estado y usuario creador.
- Estados: Borrador, Revisado, Aprobado y Anulado.
- Un cálculo puede abrir directamente el generador de certificados.
- Aguinaldo y vacaciones pueden reutilizar datos registrados previamente.
- Los cálculos aparecen en el expediente, informes y panel principal.

## Certificados y documentos

- Numeración automática por empresa, año y tipo documental.
- Relación trazable entre cálculo y documento generado.
- Logo, colores, membrete, firma y pie configurables en Word y PDF.
- Vista previa conectada con los datos reales de empresa y funcionario.
- Historial de documentos y estado de emisión.

## Informes

- Centro de informes por empresa y funcionario.
- Informe integral del funcionario en PDF.
- Exportación CSV de cálculos.
- Resumen de cálculos, certificados, vacaciones y aguinaldos.

## Asistente de IA

- Motor interno disponible sin servicios externos.
- Integración opcional con OpenAI mediante la Responses API.
- Consentimiento explícito antes de enviar el contexto seleccionado a la IA externa.
- Envío limitado a datos estructurados de la empresa, funcionario y cálculos elegidos.
- Registro de cada consulta en auditoría.
- La IA no ejecuta modificaciones ni aprueba documentos automáticamente.

## Calidad

- Versión del health check: `1.4.0-preview`.
- Once pruebas automáticas aprobadas.
- Verificación manual de rutas, Word, PDF e informes.
- Las tablas nuevas se crean automáticamente sin borrar registros existentes.
