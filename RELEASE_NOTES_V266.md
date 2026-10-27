# Release notes — DIGIT-LABORAL v2.6.6

## Módulo Secciones

- Nueva pantalla: `/app/sections`.
- Ubicación en la navegación: **Mantenimientos → Secciones**.
- Filtros por código y nombre, empresa y estado.
- CRUD con validación de código entero positivo y nombre obligatorio.
- El sistema conserva la asociación de los funcionarios al desactivar una sección.
- Registro automático de fecha y usuario que actualizan los datos.
- Ejemplos opcionales: Administración, Contabilidad, Ventas y Operaciones.
- La API y el frontend mantienen las restricciones de empresa y el control CSRF.

### Compatibilidad
El proyecto continúa usando FastAPI, Jinja2 y SQLAlchemy. Esta entrega no cambia el proveedor de despliegue ni requiere una nueva tabla: reutiliza `CompanySection` y `Employee.section_id`.
