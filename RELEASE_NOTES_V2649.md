# DIGIT-LABORAL 2.6.49 — Corrección de contraste de submódulos

## Incidencia corregida
Los enlaces de submódulos seleccionados podían conservar el texto blanco cuando pasaban a un fondo claro, especialmente durante el hover. La regla clara anterior solo cubría el estado sin hover y perdía prioridad frente a la regla tipográfica general de la barra.

## Corrección
- Los submódulos seleccionados mantienen fondo blanco, texto azul oscuro `#0B2D78` y acento lateral azul `#1D4ED8` en todos los estados.
- El mismo contraste se aplica a `:hover` y a `aria-current="page"`.
- Los submódulos no seleccionados conservan texto claro sobre el fondo azul oscuro, con fondo transparente.
- Se fuerza también `-webkit-text-fill-color` para evitar color blanco residual por reglas heredadas.
- Se renueva el parámetro de caché de `theme-261.css`.

## Límites
No se modifican módulos, rutas, base de datos, registros, cálculos, fórmulas, procesos laborales, permisos ni documentos.

## Pruebas
Se añade regresión CSS que comprueba el estado activo normal y el estado activo con hover.
