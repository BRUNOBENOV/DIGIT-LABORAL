# Digit Laboral 2.7.4

## Unificación de remuneraciones históricas con el sistema actual

- Los movimientos históricos MOV se muestran en **Informes → Liquidación de Salarios** junto a cálculos actuales, con filtros comunes por empresa, funcionario, período, estado y origen.
- Cálculo → Salario e Histórico del funcionario reutilizan la trazabilidad existente; el menú y el listado MOV independientes fueron retirados.
- La importación del archivo MOV se inicia desde el informe salarial existente y realiza una conciliación por CODEMP y CODTRA antes de permitir guardar antecedentes.
- Los importes SALARI originales conservan su identidad y precisión; los movimientos históricos no se confunden con recibos, pagos confirmados, nóminas cerradas, salarios contractuales ni comunicaciones REI/REOP.
- Pruebas agregadas para la unión paginada, controles de empresa, deduplicación y lectura por origen.

# Digit Laboral 2.7.3

## Movimientos salariales históricos MOV

- Cálculo → Historial salarial MOV incorpora un flujo autenticado para importar BASE DE DATOS MOV.csv.xlsx con previsualización, vinculación estricta CODEMP/CODTRA y bloqueo de filas ambiguas o repetidas.
- Conserva los 29 campos originales, el mes, la fila fuente, su SHA-256 y las advertencias de calendario; deja consultar el historial paginado por códigos y período.
- Registra antecedentes de solo lectura sin crear nóminas, recibos, salarios contractuales ni presentaciones oficiales, y mantiene trazabilidad del usuario que importa.
- El contenido de los archivos fuente permanece fuera del repositorio: debe subirse desde la cuenta autorizada en la aplicación.

# Digit Laboral 2.6.80

Plataforma de gestión y cumplimiento laboral para estudios contables paraguayos.

## Novedades de la versión 2.6.80

- Funcionarios → Acciones → Eliminar definitivamente permite borrar un legajo y sus datos propios de ficha, con revisión previa, motivo y confirmación escrita. Disponible para administradores y contadores, también desde el expediente.
- Incluye los avisos automáticos de entrada REOP/REI que siguen en borrador y no tienen aprobación, lote, exportación ni constancia. Las comunicaciones manuales, revisadas o utilizadas permanecen como bloqueos.
- Comprueba todas las relaciones de empleado registradas en los modelos. Nóminas, cálculos de cualquier estado, documentos, egresos y demás operaciones vinculadas bloquean el borrado con un detalle de cantidades. No se desvinculan ni se borran silenciosamente esos registros.
- La revisión firmada vence a los 15 minutos y se invalida si cambia el legajo. El servidor vuelve a comprobar permisos y vínculos, bloquea la fila y elimina ficha e historial propio junto con la auditoría en una única transacción. Conserva los filtros del listado. Sin migraciones ni dependencias nuevas.

## Novedades de la versión 2.6.79

- Corrige el bloqueo del canal de desconexión después de formularios POST protegidos por CSRF, que podía detener las descargas en streaming y dejar sin respuesta al servicio.
- La exportación salarial REOP/REI entrega el archivo ya generado con longitud explícita. Conserva los 32 encabezados REOP, el TXT REI, la asistencia guardada, las exclusiones y la auditoría del lote.
- Permite descargar y reintentar desde la misma vista previa, con mensajes claros ante errores o sesión vencida y sin dejar el botón permanentemente deshabilitado. No recalcula ni modifica registros salariales. Sin migraciones ni nuevas dependencias.

## Novedades de la versión 2.6.78

- Cálculo → Preaviso carga los días desde el ingreso del funcionario y una fecha de referencia completa. Aplicar muestra el plazo y el importe; cambiar la fecha actualiza la propuesta con una consulta al servidor. El promedio sugerido del legajo permanece editable y se identifica como una base que requiere revisión.
- Los días son de solo lectura. Un administrador puede registrar una excepción con fundamento obligatorio; quedan registrados los días automáticos, la excepción y su autor. Guardar y aprobar verifican las fuentes y los importes sin modificar cálculos históricos.
- La migración Alembic `0021_notice_rules` instala `notice_rule_sets` y `notice_rule_bands`, con vigencia, fuente legal, límites inclusivos por aniversario y RLS de lectura. La inicialización de una base nueva también instala los datos. No se agregan dependencias de producción.
- Configuración legal: conservar las versiones utilizadas. Una modificación normativa debe incorporarse mediante una migración con un código nuevo y fechas de vigencia sin superposición; no reemplazar el archivo publicado `app/data/notice_rules.json` ni sobrescribir escalas históricas. La propuesta privada consulta la versión vigente en la base; los calculadores puros conservan la referencia publicada y comparten el mismo motor de aniversarios.
- Los clientes antiguos que envían solo `AAAA-MM` usan explícitamente el último día del mes. Una referencia inválida, un ingreso posterior o una escala ausente bloquean el guardado con un mensaje; no producen un plazo de cero. La referencia no inicia un preaviso, registra un egreso ni determina por sí sola su procedencia.

