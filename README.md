# Digit Laboral v12

Sistema de gestión laboral en la nube para estudios contables paraguayos.

## Novedades de esta versión

- Expediente individual de cada funcionario.
- Historial permanente de altas, cambios salariales, cargos y estados.
- Cambios salariales con fecha efectiva, motivo y usuario responsable.
- Edición completa de datos personales y laborales.
- Sucursales editables y activables/desactivables.
- Usuarios empresariales visibles dentro del expediente de la empresa.
- Compatible con la base PostgreSQL ya desplegada: la tabla histórica se crea automáticamente sin borrar datos existentes.

# Digit Laboral

Sistema de gestión laboral para estudios contables paraguayos, con empresas vinculadas, funcionarios, solicitudes, liquidaciones en borrador, vacaciones, aguinaldo, documentos, usuarios y biblioteca jurídica.

## Publicación temporal gratuita

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/BRUNOBENOV/DIGIT-LABORAL)

Al presionar el botón, Render leerá `render.yaml` y preparará automáticamente:

- una aplicación FastAPI gratuita;
- una base PostgreSQL gratuita;
- una dirección pública `onrender.com` con HTTPS;
- las tablas y los datos demostrativos iniciales.

Durante la instalación, Render pedirá solamente:

- `ADMIN_EMAIL`: el correo con el que ingresarás al panel;
- `ADMIN_PASSWORD`: una contraseña nueva y exclusiva para Digit Laboral.

No publiques esas credenciales dentro de GitHub.

## Ejecución local

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Abrir `http://127.0.0.1:8000`.

## Seguridad y alcance

Esta publicación gratuita es una demostración. No debe usarse con datos personales o documentos reales. La base PostgreSQL gratuita de Render es temporal y el sistema de archivos del servidor no es persistente. La carga de documentos está deshabilitada en este despliegue.
