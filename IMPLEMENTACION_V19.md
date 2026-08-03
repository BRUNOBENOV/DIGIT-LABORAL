# Informe de implementación — Digit Laboral v1.9 Preview

## Estado general

La versión v1.9 incorpora la base funcional de los principales componentes solicitados. Está preparada para pruebas internas y un piloto controlado. No debe utilizarse aún como plataforma productiva con datos laborales reales hasta completar los servicios externos, la revisión jurídica y la validación de seguridad indicados al final.

## Componentes implementados

### Seguridad y acceso
- Bloqueo temporal por intentos fallidos.
- Registro de accesos y eventos de seguridad.
- Recuperación de contraseña mediante token con vencimiento.
- Segundo factor TOTP.
- Cierre de todas las sesiones.
- Protección CSRF en operaciones autenticadas cuando `CSRF_ENABLED=true`.
- Producción sin cuentas ni empresas ficticias.
- Superadministrador inicial obligatorio mediante variables protegidas.
- Preparación de PostgreSQL Row-Level Security por estudio.

### Importación y expedientes
- Plantilla Excel de funcionarios.
- Lectura XLSX/CSV, validación, vista previa y confirmación.
- Manejo de duplicados mediante omisión o actualización.
- Expediente individual del funcionario.
- Línea de tiempo laboral e historial salarial.
- Asociación de documentos, certificados, vacaciones, cálculos y liquidaciones.

### Agenda y trámites
- Agenda laboral con vencimientos, prioridades y estados.
- Alertas por atrasos y vencimientos próximos.
- Aniversarios laborales y vacaciones próximas.
- Exportación iCalendar.
- Flujo de solicitudes con responsable, fecha límite, comentarios y adjuntos.
- Comentarios internos separados de los visibles para la empresa.

### Documentos
- Permiso laboral.
- Amonestación.
- Cambio salarial.
- Alta y baja de funcionario.
- Recibo salarial.
- Liquidación final.
- Generación con los datos y la identidad visual de la empresa.

### Respaldo y administración
- Exportación ZIP por estudio sin contraseñas, tokens ni secretos 2FA.
- Datos maestros e historiales en CSV.
- Inclusión de documentos y adjuntos.
- Script para respaldo SQLite o PostgreSQL mediante `pg_dump`.
- Registro de pagos por estudio e ingresos confirmados del mes.

### Biblioteca jurídica
- Código del Trabajo organizado por libros, títulos, capítulos y artículos.
- Búsqueda, filtros, estados, fuentes y leyes modificatorias.
- Sincronización manual desde las fuentes configuradas.
- Advertencias de revisión profesional.

## Validación ejecutada

- 21 pruebas automatizadas aprobadas.
- Compilación de módulos Python aprobada.
- Pruebas manuales de ingreso, panel, empresas, funcionarios, agenda, trámites, seguridad, importación y exportación.
- Prueba productiva de CSRF: solicitud sin token rechazada con 403; solicitud válida aceptada.
- Prueba de sembrado productivo: crea únicamente el superadministrador configurado y ningún dato ficticio.

## Pendientes externos obligatorios

1. Crear el servicio de hosting y PostgreSQL administrado.
2. Configurar `DIGIT_SECRET_KEY`, administrador inicial, URL pública y dominios permitidos.
3. Configurar SMTP para correos reales.
4. Configurar almacenamiento persistente o de objetos para archivos.
5. Configurar respaldo externo automático y probar restauración.
6. Ejecutar la aplicación con un rol PostgreSQL no propietario para que RLS sea una barrera efectiva.
7. Revisar jurídicamente modelos, parámetros y cálculos.
8. Realizar prueba de penetración y revisión de privacidad.
9. Integrar pagos automáticos únicamente cuando exista contrato con un proveedor.
10. Comprar y configurar `digitlaboral.com.py` cuando se pase a producción.

## GitHub

La cuenta conectada permite leer el repositorio `BRUNOBENOV/DIGIT-LABORAL`, pero la integración devolvió error 403 al intentar crear una rama o escribir archivos. Para subir automáticamente esta versión, la aplicación de GitHub debe tener permiso **Contents: Read and write**. Mientras tanto, los paquetes ZIP contienen todo el código listo para subir.
