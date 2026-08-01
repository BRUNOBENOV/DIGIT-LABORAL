# Actualización Digit Laboral v1.1 Preview

Esta actualización unifica la interfaz del sistema real de Render con el diseño moderno de la demostración pública.

## Archivos principales modificados

- `app/templates/base.html`
- `app/templates/dashboard.html`
- `app/static/modern.css`
- `app/static/app.js`
- `app/config.py`
- `app/main.py`
- `render.yaml`
- `login.html`
- `tests/test_health.py`
- `VERSION`

## Publicación

1. Descomprimir el ZIP.
2. Subir su contenido a la raíz del repositorio `BRUNOBENOV/DIGIT-LABORAL`, reemplazando los archivos existentes.
3. Render detectará el nuevo commit y comenzará el despliegue automático.
4. Confirmar que `/health` responda `200` y luego abrir `/app`.

No subir contraseñas, archivos `.env` ni bases con datos reales.
