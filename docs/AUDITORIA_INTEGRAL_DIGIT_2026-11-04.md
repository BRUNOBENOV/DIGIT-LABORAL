# DIGIT-LABORAL — Auditoría técnica, funcional y visual
**Fecha:** 04/11/2026  
**Punto de partida:** versión 2.6.91, commit `1e6c8bc`, despliegue Render `Live`  
**Rama de correcciones:** `audit/ui-resiliencia-caché-accesibilidad-20261104`, candidata 2.6.92

> Este documento distingue **revisión de código**, **pruebas automatizadas** y **validación visual real**. Una plantilla revisada estáticamente no equivale a una prueba de funcionamiento en navegador. No se alteraron empresas, funcionarios, liquidaciones ni declaraciones de producción.

## 1. Cobertura y metodología
Se inventariaron 470 rutas de archivo en el repositorio, incluidas **75 plantillas HTML, 27 CSS, 24 JavaScript y 75 archivos Python de pruebas**. Se inspeccionaron directamente las plantillas de navegación, dashboard, administración, empresas, funcionarios, secciones, exámenes médicos, operaciones laborales, cálculos de salario, liquidación, recibos, planillas, reportes, certificados, cumplimiento REOP/REI, solicitudes, seguridad, auditoría y herramientas de importación.

Se revisaron los flujos del motor profesional, los controles de guardado y aprobación, los auxiliares de importación REOP/REI, la trazabilidad y la auditoría. Se comprobó la configuración del servicio en Render y el resultado de su último despliegue. Se usaron búsquedas estáticas para detectar formularios POST sin CSRF en los principales módulos, botones sin tipo, enlaces inertes, recursos con versiones de caché antiguas y tipografías demasiado pequeñas.

## 2. Situación verificada
| Control | Resultado | Límite |
| --- | --- | --- |
| Despliegue productivo | 2.6.91 `Live` | No comprueba la sesión privada de todos los módulos |
| Pruebas de la última versión | 841 aprobadas | Los tests no reemplazan pruebas de integración reales con portales externos |
| Errores graves en registros Render consultados | Ninguno en el conjunto devuelto | No equivale a ausencia absoluta de errores |
| Métricas de latencia y HTTP | Sin datos | No es posible cuantificar p95 ni porcentaje de errores |
| CSRF, principales formularios POST | Campo presente en todas las plantillas seleccionadas para inspección | No es una auditoría de penetración |
| Inspección gráfica real | Solo capturas disponibles y análisis de hojas de estilo | Sin acceso automatizado a una sesión autenticada para capturar las 75 vistas |

## 3. Hallazgos priorizados

### P1 — exactitud de datos laborales y declaraciones
**P1.1. Riesgo de confundir días remunerados con asistencia.** En salario mensual, `days_paid` puede prorratear el sueldo y la base IPS; `days_worked` y `hours_worked` son datos diferentes para los organismos. La interfaz tiene ayuda, pero es necesario probar con recibos reales los escenarios de 30 días de sueldo y 27 días asistidos, licencias, suspensiones, ingresos/egresos a mitad de mes y jornaleros. *No cambiar divisores ni bases imponibles sin prueba documental.*

**P1.2. Exportación REOP/REI.** El código tiene filtros por `IPS Sí`, excluye registros no aprobados y conserva exportación parcial con confirmación. Se necesita verificar con el archivo que el portal real acepte: identidad, días, horas, base IPS, tipo de remuneración, forma de pago y conceptos. *El hecho de generar un XLSX/TXT no prueba que el organismo lo haya recibido.*

**P1.3. Rectificación y aprobación.** Existe rectificación salarial no destructiva, que crea borrador y conserva el original. La prueba pendiente con datos sintéticos debe cubrir múltiples versiones del mismo funcionario/mes, anulación, aprobación, documentos y exportación posterior. No sobrescribir aprobados; un error ya declarado ante autoridad exige procedimiento externo de rectificación.

**P1.4. Consulta de asistencia capaz de bloquear el guardado (corregido en esta rama).** El navegador impedía enviar el formulario mientras esperaba una consulta remota sin plazo máximo. Se agregó un límite de 8 segundos y recuperación a edición manual si la consulta no responde; el servidor conserva la validación y no inventa jornadas. La prueba de frontend simula un servicio colgado y verifica que el formulario se desbloquee.

### P2 — estética, accesibilidad y experiencia
**P2.1. Recursos visuales con caché desigual (corregido en esta rama).** El layout base contenía 25 enlaces a CSS y 22 etiquetas de script (algunas condicionales). Varios estaban sin parámetro de versión o con versiones fijas antiguas, lo que puede dejar CSS/JS desactualizados en navegador después de una publicación. Se unificaron 47 recursos estáticos bajo `?v={{ app_version }}`, además de favicon y logos.

**P2.2. Capas CSS superpuestas (deuda técnica).** `theme-261.css` usa numerosos `!important`, junto a hojas previas y ajustes de marca. Esto aumenta el riesgo de texto invisible, cambios de color según hover, cascada impredecible y regresiones en vistas no relacionadas. Recomendación: consolidar por componentes y emplear variables de diseño, después de obtener capturas de referencia aprobadas.

**P2.3. Accesibilidad de teclado (corregido en esta rama).** Faltaba un enlace para saltar desde la navegación al contenido. Se añadió ancla al `main` y enlace visible al recibir foco con teclado.