## Novedades de la versión 2.6.77

- Comparte la asistencia del cálculo aprobado entre Salario, Liquidación de haberes, el recibo y las exportaciones REOP/REI. La liquidación carga jornadas, horas ordinarias y forma de pago disponibles; permite una modificación explícita y conserva la referencia al origen.
- Conserva una aprobación vigente mientras se prepara otro borrador. Una anulación posterior bloquea las aprobaciones anteriores. La exportación muestra jornadas, horas, legajos reales, incluidos, excluidos y borradores en preparación.
- El origen automático usa aprobados para un legajo y cuando cubren todos los funcionarios de una nómina cerrada; mantiene el origen explícito y la nómina completa en los demás casos. Guardar jornadas REI conserva horas y pago ya registrados para REOP.
- Verifica empresa, funcionario, mes y vigencia del origen al calcular, guardar y aprobar. Sin migraciones ni dependencias nuevas de producción.

## Novedades de la versión 2.6.76

- Simplifica Notificación de Preaviso con datos del legajo en un resumen, fechas a la vista y edición de datos, número, observaciones y criterios de revisión en desplegables. Las acciones acompañan la vista previa en escritorio y se reorganizan en pantallas pequeñas.
- Cuando falta un cálculo guardado, permite abrir Cálculo → Preaviso con la empresa y el funcionario seleccionados y actualizar los registros al volver. Respeta los permisos del usuario y mantiene bloqueada la emisión hasta vincular un cálculo vigente con fechas válidas.
- Conserva la precarga, la edición solo del documento y el modelo de carta en Word, PDF e impresión. No incorpora las notas internas del cálculo a las observaciones de la carta. Sin migraciones ni nuevas dependencias de producción.

## Novedades de la versión 2.6.68

- La Notificación de Preaviso usa el modelo de carta solicitado: número, ciudad y fecha, destinatario, comunicación de salida, licencia para buscar empleo y cierre con una pareja de firmas.
- Precarga empresa, funcionario y firmante desde los registros. Consulta el cálculo de preaviso guardado y sus fechas; cuando falta la fecha final, propone una a partir del inicio y el plazo, con indicación para revisión.
- Mantiene el mismo texto en vista previa, impresión, Word y PDF. Conserva los documentos históricos y exige un cálculo vigente del mismo funcionario y empresa para emitir. Sin migraciones ni nuevas dependencias de producción.

## Novedades de la versión 2.6.64

- Precarga contratos y certificados con los datos disponibles del legajo: identidad, cargo, ingreso, salario vigente a la fecha de emisión, sección, datos personales y horario registrado. Cada dato sugerido se identifica y puede editarse solo para ese documento.
- Señala los datos faltantes y bloquea generar, aprobar o emitir contratos incompletos. No deduce funciones, descansos ni medios de pago ausentes del legajo.
- Actualiza la vista previa, conserva los documentos guardados y evita mezclar datos al cambiar de funcionario o recibir respuestas fuera de orden. Sin migraciones ni dependencias nuevas.

## Novedades de la versión 2.6.63

- Detecta estabilidad por antigüedad y propone automáticamente el escenario doble para despido sin causa desde diez años, sujeto a modalidad, prueba y otras protecciones. El subtotal permanece parcial hasta documentar y confirmar su procedencia.
- Separa la detección del art. 94 de los hechos que habilitan la doble de los arts. 96–99. La causa justa judicial se registra con sentencia adjunta, fecha y referencia; no activa indemnización ni preaviso por despido injustificado.
- Conserva trazabilidad del respaldo, alcance por empresa y funcionario, aprobación protegida y reimpresiones originales.

## Novedades de la versión 2.6.62

