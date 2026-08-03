# Preparación para producción

## Obligatorio antes de datos reales

1. Configurar `INITIAL_ADMIN_EMAIL` e `INITIAL_ADMIN_PASSWORD` (mínimo 12 caracteres). En producción no se crean cuentas ni empresas de demostración.
2. Configurar `DIGIT_SECRET_KEY` con valor aleatorio largo.
3. Usar PostgreSQL administrado con copias de seguridad.
4. Configurar almacenamiento persistente para `data/uploads`.
5. Configurar HTTPS, `SECURE_COOKIES=true` y `CSRF_ENABLED=true`.
6. Configurar SMTP para recuperación y recordatorios.
7. Crear dos roles PostgreSQL:
   - rol propietario/migración;
   - rol de aplicación sin propiedad de tablas y sin `BYPASSRLS`.
8. Activar `RLS_ENABLED=true` con el rol de aplicación.
9. Probar exportación y restauración completa.
10. Verificar que el entorno sea `production`; el sembrado productivo ya bloquea los datos ficticios.
11. Revisar jurídicamente modelos, cálculos y parámetros.
12. Realizar prueba de permisos con administrador, contador, auxiliar y empresa.

## Pendientes que dependen de servicios externos

- Entrega real de correos: requiere cuenta SMTP.
- Respaldo automático fuera del servidor: requiere almacenamiento externo o tarea programada.
- Dominio `digitlaboral.com.py`: requiere compra y configuración DNS.
- Cobro automático: requiere contrato e integración con un proveedor de pagos.
- Alertas legales oficiales: requieren una fuente estable, revisión humana y proceso de actualización.

El sistema está preparado para estas integraciones, pero no deben considerarse activas hasta configurar y comprobar los servicios correspondientes.
