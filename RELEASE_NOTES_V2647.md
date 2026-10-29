# DIGIT-LABORAL 2.6.47 — Correcciones de auditoría

## Correcciones incluidas

- La edición de nómina guarda base IPS, tasa, criterio, jornadas trabajadas y aporte patronal en el detalle de cumplimiento. Los valores no contribuidos se guardan explícitamente como base y tasa cero.
- Los importes negativos se rechazan en vez de convertirse silenciosamente en cero. No se guarda una nómina ni un cálculo salarial cuyo total de descuentos exceda los haberes computables.
- La aprobación del cálculo vuelve a reproducir los datos guardados y bloquea resultados que no coincidan con la fórmula reproducida.
- Vacaciones en el calculador general usa una escala mínima mensual fechada: Gs. 2.899.048 desde julio de 2025 y Gs. 3.044.000 desde julio de 2026. Si la escala histórica no está disponible, se rechaza el cálculo en lugar de suponer un mínimo.
- La generación automática de números documentales bloquea la fila de la empresa en PostgreSQL para serializar la asignación del siguiente número entre solicitudes concurrentes.
- Se agregan pruebas unitarias para entradas negativas/invalidas, exceso de descuentos y la base salarial de vacaciones.

## Pendiente de verificación antes de producción

- Ejecutar y revisar el workflow completo de pruebas tras estos cambios.
- Confirmar jurídicamente la frontera exacta de seis meses en la fórmula de indemnización; no se modificó esa regla sin validación jurídica.
- Confirmar el rol efectivo de base de datos usado por Render y su capacidad de omitir RLS.
- Los motores general, profesional y nómina siguen existiendo como recorridos diferenciados. La unificación completa requiere una etapa de equivalencia y regresión legal.