- Calcula la remuneración anual para aguinaldo desde las nóminas cerradas del año de egreso. Precarga el monto, muestra el aguinaldo devengado y permite desbloquear el ingreso manual.
- Presenta fuentes, conceptos y cobertura por mes. Las sumas incompletas quedan como parciales; los períodos sin respaldo y los otros ingresos sin clasificación requieren revisión.
- Mantiene el ingreso manual para históricos sin nóminas y verifica las fuentes al calcular, guardar, exportar y aprobar. El resumen muestra los haberes conocidos mientras falta completar el neto.

## Novedades de la versión 2.6.61

- Propone el régimen ordinario y preaviso cumplido en cero al cambiar el motivo a despido sin causa. Renuncia y despido con causa omiten los conceptos indemnizatorios y pliegan su sección.
- Precarga el promedio con el salario sugerido del legajo y permite modificarlo o aplicar el promedio documentado de nóminas. Identifica el salario actual como sugerencia, sin presentarlo como promedio verificado.
- Actualiza las proyecciones y el resumen a los 500 ms. Muestra indemnización y preaviso aunque falte completar la base anual, manteniendo pendiente el total y la opción de guardar.
- Permite guardar un borrador desde un resumen válido; el servidor vuelve a calcular y validar las entradas. Las descargas anteriores siguen bloqueadas hasta recalcular su documento.
- Desde diez años, la ordinaria se muestra como referencia parcial y no puede aprobarse como liquidación completa. La doble conserva fundamento, respaldo y confirmación expresa; el fuero mantiene revisión de su régimen.

## Novedades de la versión 2.6.60

- Simplifica las liquidaciones salarial y final en cinco pasos plegables, con los datos base abiertos y un resumen lateral fijo.
- Actualiza el resumen con el mismo motor del servidor, con espera de 300 ms. Distingue los subtotales parciales e invalida el documento anterior cuando cambian las entradas.
- Permite calcular con F6, abrir directamente un dato pendiente, consultar ayudas por teclado o ratón y editar los conceptos dentro de su sección.
- Pliega el promedio de nóminas, los detalles técnicos, el documento completo y el historial. Mantiene los campos, las confirmaciones legales, las fuentes y las descargas existentes.

## Novedades de la versión 2.6.59

- Propone el promedio mensual para indemnización y preaviso desde las nóminas cerradas del funcionario, con desglose por período y concepto y confirmación antes de aplicarlo.
- Verifica la cobertura de los últimos seis meses o el menor tiempo de servicio. Los meses faltantes, las nóminas abiertas o inconsistentes y los intervalos parciales quedan pendientes de revisión.
- Conserva el origen y las fuentes en el cálculo guardado y sus documentos. Revalida las nóminas antes de calcular, guardar, exportar un nuevo resultado o aprobar.
- Mantiene el ingreso manual y exige modalidad mensual registrada para la propuesta automática. No interpreta códigos históricos de remuneración.

## Novedades de la versión 2.6.58

- Resuelve la liquidación de trabajadores con estabilidad desde una sección visible de Indemnización y preaviso: selección de doble indemnización, fundamento, respaldo y confirmación profesional.
- Calcula automáticamente los años computables, días de indemnización y preaviso pendiente; muestra una proyección del servidor y suma los conceptos al recalcular tras completar la revisión.
- Admite dos decimales en el promedio y conserva la base mensual de 30 días, con redondeo por concepto. El preaviso vacío equivale a cero y el formulario propone 0.
- Conserva el régimen y su respaldo en el historial, copias, PDF y CSV; impide aprobar como completa una liquidación que aún sea un subtotal parcial.

## Novedades de la versión 2.6.57

- Incorpora selectores globales de Empresa y Funcionario con búsqueda asíncrona por código, legajo, nombre o cédula, y sugerencias limitadas a la empresa elegida.
- Sustituye los menús extensos de los módulos y modales por comboboxes accesibles con flechas, Enter, limpieza y estados de carga o sin resultados.
- Reduce las opciones iniciales y consulta coincidencias en el servidor tras una pausa de 300 ms; conserva IDs, validaciones, datos de certificados y conexiones de formularios.

## Novedades de la versión 2.6.56

- Comparte una barra de paginación entre Funcionarios, Empresas, Liquidaciones e Informes: rango exacto, primera/última, páginas con elipsis, tamaños 25/50/100/200 y salto directo.
- Consulta búsquedas, filtros rápidos y orden en la base de datos antes de paginar; conserva el estado en la URL y vuelve al inicio al cambiar criterios o tamaño.
- Añade búsqueda automática con indicador de carga, controles accesibles y adaptación a tablets.

