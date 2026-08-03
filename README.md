# Digit Laboral — versión 1.5 Preview

Plataforma de gestión laboral para estudios contables paraguayos, presentada por Victor's Contabilidad.

## Vista pública y demostración

- `index.html`: sitio comercial, beneficios, módulos y planes.
- `login.html`: acceso a la demostración pública.
- `app.html`: demostración navegable sin datos reales.
- `privacidad.html` y `terminos.html`: información legal de la demostración.

La demostración pública guarda datos ficticios únicamente en el navegador. No debe utilizarse para información real de clientes.

## Aplicación productiva

La carpeta `app/` contiene el backend FastAPI con PostgreSQL, autenticación, sesiones, separación por estudio, roles, empresas, funcionarios, solicitudes, liquidaciones, vacaciones, aguinaldo, documentos, cálculos, informes, auditoría y administración.

### Automatización de la versión 1.5

- Logo y membrete configurable por cada empresa.
- Portal para que la empresa vinculada cargue o actualice su propio logo.
- Colores, firma autorizada, pie de página y prefijo documental por empresa.
- Cálculos guardados y vinculados con certificados, informes y expedientes.
- Numeración automática de documentos.
- Exportación Word y PDF con el membrete correspondiente.
- Informes integrales del funcionario y exportación CSV.
- Alertas de datos incompletos, empresas sin logo y cálculos pendientes de revisión.
- Asistente de IA con motor interno y conexión opcional a OpenAI.
- Registro de auditoría para cálculos, documentos, informes y consultas de IA.

La IA no aprueba liquidaciones ni toma decisiones jurídicas. Señala datos faltantes, inconsistencias y próximos pasos; la emisión definitiva requiere revisión humana y profesional.

## Ejecutar localmente

### Windows

```bat
run.bat
```

### Linux o macOS

```bash
./run.sh
```

Después abrí `http://127.0.0.1:8000`.

## Configuración de IA

El sistema funciona sin una clave externa mediante el motor interno. Para activar la asistencia de OpenAI, configurá en Render:

```text
AI_ENABLED=true
OPENAI_API_KEY=<clave secreta>
OPENAI_MODEL=gpt-5-mini
AI_STORE_RESPONSES=false
```

Nunca subas la clave a GitHub ni a archivos `.env` públicos.

## Publicación

- Para actualizar el repositorio y Render, leé `ACTUALIZAR_V16.md`.
- Para desplegar desde cero, leé `DEPLOYMENT.md`.
- Antes de usar datos reales, completá `SECURITY_CHECKLIST.md`.

## Credenciales demostrativas

Correo: `admin@digitlaboral.com.py`  
Contraseña: `demo123`

Cambiá las credenciales de demostración antes de ingresar información real.

## Novedades v1.5

- Corrección del cargador de logo y membrete por empresa.
- Vista previa y validación de imágenes antes de guardar.
- Código del Trabajo completo, sincronizable y ordenado por Libro, Título, Capítulo y Artículo.
- Filtros de vigencia, modificaciones y derogaciones, con trazabilidad a fuentes jurídicas.
