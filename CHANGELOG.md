## 2.6.48 — Sistema visual corporativo unificado

- Unifica la identidad del espacio autenticado con azul de marca #05256D, azul de acción #1D4ED8, lienzo #F2F5FA, paneles blancos y texto #172033.
- Consolida los estados de la barra lateral dentro del tema global y elimina cinco hojas de correcciones visuales superpuestas.
- Establece la barra lateral como navegación global única para Mantenimientos, Cálculo, Informes, Certificados y Utilitarios; elimina la barra secundaria global redundante.
- Ubica Exámenes Médicos únicamente en Mantenimientos y retira del menú el enlace MTESS/IPS heredado que redirigía al generador documental.
- Homogeneiza cabeceras, paneles, formularios, tablas, botones, estados de foco y ventanas modales en el sistema de componentes.
- Aplica la identidad corporativa al centro laboral autenticado sin alterar la apariencia de herramientas públicas ni documentos impresos.
- Añade documentación del sistema visual y pruebas de regresión para navegación, tokens y rutas.
- No modifica fórmulas, cálculos, modelos, migraciones, permisos, registros ni procesos laborales.

## 2.6.46 — Contrato Individual de Trabajo editable y versionado

- Amplía el contrato con información de las partes y cláusulas sobre funciones, lugar, duración, jornada, remuneración, beneficios, prueba, seguridad social, derechos, domicilio, condiciones especiales, terminación y firmas.
- Separa la plantilla breve del documento completo; el contrato extendido se genera con datos dinámicos, queda editable y se puede imprimir o exportar a Word/PDF.
- Incorpora datos del artículo 46 del Código del Trabajo, incluida la edad calculada desde el legajo cuando existe fecha de nacimiento.
- Añade versiones enlazadas por contrato y estados Borrador, Aprobado, Firmado y Emitido, sin reemplazar documentos anteriores.
- Registrar «Firmado» requiere confirmación expresa y solo guarda el estado de la firma recibida; no ejecuta ni certifica una firma electrónica.
- Evita exclusividad automática y autorización irrestricta de cambios de horario; ajusta la guía de período de prueba a las categorías y máximos del artículo 58 de la Ley N.º 213/93.

## 2.6.45 — Integración de Preaviso con Cálculo

- Conecta la Notificación de Preaviso con los cálculos guardados del funcionario y período, usando consulta autenticada y aislada por empresa.
- Ofrece períodos con cálculo vigente, muestra la base, los días, el importe estimado y el estado, y bloquea Guardar/Imprimir/PDF/Word si no existe un registro utilizable.
- Completa fechas iniciales a partir del plazo seleccionado, permite editarlas y registra en metadatos la trazabilidad del cálculo vinculado.
- Añade mensaje de ausencia de registro, botón Cancelar y validación de servidor para impedir vínculos cruzados, períodos incorrectos o cálculos anulados.
- Permite añadir opcionalmente el motivo comunicado y refleja el cargo del funcionario en la vista previa y en las exportaciones.

## 2.6.44 — Notificación de Preaviso

- Reescribe la Notificación de Preaviso como comunicación formal dirigida al trabajador, con fecha de emisión, período y fecha efectiva claramente expresados.
- Calcula la duración calendario a partir de las fechas de inicio y terminación, y valida fechas coherentes al guardar.
- Incorpora el derecho de licencia para buscar otra ocupación conforme al artículo 89 de la Ley N.º 213/93.
- Añade guía preventiva sobre los plazos del artículo 87 y mantiene la verificación de modalidad contractual, antigüedad y excepciones como control profesional.
- Alinea la fecha superior a la derecha y corrige la denominación del firmante alternativo cuando no figura Representante Legal en la ficha de la empresa.

## 2.6.43 — Coherencia de certificados de trabajo

- Alinea a la derecha la fecha de emisión de Certificado A, Certificado B y Constancia en vista previa, impresión, Word y PDF.
- Unifica el bloque de firma con prioridad al Representante Legal de la ficha; si no está informado, identifica correctamente al firmante alternativo como responsable autorizado.
- Homologa, para constancias al término de la relación, las fechas de ingreso y salida, el trabajo desempeñado y el salario devengado en el último período pagado.
- Evita presumir renuncia voluntaria, buena conducta o causa de salida en los certificados; esos datos no se añaden automáticamente.
- Exige el salario del último período pagado también para el Certificado B al terminar la relación laboral y no lo sustituye por el salario mensual del legajo.

## 2.6.42 — Validación explícita de documentos de vacaciones

- Evita reutilizar días ya usados de un registro anterior como si fueran los días de una nueva solicitud o notificación.
- Las solicitudes de vacaciones comienzan sin copiar automáticamente fechas ni período anual histórico.
- Exige un año válido y una cantidad entera de días entre 1 y 366 al guardar documentos de vacaciones; conserva las fechas y los importes ingresados sin inventar cálculos legales.

