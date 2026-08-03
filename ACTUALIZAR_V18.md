# Digit Laboral v18 — logos inteligentes y Código Laboral mejorado

## Qué cambia

### 1) Logos con ajuste automático
- Al subir un logo PNG o JPG, el sistema ahora:
  - corrige orientación,
  - recorta márgenes vacíos o transparentes,
  - redimensiona proporcionalmente,
  - lo centra en un lienzo optimizado,
  - lo guarda en PNG normalizado para web, Word y PDF.
- Esto evita que el logo se vea desproporcionado en tarjetas, membretes y certificados.

### 2) Código Laboral reestructurado
- Nueva hoja de referencia inicial con formato más jurídico y fácil de leer.
- Índice general con libros, títulos y capítulos.
- Rangos de artículos por libro, título y capítulo.
- Encabezado de lectura para la selección activa.
- Estilo más limpio para el articulado.

## Archivos clave modificados
- `app/main.py`
- `app/templates/companies.html`
- `app/templates/company_detail.html`
- `app/templates/labor_code_v17.html`
- `app/static/v17.css`
- `requirements.txt`
- `VERSION`

## Despliegue
1. Reemplazá los archivos de tu proyecto por esta actualización.
2. Confirmá que Render reinstale dependencias.
3. Reiniciá el servicio.
4. Probá subir nuevamente un logo ancho o grande.
5. Revisá el módulo `Código Laboral`.
