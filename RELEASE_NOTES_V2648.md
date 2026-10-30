# DIGIT-LABORAL 2.6.48 — Sistema visual corporativo

## Alcance
Actualización de presentación del espacio autenticado: identidad, navegación principal, componentes compartidos y centro laboral.

## Cambios
- Paleta unificada: navy #05256D, acción #1D4ED8, lienzo #F2F5FA, superficies blancas y texto #172033.
- Barra lateral como navegación global única de cinco áreas.
- Retiro de la barra secundaria global que repetía los apartados del menú.
- Exámenes Médicos queda únicamente en Mantenimientos.
- Eliminación del acceso lateral heredado a Certificados oficiales, cuya ruta actual redirige al generador de documentos internos.
- Eliminación de cinco hojas CSS de parches de navegación absorbidas por el tema principal.
- Unificación de estados del centro laboral autenticado con la identidad DIGIT.
- Documentación del sistema visual y pruebas de regresión.

## Límites funcionales
No se modifican cálculos, fórmulas laborales, reglas de IPS, modelos, migraciones, datos, roles, permisos, rutas de negocio ni procesos de aprobación. Se conservan las composiciones de impresión y las páginas públicas.

## Validación
La compilación de Python y plantillas Jinja pasó en CI durante las primeras iteraciones. La suite completa está en proceso de corrección para alinear pruebas históricas con los estilos y la navegación consolidados. La inspección de navegador autenticado aún requiere una sesión autorizada.
