# Sistema visual reutilizable de DigIT-Laboral — v2.6.4

## Tecnología del proyecto

La interfaz actual se implementa con **FastAPI + Jinja2 + HTML/CSS + JavaScript**, no con React ni Vue. Para evitar introducir un segundo framework solo para estilos, los ejemplos reutilizables de este cambio usan macros Jinja, clases CSS semánticas y mejoras progresivas de JavaScript. Si el frontend se migra a React/Vue en el futuro, este contrato visual puede conservarse.

## Componentes Jinja reutilizables

Archivo: `app/templates/components/ui.html`.

### Navegación secundaria

```jinja
{% from "components/ui.html" import tab_nav %}
{{ tab_nav("Secciones de nómina", [
  {"label": "Liquidaciones", "href": "/app/payrolls", "active": active_path.startswith("/app/payrolls")},
  {"label": "Vacaciones", "href": "/app/vacations", "active": active_path.startswith("/app/vacations")},
  {"label": "Aguinaldo", "href": "/app/aguinaldo", "active": active_path.startswith("/app/aguinaldo")}
]) }}
```

Los enlaces tienen fallback nativo sin JavaScript, una etiqueta accesible y un estado activo perceptible. Los módulos existentes usan rutas FastAPI para recuperar los datos y permisos del usuario.

### Panel reutilizable con contenido de formulario

```jinja
{% from "components/ui.html" import section_card, inline_help %}
{% call section_card(
  "Identificación de la empresa",
  eyebrow="DATOS PRINCIPALES",
  description="Información general para identificar la ficha."
) %}
  <div class="form-grid">
    <label>Nombre legal
      <input name="legal_name" autocomplete="organization" required maxlength="200">
      {{ inline_help("Utilizá la denominación registrada.") }}
    </label>
    <label>Correo electrónico
      <input name="email" type="email" autocomplete="email">
    </label>
  </div>
{% endcall %}
```

### Ayuda junto a un campo

```jinja
{% from "components/ui.html" import inline_help %}
<label>Número patronal IPS
  <input name="ips_employer_number" inputmode="numeric">
  {{ inline_help("Copiá el número tal como aparece en la constancia patronal.") }}
</label>
```

## Contrato de clases CSS

Archivo: `app/static/ui-system-264.css`.

| Clase | Uso |
|---|---|
| `.ui-module-nav` | Barra de subsecciones de un módulo |
| `.ui-section-card` | Panel blanco con borde, radio y sombra discreta |
| `.ui-section-card-head` | Cabecera de panel y descripción |
| `.ui-inline-help` | Texto de orientación bajo un campo |
| `.ui-table-toolbar` | Barra de búsqueda local y contador |
| `.ui-table-sort` | Control accesible para ordenar columna |
| `.ui-field-message` | Mensaje de validación junto al control |
| `.is-active`, `.is-invalid`, `.is-valid` | Estados visuales compartidos |

Tokens de diseño: navy `#0D1B2A`; azul activo `#1E40AF`; botón primario `#2563EB`; fondo `#F9FAFB`; superficie `#FFFFFF`; texto `#111827`; texto secundario `#6B7280`. Los estilos se limitan a `.app-body` para mantener independientes las páginas públicas y los documentos imprimibles.

## Cómo dar de alta una tabla con ordenación y filtro

Colocá el listado dentro de `.table-wrap` y definí encabezados descriptivos en un `thead` y filas de datos en un `tbody`. El script global aplica búsqueda local, contador, filas alternadas y ordenación por texto/número en las tablas que tienen tres o más filas de datos. Las tablas de calendario, impresión y el directorio de funcionarios con controles propios se excluyen.

```html
<section class="panel table-panel">
  <div class="panel-head">
    <div><span>REGISTRO</span><h2>Movimientos recientes</h2></div>
  </div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>Fecha</th><th>Empresa</th><th>Estado</th></tr>
      </thead>
      <tbody>
        <tr><td>27/10/2026</td><td>Ejemplo Comercial S.A.</td><td>Revisar</td></tr>
      </tbody>
    </table>
  </div>
</section>
```

No agregues información ficticia como datos de producción; el ejemplo anterior es solo ilustrativo.

## Validación y acciones

El JavaScript global marca el estado del campo tras interacción del usuario, muestra mensajes accesibles y mantiene la validación del servidor como autoridad. En las pantallas de Empresas y Funcionarios se conserva la lógica especializada existente para no duplicar validaciones del Código Empresa, RUC y Código Legajo.

Para acciones destructivas, mantené la confirmación explícita del usuario, el token CSRF y el endpoint autenticado del servidor. El estilo por sí solo nunca sustituye validaciones de permisos ni de datos.

## Navegación sin perder contexto

La navegación secundaria agrupada conserva los filtros y cálculos en la URL siempre que el módulo los admite y proporciona enlaces de vuelta coherentes. El frontend es server-rendered: los enlaces cargan la plantilla autorizada de FastAPI; este cambio no implementa una SPA ni intercepta formularios sensibles para reemplazarlos por fragmentos HTML, porque eso exige inicializadores de página específicos y pruebas adicionales. La barra, los estilos y los controles progresivos trabajan sin depender de ese comportamiento.

## Accesibilidad y móvil

- Foco visible para teclado, etiquetas accesibles y feedback inline.
- Controles con alturas táctiles aproximadas de 40–42 px.
- Tablas con scroll horizontal en móvil, sin ocultar columnas de nómina o datos laborales.
- Tamaño tipográfico con unidades relativas y encabezados fluidos.
- Respeto a `prefers-reduced-motion`.
- El contraste de estados de éxito, error y advertencia utiliza texto y fondo coordinados.
