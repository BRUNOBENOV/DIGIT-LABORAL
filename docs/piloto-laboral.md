# Piloto de Digit Laboral

Objetivo: completar un recorrido desde los datos hasta el documento y contrastarlo con documentación revisada. Los ejemplos públicos son ficticios; no crean registros de clientes ni acreditan pagos.

## Recorridos disponibles

| Público | Entrada | Comprobación |
| --- | --- | --- |
| Empresa | `/empezar?perfil=empresa` | Salario, costo patronal y consulta de su empresa vinculada. |
| Contador | `/app/guia` | Empresa, funcionario, cálculo guardado, reapertura y PDF/CSV. |
| Abogado | `/herramientas/comparar?tipo=settlement` | Dos supuestos, diferencias de datos e importes, advertencias y documentos A/B. |
| Empleado | `/empezar?perfil=empleado` | Cálculo sin cuenta y contraste con el neto informado en su recibo. |

Los recorridos públicos no agregan nuevos roles de acceso. Las cuentas profesionales mantienen sus permisos; una cuenta de empresa solo consulta la empresa válidamente vinculada dentro de su estudio.

## Casos sintéticos reproducibles

1. Abrir `/herramientas?tipo=salary&ejemplo=true` y calcular. Gs. 3.500.000 por 30 días, IPS trabajador declarado 9%: descuento Gs. 315.000 y neto Gs. 3.185.000. Aporte patronal declarado 16,5%: Gs. 577.500; costo Gs. 4.077.500.
2. Informar un neto de recibo de Gs. 3.000.000. La diferencia calculado menos informado debe ser Gs. 185.000. Es una comparación aritmética, no una determinación de deuda.
3. Abrir el comparador salarial con `ejemplo=true`. A: Gs. 3.500.000; B: Gs. 4.000.000. La variación del neto B menos A debe ser Gs. 455.000 y la del costo Gs. 582.500.
4. Abrir el comparador de egreso con `ejemplo=true`. Supuestos ficticios comunes: ingreso 01/01/2024, egreso 01/07/2026, salario y promedio Gs. 3.000.000, remuneraciones anuales Gs. 18.000.000, sin salario ni vacaciones pendientes y base IPS revisada cero. A declara despido ordinario sin causa; B declara renuncia. Totales bajo esos supuestos: A Gs. 9.000.000 y B Gs. 1.500.000. La herramienta no determina cuál causa corresponde a un caso real.
5. Descargar los PDF de A y B, comprobar sus referencias e importes. Cada documento solicitado con dos copias contiene original y duplicado.
6. Cambiar un dato después de calcular. Las descargas y la impresión deben quedar deshabilitadas hasta recalcular.

## Piloto con documentación real

- Elegir un caso y un período con datos autorizados para tratar en el sistema.
- Reunir salario, jornadas, novedades, descuentos, aportes y comprobantes del período.
- Para egresos: revisar fechas, causa, contrato, protecciones, preaviso, base promedio, vacaciones y remuneraciones computables con el profesional responsable.
- Comparar cada concepto con un cálculo revisado de forma independiente. Registrar las diferencias y sus causas.
- Con una cuenta habilitada, guardar en el funcionario y verificar que la reapertura conserve los datos originales.
- Revisar el PDF, su impresión A4 y los campos de firma. Documentar pago y firmas por el procedimiento correspondiente.

No marcar el piloto real como completado sin documentación y revisión humana del caso.

## Validación de cada entrega

GitHub Actions ejecuta las pruebas del motor, rutas, permisos, descargas y perfiles antes de fusionar, y nuevamente en `main`. Las pruebas completas ya no se ejecutan en cada arranque del servidor. El arranque conserva la inicialización y los controles de disponibilidad de la aplicación.

La validación automatizada usa SQLite aislado y datos sintéticos. La comprobación con una cuenta en producción requiere una sesión iniciada por el flujo habitual de autenticación.
