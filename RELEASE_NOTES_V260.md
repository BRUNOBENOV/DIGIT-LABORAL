# DigIT-Laboral 2.6.0 — Mantenimientos de Empresas

## Cambios funcionales
- Código numérico por empresa, único dentro del estudio, con backfill migratorio de registros existentes.
- Formulario responsivo organizado por identificación, responsables/contacto, ubicación/actividad y datos patronales.
- Selectores de los 18 departamentos y de los 262 municipios listados en el portal público de Municipios del Paraguay: https://municipios.gov.py/municipios/.
- Campos de propietario, C.I. del representante, sector, lugar de trabajo, actividad económica, contacto y fecha de actualización.
- Búsqueda por código, nombre o RUC y filtros por ciudad y departamento.
- Autocompletado autenticado por Código Empresa.
- API JSON para listado, consulta por código, consulta por ID, creación, actualización y archivado.
- Validación del RUC mediante dígito verificador módulo 11, además de código, nombre, números patronales, CI y correspondencia ciudad/departamento.
- Archivado lógico para preservar historial laboral y auditoría; las empresas archivadas pueden mostrarse y restaurarse.
- La sucursal permanece como entidad independiente. Departamento, actividad y C.I. del representante se guardan en el perfil de cumplimiento existente.
- Se completan las tres empresas sintéticas del entorno de desarrollo con códigos, RUC de prueba con verificador, datos patronales numéricos y perfil de cumplimiento. El seed solo se ejecuta cuando no es producción y no existe un estudio; no se agregan empresas ficticias a producción.

## Validación y publicación
- Pruebas de formulario, catálogo de municipios, normalización RUC, búsqueda por código y CRUD de API.
- Se requieren pruebas completas de CI y verificación del despliegue antes de considerar la versión activa en producción.
- La validación módulo 11 no consulta DNIT ni confirma estado tributario, inscripción o actividad del contribuyente.