**P2.4. Tipografía auxiliar (mejora aplicada).** Algunos datos secundarios del cálculo salarial utilizaban 10px. Se incrementó a 11px donde no altera la jerarquía ni sobrecarga los formularios. La revisión de contraste y zoom al 200% requiere sesión visual.

**P2.5. Densidad visual inconsistente.** Algunos módulos utilizan formularios extensos, tablas densas y textos de ayuda largos; otros tienen tarjetas compactas. Unificar jerarquía, navegación lateral, longitud de advertencias, estados de guardado, tabla/paginación y comportamiento móvil de forma incremental, preservando el flujo rápido estilo DOS.

### P2/P3 — arquitectura y rendimiento
**P2.6. Carga global de recursos.** El layout compartido referencia numerosas hojas y scripts, aunque algunos solo son relevantes para ciertos módulos. Después de medir tiempos y dependencias, separar recursos exclusivos por pantalla. Evitar eliminar cargas a ciegas porque puede romper dependencias.

**P2.7. Observabilidad incompleta.** El backend informó desplegarse, pero Render no devolvió datos de recuento HTTP/latencia. Registrar tiempos de respuesta, errores por ruta y consumo de memoria para validar el rendimiento antes de afirmar que es rápido.

**P3.1. Módulo central monolítico.** `app/main.py` contiene gran parte del ruteo y lógica. Extraer gradualmente subrouters y validaciones por dominio reducirá regresiones en actualizaciones.

## 4. Módulos revisados y estado
| Módulo | Revisión efectuada | Validación pendiente en navegador |
| --- | --- | --- |
| Inicio y navegación | Base HTML, dashboard, CSS global, menú y assets | Desktop 100/125/200%, móvil, teclado, tema claro y oscuro |
| Mantenimientos | Empresas, empleados, secciones, exámenes y eliminación | Crear, editar, buscar, ordenar, exportar, reingresos y relaciones |
| Cálculo | Salario, liquidación final, aguinaldo, vacaciones, preaviso, nóminas, horas, anticipos | Casos límite documentados, IVA/IPS según corresponda, jornalero y mensualizado, borrador/aprobación |
| Informes | Centro de reportes, formatos, REOP/REI y anexo de asistencia | Reconciliar con las planillas exigidas por MTESS/IPS |
| Certificados | Plantillas de generación e impresión | PDF/Word, saltos de página, autocarga y representante legal |
| Utilitarios | Seguridad, auditoría, importaciones, recuperación y administración | Roles, permisos, restauración en entorno aislado, trazabilidad |
| Datos históricos | Expedientes y reactivación/importación | Muestras anónimas y conciliación de totales |

## 5. Correcciones incluidas en la versión 2.6.92
1. Unificación del invalidado de caché para 47 recursos CSS/JS del template base, favicon y logos.
2. Acceso por teclado **Saltar al contenido principal** con foco visible.
3. Aumento de legibilidad de notas, datos base y pie del resumen de cálculo salarial.
4. Pruebas automatizadas nuevas para estos puntos, cobertura CSRF de plantillas críticas, compilación de todas las plantillas y sintaxis de todo el JavaScript.
5. Consulta de asistencia con tiempo máximo (8 segundos) y recuperación manual segura en caso de indisponibilidad, probada con simulación JavaScript.

Estas correcciones son pequeñas y verificables. **No cambian fórmulas, trabajadores, base de datos, permisos, importaciones ni documentos guardados**.

## 6. Matriz mínima de aceptación con pruebas sintéticas
- **Mensualizado:** sueldo completo de 30 días, asistencia real de 27, 216 horas; verificar bruto, IPS, neto y días REOP.
- **Jornalero:** jornal real por jornadas pagadas, sin exigir sueldo mensual y sin usar 26 como jornadas predeterminadas.
- **IPS No / Sí:** filtrar funcionarios en REOP/REI, preservar datos y bloquear el envío de registros no elegibles.
- **Aprobado → rectificación:** crear borrador nuevo, preservar el original y validar el que quede vigente después de aprobar.
- **Borrador → PDF/Word/CSV:** datos y formatos idénticos a los que se guardaron, con original/duplicado cuando corresponde.
- **Historial masivo:** empresas y empleados con miles de registros, paginación y búsqueda por código, CI y nombre.
- **Seguridad:** rol empresa, auxiliar, contador y administrador, tenencia de datos entre estudios y CSRF.
- **UI:** teclado, navegación lateral, color de enlaces activos, tablas, zoom 200%, móviles y pantallas grandes.

## 7. Pendientes que requieren evidencia adicional
Se necesita ejecutar pruebas visuales dentro de una sesión de pruebas autenticada, no sobre registros reales. Se recomienda generar capturas de cada pantalla con datos sintéticos en resoluciones 1440×900, 1024×768 y 390×844, comparar el diseño con un conjunto de referencias y medir LCP/INP/CLS, latencias y tasas de error.

Para el uso cotidiano, registrar cualquier incidente con **módulo, funcionario de prueba, fecha, resultado esperado, resultado obtenido y captura**, evitando compartir CI, RUC u otros datos personales sin necesidad. Un fallo reproducible se corrige con un test de regresión antes de desplegar.
