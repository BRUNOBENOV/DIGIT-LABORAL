# Digit Laboral 2.3.0

**Fecha:** 24 de octubre de 2026

## Cambios incluidos

### Empresas y funcionarios
- Validación más estricta de campos obligatorios, estados y sucursales.
- Selección y validación de sucursales vinculadas a la empresa y activas.
- Normalización de cédulas para prevenir duplicados por diferencias de formato.
- Controles adicionales en importaciones CSV/XLSX: encabezados repetidos, cédulas duplicadas, salarios inválidos, fechas y marcas de IPS mal formadas.
- Se conserva el flujo de aprobación para los cambios salariales.

### Calculadoras y nómina
- Corrección del cómputo de antigüedad para ingresos en 29 de febrero: los aniversarios se aplican de manera consistente en años no bisiestos.
- Verificación de que el importe IPS guardado coincida con la base y la tasa que se muestran en el recibo.
- La emisión del recibo y el cierre de nómina se bloquean ante importes IPS inconsistentes; una nómina rechazada no pasa a estado cerrada.
- Compatibilidad conservada para registros históricos que no tienen ni base ni tasa IPS guardadas.

### Identificación de versión
- La fuente de versión de la aplicación es el archivo `VERSION`.
- La interfaz autenticada muestra la versión y el identificador de build en la barra superior.
- Los endpoints de salud informan la versión activa.
- Se añade una prueba de regresión para comprobar que la versión publicada por la aplicación coincide con la versión mostrada en la interfaz.

## Verificación

Los cambios funcionales de empresas/funcionarios y calculadoras/nómina ya fueron integrados en `main` con validación automática aprobada. Este incremento de versión tiene su propia ejecución de CI antes de integrarse.

**Nota de despliegue:** que el repositorio marque la versión 2.3.0 no demuestra por sí solo que Render ya la esté ejecutando. El valor visible cambia cuando la instancia incorpora este commit y se reinicia con el código actualizado.
