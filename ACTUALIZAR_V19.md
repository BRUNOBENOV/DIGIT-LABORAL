# Actualizar a Digit Laboral v1.9 Preview

1. Realizá un respaldo de la base y de `data/uploads`.
2. Reemplazá el código por la versión v19.
3. Instalá dependencias:
   ```bash
   pip install -r requirements.txt
   ```
4. Reiniciá la aplicación. SQLAlchemy creará las nuevas tablas.
5. Verificá `/health` y confirmá `1.9.0-preview`.
6. Probá ingreso, importación, expediente, agenda, trámites y exportación ZIP.
7. Configurá las variables nuevas de `.env.example`.

No actives RLS en producción sin separar el rol propietario del rol utilizado por la aplicación.
