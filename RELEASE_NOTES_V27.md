# Digit Laboral 2.6.27 — Integridad de informes

## Correcciones funcionales
- Los informes por concepto reconocen tanto registros de calculadoras heredadas como registros del motor profesional con prefijo `suite_`.
- Liquidación de haberes, aguinaldo y vacaciones se conectan con los tipos específicos de cálculo, diferenciándolos de los listados históricos de vacaciones y aguinaldo.
- Planilla de Horas usa las horas registradas junto a la nómina; Planilla de Horas-1 conserva las operaciones horarias.
- El selector de ordenamiento muestra opciones válidas para el tipo de reporte.

## Seguridad y exportaciones
- Los textos ingresados por usuarios en XLSX se fuerzan a texto para impedir que se ejecuten como fórmulas.
- El encabezado PDF escapa los datos patronales antes de renderizarlos.

## Pruebas
- Verifica consultas de cálculos profesionales guardados en salario, haberes, aguinaldo y vacaciones.
- Verifica que una cadena con apariencia de fórmula se exporta como texto en XLSX.
