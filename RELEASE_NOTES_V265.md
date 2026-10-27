# DigIT-Laboral 2.6.5 — Contraste de la sidebar

Esta versión corrige el problema puntual de legibilidad en la barra lateral izquierda. No rediseña las páginas de los módulos ni cambia sus formularios o tablas.

## Ajustes
- Texto de los subapartados en gris casi blanco/blanco sobre fondo azul marino.
- Categorías más claras y distinguibles de sus enlaces hijos.
- Subapartado activo con fondo azul vivo, tipografía blanca y borde izquierdo claro.
- Hover, flechas, números de categoría, notificaciones y foco por teclado reforzados.
- Mismo contraste en pantallas móviles.

## Implementación
- Hoja específica: `app/static/sidebar-contrast-265.css`, cargada al final de los estilos compartidos para que tenga prioridad.
- Sin cambios de base de datos, rutas, permisos ni lógica laboral.
