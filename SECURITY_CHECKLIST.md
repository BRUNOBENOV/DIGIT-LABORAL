# Lista de seguridad antes de utilizar datos reales

- Cambiar todas las contraseñas de demostración y eliminar usuarios que no correspondan.
- Generar una `DIGIT_SECRET_KEY` extensa y aleatoria.
- Utilizar PostgreSQL y verificar que `DATABASE_URL` apunte a la base correcta.
- Forzar HTTPS, cookies seguras y dominios permitidos exactos.
- Configurar copias de seguridad automáticas y probar una restauración completa.
- Aplicar protección CSRF, límite de intentos y recuperación de contraseña por correo verificado.
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
