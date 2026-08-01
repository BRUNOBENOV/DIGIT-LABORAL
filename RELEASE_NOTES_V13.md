# Digit Laboral v1.1 Preview

## Unificación visual

- El sistema real de FastAPI adopta la navegación superior y la estética de la demostración pública.
- Se elimina visualmente la barra lateral anterior.
- Se agregan navegación adaptable a celulares, selector de espacio, búsqueda jurídica y acceso rápido al cierre de sesión.
- El panel principal incorpora accesos rápidos, estado del sistema y los módulos Mantenimientos, Cálculo, Informes, Certificados, Utilitarios y Trámites.

## Integración pública y privada

- La pantalla pública de ingreso ahora envía las credenciales directamente al servidor real de Render.
- La demostración de GitHub Pages continúa separada y conserva únicamente datos ficticios del navegador.

## Despliegue

- `ALLOWED_HOSTS` permite por defecto dominios `*.onrender.com` para evitar errores 400 en el health check.
- `render.yaml` incluye la variable `ALLOWED_HOSTS` y planes gratuitos de demostración.
