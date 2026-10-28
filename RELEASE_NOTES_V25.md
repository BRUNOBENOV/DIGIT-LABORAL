# Digit Laboral 2.6.25 — Liquidación final

## Cambios funcionales
- La causal de egreso diferencia despido sin causa, renuncia, causa alegada por el empleador, retiro justificado imputable al empleador, fin de contrato a plazo/obra, mutuo consentimiento, fallecimiento y otras causas.
- La antigüedad aparece desglosada en años, meses y días, y también en días calendario.
- El cálculo de retiro justificado se presenta como escenario condicionado a la acreditación de una causa imputable al empleador.
- Se refuerzan las alertas para estabilidad de diez años, protección especial, contratos no indefinidos y período de prueba no confirmado.
- Vacaciones pendientes simples, dobles y proporcionales siguen requiriendo días reconocidos por el profesional; no se generan automáticamente por una suposición.

## Persistencia y documentos
- Se conserva el registro histórico existente, vinculación con empresa/funcionario, estados, auditoría y API CRUD.
- Se mantienen las exportaciones PDF y CSV del motor profesional. Un documento generado no acredita por sí solo pago ni firma.

## Pruebas
- Incluye casos de retiro justificado, antigüedad, estabilidad, protección especial, período de prueba, causales especiales y opciones visibles en el formulario.
