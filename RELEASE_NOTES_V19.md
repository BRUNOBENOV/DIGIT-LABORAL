# Digit Laboral v1.9 Preview

Esta versión transforma el prototipo en una base operativa mucho más completa para pruebas internas y piloto controlado.

## Implementado

### Importación masiva
- Plantilla Excel descargable.
- Importación XLSX y CSV.
- Validación por fila y vista previa.
- Detección de cédulas duplicadas.
- Opción de omitir o actualizar registros existentes.
- Auditoría del proceso.

### Expediente digital del funcionario
- Página individual por funcionario.
- Línea de tiempo laboral.
- Historial salarial.
- Documentos, certificados, cálculos, vacaciones y liquidaciones vinculadas.
- Registro manual de eventos.

### Seguridad
- Bloqueo temporal por intentos fallidos.
- Registro de eventos de seguridad con IP y navegador.
- Recuperación de contraseña por correo SMTP.
- Verificación en dos pasos TOTP.
- Cierre de todas las sesiones.
- Restablecimiento administrativo de sesiones y 2FA.
- Contraseñas nuevas con mínimo de 10 caracteres y complejidad básica.

### Agenda laboral
- Vencimientos por empresa y funcionario.
- Prioridad y estado.
- Alertas por vencimientos atrasados o próximos.
- Aniversarios laborales y vacaciones próximas.
- Exportación iCalendar.
- Envío manual de recordatorios por correo cuando SMTP está configurado.

### Trámites
- Responsable asignado.
- Fecha límite.
- Estados ampliados.
- Comentarios visibles para la empresa y comentarios internos.
- Archivos adjuntos.
- Página individual de seguimiento.

### Documentos
- Nuevos modelos: permiso laboral, amonestación, cambio salarial, alta, baja, recibo salarial y liquidación final.
- Se conserva la advertencia de revisión profesional en documentos sensibles.

### Respaldo y portabilidad
- Exportación ZIP completa por estudio.
- CSV de datos maestros, solicitudes, agenda, auditoría e historial.
- Inclusión de archivos documentales y adjuntos.
- Exclusión de contraseñas, tokens y secretos 2FA.
- Script local para respaldar SQLite o PostgreSQL con `pg_dump`.

### Administración comercial
- Registro de pagos por estudio.
- Historial comercial.
- Ingresos confirmados del mes.

### Aislamiento multicuenta
- Políticas PostgreSQL Row-Level Security preparadas.
- Contexto de estudio por sesión SQLAlchemy.
- Requiere usuario PostgreSQL de aplicación sin propiedad de tablas y sin `BYPASSRLS` para aportar la barrera completa.

## Validación

- 21 pruebas automatizadas aprobadas.
- Compilación Python correcta.
- No se incluyen claves, `.env` ni contraseñas de producción.

## Endurecimiento final

- Protección CSRF basada en token de sesión para formularios autenticados.
- El entorno productivo ya no crea usuarios, estudios ni empresas ficticias.
- El primer superadministrador se define mediante variables protegidas del hosting.
