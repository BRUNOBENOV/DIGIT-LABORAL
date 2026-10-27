# DigIT-Laboral 2.6.0 — Mantenimientos de Empresas

## Cambios funcionales
- Código numérico por empresa, único dentro del estudio, con backfill migratorio de registros existentes.
- Formulario organizado por identificación, responsables/contacto, ubicación/actividad y datos patronales.
- Selectores de departamentos y ciudades paraguayas.
- Campos de propietario, C.I. del representante, sector, lugar de trabajo, actividad económica y contacto.
- Búsqueda por código, nombre o RUC; filtros por ciudad y departamento.
- Autocompletado autenticado por Código Empresa.
- API JSON para listado, consulta por código, creación, actualización y archivado.
- Archivado lógico para preservar historial laboral y auditoría.
- Se mantiene la sucursal como una entidad independiente y se reutiliza el perfil de cumplimiento para departamento, actividad y C.I.
- No se agregan empresas de ejemplo a producción.

## Publicación
- Se requieren pruebas de CI completas y verificación del despliegue antes de considerar esta versión activa en producción.
