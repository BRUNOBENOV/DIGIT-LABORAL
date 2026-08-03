# Actualización a Digit Laboral v2.0

## Objetivo

Esta actualización reemplaza la versión demostrativa v19 por una base estabilizada para staging y una arquitectura preparada para producción.

## Incluye

- migraciones Alembic versionadas;
- perfiles REI/REOP de empresa, sucursales y trabajadores;
- números patronales IPS y MTESS por establecimiento;
- comunicaciones automáticas e idempotentes;
- exportaciones Excel, lotes, hash y comprobantes;
- estados y doble aprobación;
- almacenamiento S3 compatible;
- respaldo PostgreSQL;
- separación entre usuario migrador y usuario de aplicación;
- CSRF general, rate limiting y observabilidad;
- navegación y panel de cumplimiento renovados;
- CI y pruebas automáticas.

## Importante sobre REI y REOP

La versión genera archivos de interoperabilidad, valida datos y conserva la trazabilidad. No realiza envíos directos porque se requiere documentación, homologación y autorización oficial. Mantener desactivados los conectores directos.

## Método seguro de actualización

1. Descargar un respaldo de la base y de los documentos.
2. Crear una rama nueva en GitHub, por ejemplo `release/v20-stabilization`.
3. Subir el contenido del ZIP de actualización respetando las carpetas.
4. Abrir un Pull Request hacia `main`.
5. Esperar que la acción **Verificación técnica** termine correctamente.
6. Desplegar primero en staging.
7. Verificar login, empresas, sucursales, trabajadores, liquidaciones, documentos y Cumplimiento.
8. Recién después fusionar a `main`.

## Render de demostración

Para conservar la base actual, `DATABASE_URL` y `MIGRATION_DATABASE_URL` deben contener la URL externa vigente de `digit-laboral-db-demo`. El plan gratuito continúa siendo únicamente demostrativo.

## Producción

No utilizar `digit-laboral-db-demo`. Seguir `PRODUCTION_DEPLOYMENT_V20.md`, crear una base nueva, almacenamiento S3, SMTP y respaldo externo.

## Verificación ejecutada

- 32 pruebas automatizadas aprobadas.
- compilación de aplicación, migraciones y pruebas;
- base nueva creada y marcada en revisión `0005_v20_security_event_ip_index`;
- base v19 actualizada hasta la misma revisión;
- exportación por sucursal comprobada;
- rutas autenticadas y CSRF comprobados.
