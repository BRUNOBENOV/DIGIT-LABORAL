-- Ejecutar conectado como propietario de la base, después de aplicar migraciones.
-- Ejemplo psql:
-- psql "$MIGRATION_DATABASE_URL" -v app_password='UNA_CLAVE_LARGA' -f scripts/configure_postgres_roles.sql

\if :{?app_password}
\else
  \echo 'Falta -v app_password=...'
  \quit 1
\endif

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'digit_laboral_app') THEN
    CREATE ROLE digit_laboral_app LOGIN;
  END IF;
END
$$;

ALTER ROLE digit_laboral_app PASSWORD :'app_password';
ALTER ROLE digit_laboral_app NOBYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;

DO $$
BEGIN
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO digit_laboral_app', current_database());
END
$$;
GRANT USAGE ON SCHEMA public TO digit_laboral_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO digit_laboral_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO digit_laboral_app;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO digit_laboral_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO digit_laboral_app;

-- Las migraciones deben seguir usando el usuario propietario.
-- La aplicación debe usar una URL construida con digit_laboral_app.
