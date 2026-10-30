# DIGIT-LABORAL 2.6.51 — Calidad visual y consistencia de módulos

## Incidencias corregidas

### Navegación de operaciones
- Eliminada la inclusión obsoleta de `module_subnav.html` de `calculation_operations.html`.
- Anticipos, Disciplina y Telegrama colacionado utilizan la navegación global que ya contiene el contexto del submódulo.
- Se amplía la prueba de integración para solicitar las tres rutas con sesión autenticada.

### Sistema de estilos
- Se incorporan tokens de compatibilidad dentro de `body.app-body`: texto primario/secundario, bordes, superficies y fondos de campos.
- Se impide que hojas heredadas activen los fallbacks oscuros del antiguo tema.
- Operaciones e histórico del funcionario adoptan formularios blancos, etiquetas legibles, bordes suaves, acciones azules y estados semánticos con contraste.
- Las transiciones de accesos rápidos se mantienen y respetan `prefers-reduced-motion`.
- Se actualizan las claves de caché de las hojas de estilos afectadas.

## Paleta de referencia
- Navegación: `#05256D`
- Azul de acción: `#1D4ED8`
- Fondo del espacio: `#F2F5FA`
- Superficie: `#FFFFFF`
- Texto principal: `#172033`
- Texto secundario: `#667085`
- Borde: `#D8E1EF`

## Alcance funcional
No se modifican fórmulas, reglas de cálculo, datos, permisos, registros laborales, documentos emitidos ni migraciones.

## Validación
Se ejecutan la compilación de Python, compilación Jinja, suite completa y smoke tests. Las tres rutas de operaciones se agregan explícitamente a la prueba de renderizado autenticado.
