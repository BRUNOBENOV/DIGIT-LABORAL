# Release notes — DigIT Laboral 2.5.6

## Automatización inicial de períodos

- Añade el panel autenticado `/app/calculations/periodos` para revisar la cobertura mensual de un trabajador por ejercicio.
- Detecta meses esperados según las fechas de ingreso/egreso y el mes actual de Paraguay.
- Distingue nóminas cerradas, nóminas abiertas, importes inconsistentes, cálculos salariales aislados y meses sin registro.
- Señala variaciones de salario base registradas.
- La opción de preparar aguinaldo puede reutilizar como propuesta la suma bruta de nóminas cerradas y consistentes, dejando trazabilidad en observaciones.
- La propuesta no se considera base legal validada: requiere revisión de conceptos computables, ajustes, anticipos y período aplicable.
- No se agregan tablas ni migraciones de base de datos; se reutilizan las entidades existentes de nóminas, líneas y cálculos.
- Se agregan pruebas unitarias de cobertura y una prueba de acceso autenticado al panel.

## Límites y seguridad

- La pantalla no calcula automáticamente una remuneración para meses sin registro.
- Las nóminas abiertas y las líneas cuyos importes no cuadran se excluyen de la suma sugerida.
- REOP/REI continúan en el modo de preparación/exportación/manual hasta contar con autorización y documentación técnica oficial.
- No se declara una firma cualificada integrada en esta versión.
- Este cambio está en una rama de trabajo y no implica un despliegue en producción.
