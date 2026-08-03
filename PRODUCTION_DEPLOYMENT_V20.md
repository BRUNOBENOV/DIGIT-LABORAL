# Despliegue de producción — Digit Laboral v2.0

## Arquitectura mínima

- Servicio web Docker.
- PostgreSQL de pago con respaldo.
- Almacenamiento S3/R2/B2.
- SMTP transaccional.
- Dominio HTTPS.
- Ambiente staging separado.
- Monitoreo de disponibilidad y errores.

No reutilizar la base `digit-laboral-db-demo` como producción.

## Variables obligatorias

```text
ENVIRONMENT=production
DIGIT_SECRET_KEY=<generada y secreta>
DATABASE_URL=<PostgreSQL del usuario restringido digit_laboral_app>
MIGRATION_DATABASE_URL=<PostgreSQL del propietario/migrador>
PUBLIC_URL=https://app.digitlaboral.com.py
SECURE_COOKIES=true
ALLOWED_HOSTS=app.digitlaboral.com.py
CSRF_ENABLED=true
COMPLIANCE_DUAL_APPROVAL=true
RLS_ENABLED=true
RLS_FORCE=true
STORAGE_BACKEND=s3
S3_BUCKET=<bucket>
S3_ACCESS_KEY_ID=<secreto>
S3_SECRET_ACCESS_KEY=<secreto>
INITIAL_ADMIN_EMAIL=<correo del propietario>
INITIAL_ADMIN_PASSWORD=<contraseña temporal fuerte>
SMTP_HOST=<servidor>
SMTP_FROM_EMAIL=<correo del sistema>
AI_ENABLED=false
REI_DIRECT_ENABLED=false
REOP_DIRECT_ENABLED=false
```

## Migraciones

El inicio de la aplicación ejecuta el control de migraciones:

- base nueva: crea el esquema y marca la revisión vigente;
- base v19: marca la línea base y aplica la revisión v20;
- base versionada: aplica únicamente revisiones pendientes.

Antes de cada actualización:

1. generar respaldo;
2. probar restauración en staging;
3. desplegar en staging;
4. ejecutar pruebas;
5. aplicar en producción;
6. comprobar `/health/ready`;
7. probar login, empresa, trabajador, documentos y cumplimiento.

## RLS

`RLS_ENABLED=true` crea políticas. Para que sean una segunda barrera real:

1. usar `MIGRATION_DATABASE_URL` con el usuario propietario/migrador solo para migraciones;
2. usar `DATABASE_URL` con el usuario restringido para la aplicación;
3. retirar `BYPASSRLS` al usuario de aplicación;
4. probar aislamiento entre dos estudios;
5. recién después activar `RLS_FORCE=true`.

Activar `RLS_FORCE` con una configuración incorrecta puede bloquear migraciones o procesos administrativos.

## Datos iniciales

En producción no se crean empresas ni usuarios demostrativos. El primer superadministrador se crea con `INITIAL_ADMIN_EMAIL` y `INITIAL_ADMIN_PASSWORD` y debe cambiar la contraseña en el primer acceso.

## Checklist antes de clientes reales

- [ ] Base productiva nueva.
- [ ] Dominio y HTTPS.
- [ ] S3 operativo.
- [ ] SMTP operativo.
- [ ] Respaldo diario externo.
- [ ] Restauración probada.
- [ ] Staging independiente.
- [ ] RLS probado entre dos estudios.
- [ ] 2FA activado para administradores.
- [ ] Revisión de permisos.
- [ ] Revisión jurídica de plantillas y cálculos.
- [ ] Contrato de tratamiento de datos y política de privacidad.
- [ ] Prueba piloto con datos controlados.


El script `scripts/configure_postgres_roles.sql` prepara el rol restringido sin guardar su contraseña en el repositorio.
