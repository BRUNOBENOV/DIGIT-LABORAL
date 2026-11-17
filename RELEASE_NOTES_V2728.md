# Digit Laboral 2.7.28 — Correcciones de auditoría

## Informes

- **Personales Despedidos:** el filtro anual corresponde a la fecha de egreso registrada, no a la fecha original de ingreso.
- **Registros anuales de personal:** se incluyen trabajadores cuyo vínculo se superpuso al año consultado, incluso si comenzaron antes. La lista por fecha de ingreso mantiene su significado original.
- **Informes de cálculos:** la selección de año se basa en el período de referencia cuando existe; se incorpora realmente el filtro mensual que antes era ignorado. Los antecedentes sin período conservan el año de creación.
- El formulario oculta filtros que no se aplican para evitar resultados inesperados; la etiqueta del año indica el criterio pertinente.
- Los PDF con más de 12 columnas utilizan papel A3 apaisado y texto adaptado, sin eliminar datos.
- La evaluación de vencimiento de exámenes médicos utiliza la fecha local de Paraguay.

## Seguridad

- Las solicitudes POST protegidas por CSRF tienen un límite de tamaño global para evitar almacenarlas ilimitadamente en memoria, además de los límites especiales ya existentes para XLSX y calculadoras. Se rechazan cabeceras Content-Length excesivas o malformadas antes de leer el cuerpo.
- Se añade .gitignore para prevenir que entren nuevas bases de trabajo, archivos subidos, credenciales y cachés. Esto **no retira** la base SQLite ya versionada ni su historial; exige una auditoría independiente antes de adoptar medidas sobre ella.

## Pruebas

Casos sintéticos para egresos, años de cobertura laboral, diferencias entre fecha de creación y período de cálculo, legibilidad de PDF, filtros disponibles y cargas HTTP grandes.

No se modifican las fórmulas, liquidaciones históricas, datos de producción ni las comunicaciones reales con MTESS, REOP o REI.
