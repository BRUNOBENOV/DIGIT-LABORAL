# Publicar Digit Laboral en internet

## Explicación sencilla

- **Dominio:** `digitlaboral.com.py` es la dirección pública.
- **Aplicación:** `app.digitlaboral.com.py` será la dirección privada del sistema.
- **Hosting:** es la computadora online que mantiene el sistema encendido.
- **PostgreSQL:** es la base central donde se guardan los datos.
- **DNS:** conecta el dominio con el hosting.

## Lo que debe contratar o crear el propietario

1. Registrar `digitlaboral.com.py`.
2. Crear una cuenta en un proveedor que acepte Docker y PostgreSQL.
3. Crear la base PostgreSQL.
4. Subir este proyecto o conectarlo a un repositorio privado.
5. Configurar las variables de entorno.
6. Conectar `app.digitlaboral.com.py` al servicio web.
7. Activar HTTPS.
8. Cambiar todas las contraseñas de demostración.

## Variables de entorno

```env
APP_NAME=Digit Laboral
ENVIRONMENT=production
DIGIT_SECRET_KEY=UNA_CLAVE_LARGA_ALEATORIA
DATABASE_URL=postgresql://USUARIO:CONTRASENA@HOST:5432/BASE
PUBLIC_URL=https://app.digitlaboral.com.py
SECURE_COOKIES=true
```

## Despliegue con Docker

```bash
docker build -t digit-laboral .
docker run --env-file .env -p 8000:8000 digit-laboral
```

El archivo `render.yaml` sirve como punto de partida para un proveedor compatible, pero debe revisarse contra la configuración vigente del proveedor elegido.

## Estructura recomendada

- `digitlaboral.com.py`: página comercial.
- `app.digitlaboral.com.py`: sistema privado.
- PostgreSQL administrado: datos.
- Almacenamiento privado persistente: documentos.
- Copia de seguridad diaria: base y archivos.

## Antes de abrir al público

- Ejecutar pruebas de seguridad.
- Configurar correo transaccional para invitaciones y recuperación de contraseña.
- Implementar migraciones de base de datos.
- Definir política de privacidad, términos y tratamiento de datos.
- Revisar cálculos y contenido jurídico con profesionales.
