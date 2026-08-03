# Actualizar Digit Laboral a v1.5 Preview

1. Descomprimir `digit-laboral-v17-actualizacion.zip`.
2. Subir su contenido a la raíz del repositorio `BRUNOBENOV/DIGIT-LABORAL`, reemplazando archivos.
3. Esperar el despliegue automático de Render.
4. Si Render no inicia, usar **Manual Deploy → Deploy latest commit**.
5. Actualizar el navegador con `Ctrl + F5`.
6. Verificar `/health`: debe indicar `1.5.0-preview`.
7. Entrar a una empresa y probar **Configurar logo y membrete**.
8. Entrar a **Código Laboral** y pulsar **Actualizar desde fuentes** para cargar y ordenar el Código completo.

La sincronización jurídica requiere acceso saliente a internet desde Render. Si una fuente falla, el sistema conserva los artículos existentes. No subir `.env`, claves ni bases de datos reales.