## 2.6.41 — Representante Legal también en Certificado B

- Aplica la prioridad del campo Representante Legal a Certificado de Trabajo B cuando la empresa lo tiene registrado.
- Mantiene nombre de empresa, domicilio y teléfono debajo del representante legal.
- Conserva el bloque anterior de empresa, domicilio y teléfono si no hay representante legal cargado.
- Sincroniza vista previa, impresión, Word y PDF y añade pruebas de regresión para ambos formatos exportados.

## 2.6.40 — Prioridad al Representante Legal de la empresa

- Prioriza el campo Representante Legal registrado en la empresa sobre el nombre de firma configurado en Branding.
- Aplica el mismo nombre y el cargo «Representante legal» a la vista previa, impresión, Word y PDF.
- Conserva los datos de Branding o responsable alternativo solo como respaldo cuando el campo legal está vacío.
- Agrega una prueba de regresión que verifica la prioridad del representante ante datos de firma alternativos.

## 2.6.39 — Ajuste fiel del formato de Constancia

- Incluye «C E R T I F I C O:» como encabezado del cuerpo de la Constancia en vista previa, impresión, Word y PDF.
- Evita duplicar la fecha de expedición: queda al cierre en letras, conforme al modelo suministrado.
- Ajusta la firma al ejemplo: «Sr(a). [responsable]», «Responsable» y teléfono, sin repetir el nombre de la empresa debajo de la firma.
- Presenta nacionalidad y estado civil en mayúsculas y conserva la dirección como «ubicada sobre la calle ...».

## 2.6.38 — Modelo de Constancia de Trabajo

- Adapta la Constancia al modelo entregado: identificación, nacionalidad, estado civil, domicilio, empresa y dirección, cargo, ingreso, remuneración y fecha de expedición.
- Genera una fecha formal en letras en el texto de la constancia y conserva una variante de relación laboral finalizada con el último período de pago.
- Añade los datos de quien suscribe y el teléfono en impresión, Word y PDF, con la firma visible en la vista previa.
- Sincroniza la vista previa de Constancia con el generador canónico del servidor y agrega el domicilio al legajo visible en el formulario.
- Incorpora pruebas de regresión del texto y de los formatos descargables.

## 2.6.37 — Criterio de firmas unificado

- Unifica la política de firmas para los modelos, sin pedir firma o recepción del trabajador en certificados de trabajo A/B ni en constancias.
- Utiliza el mismo criterio en vista previa, impresión HTML, Word y PDF.
- Fuerza la visibilidad correcta de la firma simple o doble en la vista previa, aunque las hojas de estilo compartidas cambien.
- Sincroniza en la vista previa los renglones de recepción/autorización de solicitudes y notificaciones que sí los requieren.
- Agrega pruebas de regresión para el esquema de firmas y los cuatro formatos.

## 2.6.36 — Vista previa con datos pendientes

- Evita frases incompletas cuando todavía no se seleccionó una empresa o un funcionario; muestra marcadores claros en los modelos A y B.
- Solo consulta la vista previa canónica del servidor cuando ambos registros están seleccionados.
- Mejora el espaciado y la lectura de los nombres, cargos y datos debajo de las firmas.
- Incorpora comprobaciones de regresión para marcadores y estructura visual.

## 2.6.35 — Modelo B y sincronización real de vista previa

- Adapta el Certificado de Trabajo B al texto solicitado, con fechas/cargo automatizados y el encabezado «C E R T I F I C O:».
- Hace que la vista previa de los certificados A y B consulte el mismo generador del servidor utilizado para emitir, evitando dos plantillas divergentes.
- La previsualización se procesa sin crear borradores ni consumir numeración; permite visualizar el certificado aunque el salario del último período todavía esté pendiente de completar.
- Desactiva la caché del HTML del generador y mantiene la versión del recurso JavaScript para reducir la posibilidad de mostrar la plantilla anterior.
- Añade pruebas de regresión para el modelo B, el endpoint de vista previa y las cabeceras anti-caché.

## 2.6.34 — Sincronización de vista previa del Certificado A

- Actualiza el texto generado por el navegador para que coincida con el modelo automatizado del Certificado A en Word y PDF.
- Centra la fecha y el encabezado «C E R T I F I C O:» en la vista previa.
- Versiona la URL de app.js con la versión del sistema para evitar que el navegador siga usando el JavaScript anterior en caché.
- Actualiza el identificador de caché del CSS del certificado y agrega prueba de regresión para el modelo y el recurso versionado.

## 2.6.33 — Modelo automatizado de Certificado de Trabajo A

