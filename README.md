# Digit Laboral 2.5.0

Plataforma de gestión y cumplimiento laboral para estudios contables paraguayos.

## Alcance de la versión

Digit Laboral 2.5.0 integra:

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

La cantidad vigente de pruebas aprobadas se informa en cada ejecución de CI de GitHub Actions.

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

## Solicitudes, vacaciones y notificaciones

- Las solicitudes de vacaciones consultan el saldo anual antes de enviarse y vuelven a validarlo al aprobarse para evitar reservas por encima del saldo disponible.
- Los días aprobados quedan reservados; solo pasan a usados cuando finaliza el periodo y el estudio confirma su utilización. Los permisos/licencias se incorporan a la línea de tiempo del funcionario una vez finalizados.
- El trabajador periódico se ejecuta cada hora a través de `scripts/notification_cron.py`, que invoca `/internal/cron/notifications` con un token Bearer. Configurá el mismo secreto `NOTIFICATION_CRON_TOKEN` en el servicio web y en el Cron Job de Render. Sin ese secreto, el endpoint no ejecuta el procesamiento.

- Las solicitudes admiten campos estructurados para funcionario, fecha efectiva, periodo, días, importe y permisos/licencias.
- La bandeja de notificaciones es individual y persistente, con lectura/no lectura, filtros y enlaces al trámite.
- La creación, asignación, comentarios, adjuntos y decisiones generan avisos según roles y visibilidad.
- Los cambios salariales requieren aprobación explícita; su aplicación registra el historial salarial y la auditoría.
- Si SMTP está configurado, los correos se registran en una cola persistente y se intentan enviar en segundo plano. El Cron Job horario llama al endpoint autenticado del servicio web para generar recordatorios y procesar la cola usando la configuración SMTP ya definida en el servicio.
- Si SMTP no está configurado, las notificaciones internas siguen funcionando.

## Seguridad

- No almacenar PIN o contraseñas gubernamentales.
- No subir `.env`, bases o documentos a GitHub.
- Mantener IA desactivada hasta aprobar la política de tratamiento de datos.
- Activar 2FA para administradores.
- Probar restauraciones, no solo generar respaldos.

## Documentación principal

- `REVISION_INTEGRAL_V20.md`
- `RELEASE_NOTES_V24.md`
- `RELEASE_NOTES_V23.md`
- `RELEASE_NOTES_V20.md`
- `REI_REOP_INTEGRATION.md`
- `PRODUCTION_DEPLOYMENT_V20.md`
- `SECURITY_AND_BACKUP_V20.md`
- `MIGRATION_V19_TO_V20.md`
- `SOLICITUD_INTEROPERABILIDAD_REI_REOP.md`
