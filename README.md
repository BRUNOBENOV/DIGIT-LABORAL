# Digit Laboral 2.6.29

Plataforma de gestión y cumplimiento laboral para estudios contables paraguayos.

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
