# Digit Laboral — versión 1.3 Preview

Plataforma de gestión laboral para estudios contables paraguayos, presentada por Victor's Contabilidad.

## Vista pública y demostración

- `index.html`: sitio comercial, beneficios, módulos, planes y preguntas frecuentes.
- `login.html`: acceso controlado a la demostración.
- `app.html`: sistema navegable con Mantenimientos, Cálculo, Informes, Certificados, Utilitarios, Trámites, Código Laboral, Consulta IA y Administración.
- `privacidad.html` y `terminos.html`: textos específicos para la demostración pública.
- `manifest.webmanifest` y `sw.js`: instalación como aplicación web y funcionamiento básico sin conexión.

La demostración usa datos ficticios y guarda cambios en el navegador. Incluye respaldo y restauración JSON, exportación CSV, tema claro/oscuro, diseño responsive, aviso de conexión y accesibilidad mejorada.

## Aplicación productiva

La carpeta `app/` contiene un backend FastAPI con autenticación, sesiones, separación por estudio, roles, empresas, sucursales, funcionarios, solicitudes, liquidaciones, vacaciones, aguinaldo, certificados generados, documentos, parámetros laborales, auditoría y soporte PostgreSQL.

La versión 1.3 Preview incorpora exportación real a Word y PDF, modelos laborales mejorados, membretes por empresa, numeración documental y auditoría de descargas. Mantiene el centro de Cálculos, el generador de documentos conectado a la base de datos, autenticación, permisos, seguridad y soporte PostgreSQL.

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

## Publicación

- Para actualizar GitHub Pages, leé `SUBIR_A_GITHUB.md`.
- Para desplegar el backend con PostgreSQL, leé `DEPLOYMENT.md`.
- Antes de usar datos reales, completá `SECURITY_CHECKLIST.md`.

## Demostración

Correo: `admin@digitlaboral.com.py`  
Contraseña: `demo123`

No uses esas credenciales en producción.
