# Registro de cambios

## 2.5.2 — 26-10-2026

### Seguridad
- Se fijó el `search_path` de las funciones PostgreSQL de contexto multiempresa.
- Se agregó una prueba de regresión para impedir que el SQL del arranque pierda sus delimitadores.
- Se retiraron los permisos de `anon` y `authenticated` sobre la tabla interna `alembic_version` en la base productiva; el usuario de aplicación conserva su acceso.

### Rendimiento
- Se agregaron índices a las claves foráneas `employees.branch_id` y `request_workflows.approved_by_user_id`.

### Validación de publicación
- La suite completa de CI y las comprobaciones de arranque pasaron.
- Render confirmó el despliegue activo.
- Supabase confirmó Alembic `0013_tenant_function_search_path`, `search_path` restringido en las dos funciones y cero avisos activos en el asesor de seguridad.

### Requisitos operativos aún pendientes
- Configurar almacenamiento persistente S3 compatible.
- Configurar y probar la entrega SMTP.
- Separar el rol de migraciones del rol de aplicación antes de forzar RLS.
- Ejecutar una prueba formal de aislamiento entre empresas y verificar la restauración desde una copia externa.
