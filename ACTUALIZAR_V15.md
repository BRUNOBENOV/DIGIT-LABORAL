# Actualizar Digit Laboral a v1.3 Preview

1. Descomprimí `digit-laboral-v15-actualizacion.zip`.
2. Subí todo su contenido a la raíz del repositorio `BRUNOBENOV/DIGIT-LABORAL`.
3. Aceptá reemplazar los archivos existentes.
4. Confirmá el commit.
5. Render iniciará un nuevo despliegue automáticamente.
6. Esperá que el estado cambie a `Live`.
7. Abrí `/health` y verificá que muestre `1.3.0-preview`.
8. Ingresá en `/app/certificates` y generá un documento de prueba.

## Dependencias nuevas

Render instalará automáticamente:

- `python-docx`, para archivos Word.
- `reportlab`, para archivos PDF.

No hace falta instalar LibreOffice en Render.

## Datos existentes

La actualización no elimina empresas, funcionarios, usuarios, liquidaciones ni documentos anteriores. No agrega columnas nuevas a la base de datos.
