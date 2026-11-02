# Asistente temporal de corrección post-importación · v2.6.65

## Propósito

Corregir exclusivamente legajos creados por la importación histórica que quedaron en estado `Desvinculado` pese a conservar un vínculo laboral vigente. No se ejecuta SQL manual.

## Acceso

`Mantenimientos → Herramientas de mantenimiento · Post-importación`

- Solo `administrador` de su propio estudio.
- Formulario protegido por sesión y token CSRF (cuando CSRF está habilitado en la instalación).
- Ruta: `/app/maintenance/post-import`.
- La herramienta puede ocultarse y deshabilitarse tras completar la corrección, fijando `DIGIT_POST_IMPORT_REACTIVATION_ENABLED=false` en el servicio y desplegando de nuevo. No modifica el importador ni las acciones diarias.

## Archivo de entrada

Una sola columna con encabezado **employee_id** (ID interno de la fila `employees.id`) **o CODTRA** (código histórico registrado en las notas de importación). Admitidos `.xlsx` y `.csv` UTF-8, 2 MB y un máximo de 15.000 identificadores. No se aceptan segundas columnas.

**Atención:** `CODTRA` NO se equipara directamente con `employees.employee_code` porque el importador puede reasignarlo en conflictos. Se usa la evidencia del origen `Código(s) histórico(s) CODTRA:` guardada en el legajo. Un `CODTRA` ambiguo entre empresas se excluye, nunca se resuelve por aproximación. Los trabajadores no encontrados se excluyen.

## Condiciones antes de reactivar

- El trabajador existe en una empresa accesible del estudio.
- Estado actual exactamente `Desvinculado`.
- Empresa no archivada.
- Sin `FinalSettlement` vinculado.
- Sin `EmployeeExit` vigente no cancelado.
- Sin duplicados o ambigüedad del identificador.

El usuario revisa resultados completos y marca la confirmación obligatoria. La vista previa queda vinculada al usuario y al estudio, expira en dos horas, no persiste en el navegador y se consume después de una confirmación exitosa. Un registro cambiado desde la vista previa bloquea la operación completa.

## Modificaciones permitidas

| Campo/registro | Acción |
|---|---|
| `Employee.status` | `Activo` |
| `Employee.termination_date` | `NULL` |
| `Employee.admission_date` | **No se modifica** |
| `Employee.updated_at/updated_by` | Actualizado con operador y fecha |
| `EmployeeEvent` | Una entrada de corrección administrativa por trabajador |
| `AuditLog` | Una entrada por trabajador con detalle y valores anteriores |

Sin modificaciones a liquidaciones, cálculos, salarios, historial de ingresos, IPS ni REOP.

## Transaccionalidad y despliegue

Todos los registros aptos se verifican de nuevo, bloqueando las filas con `SELECT ... FOR UPDATE`, y se modifican con un solo `COMMIT` SQLAlchemy. En error la sesión hace `ROLLBACK` y ningún trabajador se reactiva a medias.

**Antes de usar en producción:** respaldar la base y verificar manualmente una muestra de los 381 trabajadores y los resultados excluidos. El asistente **no se ha ejecutado** con los legajos reales; solamente se publica el código y las pruebas.

## Verificación esperada

1. Cargar CSV/XLSX con 381 identificadores verificados.
2. Revisar los totales listos/excluidos y los nombres, empresa, estado y fecha de ingreso.
3. Confirmar con la casilla; abrir el directorio de funcionarios filtrado por `Activo`.
4. Comprobar fecha de ingreso conservada, egreso vacío y una auditoría por cada caso actualizado.
5. Tras concluir, deshabilitar la herramienta desde la variable de entorno.
