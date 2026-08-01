# Actualización Digit Laboral v1.2 Preview

Esta actualización incorpora al sistema real de Render las pantallas de Cálculos y Certificados que ya existían en la demostración pública.

## Archivos principales modificados

- `app/main.py`
- `app/models.py`
- `app/templates/base.html`
- `app/templates/dashboard.html`
- `app/templates/calculations.html`
- `app/templates/certificates.html`
- `app/templates/certificate_print.html`
- `app/static/modern.css`
- `app/static/app.js`
- `tests/test_health.py`
- `tests/test_modules_v14.py`
- `VERSION`

## Publicación

1. Descomprimir el ZIP.
2. Subir todo su contenido a la raíz del repositorio `BRUNOBENOV/DIGIT-LABORAL`, reemplazando los archivos existentes.
3. Render detectará el commit y ejecutará un nuevo despliegue.
4. Esperar a que `/health` responda `200`.
5. Ingresar al sistema y revisar `/app/calculations` y `/app/certificates`.

La nueva tabla `generated_certificates` se crea automáticamente al iniciar la aplicación. No se eliminan las empresas, funcionarios, usuarios ni liquidaciones existentes.

No subir archivos `.env`, contraseñas ni bases con datos reales.
