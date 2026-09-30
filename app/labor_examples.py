"""Synthetic examples: never import these records into a customer workspace."""


def example_values(kind, defaults):
    values = dict(defaults, employer="Empresa de ejemplo", ruc="80000000-0",
                  employee="Persona de ejemplo", ci="1000000", salary="3500000",
                  notes="DATOS FICTICIOS. Ejemplo para probar Digit Laboral; reemplazá los datos antes de usarlo en un caso real.",
                  reference="EJEMPLO", days_worked="22")
    if kind == "settlement":
        values.update(salary="3000000", average_salary="3000000", start_date="2024-01-01",
                      end_date="2026-07-01", days_paid="0", annual_remuneration="18000000",
                      ips_base="0", ips_reason="Ejemplo sin haberes remunerativos pendientes de aporte.")
    return values