- Adapta el texto del Certificado A al modelo solicitado, integrando automáticamente nombre, documento, fecha de ingreso, fecha de conclusión, cargo y fecha/lugar de emisión.
- Conserva la indicación del salario devengado durante el último período de pago para certificados por terminación laboral.
- Centra el encabezado «C E R T I F I C O:» y la fecha en mayúsculas para este modelo, sin alterar el formato de los demás documentos.
- Mantiene sin cambios los modelos B, constancias, contratos y demás documentos.

## 2.6.31 — Flujo asistido de liquidación salarial REOP

- Incorpora en el recibo de Liquidación de Salarios un panel REOP vinculado al cálculo de origen.
- Genera un snapshot de los importes guardados con hash SHA-256, validaciones locales y un Excel de apoyo claramente identificado como no oficial.
- Permite aprobación interna, seguimiento de los estados Presentado/Aceptado/Observado/Rechazado, registro de referencia externa y archivo del comprobante PDF/PNG/JPG que el usuario obtiene de REOP.
- Conserva intentos separados, errores, responsable y auditoría; limita acciones de presentación a administrador/contador y aplica doble aprobación cuando está activada.
- Añade migración para asociar el lote a su cálculo y pruebas de preparación, validación y archivo de comprobantes.
- El envío automático directo sigue deshabilitado: no se activará sin especificación técnica y autorización oficial de interoperabilidad del MTESS. El Excel generado es un documento de apoyo y no sustituye la plantilla oficial de importación de REOP.

## 2.6.32 — Catálogo lateral de certificados ajustado

- Actualiza el listado lateral con los diez documentos solicitados, en el orden y con las etiquetas especificadas.
- Mantiene intactos el catálogo general, las reglas de generación, las automatizaciones, el formulario dinámico y la vista previa.

## 2.6.30 — Liquidación salarial integrada en Centro de Informes

- Reutiliza la entrada existente de Liquidación de Salarios dentro del catálogo Centro de Informes para abrir el recibo detallado.
- Elimina la tarjeta destacada y los enlaces laterales/secundarios que duplicaban el mismo submódulo.
- Conserva filtros, historial, PDF A4, impresión, auditoría y controles de acceso de la implementación existente.
- Mantiene la API del catálogo y la consulta de datos históricos; la ruta de acceso anterior redirige al recibo detallado y conserva los filtros compatibles.

## 2.6.29 — Liquidación de Salarios dentro de Informes

- Añade un submódulo dedicado en `/app/reports/liquidaciones-salarios`, enlazado desde la navegación de Informes.
- Consulta los cálculos salariales persistidos del módulo Cálculo (clásico y motor profesional), con filtros de empresa, funcionario, período, estado y búsqueda.
- Emite una vista de recibo interno con datos patronales y del funcionario, haberes, descuentos, neto, observaciones, validaciones pendientes y espacio de firmas.
- Agrega exportación a PDF A4, impresión desde navegador y registro de cada reimpresión en Auditoría.
- Muestra cálculos anteriores para el mismo funcionario y período como versiones históricas; conserva los importes del registro de origen sin volver a calcularlos.
- Refuerza el aislamiento por empresa y evita la emisión o reimpresión desde registros anulados. El recibo se identifica expresamente como documento interno, no como formulario oficial MTESS/IPS.
- No agrega tablas ni migraciones; utiliza los registros de cálculo ya existentes.

## 2.6.28 — Visibilidad del Centro de Informes

- Hace visible el Centro de Informes en el menú lateral para el perfil empresa, que antes no veía el grupo Informes.
- Conserva ocultos para el perfil empresa los accesos de Cumplimiento REI/REOP y Auditoría.
- Mantiene la protección del listado de exámenes médicos; el catálogo de empresa muestra únicamente los 34 informes permitidos.
- Añade prueba de navegación y catálogo para perfil empresa.

## 2.6.27 — Integridad de informes y exportaciones

- Incluye en los informes los cálculos persistidos por el motor profesional (`suite_salary`, `suite_settlement`, `suite_aguinaldo` y `suite_vacation`) y los presenta con etiquetas legibles.
- Corrige los orígenes de datos: planilla de horas usa horas registradas en las nóminas; la segunda vista conserva las operaciones horarias.
- Adapta las opciones de ordenamiento a los campos soportados por cada informe.
- Blinda la exportación XLSX contra la interpretación de texto ingresado por usuarios como fórmulas de hoja de cálculo.
- Escapa el nombre patronal en la cabecera PDF y amplía la búsqueda de empresas al código y rubro.
- Añade pruebas para cálculos del motor profesional y cadenas potencialmente ejecutables en XLSX.

## 2.6.26 — Centro de Informes

