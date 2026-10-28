# Digit Laboral 2.6.26 — Centro de Informes

## Alcance
Se incorpora un catálogo navegable de 35 submódulos agrupados por familia. Los informes reutilizan los modelos existentes de empresas, funcionarios, nóminas, cálculos, vacaciones, aguinaldos, operaciones laborales, eventos, vencimientos, documentos y exámenes médicos.

## Experiencia
- Catálogo filtrable por nombre/tema y tarjetas responsivas.
- Vista propia por informe con búsqueda, empresa, funcionario, estado, año, periodo, ordenamiento y paginación.
- Descarga en PDF, Excel (.xlsx) y CSV; impresión directa desde la vista.
- Mensajes contextuales cuando no hay datos y advertencias para salidas preparatorias.

## API
- `GET /api/reports/catalog`
- `GET /api/reports/{report_key}?page=1&page_size=25&q=&company_id=&employee_id=&status=&year=&period=&sort=`
- `GET /api/reports/{report_key}/export?format=xlsx|pdf|csv`

## Seguridad y tratamiento de datos
- Cada consulta se limita a las empresas autorizadas del usuario.
- Los identificadores de empresa y funcionario se validan antes de consultar o exportar.
- El listado de exámenes médicos tiene acceso restringido a roles autorizados del estudio.
- Las exportaciones registran auditoría.
- No se inventan datos faltantes. Los formatos llamados “pre-impresos” son vistas internas de preparación, no sustitutos de formularios oficiales de IPS o MTESS.
- No se incorporan migraciones de base de datos.

## Validación
Incluye pruebas para el catálogo completo, el esquema paginado de todas las APIs, las vistas y las exportaciones Excel/PDF.
