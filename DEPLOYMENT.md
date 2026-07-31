# Publicar Digit Laboral

## Arquitectura recomendada

- `digitlaboral.com.py`: página comercial.
- `app.digitlaboral.com.py`: aplicación privada FastAPI.
- PostgreSQL administrado: base de datos central.
- Almacenamiento privado persistente: documentos.
- Copia de seguridad automática: base y archivos.

## Variables de entorno mínimas

```env
APP_NAME=Digit Laboral
ENVIRONMENT=production
DIGIT_SECRET_KEY=UNA_CLAVE_LARGA_ALEATORIA_Y_EXCLUSIVA
DATABASE_URL=postgresql://USUARIO:CONTRASENA@HOST:5432/BASE
PUBLIC_URL=https://app.digitlaboral.com.py
SECURE_COOKIES=true
ALLOWED_HOSTS=app.digitlaboral.com.py
```

La aplicación se negará a iniciar en producción si conserva la clave secreta predeterminada.

## Docker

```bash
docker build -t digit-laboral .
docker run --env-file .env -p 8000:8000 digit-laboral
```

## Antes del lanzamiento

1. Cambiar todas las contraseñas de demostración.
2. Configurar PostgreSQL y migraciones de base de datos.
3. Activar HTTPS y cookies seguras.
4. Configurar correo para invitaciones y recuperación de contraseña.
5. Añadir protección CSRF y límite de intentos de acceso.
6. Guardar documentos en almacenamiento privado.
7. Automatizar y probar copias de seguridad.
8. Validar cálculos, parámetros y contenido jurídico.
9. Adaptar privacidad, términos y contratos al tratamiento real de datos.
10. Realizar pruebas funcionales y de seguridad antes de cargar clientes.