- Incorpora el catálogo navegable de los 35 submódulos de Informes, agrupados por liquidaciones/remuneraciones, legajos/empresas, IPS/cumplimiento, vacaciones/aguinaldo, trámites/seguimiento, salud ocupacional y registros anuales.
- Añade consultas paginadas en base de datos, búsqueda, filtros por empresa/funcionario/estado/año/periodo y ordenamiento por campos permitidos.
- Añade exportaciones PDF, Excel (.xlsx) y CSV con encabezados, nombre de archivo seguro y registro de auditoría para descargas.
- Publica API de catálogo, consulta paginada y exportación: `/api/reports/catalog`, `/api/reports/{report_key}` y `/api/reports/{report_key}/export`.
- Las consultas se restringen a las empresas autorizadas del usuario; el reporte de exámenes médicos se reserva a los roles de estudio autorizados.
- Los informes usan registros reales existentes, sin fabricar nóminas ni expedientes de prueba en producción. Los preimpresos IPS/MTESS se identifican como preparatorios y no como formularios oficiales.
- No se agregan tablas ni migraciones. Se incorporan pruebas del catálogo completo, APIs, vistas y exportaciones.

# Registro de cambios

## 2.6.25 — Revisión de causales y antigüedad en liquidación final

- Diferencia ocho causales/supuestos de egreso: despido sin causa, renuncia, despido con causa invocada, retiro justificado, fin de contrato a plazo/obra, mutuo consentimiento, fallecimiento y otros.
- Distingue el retiro justificado imputable al empleador de la causa alegada por el empleador; el primero calcula un escenario condicionado y advierte que exige acreditar los hechos.
- Agrega la antigüedad exacta en años, meses y días, junto con los días calendario del vínculo.
- Mejora advertencias para estabilidad de diez años, protecciones especiales, contratos no indefinidos y período de prueba sin confirmar.
- Conserva registros existentes, estados, auditoría, API REST, historial y exportación PDF/CSV; no se agregan migraciones.

## 2.6.24 — Color de marca y logo original en la barra lateral

- Establece #05256d como fondo de la barra lateral, también en modo móvil, y adapta los colores de texto, grupos, indicadores, estados hover y foco.
- Sustituye el logo blanco reconstruido por una versión blanca derivada del mismo archivo horizontal original usado en el encabezado; mantiene geometría, proporciones y contornos sin redibujar el símbolo ni las letras.
- Añade prueba de regresión para el color exacto, la carga de la hoja final y el uso del wordmark original.

## 2.6.23 — Integración de horas extras dentro de Salario

- Integra en Salario el adicional por trabajo nocturno ordinario del 30 %, las horas extraordinarias diurnas (mínimo 50 %), las extraordinarias nocturnas (100 %) y el adicional de feriado (100 %).
- Distingue el adicional nocturno ordinario (solo el 30 % incremental) del pago total de horas extraordinarias diurnas (1,5 × base) y nocturnas (2 × base); el adicional de feriado se calcula sobre la hora diurna, suponiendo que el salario mensual ya cubre la remuneración ordinaria.
- Propone bases diurna/nocturna conforme a la escala general seleccionada, permite bases manuales revisadas para categorías especiales y presenta una vista previa accesible actualizada al cambiar los campos.
- Incorpora los importes calculados a los haberes brutos y la base de aporte propuesta; el motor valida cantidades, decimales, combinación con importe manual y valores negativos.
- Añade referencias al Código del Trabajo, art. 234 y a la guía MTESS para revisión de conceptos y evita aplicar el adicional nocturno del 30 % cuando la escala elegida ya es nocturna.
- Advierte si hay feriados cargados junto con otras categorías horarias y recuerda verificar solapamientos y recargos acumulables.
- Retira “Carga de hora” de la navegación principal y contextual de Cálculo. La ruta y los registros existentes se conservan para compatibilidad.
- Añade pruebas para cálculos, base IPS, alternativa manual, conflictos y entradas inválidas.

## 2.6.22 — Control de salario mínimo y asignación familiar en Salario

- Agrega escalas de salario mínimo con vigencia para julio de 2025 y julio de 2026, a partir de publicaciones oficiales del MTESS.
- Advierte si la base mensual queda por debajo de la escala seleccionada; el cálculo no se bloquea ni declara automáticamente una infracción.
- Permite indicar actividad o categoría con mínimo diferenciado y requiere ingresar su valor mensual vigente, sin adivinarlo.
- Calcula la asignación familiar por hijo con derecho documentado, confirma sus requisitos mediante el usuario y aplica el límite de dos salarios mínimos.
- La asignación familiar continúa fuera de la base de aporte IPS. Se mantiene el ingreso manual como excepción trazable con advertencia.
- Añade pruebas de vigencias, mínimos especiales, documentación, límite del artículo 263 y base IPS.


## 2.6.21 — Depuración de Cálculo e inicio de modernización de Salario

