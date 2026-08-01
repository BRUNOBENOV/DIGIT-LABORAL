# Digit Laboral v1.2 Preview

## Cálculos integrados

- Nuevo centro de Cálculos conectado al sistema real.
- Simuladores de salario neto, valor hora, aguinaldo, vacaciones y preaviso.
- Accesos directos a liquidaciones, vacaciones, aguinaldo, anticipos, novedades e histórico del funcionario.
- Los parámetros sensibles permanecen manuales y los resultados se identifican como estimaciones para revisión profesional.

## Certificados y documentos

- Nuevo generador de certificados con datos de empresas y funcionarios almacenados en PostgreSQL.
- Diez modelos: certificados de trabajo A y B, constancia, contrato, ficha, solicitud y usufructo de vacaciones, preaviso, renuncia y despido.
- Vista previa en tiempo real.
- Guardado de borradores en la nueva tabla `generated_certificates`.
- Historial de documentos generados.
- Impresión y guardado como PDF desde el navegador.
- Acceso de empresa limitado a consulta y solicitud; la emisión queda reservada al estudio.

## Interfaz

- El menú superior y el panel principal ahora dirigen a los nuevos módulos reales.
- Certificados y Cálculos mantienen la estética de la demostración pública.
- Diseño responsive para escritorio, tablet y celular.

## Calidad

- Se corrigió una declaración duplicada en el modelo de empresas.
- La versión del health check pasa a `1.2.0-preview`.
- Cinco pruebas automáticas aprobadas.
