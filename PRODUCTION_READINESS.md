# Preparación para producción

## Auditoría de seguridad registrada — 26-10-2026

### Estado verificado antes de v2.5.3
- Render tenía activa la versión 2.5.2 y Supabase registraba Alembic `0013_tenant_function_search_path`.
- El rol PostgreSQL `digit_app` no tiene `BYPASSRLS` ni es superusuario, pero es propietario de 39 de las 40 tablas públicas.
- En esa revisión, 32 de las 40 tablas tenían RLS habilitado y ninguna tenía `FORCE ROW LEVEL SECURITY`.
- **Consecuencia:** el rol propietario omite las políticas RLS en las tablas que posee mientras no se fuerce RLS. Por tanto, tener políticas definidas no basta para demostrar aislamiento multiempresa efectivo.
- `anon` y `authenticated` no tienen permisos sobre las tablas/vistas del esquema `public`. El asesor de seguridad de Supabase no devolvió avisos activos en esa verificación.

### Cambios incorporados en el código v2.5.3
- Se añadieron políticas RLS para `studios`, `users`, `user_security`, `password_reset_tokens` y `activation_requests`.
- Se añadió la función `digit_current_user_id()` con `search_path = pg_catalog, pg_temp` en la migración `0014_tenant_user_context`.
- La sesión firmada establece el ID del usuario antes de consultar la fila de usuario; el estudio y el rol se cargan luego desde el registro de PostgreSQL.
- El arranque y `/health/ready` verifican si el rol de ejecución puede omitir RLS por privilegios o por propiedad de tablas.
- Estas mejoras preparan el aislamiento para un rol de ejecución no propietario. **No cambian por sí solas la propiedad de las tablas ni sustituyen la configuración separada de credenciales.**

La aplicación no debe certificarse como lista para operar con datos reales hasta completar los puntos obligatorios que siguen y verificar los resultados en producción.

## Obligatorio antes de datos reales

1. Confirmar que `INITIAL_ADMIN_EMAIL` e `INITIAL_ADMIN_PASSWORD` estén configurados (contraseña de al menos 12 caracteres). En producción no se crean cuentas ni empresas de demostración.
2. Mantener `DIGIT_SECRET_KEY` como una clave aleatoria larga.
3. Usar PostgreSQL administrado con copias de seguridad.
4. Configurar almacenamiento de objetos persistente compatible con S3. `STORAGE_BACKEND=local` sigue siendo el modo actual por defecto. En modo local, las nuevas cargas de documentos, adjuntos y lotes también se guardan en PostgreSQL como respaldo de recuperación; esto no migra automáticamente archivos antiguos ni reemplaza las copias externas.
5. Mantener HTTPS, `SECURE_COOKIES=true` y `CSRF_ENABLED=true`.
6. Configurar y probar SMTP para recuperación de contraseña y recordatorios.
7. **Separar los roles PostgreSQL antes de dar por efectivo RLS:**
   - conservar `MIGRATION_DATABASE_URL` para el usuario de migraciones/propietario;
   - configurar `DATABASE_URL` con un usuario de ejecución que no sea propietario de tablas, no sea superusuario y no tenga `BYPASSRLS`;
   - otorgarle los privilegios DML y de secuencias necesarios, sin propiedad de objetos;
   - verificar con una consulta de diagnóstico que el rol de ejecución no sea propietario de tablas de aplicación.
8. Mantener `RLS_ENABLED=true`. No activar `RLS_FORCE=true` hasta completar la separación y probar acceso, escritura, inicio de sesión, recuperación de contraseña, sesiones, importación, exportación y solicitudes con el usuario de ejecución real.
9. Ejecutar pruebas de aislamiento entre dos estudios distintos sobre PostgreSQL usando el rol de ejecución, incluyendo lecturas, inserciones, actualizaciones y borrados. Las pruebas unitarias de las políticas no sustituyen esta prueba integrada.
10. Completar una exportación y una restauración real desde una copia externa; validar archivos, documentos, lotes, adjuntos y recuentos.
11. Confirmar `ENVIRONMENT=production`; el sembrado productivo debe permanecer sin datos ficticios.
12. Revisar jurídicamente modelos, cálculos y parámetros laborales paraguayos.
13. Realizar pruebas de permisos diferenciadas con superadministrador, administrador/contador, auxiliar y usuario de empresa.

## Pendientes que dependen de servicios externos

- Almacenamiento S3 compatible: requiere un bucket, endpoint/región si corresponde y claves guardadas como variables secretas en Render.
- Copias externas automáticas: requieren un destino independiente y una tarea programada, además de una restauración comprobada.
- Entrega de correos: requiere una cuenta SMTP válida y prueba de envío.
- Dominio `digitlaboral.com.py`: requiere compra y configuración DNS.
- Cobro automático: requiere contrato e integración con un proveedor de pagos.
- Alertas oficiales: requieren fuente estable, revisión humana y proceso de actualización.

La existencia de variables o código de integración no demuestra que un servicio externo esté conectado. Marcar cada punto como completado únicamente después de probarlo en el entorno productivo.