- La navegación lateral y contextual de Cálculo se limita a los 11 submódulos definidos por el usuario.
- Se quitan del acceso principal los accesos auxiliares a cobertura de períodos, liquidaciones mensuales y calculadoras de horas, aguinaldo y vacaciones que no forman parte de la lista.
- Salario abre el motor profesional existente, con historial salarial, desglose de haberes y descuentos, control de IPS y emisión de documentos.
- Los haberes adicionales del salario quedan visibles al entrar; el importe de horas extras indica cómo relacionarlo con Carga de hora y evita su duplicación.
- Se conservan rutas de compatibilidad, motores compartidos y registros históricos; esta depuración no elimina información ni tablas.


## 2.6.20 — Estructura unificada del módulo Cálculo

- Ordena la navegación principal y la navegación contextual alrededor de los 11 submódulos solicitados.
- Incorpora un panel de entrada con acceso directo a los módulos operativos existentes de liquidación, carga horaria, anticipos, novedades disciplinarias, telegramas e histórico del funcionario.
- Mantiene disponibles las calculadoras auxiliares de horas/recargos, aguinaldo y vacaciones, además de las liquidaciones mensuales y la cobertura de períodos.
- Integra el acceso a Examen Médico con el módulo existente de Mantenimientos; no crea un registro médico paralelo.
- Esta fase organiza rutas y navegación; las mejoras funcionales y legales se abordarán submódulo por submódulo.

## 2.6.16 — Corregir el estado de Inicio al entrar en subapartados

- Corrige la causa de la regla que no surtía efecto: el enlace Inicio solo tenía la clase `active` en la ruta exacta `/app`, no cuando se visitaba Empresas, Secciones o Funcionarios.
- Añade el estado de contexto `home-in-section-context` cuando la ruta empieza por `/app/`.
- El texto Inicio se fuerza a azul `#2563EB` y visibilidad completa cuando está activo o el usuario está dentro de un subapartado, pero el cursor no está encima.
- No se modifica el fondo, el icono, los estilos hover ni ningún otro enlace. El logo se conserva.

## 2.6.15 — Corrección final de la etiqueta Inicio en plantilla

- Asigna una clase propia `workspace-home-label` al texto `Inicio`, sin cambiar el ícono ni la ruta del enlace.
- Aplica la corrección en el bloque de estilos de `base.html`, después de todas las hojas CSS externas, para evitar que reglas anteriores lo sobreescriban.
- Solo afecta a `/app` cuando está activo y el cursor no está encima: azul `#2563EB`, relleno de texto azul, opacidad 1, visibilidad visible y filtros/mezclas neutralizados.
- No altera estados hover, normales, otros enlaces ni el logo.

## 2.6.14 — Corregir la regla fuente del color de Inicio

- Modifica el bloque original de `sidebar-contrast-265.css` que aplicaba `color:#F1F5F9!important` a todos los enlaces de inicio.
- Conserva tamaño y peso tipográfico en el selector general, pero limita el gris claro a `.workspace-home-link:not(.active):not(:hover)`.
- El enlace activo y sin hover ya no recibe el color pálido de esa regla; la etiqueta específica de Inicio aplica `#2563EB` con visibilidad completa.
- No altera hover, estilos de los demás enlaces ni el logo.
- Actualiza la referencia cache-busting y añade pruebas de regresión.

## 2.6.13 — Refuerzo final del texto activo de Inicio

- Añade una hoja CSS de carga final con alta especificidad para el texto de `Inicio` únicamente cuando el enlace `href="/app"` está activo y no hay hover.
- Fuerza el texto a azul `#2563EB`, el relleno del texto para WebKit, opacidad completa y visibilidad, neutralizando filtros y mezclas translúcidas en la propia etiqueta.
- No toca el icono, el fondo, el enlace de Administración general, los estados normales, los estados hover ni el logo.
- Incluye una prueba para asegurar que el archivo se carga después de las reglas existentes.

## 2.6.12 — Selector limitado al botón Inicio

- Limita las reglas de color y visibilidad del texto a `a.workspace-home-link[href="/app"]`, el botón Inicio del espacio laboral.
- Evita alterar el enlace independiente de Administración general, que usa una clase compartida.
- Conserva `color`, `-webkit-text-fill-color`, `opacity`, `visibility` y `filter` forzados en el estado activo sin hover.
- No modifica los estados hover, normal ni el logo.

## 2.6.11 — Visibilidad forzada del texto Inicio

- Refuerza únicamente la etiqueta de texto dentro del botón Inicio cuando está activo y no está bajo el cursor.
- Usa `color` y `-webkit-text-fill-color` en `#2563EB`, `opacity: 1`, `visibility: visible` y `filter: none` con `!important`.
- No cambia el ícono, el fondo activo, otros enlaces, estados inactivos ni el hover.
- Actualiza la versión, el cache-busting de CSS y las pruebas de regresión.

## 2.6.10 — Corrección limitada al texto de Inicio

