# DigIT-Laboral 2.6.4 — Sistema visual global

## Objetivo
Unificar la experiencia visual en los módulos autenticados sin reescribir el backend ni introducir otro framework de UI. El proyecto continúa con FastAPI, Jinja2, CSS y JavaScript progresivo.

## Cambios
- Nueva hoja global `app/static/ui-system-264.css`: tarjetas y paneles, separación, formularios, controles, tablas, feedback, modales, foco de teclado, responsividad, texto escalable y movimiento reducido.
- Nueva capa de comportamiento `app/static/ui-system-264.js`: validación de campos después de la interacción, búsqueda rápida por tabla, contador de filas visibles y ordenación por encabezados para tablas aptas.
- Nueva plantilla `app/templates/module_subnav.html`: navegación secundaria para Cálculo, Informes, Certificados, Utilitarios y mantenimiento administrativo.
- Macros reutilizables `app/templates/components/ui.html`: `tab_nav`, `section_card` e `inline_help`.
- Documentación de componentes y ejemplos: `docs/UI_SYSTEM_V264.md`.

## Alcance y compatibilidad
- Los cambios visuales se restringen al espacio autenticado y conservan el tema azul/blanco y el sidebar azul marino.
- Los listados dinámicos mantienen el conjunto de resultados filtrados en el servidor y agregan controles locales de búsqueda/ordenación.
- Se respetan los comportamientos específicos existentes de Empresas y Funcionarios, los formularios de cálculo, las páginas públicas y las vistas imprimibles.
- No hay migraciones de base de datos; no se cambian roles, rutas de negocio ni fórmulas laborales.
- La navegación permanece server-rendered. No se sustituye por una SPA ni se interceptan formularios sensibles, para evitar afectar a los scripts de cada módulo.

## Verificación
- Nuevas pruebas de regresión para recursos CSS/JS, macros y navegación de los principales módulos.
- La publicación depende de CI en verde y la confirmación del despliegue Render.
