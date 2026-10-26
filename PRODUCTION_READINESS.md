# Preparación para producción

## Verificación técnica registrada (26-10-2026)

- El servicio de Render está activo y la aplicación arranca con la versión publicada en `main`.
- La base Supabase de producción está en Alembic `0013_tenant_function_search_path`; se verificó que las funciones de contexto mantienen `search_path = pg_catalog, pg_temp`.
- La revisión de seguridad de Supabase no devuelve avisos activos. Los roles `anon` y `authenticated` no tienen permisos sobre tablas/vistas del esquema `public`; los metadatos de Alembic siguen accesibles para el usuario de aplicación.
- Se agregaron índices para `employees.branch_id` y `request_workflows.approved_by_user_id`.
- La suite completa de CI, incluyendo compilación, pruebas y comprobaciones de arranque, pasó.

Esta verificación técnica **no equivale a certificar el sistema como listo para operar con todos los datos reales**. Los requisitos de infraestructura y las pruebas de aislamiento multiempresa indicados abajo siguen siendo relevantes.

## Obligatorio antes de datos reales

1. Configurar `INITIAL_ADMIN_EMAIL` e `INITIAL_ADMIN_PASSWORD` (mínimo 12 caracteres). En producción no se crean cuentas ni empresas de demostración.
2. Configurar `DIGIT_SECRET_KEY` con valor aleatorio largo.
3. Usar PostgreSQL administrado con copias de seguridad.
4. Configurar almacenamiento de objetos persistente compatible con S3 para producción. En modo local, las nuevas cargas de documentos, adjuntos y lotes también se guardan en PostgreSQL como respaldo de recuperación; esto no migra automáticamente archivos antiguos, no reemplaza almacenamiento de objetos ni copias externas verificadas.
5. Configurar HTTPS, `SECURE_COOKIES=true` y `CSRF_ENABLED=true`.
6. Configurar SMTP para recuperación y recordatorios.
7. Separar los roles PostgreSQL:
   - rol propietario/migración;
   - rol de aplicación sin propiedad de tablas y sin `BYPASSRLS`.
8. Mantener `RLS_ENABLED=true` y completar las pruebas de aislamiento con el rol de aplicación separado antes de considerar habilitado el refuerzo de RLS. Actualmente `RLS_FORCE=false` de forma deliberada hasta validar la separación de roles.
9. Probar exportación y restauración completa.
10. Verificar que el entorno sea `production`; el sembrado productivo ya bloquea los datos ficticios.
11. Revisar jurídicamente modelos, cálculos y parámetros.
12. Realizar prueba de permisos y accesos cruzados con administrador, contador, auxiliar y empresa.

## Pendientes que dependen de servicios externos

- Entrega real de correos: requiere cuenta SMTP.
- Almacenamiento de objetos persistente: requiere bucket S3 compatible y credenciales configuradas en Render.
- Respaldo automático fuera del servidor: requiere almacenamiento externo o tarea programada y una restauración probada.
- Dominio `digitlaboral.com.py`: requiere compra y configuración DNS.
- Cobro automático: requiere contrato e integración con un proveedor de pagos.
- Alertas legales oficiales: requieren una fuente estable, revisión humana y proceso de actualización.

El sistema está preparado para estas integraciones, pero no deben considerarse activas hasta configurar y comprobar los servicios correspondientes.
