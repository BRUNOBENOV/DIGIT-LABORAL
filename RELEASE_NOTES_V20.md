# Digit Laboral 2.0 — Release notes

## Nueva plataforma de cumplimiento

- Centro REI/REOP por empresa.
- Perfiles oficiales de empresa y trabajador.
- Comunicaciones automáticas vinculadas al expediente.
- Exportaciones Excel, lotes, hashes y comprobantes.
- Planillas REOP de trabajo.

## Producción

- Alembic.
- S3 compatible.
- Readiness y liveness.
- Logs con Request ID.
- Docker sin root.
- Respaldo PostgreSQL.
- CI y control de secretos.

## Seguridad y usabilidad

- RLS extendido.
- Formularios sin errores JSON crudos.
- Página de error amigable.
- Navegación reorganizada.
- Mejoras responsive y de foco.
- Contraseñas demo fuera del código.

## Estado

Versión apta para staging y prueba piloto con datos ficticios. La conexión directa con organismos queda bloqueada hasta autorización oficial.


## Mejora de establecimientos

- Perfil REI/REOP por sucursal.
- Número patronal IPS y MTESS por establecimiento.
- Comunicaciones ligadas a la sucursal del trabajador.
- Planillas REOP con establecimiento y patronal aplicable.
- Migración Alembic `0003_v20_branch_compliance`.


## Seguridad y consistencia adicionales

- CSRF ampliado a todos los formularios de escritura, incluidos login y recuperación.
- Limitación por IP para intentos fallidos, recuperación y solicitudes de activación.
- Clave idempotente persistente para evitar comunicaciones oficiales duplicadas.
- Flujo de estados controlado y exportación limitada a comunicaciones validadas.
- Doble aprobación configurable para cumplimiento.
- Separación entre `DATABASE_URL` y `MIGRATION_DATABASE_URL`.
- Verificación de creación limpia y actualización real desde v19.
