# Registro de cambios

## 2.5.5 — 27-10-2026

### Autorización por rol
- Se restringió la ruta interna de cálculos laborales a administrador, contador y auxiliar.
- Se restringió el historial y la pantalla del asistente de IA a los perfiles operativos autorizados; no basta con ocultar el enlace en el menú.
- Se limitó la pantalla de parámetros administrativos al rol administrador.
- Se añadieron pruebas de regresión para confirmar que abogado y empleador reciben denegación al intentar acceder por URL, y que el contador mantiene acceso a sus herramientas.

### Validación
- La publicación depende de que CI pase con la suite completa y se confirme el nuevo despliegue de Render.
- Se mantiene el requisito de separar los roles PostgreSQL antes de certificar el aislamiento RLS entre estudios.

## 2.5.4 — 26-10-2026

### Flujos de trabajo por perfil
- Se agregó un espacio funcional para el rol `abogado`, disponible al crear usuarios, con orientación jurídica, consulta de expedientes, documentos laborales y acceso a solicitudes asignadas.
- La bandeja de solicitudes ahora se filtra en el servidor por empresa, estado, tipo de trámite, responsable y vencimiento.
- El abogado queda limitado a solicitudes asignadas: no puede abrir trámites de otro profesional por URL, dejar comentarios o adjuntos sobre casos no asignados ni transferir una asignación.
- Las aprobaciones y rechazos siguen reservados a administrador y contador; el abogado puede registrar seguimiento y respuestas en los casos a su cargo.
- La agenda laboral es visible para el empleador en modo consulta, mientras que alta y actualización de vencimientos quedan reservadas al equipo del estudio.
- Se ajustaron las pantallas de empresa, funcionario, informe, cumplimiento y certificado oficial para no ofrecer botones de edición que el perfil no puede ejecutar.
- Se añadieron pruebas de recorrido para abogado y empleador, incluyendo cola asignada, lecturas rechazadas en casos ajenos y límites de permisos.

### Validación
- La publicación de esta versión queda supeditada a la suite completa de CI y a la verificación del despliegue de Render.
- La configuración PostgreSQL de RLS sigue documentada como pendiente de separar rol de aplicación y rol de migraciones; no debe inferirse que este cambio funcional completa ese trabajo.

## 2.5.3 — 26-10-2026

### Seguridad multiempresa
- Se añadieron políticas RLS para `studios`, `users`, `user_security`, `password_reset_tokens` y `activation_requests`.
- Se incorporó `digit_current_user_id()` con `search_path = pg_catalog, pg_temp` y migración Alembic `0014_tenant_user_context`.
- La sesión firmada establece primero el ID del usuario; después de leer el registro canónico se establece el estudio y el rol. Esto permite la consulta inicial segura cuando el usuario de ejecución no es propietario de las tablas.
- Se añadieron pruebas de regresión para el contexto de sesión y las políticas de las tablas sensibles.
- El arranque y `/health/ready` informan si el rol PostgreSQL de ejecución tiene `BYPASSRLS`, es superusuario o es propietario de tablas.

### Límites de publicación
- La separación real de roles PostgreSQL sigue pendiente: el rol actual `digit_app` es propietario de la mayoría de las tablas y `RLS_FORCE` permanece desactivado deliberadamente. Las políticas añadidas no deben interpretarse como aislamiento RLS efectivo hasta que la conexión de ejecución use un rol no propietario y sin `BYPASSRLS`.
- El almacenamiento S3 compatible, SMTP y una restauración probada desde copias externas requieren credenciales y servicios configurados.

## 2.5.2 — 26-10-2026

### Seguridad
- Se fijó el `search_path` de las funciones PostgreSQL de contexto multiempresa.
- Se agregó una prueba de regresión para impedir que el SQL del arranque pierda sus delimitadores.
- Se retiraron los permisos de `anon` y `authenticated` sobre la tabla interna `alembic_version` en la base productiva; el usuario de aplicación conserva su acceso.

### Rendimiento
- Se agregaron índices a las claves foráneas `employees.branch_id` y `request_workflows.approved_by_user_id`.

### Validación de publicación
- La suite completa de CI y las comprobaciones de arranque pasaron.
- Render confirmó el despliegue activo.
- Supabase confirmó Alembic `0013_tenant_function_search_path`, `search_path` restringido en las dos funciones y cero avisos activos en el asesor de seguridad.

### Requisitos operativos aún pendientes
- Configurar almacenamiento persistente S3 compatible.
- Configurar y probar la entrega SMTP.
- Separar el rol de migraciones del rol de aplicación antes de forzar RLS.
- Ejecutar una prueba formal de aislamiento entre empresas y verificar la restauración desde una copia externa.
