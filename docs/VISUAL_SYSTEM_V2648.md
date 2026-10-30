# Sistema visual de DIGIT-LABORAL — v2.6.48

## Objetivo

Mantener una identidad corporativa única en el espacio autenticado, con navegación principal basada en cinco áreas y componentes compartidos para cabeceras, formularios, tarjetas, tablas, estados y ventanas modales.

La aplicación continúa utilizando **FastAPI + Jinja2 + HTML/CSS + JavaScript**. Este cambio no introduce un framework de frontend ni altera las rutas de negocio.

## Identidad visual

| Token | Valor | Uso |
|---|---|---|
| `--ui-navy` | `#05256D` | Barra lateral y marca |
| `--ui-blue` | `#0B2D78` | Enlaces y acentos corporativos |
| `--ui-primary` | `#1D4ED8` | Acción primaria |
| `--ui-primary-hover` | `#1741B5` | Hover de acción |
| `--ui-bg` | `#F2F5FA` | Lienzo de trabajo |
| `--ui-surface` | `#FFFFFF` | Paneles y formularios |
| `--ui-border` | `#E1E7F0` | Separadores |
| `--ui-text` | `#172033` | Texto principal |
| `--ui-muted` | `#667085` | Texto secundario |

El verde, amarillo y rojo se reservan para estados semánticos: éxito, advertencia y error. Las vistas de impresión pueden conservar tipografías y formatos documentales propios.

## Navegación

La barra lateral de `base.html` es la única fuente de navegación global del espacio autenticado:

1. **Mantenimientos:** empresas, funcionarios, secciones, exámenes médicos, usuarios y parámetros.
2. **Cálculo:** salario, liquidación de haberes, liquidación final, nóminas mensuales, horas y recargos, preaviso, calculadoras laborales, aguinaldo, vacaciones y operaciones.
3. **Informes:** centro de informes, cumplimiento REI/REOP y auditoría.
4. **Certificados:** documentos laborales, certificados oficiales MTESS/IPS y archivo documental.
5. **Utilitarios:** solicitudes, agenda, notificaciones, comparación, Código Laboral, asistente, guía y seguridad.

Las pantallas de directorios y expedientes pueden conservar navegación contextual propia cuando aporta subsecciones específicas. No se debe volver a introducir una barra global que repita todos los enlaces de la barra lateral.

Los accesos deben mantener sus rutas FastAPI existentes y sus restricciones de rol.

## Componentes compartidos

Archivo: `app/static/ui-system-264.css`.

- Encabezados de módulo con jerarquía tipográfica y separador discreto.
- Paneles y tarjetas blancos con borde y sombra de baja elevación.
- Campos de formulario de altura y radio consistentes.
- Estados de foco visibles para teclado.
- Botones primarios, secundarios y destructivos con semántica estable.
- Tablas con encabezado fijo cuando corresponde, filas legibles y desplazamiento horizontal dentro de su contenedor.
- Modales con altura máxima y desplazamiento interno.
- Estados vacíos, alertas y métricas con tratamiento consistente.

Los macros Jinja reutilizables para tarjetas y ayuda contextual se mantienen en `app/templates/components/ui.html`.

## Responsividad

Los componentes generales deben adaptarse sin ocultar información:

- Escritorio: navegación lateral fija y área central flexible.
- Hasta 900 px: menú lateral móvil y contenido a ancho completo.
- Hasta 620 px: formularios generales en una columna y acciones apilables.
- Tablas: desplazamiento contenido; no deben forzar el ancho de toda la página.
- Certificados: la vista previa documental debe preservar su proporción y seguir siendo legible al apilar el editor.

Los módulos con necesidades especiales pueden añadir breakpoints locales, pero deben respetar los tokens y componentes comunes.

## Límites funcionales

Este sistema visual no modifica:

- cálculos de salarios, IPS, haberes o liquidaciones;
- reglas laborales ni parámetros de cálculo;
- modelos, registros ni migraciones de base de datos;
- roles, permisos ni aislamiento por empresa;
- rutas, procesos de aprobación ni auditoría;
- generación, impresión o exportación de documentos.

Toda ampliación de estilos debe comprobar que conserva estos límites.

## Validación

Antes de integrar cambios visuales:

1. Compilar la aplicación y todas las plantillas Jinja.
2. Ejecutar las pruebas automatizadas.
3. Probar navegación y visibilidad por rol.
4. Revisar escritorio, tablet y móvil.
5. Añadir capturas de referencia para regresión visual cuando la pantalla pueda inspeccionarse en navegador.

Las pruebas de HTML/CSS no sustituyen una revisión visual real del navegador.