- Mantiene el fondo blanco del botón Inicio cuando está activo, pero fuerza únicamente el texto de su etiqueta a azul `#2563EB`.
- El selector excluye el estado hover y no cambia el color de estados inactivos ni del ícono de Inicio.
- No modifica las reglas de los subapartados ni sus colores de hover.
- Conserva el logo actual y actualiza el cache-busting de la hoja de estilos.
- Añade pruebas específicas para asegurar que la regla solo afecta la etiqueta de Inicio.

## 2.6.9 — Contraste de enlaces activos en la barra lateral

- Los enlaces activos de la sidebar, incluido Inicio, usan texto azul visible `#2563EB` sobre una tarjeta blanca cuando no están bajo el cursor.
- Los enlaces inactivos y los estados hover conservan los colores existentes; la hoja nueva no define reglas `:hover`.
- Mantiene el logo horizontal incorporado en 2.6.7 y la corrección de Inicio revertida/restaurada visualmente según esta solicitud.
- Añade pruebas de regresión para el orden de carga y la diferencia entre estado activo y hover.

## 2.6.8 — Restaurar el color original de Inicio

- Revierte exclusivamente la regla introducida en 2.6.7 que forzaba el texto de Inicio a azul cuando estaba seleccionado y el cursor no estaba encima.
- Conserva íntegramente el logo horizontal nuevo en el encabezado, la sidebar, las pantallas de acceso y el sitio público.
- No agrega estilos para hover ni cambia el resto de la paleta o navegación.
- Actualiza las pruebas de regresión para exigir el color original de Inicio y seguir verificando la marca nueva.

## 2.6.7 — Ajuste de Inicio y actualización de marca

- Corrige el color del texto **Inicio** cuando la opción está seleccionada y el cursor no está encima; el estado hover existente se conserva sin cambios.
- Sustituye el logo anterior por el nuevo logo horizontal proporcionado para el encabezado, el pie de la barra lateral y las pantallas de acceso, recuperación y segundo factor.
- Añade reglas responsive y una base blanca discreta para mantener legible el logo sobre el fondo oscuro de la sidebar.
- No modifica rutas, permisos, datos, API ni lógica laboral.

### Validación
- Incorpora pruebas de regresión para el color de Inicio y el uso coherente de la nueva marca.

## 2.6.6 — Módulo Secciones dentro de Mantenimientos

- Añade una pantalla de gestión dedicada en `/app/sections`, accesible como subapartado de **Mantenimientos** junto a Empresas y Funcionarios.
- Incorpora filtros por código y nombre, selección de empresa, visualización de secciones activas/inactivas y recuento de funcionarios vinculados.
- Permite crear, editar, desactivar y reactivar secciones; la fecha y el usuario de actualización se generan en el backend y se muestran como auditoría de solo lectura.
- Añade carga opcional y transaccional de cuatro ejemplos de prueba para empresas que aún no tienen secciones.
- Mantiene la API existente, el vínculo `Employee.section_id`, el aislamiento por empresa y los controles de rol; la desactivación conserva las referencias históricas.
- Conserva FastAPI/Jinja2, SQLAlchemy y la configuración de despliegue de Render; no crea una aplicación paralela ni requiere una tabla nueva.

### Validación
- Añade pruebas para la navegación, los filtros del módulo, los metadatos de auditoría, la desactivación segura y el registro de la ruta.

## 2.6.5 — Corrección de contraste en la sidebar

- Corrige exclusivamente la barra lateral izquierda: textos de subapartados más claros, encabezados de categorías con mayor contraste y espaciado legible.
- Destaca el subapartado activo con azul más visible, texto blanco y un indicador lateral claro; el hover también mantiene alto contraste.
- Mejora la visibilidad de numeración de grupos, flechas, contador de notificaciones y foco de teclado.
- Conserva el resto de la interfaz y los enlaces existentes; no cambia rutas, permisos, cálculos ni datos.

### Validación
- Añade una prueba para comprobar que la hoja de contraste se carga después del tema global y que define estados normal, hover y activo.

## 2.6.4 — Sistema visual global y navegación modular

- Extiende la paleta azul/blanco/gris, tarjetas, espaciado, tipografía, paneles y feedback de estado a las pantallas autenticadas de los distintos módulos.
- Añade navegación secundaria reutilizable para Cálculo, Informes, Certificados, Utilitarios y mantenimientos administrativos.
- Incorpora macros Jinja reutilizables para pestañas de módulo, paneles seccionados y ayuda inline.
- Añade búsqueda inmediata y ordenación por encabezado a tablas de listados con tres o más filas, manteniendo la búsqueda dentro de los resultados ya cargados.
- Unifica estilos de formularios, validación inline accesible, controles táctiles, tablas con encabezados fijos y filas alternadas, modales y mensajes de éxito/error/advertencia.
- Refuerza responsividad, escalado tipográfico, foco por teclado y compatibilidad con movimiento reducido.
- Se limita al espacio autenticado y excluye páginas públicas, impresión y algunas tablas especiales; no cambia cálculos, permisos, datos persistidos ni rutas de negocio.
- Documenta el sistema en `docs/UI_SYSTEM_V264.md`. Se usa FastAPI + Jinja2 + HTML/CSS/JavaScript, sin añadir React ni Vue.

