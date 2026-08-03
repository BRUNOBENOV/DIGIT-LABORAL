# Revisión integral — Digit Laboral v2.0

Fecha de revisión: 3 de agosto de 2026

## Resultado

La versión 2.0 transforma el proyecto anterior en una base de **estabilización y cumplimiento**. El sistema queda preparado para pruebas piloto controladas, migraciones versionadas, almacenamiento persistente compatible con S3 y operación asistida con REI/REOP mediante archivos, lotes, comprobantes y trazabilidad.

No se declara una integración directa con IPS o MTESS porque no se encontró una API pública documentada en las fuentes oficiales revisadas. Los conectores directos permanecen bloqueados hasta obtener autorización, especificación técnica, ambiente de pruebas y credenciales institucionales.

## Implementado

### Estabilidad técnica

- Migraciones de base mediante Alembic.
- Migración segura desde una base v19 existente.
- Creación limpia de una base v20.
- Health checks de vida y disponibilidad.
- Registros estructurados con identificador por solicitud.
- Página HTML amigable para errores y validaciones.
- Contenedor Docker sin ejecución como usuario root.
- Cliente PostgreSQL incluido para respaldos verificables.
- CI de GitHub con compilación, pruebas, cobertura y control de secretos.
- GitHub Pages restringido a los archivos comerciales públicos.

### Seguridad

- Sesiones seguras, expiración, 2FA, bloqueo de accesos y cierre de sesiones.
- Protección CSRF en formularios autenticados.
- Encabezados de seguridad y política de contenido.
- RLS ampliado a las tablas de cumplimiento.
- Preparación para separar usuario de migración y usuario de aplicación.
- Eliminación de contraseñas demostrativas incrustadas en el código.
- Validación de rutas de almacenamiento y archivos.
- Credenciales de REI/REOP expresamente excluidas del sistema.

### Almacenamiento y respaldo

- Backend local para desarrollo.
- Backend compatible con S3/R2/B2 para producción.
- Documentos, lotes y comprobantes desacoplados del disco efímero.
- Respaldo de SQLite o PostgreSQL.
- Opción de subir el respaldo al almacenamiento configurado.
- Conservación local parametrizable.
- Guía de restauración y controles de prueba.

### REI y REOP

- Centro de cumplimiento por empresa.
- Perfil oficial de empresa, sucursal y trabajador.
- Números patronales IPS/MTESS por establecimiento y validación previa de datos faltantes.
- Borradores automáticos al registrar:
  - entrada de trabajador;
  - salida de trabajador;
  - vacaciones;
  - aguinaldo;
  - liquidación salarial;
  - declaración salarial para IPS.
- Estados de comunicación: borrador, validado, exportado, presentado, aceptado, observado, rechazado o anulado.
- Exportación de comunicaciones a Excel.
- Generación de las tres planillas REOP de trabajo:
  - empleados y obreros;
  - sueldos y jornales;
  - resumen general de personas ocupadas.
- Lotes con hash SHA-256.
- Registro de comprobante, referencia externa, responsable y fecha.
- Prohibición funcional de presentar como “conexión directa” una integración no autorizada.

### Experiencia visual

- Navegación reorganizada por Personas, Empresas, Trámites, Operaciones, Cumplimiento, Documentos, Reportes y Administración.
- Panel de alertas REI/REOP.
- Centro de cumplimiento responsive.
- Mejores estados vacíos, errores, foco y controles móviles.
- Botones con estado de procesamiento.
- Formularios con errores entendibles en lugar de JSON técnico.
- Logos normalizados para web y documentos.

## Verificación ejecutada

- 32 pruebas automatizadas aprobadas.
- Compilación completa de `app`, `alembic` y `tests`.
- Migración probada sobre base nueva.
- Migración probada desde esquema v19.
- Pruebas de rutas autenticadas principales.
- Pruebas de formularios CSRF.
- Prueba de exportación Excel REI/REOP y selección del número patronal por sucursal.
- Prueba de almacenamiento local e integridad.
- Cobertura global aproximada: 56 %.
- Cobertura del servicio de cumplimiento: superior al 70 %.

La cobertura global todavía debe aumentar antes de considerar al sistema una plataforma madura. La prioridad siguiente es cubrir flujos de liquidación, documentos, permisos cruzados y errores de producción.

## Límites que permanecen

1. La base gratuita de Render sigue siendo solo demostrativa.
2. El almacenamiento local del plan gratuito no es apto para documentos reales.
3. Los archivos generados deben validarse contra la plantilla oficial vigente antes de cada presentación.
4. No existe envío directo autorizado a REI o REOP.
5. La plataforma no debe almacenar PIN, contraseña ni sesión de los portales gubernamentales.
6. Falta una auditoría externa de seguridad y revisión jurídica de documentos/cálculos.
7. El archivo principal conserva lógica heredada que debe seguir dividiéndose en routers y servicios.
8. Falta un ambiente staging independiente del ambiente productivo.

## Dictamen de uso

- **Datos ficticios y prueba piloto:** aprobado.
- **Uso interno con información limitada y respaldo controlado:** condicionado a hosting persistente.
- **Clientes reales y documentos sensibles:** no habilitar hasta completar el despliegue de producción, almacenamiento S3, respaldo externo, prueba de restauración y revisión de seguridad.
- **Presentación directa a REI/REOP:** no habilitada; se trabaja mediante exportación, revisión humana y carga en el portal oficial.