## Novedades de la versión 2.6.55

- Conserva los filtros opcionales vacíos sin provocar errores al ordenar informes.
- Mantiene una etiqueta clara del selector para lectores de pantalla.

## Novedades de la versión 2.6.54

- Unifica el orden ascendente y descendente con dos flechas visibles y controles accesibles por teclado.
- Sincroniza selectores y encabezados, conserva búsquedas y aplica el orden antes de paginar en Funcionarios e Informes.
- Ordena importes y fechas correctamente en los listados y conserva el orden al exportar informes.

## Novedades de la versión 2.6.53

- Permite cargar el padrón histórico completo como Desvinculado, sin activar vínculos abiertos ni crear liquidaciones finales.
- Excluye legajos con egresos inconsistentes para revisión y muestra los estados previstos antes de confirmar.
- Conserva los legajos existentes y registra las opciones de importación en auditoría.

## Novedades de la versión 2.6.51

- Corrige la navegación de Anticipos, Disciplina y Telegrama colacionado para usar la navegación global única.
- Unifica las variables antiguas de color con la paleta clara DIGIT.
- Mejora formularios, estados, acciones e historial de operaciones laborales.
- Añade pruebas de renderizado de las pantallas afectadas.

## Novedades de la versión 2.6.50

- Recupera las animaciones y el hover azul del menú lateral.
- Mantiene azul oscuro en el texto del submódulo seleccionado cuando el cursor no está encima.
- Restaura el texto blanco sobre el fondo azul al pasar el cursor, con transición suave.

## Novedades de la versión 2.6.49

- Corrige el contraste de los submódulos seleccionados: el texto permanece azul oscuro sobre fondo claro con y sin hover.
- Los accesos no seleccionados conservan el texto claro sobre la barra azul.
- Actualiza la caché del tema y añade pruebas de regresión.

## Novedades de la versión 2.6.48

- Unifica la identidad visual del espacio autenticado con la marca azul DIGIT y componentes compartidos.
- Simplifica la navegación en cinco áreas y elimina accesos secundarios duplicados.
- Unifica visualmente el centro laboral interno con el espacio de trabajo sin alterar cálculos ni documentos impresos.
- Consolida los estilos de navegación y documenta los tokens del sistema visual.

## Novedades de la versión 2.6.43

- Alinea la fecha a la derecha y la muestra una sola vez en los tres primeros certificados.
- Unifica la firma y la información de contacto; prioriza el Representante Legal registrado.
- Unifica los datos esenciales de la constancia al término de la relación y no presume renuncia voluntaria ni buena conducta.
- Solicita el salario realmente devengado en el último período también para el Certificado B.

## Novedades de la versión 2.6.42

- Evita copiar días ya usados de registros históricos a una nueva solicitud de vacaciones.
- Solicita fechas, período anual y cantidad explícita de días antes de guardar documentos de vacaciones; valida la información en el servidor.
- No calcula automáticamente saldos ni días legales: utiliza los datos revisados por el profesional.



## Novedades de la versión 2.6.41

- Prioriza el campo **Representante Legal** registrado en la ficha de la empresa para la firma del Certificado de Trabajo B.
- Conserva debajo del firmante la razón social, el domicilio y el teléfono; mantiene el formato anterior como respaldo si el representante legal no está informado.
- Sincroniza la vista previa, la impresión, Word y PDF, con pruebas de regresión.

## Novedades de la versión 2.6.40

- Unifica la prioridad del Representante Legal frente a los datos de firma de Branding o del responsable alternativo en los documentos laborales compatibles.
- Presenta el cargo «Representante legal» cuando el dato consta en la ficha de la empresa.


## Novedades de la versión 2.6.29

- Informes incorpora una vista dedicada de liquidación salarial vinculada con los cálculos guardados, con historial, impresión y PDF.
- Las reimpresiones registran usuario, fecha y operación en Auditoría.
- El documento es un recibo interno de DIGIT-LABORAL; no simula un formulario oficial de MTESS o IPS.

## Novedades de la versión 2.6.25

- Liquidación final distingue ocho causales/supuestos de egreso y muestra cuándo el cálculo es solo un subtotal sujeto a revisión.
- El motor informa antigüedad exacta en años, meses y días, además de la duración calendario de la relación.
- El retiro justificado y los casos de estabilidad, protección especial, fin de contrato a plazo/obra, mutuo consentimiento y fallecimiento tienen advertencias específicas.
- Se conservan la API REST, la auditoría, el historial, los estados del registro y los formatos PDF/CSV.

