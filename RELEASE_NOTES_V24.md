# Digit Laboral 2.4.0

**Fecha:** 24 de octubre de 2026

## Sector: vacaciones y consistencia de registros

- Las fechas de inicio y fin se validan antes de guardar. Una fecha mal formada ya no se convierte silenciosamente en un campo vacío.
- Se exige informar ambas fechas juntas o dejar las dos vacías; los estados que requieren planificación deben contener el rango.
- No se admite iniciar vacaciones antes de la fecha de ingreso registrada del funcionario.
- Los estados `Pendiente` y `Aprobada` no pueden declarar días ya utilizados.
- El estado `Completada` exige días utilizados mayores que cero y una fecha de fin que no sea futura.
- Se mantienen el límite de días, la validación de rango y la referencia automática de antigüedad del Código del Trabajo.
- Se agregaron pruebas de regresión para fechas inválidas, rangos parciales, fechas previas al ingreso, estados inconsistentes y vacaciones completadas con fechas futuras.

## Versionado

- La versión canónica se mantiene en `VERSION`.
- El fallback de `APP_VERSION` se actualiza a `2.4.0` para que la interfaz no muestre una versión antigua si el archivo no está disponible.
- El indicador de la barra superior muestra la versión y el identificador de build.

## Alcance y advertencia

Estas validaciones mejoran la integridad de los registros; no sustituyen la revisión profesional del derecho anual, de regímenes especiales, de acumulaciones autorizadas ni del calendario laboral aplicable. La escala de antigüedad se conserva como referencia de control basada en el artículo 218 del Código del Trabajo.

La actualización del repositorio no demuestra por sí sola que Render esté ejecutando esta versión. La versión real debe confirmarse en el servicio después del despliegue.
