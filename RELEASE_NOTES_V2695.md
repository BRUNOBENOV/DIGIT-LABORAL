# DIGIT-LABORAL v2.6.95 — Conciliación de novedades salariales

## Qué cambia
- En **Cálculo → Salarios**, el panel de conciliación consulta novedades del período por empresa y funcionario: suspensiones, permisos, reposos, ausencias, licencias, amonestaciones, vacaciones y jornadas con horas registradas.
- Los movimientos de **Amonestación** no generan descuento por sí solos.
- Los registros de **Vacaciones** aprobados se señalan como descansos remunerados sin contarlos como horas efectivamente trabajadas.
- Para permisos, licencias, suspensiones, reposos y ausencias, el responsable registra expresamente el tratamiento de salario (**por definir**, **con goce**, **sin goce** o **subsidio IPS en revisión**).
- Solo un movimiento **Aprobado** y clasificado expresamente **Sin goce** puede proponer días remunerados reducidos para mensualizados, y el ajuste requiere acción del usuario. En meses de 31 días o con contradicciones se exige conciliación manual.
- Jornadas y horas solo se cargan desde registros diarios **Aprobados**, luego de que el usuario confirme que la asistencia del mes está completa.
- Se identifica y advierte sobre superposición de vacaciones remuneradas y ausencias sin goce.
- Si los registros cambian desde que el usuario aplicó una propuesta, el cálculo y la aprobación rechazan el snapshot desactualizado; deben repetirse la conciliación.
- La información del cálculo se guarda con su referencia de novedades, sin cambiar registros históricos ni cálculos previamente aprobados.

## Alcance y cautelas
- No se infieren horas ordinarias a partir de los divisores 30, 26 o 240.
- La propuesta NO reemplaza los controles de asistencia ni establece por sí sola el tratamiento IPS de un reposo.
- No se aplican descuentos automáticos por movimientos en estado «Registrado», pendientes de clasificación o por solicitudes históricas sin tratamiento salarial determinado.
- La nómina masiva y sus cierres conservan su flujo actual; el panel nuevo se encuentra en el cálculo salarial individual del motor profesional.

## Verificación
- Se agregaron pruebas automatizadas de ausencia sin goce, permiso y reposo pendiente, vacaciones superpuestas, suspensión registrada y snapshot desactualizado.
- Antes de pasar a producción definitiva, confirmar el estado del flujo de CI y el despliegue automático de Render.
