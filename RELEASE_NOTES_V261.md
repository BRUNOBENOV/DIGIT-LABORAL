# DigIT-Laboral 2.6.1 — Mantenimiento de funcionarios y legajos

## Funcionalidad

- Añade Código Legajo numérico único dentro de cada empresa. La migración asigna códigos a los registros existentes sin reemplazar sus identificadores internos.
- Permite buscar el legajo por empresa y código, autocompletar sus datos y abrir el registro existente para edición.
- Añade filtros por legajo, nombre, cédula, cargo, empresa, sección y estado.
- Incorpora secciones internas por empresa, separadas de sucursales físicas, con alta, edición y desactivación lógica.
- Integra nacionalidad, estado civil, categoría, jornada, turno y horas semanales mediante el perfil complementario ya existente.
- Registra usuario y fecha de última modificación del legajo.
- Amplía los endpoints REST con autorización por estudio, validación del lado servidor y archivo lógico.
- La importación de funcionarios asigna legajos a los registros nuevos.

## Integridad y seguridad

- No se permite modificar el salario vigente desde la edición ordinaria. Los cambios deben seguir el flujo de solicitud y aprobación salarial.
- El archivo lógico conserva nóminas, cálculos, certificados, documentos y eventos históricos.
- El legajo y la sección se validan dentro de la empresa correspondiente.
- Las relaciones existentes, el historial salarial y las instantáneas de cálculos anteriores se mantienen.
- El cambio está en rama de trabajo; no implica que la versión esté desplegada en producción hasta superar CI y verificarse el servicio.