## Novedades de la versión 2.6.24

- La barra lateral del espacio de trabajo usa el azul de marca solicitado #05256d, también en el menú móvil, con contraste reforzado para etiquetas, categorías y enlaces.
- La versión blanca del logotipo reutiliza el archivo horizontal original y aplica una máscara de color/transparencia, en lugar de volver a dibujar el emblema y la tipografía.

## Novedades de la versión 2.6.23

- Salario diferencia el adicional nocturno ordinario del 30 %, las horas extraordinarias diurnas (mínimo 50 %), las extraordinarias nocturnas (100 %) y el adicional por feriado (100 %), con vista previa inmediata.
- La carga horaria deja de figurar como submódulo separado de Cálculo; se conserva su ruta de compatibilidad sin eliminar operaciones ni registros antiguos.
- Se mantiene el importe manual de horas extras para casos heredados/excepcionales, con validación que impide duplicarlo con las horas por tramo.

## Novedades de la versión 2.6.22

- Salario compara la base mensual con la escala legal seleccionada y advierte si queda por debajo del mínimo de referencia vigente en el período.
- Se incorpora cálculo de asignación familiar por hijo, sujeto a confirmación del derecho, documentación y límite de remuneración.
- Las actividades con escala salarial especial requieren registrar el mínimo aplicable; el sistema no presume la escala general.

## Novedades de la versión 2.6.21

- La navegación de Cálculo se limita a los 11 submódulos definidos.
- Salario usa el motor profesional existente y muestra sus haberes adicionales sin ocultarlos inicialmente.
- Los accesos auxiliares no solicitados salen de la navegación principal; los datos y rutas compartidas se conservan para evitar pérdida de información.

## Novedades de la versión 2.6.20

- El módulo Cálculo presenta los 11 submódulos en una navegación unificada.
- Se conservan rutas diferenciadas entre calculadoras, nóminas, gestión operativa e histórico para evitar duplicar funciones existentes.
- Examen Médico enlaza al registro compartido de Mantenimientos.
- Esta versión establece la estructura inicial; no implica que todos los procesos jurídicos estén completamente automatizados.

## Novedades de la versión 2.5.9

- Las calculadoras profesionales proponen el salario registrado con vigencia en la fecha del período seleccionado.
- Al cambiar el mes de una liquidación salarial o la fecha de egreso, la sugerencia se actualiza a partir del historial salarial del legajo.
- Las nóminas mensuales se inicializan con el salario vigente al inicio del período, o a la fecha de ingreso si el funcionario fue contratado durante ese mes.
- Los cambios salariales dentro del período y los ingresos a mitad de mes generan advertencias de revisión manual en las observaciones de la nómina. El sistema no inventa un prorrateo legal ni reemplaza la validación profesional.
- Los cálculos guardados y las nóminas existentes conservan sus importes históricos; esta mejora solo afecta nuevas propuestas de importe.

## Novedades de la versión 2.5.8

- Elimina el selector global de empresa y funcionario; cada módulo conserva su propia selección y no contamina otros módulos.
- Valida en servidor que el funcionario elegido pertenezca a la empresa seleccionada.
- Mantiene los filtros de los módulos independientes y agrega pruebas para evitar cruces de contexto entre empresas.

## Módulos incluidos

El sistema integra:

- estudios, empresas y sucursales;
- funcionarios y expedientes digitales;
- usuarios, roles, sesiones y 2FA;
- solicitudes y flujo de trámites;
- liquidaciones, vacaciones y aguinaldo;
- documentos Word/PDF e informes;
- agenda, auditoría y respaldos;
- Código Laboral estructurado;
- centro REI/REOP con borradores, validación, Excel, lotes y comprobantes.

La interoperabilidad REI/REOP funciona mediante archivos y revisión humana. Los conectores directos permanecen desactivados porque requieren documentación y autorización oficial.

## Aplicación activa

La URL principal de trabajo es **https://digit-laboral-app.onrender.com/**. La dirección `digit-laboral-py-demo.onrender.com` corresponde a una demo anterior y no debe usarse como URL principal. Configurá `PUBLIC_URL=https://digit-laboral-app.onrender.com` en Render para que los enlaces de correo y recuperación de contraseña apunten al servicio correcto.

