# Digit Laboral

Sistema de gestión laboral para estudios contables paraguayos, presentado por Victor's Contabilidad.

## Qué contiene este proyecto

### Sitio público y demostración

- `index.html`: página comercial con presentación, módulos, planes y contacto.
- `login.html`: pantalla de acceso de demostración.
- `app.html`: panel navegable con Mantenimientos, Cálculo, Informes, Certificados, Utilitarios, Trámites, Código Laboral, Consulta IA y Administración.
- `assets/`: estilos y funcionamiento de la demostración.

La demostración utiliza datos ficticios y guarda cambios solamente en `localStorage` del navegador. No se deben cargar datos reales de clientes.

### Aplicación productiva

La carpeta `app/` contiene el backend FastAPI con:

- autenticación y sesiones;
- estudios, planes y límites de empresas;
- empresas, sucursales y funcionarios;
- solicitudes de empresas vinculadas;
- liquidaciones, vacaciones y aguinaldo;
- documentos y usuarios;
- parámetros laborales, auditoría y biblioteca jurídica;
- soporte para SQLite local y PostgreSQL en producción.

## Ejecutar localmente

### Windows

```bat
run.bat
```

### Linux o macOS

```bash
./run.sh
```

Luego abrir `http://127.0.0.1:8000`.

## Publicación

- GitHub Pages publica la página comercial y demostración mediante `.github/workflows/pages.yml`.
- `render.yaml` y `Dockerfile` preparan la aplicación FastAPI y PostgreSQL para un proveedor compatible.

Antes de usar el sistema con información real, deben cambiarse las credenciales de demostración, configurar secretos seguros, revisar permisos, habilitar copias de seguridad y validar profesionalmente los cálculos y contenidos jurídicos.
