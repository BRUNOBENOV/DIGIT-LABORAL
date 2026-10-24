# Digit Laboral 2.0

Plataforma de gestión y cumplimiento laboral para estudios contables paraguayos.

## Alcance de la versión

Digit Laboral 2.0 integra:

- estudios, empresas y sucursales;
- funcionarios y expedientes digitales;
- usuarios, roles, sesiones y 2FA;
- solicitudes y flujo de trámites;
- liquidaciones, vacaciones y aguinaldo;
- documentos Word/PDF e informes;
- agenda, auditoría y respaldos;
- Código Laboral estructurado;
- centro REI/REOP con borradores, validación, Excel, lotes y comprobantes.

La interoperabilidad REI/REOP funciona mediante archivos y revisión humana. Los conectores directos permanecen desactivados porque requieren documentación y autorización oficial.

## Aplicación activa

La URL principal de trabajo es **https://digit-laboral-app.onrender.com/**. La dirección `digit-laboral-py-demo.onrender.com` corresponde a una demo anterior y no debe usarse como URL principal. Configurá `PUBLIC_URL=https://digit-laboral-app.onrender.com` en Render para que los enlaces de correo y recuperación de contraseña apunten al servicio correcto.

## Inicio local

### Windows

```bat
run.bat
```

### Linux/macOS

```bash
./run.sh
```

Abrir `http://127.0.0.1:8000`.

Para una base local de desarrollo se pueden definir:

```text
DEMO_ADMIN_PASSWORD=<contraseña local>
DEMO_SUPERADMIN_PASSWORD=<contraseña local>
```

Las contraseñas de demostración no están incrustadas en el código.

## Pruebas

```bash
pip install -r requirements-dev.txt
pytest -q
```

Verificación ampliada:

```bash
python -m compileall -q app alembic tests
pytest --cov=app --cov-report=term-missing -q
```

Resultado de la entrega: **32 pruebas aprobadas**.

## Migraciones

La aplicación usa Alembic y ejecuta el control de migraciones al iniciar.

```bash
alembic current
alembic upgrade head
```

Documentación: `MIGRATION_V19_TO_V20.md`.

## Producción

Usar como base `render.production.yaml`, no el Blueprint gratuito de demostración.

Producción requiere:

- PostgreSQL persistente;
- almacenamiento S3 compatible;
- SMTP;
- HTTPS;
- respaldo externo;
- staging separado;
- RLS probado;
- revisión jurídica y de seguridad.

Documentación: `PRODUCTION_DEPLOYMENT_V20.md` y `SECURITY_AND_BACKUP_V20.md`.

## REI y REOP

El centro de cumplimiento permite:

- completar perfiles oficiales de empresa, sucursal y trabajador;
- crear comunicaciones automáticas desde operaciones internas;
- validar datos faltantes;
- exportar lotes Excel con número patronal por establecimiento;
- generar planillas REOP de trabajo;
- registrar comprobantes y resultados;
- conservar hash, usuario y trazabilidad.

Documentación: `REI_REOP_INTEGRATION.md`.

## Solicitudes y notificaciones

- Las solicitudes admiten campos estructurados para funcionario, fecha efectiva, periodo, días, importe y permisos/licencias.
- La bandeja de notificaciones es individual y persistente, con lectura/no lectura, filtros y enlaces al trámite.
- La creación, asignación, comentarios, adjuntos y decisiones generan avisos según roles y visibilidad.
- Los cambios salariales requieren aprobación explícita; su aplicación registra el historial salarial y la auditoría.
- Si SMTP está configurado, los correos se registran en una cola persistente y se intentan enviar en segundo plano. Para recuperar entregas pendientes y generar recordatorios por vencimiento, ejecutá diariamente `python -m app.notification_worker` como Render Cron Job, con las mismas variables de entorno seguras del servicio web.
- Si SMTP no está configurado, las notificaciones internas siguen funcionando.

## Seguridad

- No almacenar PIN o contraseñas gubernamentales.
- No subir `.env`, bases o documentos a GitHub.
- Mantener IA desactivada hasta aprobar la política de tratamiento de datos.
- Activar 2FA para administradores.
- Probar restauraciones, no solo generar respaldos.

## Documentación principal

- `REVISION_INTEGRAL_V20.md`
- `RELEASE_NOTES_V23.md`
- `RELEASE_NOTES_V20.md`
- `REI_REOP_INTEGRATION.md`
- `PRODUCTION_DEPLOYMENT_V20.md`
- `SECURITY_AND_BACKUP_V20.md`
- `MIGRATION_V19_TO_V20.md`
- `SOLICITUD_INTEROPERABILIDAD_REI_REOP.md`
