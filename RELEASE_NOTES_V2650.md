# DIGIT-LABORAL 2.6.50 — Animaciones y contraste del menú lateral

## Objetivo
Conservar el tratamiento visual anterior del menú, sin sacrificar la lectura del submódulo activo.

## Comportamiento esperado
- En reposo, el apartado seleccionado muestra fondo blanco, texto azul oscuro `#0B2D78` y acento azul lateral.
- Al pasar el cursor por el seleccionado, vuelve el fondo azul y el texto blanco del diseño anterior.
- Los apartados no seleccionados mantienen texto claro y transición a fondo azul al pasar el cursor.
- La transición de color, fondo, borde y sombra es suave y respeta la preferencia de movimiento reducido configurada en el sistema.

## Alcance
Solo estilos, versión, documentación y pruebas; no se modifican módulos de negocio, datos, cálculos, rutas ni permisos.

## Validación
La suite de CI y los smoke tests se ejecutan antes de publicar.