### Validación
- Se agregan pruebas de regresión para el CSS global, macros Jinja y navegación en los principales módulos.
- La integración requiere la suite completa de CI y un despliegue exitoso en Render.

# Registro de cambios
## 2.6.3 — Mejora de usabilidad en Empresas y Funcionarios

- Agrega navegación secundaria para cambiar entre Empresas y Funcionarios y pestañas contextuales dentro de los expedientes.
- Mejora el directorio de empresas con tarjetas más legibles, filtros rápidos por estado y logo, búsqueda inmediata y ordenación por nombre, código o cantidad de funcionarios.
- Mejora el directorio de funcionarios con filtros rápidos por estado, aportes IPS y sección, además de ordenación por nombre, legajo, empresa, sección, ingreso y salario.
- Actualiza en vivo los contadores de resultados sin recargar la página; mantiene los filtros por empresa, sección, ciudad y departamento del servidor.
- Añade mensajes de validación junto al campo después de interactuar con formularios, con estados accesibles para lectores de pantalla.
- Refuerza espacios, tarjetas, bordes, sombras suaves, estados de foco y adaptación móvil usando la paleta azul/blanco vigente.
- No cambia rutas de negocio, permisos, lógica de cálculo, datos persistidos ni estructura de la base de datos.

### Validación
- Nuevas pruebas de regresión para navegación secundaria, filtros, ordenación, assets y pestañas contextuales.
- La publicación requiere suite completa de CI y confirmación del despliegue exitoso en Render.

## 2.6.2 — Renovación visual azul y accesible

- Unifica la paleta del espacio autenticado en azul marino `#0D1B2A`, azul medio `#1E40AF`, azul de acción `#2563EB`, fondo `#F9FAFB`, superficies blancas y texto `#111827`.
- Consolida la sidebar oscura y mantiene la navegación activa, los grupos y sus estados legibles en escritorio y móvil.
- Unifica botones, paneles, tarjetas, tablas, formularios y modales con bordes neutros, radios consistentes y sombras discretas.
- Refuerza el foco visible para teclado, contraste, placeholders y mensajes secundarios.
- Mantiene Inter como tipografía principal con familias de respaldo del sistema.
- Carga los estilos desde una hoja de diseño global para facilitar ajustes futuros sin reescribir cada módulo.


## 2.6.1 — Mantenimiento de funcionarios y legajos

- Código Legajo numérico único dentro de cada empresa, con asignación retroactiva a los funcionarios existentes.
- Búsqueda y autocompletado por empresa + legajo; filtros por legajo, nombre, cédula, cargo, empresa, sección y estado.
- Nueva entidad Secciones, separada de las sucursales físicas, con creación, edición y desactivación lógica.
- Integración de nacionalidad, estado civil, categoría laboral, jornada, turno, horas diarias/semanales y número IPS mediante el perfil complementario existente.
- Registro del usuario y fecha de última modificación.
- Endpoints REST autenticados para consulta, alta, edición y archivo lógico de funcionarios y secciones; política RLS por estudio para la nueva tabla.
- Importaciones nuevas asignan Código Legajo. Las modificaciones salariales continúan sujetas a aprobación.
- La versión 2.6.1 se integró en main y fue desplegada en Render el 27-10-2026 tras superar la suite de CI.


## 2.6.0 — 27-10-2026

