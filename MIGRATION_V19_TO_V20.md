# Migración de v19 a v2.0

1. No sobrescribir la producción sin respaldo.
2. Descargar la versión completa v2.0.
3. Comparar variables de entorno.
4. Configurar almacenamiento.
5. Ejecutar primero en staging.
6. Iniciar la aplicación: Alembic detectará la base v19 y aplicará en orden `0002_v20_compliance`, `0003_v20_branch_compliance`, `0004_v20_compliance_idempotency` y `0005_v20_security_event_ip_index`.
7. Comprobar `/health/ready`.
8. Revisar usuarios, empresas y funcionarios.
9. Entrar a Cumplimiento y completar perfiles oficiales de empresa, sucursales y trabajadores.
10. Probar una exportación ficticia REOP y registrar un comprobante de prueba.

Rollback técnico:

```bash
alembic downgrade 0001_v19_baseline
```

El downgrade elimina las tablas de cumplimiento v2.0; debe ejecutarse únicamente con respaldo y en una ventana de mantenimiento.
