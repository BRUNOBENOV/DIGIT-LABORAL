# Registro de cambios
## 2.6.8 — Restaurar el color original de Inicio

- Revierte exclusivamente la regla introducida en 2.6.7 que forzaba el texto de Inicio a azul cuando estaba seleccionado y el cursor no estaba encima.
- Conserva íntegramente el logo horizontal nuevo en el encabezado, la sidebar, las pantallas de acceso y el sitio público.
- No agrega estilos para hover ni cambia el resto de la paleta o navegación.
- Actualiza las pruebas de regresión para exigir el color original de Inicio y seguir verificando la marca nueva.

## 2.6.7 — Ajuste de Inicio y actualización de marca

- Corrige el color del texto **Inicio** cuando la opción está seleccionada y el cursor no está encima; el estado hover existente se conserva sin cambios.
- Sustituye el logo anterior por el nuevo logo horizontal proporcionado para el encabezado, el pie de la barra lateral y las pantallas de acceso, recuperación y segundo factor.
- Añade reglas responsive y una base blanca discreta para mantener legible el logo sobre el fondo oscuro de la sidebar.
- No modifica rutas, permisos, datos, API ni lógica laboral.

### Validación
- Incorpora pruebas de regresión para el color de Inicio y el uso coherente de la nueva marca.

## 2.6.6 — Módulo Secciones dentro de Mantenimientos

- Añade una pantalla de gestión dedicada en `/app/sections`, accesible como subapartado de **Mantenimientos** junto a Empresas y Funcionarios.
- Incorpora filtros por código y nombre, selección de empresa, visualización de secciones activas/inactivas y recuento de funcionarios vinculados.
- Permite crear, editar, desactivar y reactivar secciones; la fecha y el usuario de actualización se generan en el backend y se muestran como auditoría de solo lectura.
- Añade carga opcional y transaccional de cuatro ejemplos de prueba para empresas que aún no tienen secciones.
- Mantiene la API existente, el vínculo `Employee.section_id`, el aislamiento por empresa y los controles de rol; la desactivación conserva las referencias históricas.
- Conserva FastAPI/Jinja2, SQLAlchemy y la configuración de despliegue de Render; no crea una aplicación paralela ni requiere una tabla nueva.

### Validación
- Añade pruebas para la navegación, los filtros del módulo, los metadatos de auditoría, la desactivación segura y el registro de la ruta.

## 2.6.5 — Corrección de contraste en la sidebar

- Corrige exclusivamente la barra lateral izquierda: textos de subapartados más claros, encabezados de categorías con mayor contraste y espaciado legible.
- Destaca el subapartado activo con azul más visible, texto blanco y un indicador lateral claro; el hover también mantiene alto contraste.
- Mejora la visibilidad de numeración de grupos, flechas, contador de notificaciones y foco de teclado.
- Conserva el resto de la interfaz y los enlaces existentes; no cambia rutas, permisos, cálculos ni datos.

### Validación
- Añade una prueba para comprobar que la hoja de contraste se carga después del tema global y que define estados normal, hover y activo.

## 2.6.4 — Sistema visual global y navegación modular

- Extiende la paleta azul/blanco/gris, tarjetas, espaciado, tipografía, paneles y feedback de estado a las pantallas autenticadas de los distintos módulos.
- Añade navegación secundaria reutilizable para Cálculo, Informes, Certificados, Utilitarios y mantenimientos administrativos.
- Incorpora macros Jinja reutilizables para pestañas de módulo, paneles seccionados y ayuda inline.
- Añade búsqueda inmediata y ordenación por encabezado a tablas de listados con tres o más filas, manteniendo la búsqueda dentro de los resultados ya cargados.
- Unifica estilos de formularios, validación inline accesible, controles táctiles, tablas con encabezados fijos y filas alternadas, modales y mensajes de éxito/error/advertencia.
- Refuerza responsividad, escalado tipográfico, foco por teclado y compatibilidad con movimiento reducido.
- Se limita al espacio autenticado y excluye páginas públicas, impresión y algunas tablas especiales; no cambia cálculos, permisos, datos persistidos ni rutas de negocio.
- Documenta el sistema en `docs/UI_SYSTEM_V264.md`. Se usa FastAPI + Jinja2 + HTML/CSS/JavaScript, sin añadir React ni Vue.

### Validación
- Se agregan pruebas de regresión para el CSS global, macros Jinja y navegación en los principales módulos.
- La integración requiere la suite completa de CI y un despliegue exitoso en Render.