### Mantenimientos · formulario principal de Empresas
- Se incorpora el Código Empresa numérico, único por estudio, con asignación retroactiva a empresas existentes.
- Se amplía la ficha con propietario, C.I. del representante, sector/lugar de trabajo, actividad económica, contacto y datos patronales.
- Ciudad y departamento se eligen mediante listas paraguayas: 18 departamentos y 262 municipios, contrastados con el portal público de Municipios del Paraguay (https://municipios.gov.py/municipios/).
- La búsqueda admite código, nombre o RUC y filtros por ciudad y departamento.
- La carga por código recupera la empresa existente mediante API autenticada.
- Se agregan endpoints JSON de consulta, creación, actualización y archivado con validaciones de datos, permisos, CSRF y aislamiento por estudio.
- El botón Eliminar archiva el registro para conservar nóminas, cálculos, certificados, trámites y auditoría; el registro puede volver a mostrarse y restaurarse.
- Se completan las empresas sintéticas del seed de desarrollo con códigos numéricos, RUC de prueba módulo 11, registros patronales numéricos y perfil de cumplimiento; el seed no se ejecuta para insertar estas empresas en producción.

### Validación
- Se agregan pruebas para el formulario, catálogo paraguayo, RUC módulo 11, consulta por código y operaciones CRUD de la API.
- La publicación requiere CI en verde y confirmación del despliegue de Render.


## 2.5.5 — 27-10-2026

### Autorización por rol
- Se restringió la ruta interna de cálculos laborales a administrador, contador y auxiliar.
- Se restringió el historial y la pantalla del asistente de IA a los perfiles operativos autorizados; no basta con ocultar el enlace en el menú.
- Se limitó la pantalla de parámetros administrativos al rol administrador.
- Se añadieron pruebas de regresión para confirmar que abogado y empleador reciben denegación al intentar acceder por URL, y que el contador mantiene acceso a sus herramientas.

### Validación
- La publicación depende de que CI pase con la suite completa y se confirme el nuevo despliegue de Render.
- Se mantiene el requisito de separar los roles PostgreSQL antes de certificar el aislamiento RLS entre estudios.

## 2.5.4 — 26-10-2026

### Flujos de trabajo por perfil
- Se agregó un espacio funcional para el rol `abogado`, disponible al crear usuarios, con orientación jurídica, consulta de expedientes, documentos laborales y acceso a solicitudes asignadas.
- La bandeja de solicitudes ahora se filtra en el servidor por empresa, estado, tipo de trámite, responsable y vencimiento.
- El abogado queda limitado a solicitudes asignadas: no puede abrir trámites de otro profesional por URL, dejar comentarios o adjuntos sobre casos no asignados ni transferir una asignación.
- Las aprobaciones y rechazos siguen reservados a administrador y contador; el abogado puede registrar seguimiento y respuestas en los casos a su cargo.
- La agenda laboral es visible para el empleador en modo consulta, mientras que alta y actualización de vencimientos quedan reservadas al equipo del estudio.
- Se ajustaron las pantallas de empresa, funcionario, informe, cumplimiento y certificado oficial para no ofrecer botones de edición que el perfil no puede ejecutar.
- Se añadieron pruebas de recorrido para abogado y empleador, incluyendo cola asignada, lecturas rechazadas en casos ajenos y límites de permisos.

### Validación
- La publicación de esta versión queda supeditada a la suite completa de CI y a la verificación del despliegue de Render.
- La configuración PostgreSQL de RLS sigue documentada como pendiente de separar rol de aplicación y rol de migraciones; no debe inferirse que este cambio funcional completa ese trabajo.

## 2.5.3 — 26-10-2026

### Seguridad multiempresa
- Se añadieron políticas RLS para `studios`, `users`, `user_security`, `password_reset_tokens` y `activation_requests`.
- Se incorporó `digit_current_user_id()` con `search_path = pg_catalog, pg_temp` y migración Alembic `0014_tenant_user_context`.
- La sesión firmada establece primero el ID del usuario; después de leer el registro canónico se establece el estudio y el rol. Esto permite la consulta inicial segura cuando el usuario de ejecución no es propietario de las tablas.
- Se añadieron pruebas de regresión para el contexto de sesión y las políticas de las tablas sensibles.
- El arranque y `/health/ready` informan si el rol PostgreSQL de ejecución tiene `BYPASSRLS`, es superusuario o es propietario de tablas.

### Límites de publicación
- La separación real de roles PostgreSQL sigue pendiente: el rol actual `digit_app` es propietario de la mayoría de las tablas y `RLS_FORCE` permanece desactivado deliberadamente. Las políticas añadidas no deben interpretarse como aislamiento RLS efectivo hasta que la conexión de ejecución use un rol no propietario y sin `BYPASSRLS`.
- El almacenamiento S3 compatible, SMTP y una restauración probada desde copias externas requieren credenciales y servicios configurados.

## 2.5.2 — 26-10-2026

### Seguridad
- Se fijó el `search_path` de las funciones PostgreSQL de contexto multiempresa.
- Se agregó una prueba de regresión para impedir que el SQL del arranque pierda sus delimitadores.
- Se retiraron los permisos de `anon` y `authenticated` sobre la tabla interna `alembic_version` en la base productiva; el usuario de aplicación conserva su acceso.

### Rendimiento
- Se agregaron índices a las claves foráneas `employees.branch_id` y `request_workflows.approved_by_user_id`.

### Validación de publicación
- La suite completa de CI y las comprobaciones de arranque pasaron.
- Render confirmó el despliegue activo.
- Supabase confirmó Alembic `0013_tenant_function_search_path`, `search_path` restringido en las dos funciones y cero avisos activos en el asesor de seguridad.

### Requisitos operativos aún pendientes
- Configurar almacenamiento persistente S3 compatible.
- Configurar y probar la entrega SMTP.
- Separar el rol de migraciones del rol de aplicación antes de forzar RLS.
- Ejecutar una prueba formal de aislamiento entre empresas y verificar la restauración desde una copia externa.
