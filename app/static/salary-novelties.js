(() => {
  "use strict";
  const form = document.getElementById("labor-form");
  const panel = form?.querySelector("[data-salary-novelties]");
  if (!panel) return;
  const input = name => form.elements.namedItem(name);
  const status = panel.querySelector("[data-novelties-status]");
  const events = panel.querySelector("[data-novelties-events]");
  const warnings = panel.querySelector("[data-novelties-warnings]");
  const paid = panel.querySelector("[data-novelties-paid]");
  const work = panel.querySelector("[data-novelties-work]");
  const hours = panel.querySelector("[data-novelties-hours]");
  const applyPaid = panel.querySelector("[data-apply-paid-days]");
  const applyAttendance = panel.querySelector("[data-apply-attendance]");
  const complete = panel.querySelector("[data-attendance-complete]");
  let current = null, sequence = 0, controller = null;

  function clearApproval() {
    input("novelties_applied").value = "";
    input("novelties_attendance_confirmed").value = "";
    input("novelties_fingerprint").value = "";
  }
  function rows(target, values, format) {
    target.replaceChildren();
    for (const item of values) {
      const row = document.createElement("li");
      row.textContent = format(item);
      target.appendChild(row);
    }
  }
  function controls() {
    applyPaid.disabled = !current?.can_apply_paid_days;
    applyAttendance.disabled = !current?.daily_attendance?.length || !complete.checked;
  }
  async function refresh() {
    const id = ++sequence;
    controller?.abort();
    controller = new AbortController();
    current = null;
    clearApproval();
    complete.checked = false;
    paid.textContent = "—"; work.textContent = "—"; hours.textContent = "—";
    rows(events, [], String); rows(warnings, [], String); controls();
    const companyId = input("company_id")?.value;
    const employeeId = input("employee_id")?.value;
    const period = input("month")?.value;
    const basis = input("pay_basis")?.value || "monthly";
    if (!companyId || !employeeId || !/^\d{4}-\d{2}$/.test(period || "")) {
      status.textContent = "Seleccioná empresa, funcionario y mes para conciliar las novedades.";
      return;
    }
    status.textContent = "Consultando novedades registradas…";
    try {
      const query = new URLSearchParams({
        company_id: companyId, employee_id: employeeId, period, pay_basis: basis
      });
      const response = await fetch("/api/liquidaciones/novedades-salariales?" + query, {
        credentials: "same-origin", headers: {Accept: "application/json"}, signal: controller.signal
      });
      if (!response.ok) throw new Error("No se pudieron consultar las novedades.");
      const data = await response.json();
      if (id !== sequence) return;
      current = data;
      paid.textContent = String(data.unpaid_days);
      work.textContent = String(data.observed_worked_days);
      hours.textContent = String(data.observed_ordinary_hours);
      rows(events, data.events || [], e =>
        e.type + " · " + e.title + " · " + e.status + " · " + e.detail
      );
      rows(warnings, data.warnings || [], String);
      status.textContent = data.events?.length
        ? "Se encontraron " + data.events.length + " novedades del mes. Verificá las fuentes antes de aplicar cambios."
        : "No hay novedades registradas para este período. Mantené la asistencia real y el salario de la ficha.";
      controls();
    } catch (error) {
      if (id !== sequence || error.name === "AbortError") return;
      status.textContent = "No se pudo consultar la asistencia y las novedades. Continuá solo con datos comprobados.";
    }
  }

  applyPaid.addEventListener("click", () => {
    if (!current?.can_apply_paid_days) return;
    const target = input("days_paid");
    if (!target) return;
    target.value = String(current.suggested_paid_days);
    clearApproval();
    input("novelties_applied").value = "on";
    input("novelties_fingerprint").value = current.fingerprint;
    status.textContent = "Días remunerados propuestos desde ausencias sin goce aprobadas. Revisá el importe antes de guardar.";
    target.dispatchEvent(new Event("input", {bubbles: true}));
  });

  applyAttendance.addEventListener("click", () => {
    if (!current?.daily_attendance?.length || !complete.checked) return;
    if (input("attendance_source_id")?.value && !input("attendance_override")?.checked) {
      status.textContent = "Para reemplazar una asistencia heredada, activá «Editar asistencia cargada».";
      return;
    }
    input("days_worked").value = String(current.observed_worked_days);
    input("hours_worked").value = String(current.observed_ordinary_hours);
    if (input("pay_basis")?.value === "daily") {
      input("days_paid").value = String(current.observed_worked_days);
    }
    input("novelties_attendance_confirmed").value = "on";
    input("novelties_fingerprint").value = current.fingerprint;
    status.textContent = "Asistencia aplicada con confirmación expresa de cobertura completa. Revisá el salario antes de guardar.";
    form.dispatchEvent(new Event("input", {bubbles: true}));
  });

  complete.addEventListener("change", controls);
  input("month")?.addEventListener("change", refresh);
  input("pay_basis")?.addEventListener("change", refresh);
  for (const name of ["days_paid", "days_worked", "hours_worked"]) {
    input(name)?.addEventListener("change", () => {
      if (input("novelties_applied").value || input("novelties_attendance_confirmed").value) {
        clearApproval();
        status.textContent = "Cambiaste un dato conciliado: el ajuste ahora es manual. Revisá las cifras antes de guardar.";
      }
    });
  }
  refresh();
})();
