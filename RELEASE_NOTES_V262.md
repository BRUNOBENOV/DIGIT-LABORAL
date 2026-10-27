# DigIT-Laboral 2.6.2 — Renovación visual azul y accesible

## Sistema visual

| Elemento | Valor |
|---|---|
| Sidebar | `#0D1B2A` |
| Texto de sidebar | `#FFFFFF` / azul grisáceo claro |
| Acentos y estado activo | `#1E40AF` |
| Botón principal | `#2563EB` |
| Hover de botón primario | `#1D4ED8` |
| Fondo de trabajo | `#F9FAFB` |
| Superficies | `#FFFFFF` |
| Texto principal | `#111827` |
| Texto secundario | `#6B7280` |
| Foco de teclado | contorno azul visible de 3px |

## Alcance

- Hoja de estilos compartida `app/static/theme-261.css`, cargada después del resto de CSS del espacio autenticado.
- Unifica topbar, sidebar, navegación activa, paneles, tarjetas, cabeceras, tablas, botones, inputs, selects, textareas y modales.
- Mantiene una tipografía sans-serif moderna con Inter como primera opción.
- Mantiene las páginas públicas fuera del alcance de las sobrescrituras del workspace.
- Respeta responsividad, movimiento reducido, y navegación de teclado.
- No modifica la lógica de negocio, rutas ni permisos.

## Verificación

La versión debe superar compilación, análisis de plantillas, pruebas y smoke tests de CI antes de integrarse en `main`. Render despliega automáticamente cuando se integra la rama a `main`.
