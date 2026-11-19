/* Read-only reconciliation of a visibly opened IPS/REI planilla. */
(() => {
  "use strict";
  const root = document.querySelector("[data-portal-reconcile]");
  if (!root) return;
  const button = document.getElementById("portalFetchIPS");
  const company = document.getElementById("portalCompany");
  const period = document.getElementById("portalPeriod");
  const feedback = document.getElementById("portalReconcileFeedback");
  const result = document.getElementById("portalReconcileResult");
  const summary = document.getElementById("portalReconcileSummary");
  const body = document.getElementById("portalReconcileBody");
  const notice = document.getElementById("portalReconcileNotice");
  const extensionId = root.dataset.extensionId;
  const money = value => Number.isSafeInteger(value) ? "₲ " + value.toLocaleString("es-PY") : "—";
  const displayed = value => value == null || String(value).trim() === "" ? "Pendiente" : String(value);
  const textNode = value => document.createTextNode(String(value));
  function el(tag, content = "", cls = "") {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    node.textContent = content;
    return node;
  }
  function cell(value, small = "", numeric = false) {
    const td = document.createElement("td");
    td.textContent = displayed(value);
    if (numeric) td.dataset.number = "true";
    if (small) td.append(el("small", small));
    return td;
  }
  function sendExtension(payload) {
    return new Promise((resolve, reject) => {
      const runtime = window.chrome?.runtime;
      if (!runtime?.sendMessage) {
        reject(new Error("Instalá la extensión de Digit Laboral en este perfil de Chrome."));
        return;
      }
      try {
        runtime.sendMessage(extensionId, payload, data => {
          if (runtime.lastError || !data) {
            reject(new Error("Actualizá la extensión Digit Laboral a 1.6.0 y abrí la planilla IPS en otra pestaña."));
          } else if (!data.ok) {
            reject(new Error(data.message || "La extensión no pudo leer la planilla visible."));
          } else {
            resolve(data);
          }
        });
      } catch (_) {
        reject(new Error("No se pudo contactar con la extensión de Chrome."));
      }
    });
  }
  function addStat(label, value) {
    const item = document.createElement("span");
    item.append(el("b", value), el("small", label));
    summary.append(item);
  }
  function render(data) {
    result.hidden = false;
    summary.replaceChildren();
    body.replaceChildren();
    addStat("Trabajadores en IPS", String(data.count));
    addStat("Legajos en empresa", String(data.counts.same_company));
    addStat("En empresas anteriores", String(data.counts.prior_company));
    addStat("Sin legajo", String(data.counts.not_found));
    addStat("Salarios aprobados", String(data.counts.approved));
    addStat("Pendientes", String(data.counts.pending));
    notice.textContent = data.notice || "";
    for (const worker of data.rows) {
      const tr = document.createElement("tr");
      const identity = cell(worker.name, "C.I. " + worker.document);
      const previous = worker.other_employers.map(x => x.name).join(", ");
      if (previous) identity.append(el("small", "Legajo previo: " + previous));
      tr.append(identity, cell(worker.movement || "No informado"));
      tr.append(cell(worker.days_ips, "Declarado en IPS", true));
      tr.append(cell(money(worker.salary_paid_ips), "Salario a pagar declarado IPS", true));
      tr.append(cell(money(worker.saved_gross), worker.salary_source, true));
      tr.append(cell(worker.salary_status, worker.employee_id ? "Legajo de la empresa" : "Sin legajo en esta empresa"));
      tr.append(cell(
        "Días: " + displayed(worker.days_actual) + " · Horas: " + displayed(worker.hours_actual),
        "Origen: " + worker.attendance_source,
      ));
      const missing = worker.missing.length ? "Falta: " + worker.missing.join(", ") : "Datos disponibles en Digit";
      tr.append(cell(
        "Medio: " + displayed(worker.payment_method) + " · Fecha: " + displayed(worker.payment_date),
        missing,
      ));
      const action = document.createElement("td");
      const link = document.createElement("a");
      link.href = worker.action.url;
      link.textContent = worker.action.label;
      action.append(link);
      tr.append(action);
      body.append(tr);
    }
    feedback.textContent = "Se conciliaron " + data.count + " trabajadores en modo lectura.";
  }
  button?.addEventListener("click", async () => {
    if (!company.value || !period.value) {
      feedback.textContent = "Elegí empresa y período antes de consultar IPS.";
      return;
    }
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    result.hidden = true;
    feedback.textContent = "Leyendo la planilla IPS visible en este Chrome…";
    try {
      const portal = await sendExtension({type: "read-ips-planilla", protocol: 1});
      if (!portal.snapshot) throw new Error("La extensión no encontró una planilla IPS visible.");
      feedback.textContent = "Comparando cédulas y patronal con Digit Laboral…";
      const response = await fetch("/app/compliance/portal-reconciliation/preview", {
        method: "POST", credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json",
          "X-CSRF-Token": root.dataset.csrf,
        },
        body: JSON.stringify({
          company_id: Number(company.value), period: period.value, snapshot: portal.snapshot,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(
        typeof data.detail === "string" ? data.detail : "No se pudo validar la planilla.",
      );
      render(data);
    } catch (error) {
      feedback.textContent = error.message || "No se pudo leer o conciliar la planilla.";
    } finally {
      button.disabled = false;
      button.removeAttribute("aria-busy");
    }
  });
})();