## Inicio local

### Windows

```bat
run.bat
```

### Linux/macOS

```bash
./run.sh
```

Abrir `http://127.0.0.1:8000`.

Para una base local de desarrollo se pueden definir:

```text
DEMO_ADMIN_PASSWORD=<contraseña local>
DEMO_SUPERADMIN_PASSWORD=<contraseña local>
```

Las contraseñas de demostración no están incrustadas en el código.

## Pruebas

```bash
pip install -r requirements-dev.txt
pytest -q
```

Verificación ampliada:

```bash
python -m compileall -q app alembic tests
pytest --cov=app --cov-report=term-missing -q
```

La cantidad vigente de pruebas aprobadas se informa en cada ejecución de CI de GitHub Actions.

## Migraciones

La aplicación usa Alembic y ejecuta el control de migraciones al iniciar.

```bash
alembic current
alembic upgrade head
```

Documentación: `MIGRATION_V19_TO_V20.md`.

## Producción

Usar como base `render.production.yaml`, no el Blueprint gratuito de demostración.

Producción requiere:

- PostgreSQL persistente;
- almacenamiento S3 compatible;
- SMTP;
- HTTPS;
- respaldo externo;
- staging separado;
- RLS probado;
- revisión jurídica y de seguridad.

Documentación: `PRODUCTION_DEPLOYMENT_V20.md` y `SECURITY_AND_BACKUP_V20.md`.

## REI y REOP

El centro de cumplimiento permite:

- completar perfiles oficiales de empresa, sucursal y trabajador;
- crear comunicaciones automáticas desde operaciones internas;
- validar datos faltantes;
- exportar lotes Excel con número patronal por establecimiento;
- generar planillas REOP de trabajo;
- registrar comprobantes y resultados;
- conservar hash, usuario y trazabilidad.

Documentación: `REI_REOP_INTEGRATION.md`.

## Solicitudes, vacaciones y notificaciones

- Las solicitudes de vacaciones consultan el saldo anual antes de enviarse y vuelven a validarlo al aprobarse para evitar reservas por encima del saldo disponible.
- Los días aprobados quedan reservados; solo pasan a usados cuando finaliza el periodo y el estudio confirma su utilización. Los permisos/licencias se incorporan a la línea de tiempo del funcionario una vez finalizados.
- El propio servicio web ejecuta recordatorios y recuperación de entregas cada hora mientras el proceso está activo, sin crear un servicio de pago adicional. En el plan gratuito de Render la aplicación puede entrar en suspensión por inactividad; al reiniciarse, el trabajador vuelve a ejecutarse. Para una ejecución garantizada incluso durante la suspensión, se requiere un programador externo.

- Las solicitudes admiten campos estructurados para funcionario, fecha efectiva, periodo, días, importe y permisos/licencias.
- La bandeja de notificaciones es individual y persistente, con lectura/no lectura, filtros y enlaces al trámite.
- La creación, asignación, comentarios, adjuntos y decisiones generan avisos según roles y visibilidad.
- Los cambios salariales requieren aprobación explícita; su aplicación registra el historial salarial y la auditoría.
- Si SMTP está configurado, los correos se registran en una cola persistente y se intentan enviar en segundo plano. El barrido horario genera recordatorios y procesa la cola usando la configuración SMTP del servicio. El endpoint `/internal/cron/notifications` permanece protegido por `NOTIFICATION_CRON_TOKEN` para permitir un programador externo en el futuro.
- Si SMTP no está configurado, las notificaciones internas siguen funcionando.

## Seguridad

- No almacenar PIN o contraseñas gubernamentales.
- No subir `.env`, bases o documentos a GitHub.
- Mantener IA desactivada hasta aprobar la política de tratamiento de datos.
- Activar 2FA para administradores.
- Probar restauraciones, no solo generar respaldos.

## Documentación principal

- `REVISION_INTEGRAL_V20.md`
- `RELEASE_NOTES_V24.md`
- `RELEASE_NOTES_V23.md`
- `RELEASE_NOTES_V20.md`
- `REI_REOP_INTEGRATION.md`
- `PRODUCTION_DEPLOYMENT_V20.md`
- `SECURITY_AND_BACKUP_V20.md`
- `MIGRATION_V19_TO_V20.md`
- `SOLICITUD_INTEROPERABILIDAD_REI_REOP.md`
- `RELEASE_NOTES_V259.md`
