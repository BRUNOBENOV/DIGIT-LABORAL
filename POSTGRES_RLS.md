# Row-Level Security en PostgreSQL

Digit Laboral v2.0 puede crear políticas RLS automáticamente cuando `RLS_ENABLED=true`.

## Arquitectura recomendada

- `digit_owner`: propietario de tablas, utilizado solamente para migraciones.
- `digit_app`: utilizado por FastAPI; no debe ser propietario ni poseer `BYPASSRLS`.

Ejemplo orientativo ejecutado por un administrador PostgreSQL:

```sql
CREATE ROLE digit_app LOGIN PASSWORD 'CAMBIAR';
GRANT CONNECT ON DATABASE digit_laboral TO digit_app;
GRANT USAGE ON SCHEMA public TO digit_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO digit_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO digit_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO digit_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO digit_app;
```

La aplicación establece por transacción:

- `app.current_studio_id`
- `app.is_superadmin`

Las políticas permiten acceso a las filas del estudio activo. Las tablas públicas globales, como el Código Laboral y los parámetros jurídicos, no se aíslan por estudio.

## Prueba obligatoria

1. Crear dos estudios con datos ficticios.
2. Ingresar como administrador del estudio A.
3. Intentar consultar identificadores conocidos del estudio B.
4. Repetir como empresa vinculada.
5. Confirmar rechazo tanto desde la interfaz como con consultas directas usando `digit_app`.


## Separación de URLs

- `MIGRATION_DATABASE_URL`: propietario de tablas, migraciones y creación de políticas.
- `DATABASE_URL`: rol `digit_laboral_app`, sin `BYPASSRLS`.

Usar `scripts/configure_postgres_roles.sql` y activar `RLS_FORCE=true` solo después de probar ambos accesos.
