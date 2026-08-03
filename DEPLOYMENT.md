# Despliegue de Digit Laboral

## Arquitectura

- FastAPI para la aplicación.
- PostgreSQL para datos persistentes.
- Render como alojamiento temporal.
- GitHub como repositorio y origen del despliegue.

## Variables obligatorias

```text
DATABASE_URL=<conexión PostgreSQL>
DIGIT_SECRET_KEY=<clave aleatoria extensa>
ENVIRONMENT=production
SECURE_COOKIES=true
ALLOWED_HOSTS=*.onrender.com,localhost,127.0.0.1
PUBLIC_URL=<URL pública vigente>
```

## Variables de automatización e IA

```text
AI_ENABLED=true
OPENAI_MODEL=gpt-5-mini
AI_STORE_RESPONSES=false
MAX_LOGO_SIZE=2097152
OPENAI_API_KEY=<opcional y secreto>
```

El sistema mantiene un motor interno cuando `OPENAI_API_KEY` no está configurada. La clave nunca debe incluirse en GitHub.

## Inicio y health check

El contenedor ejecuta Uvicorn y expone `/health`. Un despliegue correcto debe responder con código 200 y versión `1.4.0-preview`.

## Datos y archivos

- PostgreSQL guarda expedientes, cálculos, documentos, auditoría y configuración.
- Los logos se guardan en la base para evitar depender del disco efímero de una instancia gratuita.
- Los documentos Word y PDF se generan al momento de la descarga.
- Configurá respaldos periódicos antes de utilizar datos reales.

## Dominio

Mientras no se conecte el dominio definitivo, utilizá la URL vigente mostrada en el panel del servicio de Render. Al conectar un dominio propio, añadilo también a `ALLOWED_HOSTS` y actualizá `PUBLIC_URL`.

## Variables agregadas en v1.9

```text
MAX_IMPORT_ROWS=2000
LOGIN_MAX_ATTEMPTS=5
LOGIN_LOCK_MINUTES=15
PASSWORD_RESET_MINUTES=30
RLS_ENABLED=true
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM_EMAIL=
SMTP_FROM_NAME=Digit Laboral
SMTP_USE_TLS=true
```

La recuperación de contraseña y los recordatorios por correo permanecerán desactivados hasta configurar SMTP.

## Datos persistentes

Además de PostgreSQL, deben conservarse:

```text
data/uploads/
```

En un servicio sin disco persistente, los documentos y adjuntos pueden desaparecer al redesplegar. Para producción utilizá un disco persistente o almacenamiento de objetos privado.

## Respaldo

- Exportación funcional por estudio: `/app/export/studio.zip`.
- Respaldo técnico: `python scripts/backup_database.py`.
- Instrucciones de restauración: `scripts/restore_notes.md`.
