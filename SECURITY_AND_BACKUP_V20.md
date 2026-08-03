# Seguridad y respaldo — Digit Laboral v2.0

## Controles implementados

- Hash de contraseñas.
- Política de complejidad.
- Bloqueo por intentos fallidos y limitación por IP para login, recuperación y activación.
- Recuperación con token temporal.
- Autenticación TOTP.
- Invalidación de sesiones.
- CSRF.
- Cookies seguras en producción.
- Trusted Hosts.
- Encabezados de seguridad.
- Auditoría y eventos de seguridad.
- RLS preparado con URL separada para migración y ejecución.
- Archivos con claves normalizadas.
- Lotes con SHA-256, claves idempotentes y doble aprobación configurable.
- Ejecución Docker sin root.

## Controles operativos obligatorios

- 2FA para superadministradores y administradores.
- Contraseñas únicas y gestor de contraseñas.
- Ningún secreto en GitHub.
- Acceso mínimo al panel de Render y al almacenamiento.
- Revisión mensual de usuarios activos.
- Desactivación inmediata de cuentas desvinculadas.
- Registro de exportaciones y descargas.
- Revisión de logs y alertas.

## Respaldo

Comando local:

```bash
python scripts/backup_database.py
```

Con subida al almacenamiento configurado:

```bash
python scripts/backup_database.py --upload --keep-local 7
```

La imagen Docker incluye `pg_dump` para PostgreSQL.

## Política sugerida

- Diario: 14 copias.
- Semanal: 8 copias.
- Mensual: 12 copias.
- Copia externa en otra cuenta o proveedor.
- Cifrado del bucket.
- Prueba de restauración trimestral.
- Registro firmado del resultado de la restauración.

## Objetivos iniciales

- RPO: máximo 24 horas de datos.
- RTO: restauración dentro de 8 horas.

Para operación crítica deben reducirse estos objetivos mediante mayor frecuencia, replicación y procedimientos documentados.

## Archivos

En producción usar `STORAGE_BACKEND=s3`. El disco local del hosting no es una fuente persistente. Los documentos reales no deben cargarse hasta comprobar:

- subida;
- descarga;
- permisos;
- respaldo;
- restauración;
- eliminación;
- trazabilidad.
