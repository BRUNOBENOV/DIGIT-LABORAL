# DigIT-Laboral 2.6.3 — Usabilidad de Empresas y Funcionarios

## Experiencia de navegación
- Navegación secundaria dentro de los dos módulos de mantenimiento.
- Pestañas contextuales en el expediente de empresa: resumen, funcionarios, sucursales, cumplimiento y documentos.
- Pestañas contextuales en el expediente laboral del funcionario: resumen, historial, documentos y accesos directos a cálculos y liquidaciones, según los permisos del rol.

## Directorios
- Empresas: orden por nombre, código o cantidad de funcionarios; filtros rápidos por activas, archivadas y sin logo; búsqueda inmediata sobre los resultados ya consultados en el servidor.
- Funcionarios: orden por nombre, legajo, empresa, sección, fecha de ingreso y salario; filtros rápidos por activos, aportantes a IPS y funcionarios sin sección.
- Los contadores reflejan la cantidad visible y se actualizan al instante.
- Los filtros del servidor se mantienen como fuente principal; los controles rápidos solo refinan los resultados ya cargados.

## Formularios y accesibilidad
- Validación en vivo junto a los campos después del primer contacto del usuario.
- Mensajes diferenciados para campos obligatorios, formato de correo, patrón y rango de valores.
- Foco visible, contraste mejorado y estados accesibles con aria-live y aria-invalid.
- Interfaz adaptable a teléfonos y pantallas estrechas; se conserva el desplazamiento horizontal de tablas extensas.

## Alcance técnico
- Nuevos assets: app/static/maintenance-workspace-263.css y app/static/maintenance-workspace-263.js.
- No se agregan migraciones ni se modifican permisos, reglas de negocio o cálculos laborales.
- Pruebas nuevas: tests/test_maintenance_usability.py.
