# Sistema visual DIGIT-LABORAL 2.6.51

## Principios

1. Una identidad única para el espacio autenticado: azul marino DIGIT, azul de acción, lienzo azul-gris muy claro y superficies blancas.
2. La barra lateral es la única navegación global de las cinco áreas principales. Los submódulos se muestran dentro del grupo correspondiente.
3. Los módulos conservan su jerarquía local, pero reutilizan los mismos tokens de texto, superficie, borde, campo y foco.
4. Los estados funcionales no dependen solamente del color: las etiquetas de estado mantienen texto explícito y diferenciación semántica.
5. Las transiciones son discretas y respetan la preferencia de movimiento reducido.

## Tokens

| Token | Valor |
|---|---|
| Navy | `#05256D` |
| Azul de acción | `#1D4ED8` |
| Lienzo | `#F2F5FA` |
| Superficie | `#FFFFFF` |
| Texto principal | `#172033` |
| Texto secundario | `#667085` |
| Borde | `#D8E1EF` |
| Superficie secundaria | `#F8FAFC` |

Los tokens de compatibilidad viven en `body.app-body` para que las pantallas autenticadas que aún usan variables históricas hereden la paleta clara sin alterar las páginas públicas.

## Componentes unificados

- Encabezados de módulo: eyebrow, título, descripción y acciones.
- Paneles: fondo blanco, borde suave, radio consistente y sombra discreta.
- Formularios: etiqueta sobre el control, superficie blanca, texto oscuro y foco azul visible.
- Tablas: encabezado diferenciado, cuerpo legible, acciones visibles y contenedor con desplazamiento horizontal solo cuando el ancho lo exige.
- Estados: neutral, aprobado/enviado y anulado con fondos suaves y texto de contraste.
- Navegación: menú navy con hover animado, texto claro en reposo y estado activo legible.

## Operaciones de Cálculo e histórico

La hoja `calculation-operations-2619.css` alinea sus formularios, atajos, estados, acciones e indicadores del histórico con los tokens compartidos.

## Calidad y regresión

Las pruebas de integración abren Anticipos, Disciplina y Telegrama colacionado con sesión autenticada para detectar referencias Jinja eliminadas. Se comprueba la presencia de tokens de compatibilidad y de estados semánticos en la hoja de operaciones.

## Límites de la auditoría

Los estilos y las rutas automatizadas se validan en CI. Una inspección visual real de todas las pantallas con datos y sesión de usuario requiere QA autenticado en navegador y en resoluciones representativas.