# Registro de cambios
## 2.6.3 — Mejora de usabilidad en Empresas y Funcionarios

- Agrega navegación secundaria para cambiar entre Empresas y Funcionarios y pestañas contextuales dentro de los expedientes.
- Mejora el directorio de empresas con tarjetas más legibles, filtros rápidos por estado y logo, búsqueda inmediata y ordenación por nombre, código o cantidad de funcionarios.
- Mejora el directorio de funcionarios con filtros rápidos por estado, aportes IPS y sección, además de ordenación por nombre, legajo, empresa, sección, ingreso y salario.
- Actualiza en vivo los contadores de resultados sin recargar la página; mantiene los filtros por empresa, sección, ciudad y departamento del servidor.
- Añade mensajes de validación junto al campo después de interactuar con formularios, con estados accesibles para lectores de pantalla.
- Refuerza espacios, tarjetas, bordes, sombras suaves, estados de foco y adaptación móvil usando la paleta azul/blanco vigente.
- No cambia rutas de negocio, permisos, lógica de cálculo, datos persistidos ni estructura de la base de datos.

### Validación
- Nuevas pruebas de regresión para navegación secundaria, filtros, ordenación, assets y pestañas contextuales.
- La publicación requiere suite completa de CI y confirmación del despliegue exitoso en Render.

## 2.6.2 — Renovación visual azul y accesible

- Unifica la paleta del espacio autenticado en azul marino `#0D1B2A`, azul medio `#1E40AF`, azul de acción `#2563EB`, fondo `#F9FAFB`, superficies blancas y texto `#111827`.
- Consolida la sidebar oscura y mantiene la navegación activa, los grupos y sus estados legibles en escritorio y móvil.
- Unifica botones, paneles, tarjetas, tablas, formularios y modales con bordes neutros, radios consistentes y sombras discretas.
- Refuerza el foco visible para teclado, contraste, placeholders y mensajes secundarios.
- Mantiene Inter como tipografía principal con familias de respaldo del sistema.
- Carga los estilos desde una hoja de diseño global para facilitar ajustes futuros sin reescribir cada módulo.


## 2.6.1 — Mantenimiento de funcionarios y legajos

- Código Legajo numérico único dentro de cada empresa, con asignación retroactiva a los funcionarios existentes.
- Búsqueda y autocompletado por empresa + legajo; filtros por legajo, nombre, cédula, cargo, empresa, sección y estado.
- Nueva entidad Secciones, separada de las sucursales físicas, con creación, edición y desactivación lógica.
- Integración de nacionalidad, estado civil, categoría laboral, jornada, turno, horas diarias/semanales y número IPS mediante el perfil complementario existente.
- Registro del usuario y fecha de última modificación.
- Endpoints REST autenticados para consulta, alta, edición y archivo lógico de funcionarios y secciones; política RLS por estudio para la nueva tabla.
- Importaciones nuevas asignan Código Legajo. Las modificaciones salariales continúan sujetas a aprobación.
- La versión 2.6.1 se integró en main y fue desplegada en Render el 27-10-2026 tras superar la suite de CI.


## 2.6.0 — 27-10-2026

### Mantenimientos · formulario principal de Empresas
- Se incorpora el Código Empresa numérico, único por estudio, con asignación retroactiva a empresas existentes.
- Se amplía la ficha con propietario, C.I. del representante, sector/lugar de trabajo, actividad económica, contacto y datos patronales.
- Ciudad y departamento se eligen mediante listas paraguayas: 18 departamentos y 262 municipios, contrastados con el portal público de Municipios del Paraguay (https://municipios.gov.py/municipios/).
- La búsqueda admite código, nombre o RUC y filtros por ciudad y departamento.
- La carga por código recupera la empresa existente mediante API autenticada.
- Se agregan endpoints JSON de consulta, creación, actualización y archivado con validaciones de datos, permisos, CSRF y aislamiento por estudio.
- El botón Eliminar archiva el registro para conservar nóminas, cálculos, certificados, trámites y auditoría; el registro puede volver a mostrarse y restaurarse.
- Se completan las empresas sintéticas del seed de desarrollo con códigos numéricos, RUC de prueba módulo 11, registros patronales numéricos y perfil de cumplimiento; el seed no se ejecuta para insertar estas empresas en producción.

### Validación
- Se agregan pruebas para el formulario, catálogo paraguayo, RUC módulo 11, consulta por código y operaciones CRUD de la API.
- La publicación requiere CI en verde y confirmación del despliegue de Render.


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
