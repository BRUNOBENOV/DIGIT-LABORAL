# Actualizar Digit Laboral a v1.4 Preview

## 1. Preparar respaldo

Antes del despliegue, realizá una copia de seguridad de la base PostgreSQL y verificá que no haya una liquidación en proceso de cierre.

## 2. Subir los archivos

1. Descomprimí `digit-laboral-v16-actualizacion.zip`.
2. Abrí el repositorio `BRUNOBENOV/DIGIT-LABORAL`.
3. Usá **Add file → Upload files**.
4. Subí todo el contenido, conservando las carpetas.
5. Confirmá el reemplazo de archivos y realizá el commit.

Render detectará el commit y desplegará la nueva versión. Las tablas de logos, cálculos e interacciones de IA se crean automáticamente durante el inicio.

## 3. Variables de Render

Mantené las variables actuales y agregá:

```text
AI_ENABLED=true
OPENAI_MODEL=gpt-5-mini
AI_STORE_RESPONSES=false
MAX_LOGO_SIZE=2097152
```

`OPENAI_API_KEY` es opcional. Debe cargarse únicamente como secreto de Render. Sin esa clave, Digit Laboral utiliza el motor interno de asistencia.

## 4. Comprobación

Esperá que Render indique **Live** y verificá:

```text
/health
/app
/app/calculations
/app/certificates
/app/reports
/app/ai
```

`/health` debe informar `version: 1.4.0-preview`.

## 5. Configurar una empresa

Entrá a una empresa y abrí **Logo y membrete**. Cargá el logo, colores, firma autorizada, pie y prefijo documental. Luego guardá un cálculo y generá un certificado vinculado para comprobar Word y PDF.
