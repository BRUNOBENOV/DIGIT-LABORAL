# Lista de seguridad antes de utilizar datos reales

- Cambiar todas las contraseñas de demostración y eliminar usuarios que no correspondan.
- Generar una `DIGIT_SECRET_KEY` extensa y aleatoria.
- Utilizar PostgreSQL y verificar que `DATABASE_URL` apunte a la base correcta.
- Forzar HTTPS, cookies seguras y dominios permitidos exactos.
- Configurar copias de seguridad automáticas y probar una restauración completa.
- Mantener `CSRF_ENABLED=true`, límite de intentos y recuperación de contraseña por correo verificado.
- Revisar permisos de administrador, contador, auxiliar y empresa vinculada.
- Confirmar que una empresa vinculada solo pueda acceder a sus propios datos.
- Mantener y revisar el registro de auditoría.
- Limitar logos a PNG/JPG, 2 MB y dimensiones razonables.
- No guardar claves API en GitHub, documentos, capturas o archivos públicos.
- Mantener `AI_STORE_RESPONSES=false` salvo decisión expresa y documentada.
- Solicitar consentimiento antes de enviar contexto a una IA externa.
- No enviar adjuntos, documentos completos ni datos innecesarios a la IA.
- Revisar humanamente toda liquidación, preaviso, despido, contrato y cálculo antes de emitirlo.
- Definir una política de retención, exportación y eliminación de datos personales.
- Configurar monitoreo de errores y alertas de disponibilidad.
- Realizar una revisión técnica, contable, laboral y de privacidad antes del lanzamiento comercial.

## Controles v1.9

- [x] Bloqueo temporal por intentos fallidos.
- [x] Eventos de acceso con IP y agente de usuario.
- [x] Recuperación mediante token de un solo uso y vencimiento.
- [x] Segundo factor TOTP.
- [x] Invalidación de todas las sesiones mediante versión de sesión.
- [x] Exportación sin hashes de contraseña ni secretos 2FA.
- [x] Preparación de políticas RLS por estudio.
- [x] Producción sin usuarios ni empresas de demostración.
- [x] Primer superadministrador obligatorio mediante variables protegidas.
- [ ] Configurar SMTP real.
- [ ] Ejecutar la app con rol PostgreSQL no propietario.
- [x] Protección CSRF explícita para operaciones autenticadas en `/app` y `/admin`.
- [ ] Agregar escaneo antimalware para adjuntos antes de permitir archivos de clientes reales.
- [ ] Configurar respaldo automático externo y alertas de fallos.
- [ ] Realizar prueba de penetración y revisión de código independiente.
