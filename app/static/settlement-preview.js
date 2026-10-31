(() => {
  "use strict";
  const form = document.getElementById("labor-form");
  if (!form) return;
  const projectionFields = ["start_date", "end_date", "reason", "indefinite", "trial_completed",
    "protected", "average_salary", "notice_served", "severance_regime"];
  const confirmationFields = new Set([...projectionFields, "stability_basis", "stability_evidence"]);
  const money = value => "Gs. " + new Intl.NumberFormat("es-PY").format(value);

  form.querySelectorAll("[data-settlement-preview]").forEach(panel => {
    const prefix = panel.dataset.prefix || "";
    const field = name => form.elements.namedItem(prefix + name);
    const status = panel.querySelector("[data-settlement-status]");
    let timer, controller, sequence = 0, projection = null;
    const write = (key, value) => {
      const output = panel.querySelector(`[data-settlement-value="${key}"]`);
      if (output) output.textContent = value;
    };
    const needsConfirmation = () => field("severance_regime")?.value === "stability_double";
    const hasConfirmation = () => field("stability_confirmed")?.checked
      && Boolean(field("stability_basis")?.value)
      && (field("stability_evidence")?.value.trim().length || 0) >= 10;
    const syncFields = () => {
      const needed = needsConfirmation();
      ["stability_basis", "stability_evidence", "stability_confirmed"].forEach(name => {
        const input = field(name);
        if (!input) return;
        input.disabled = !needed;
        input.required = needed;
        input.closest(".dl-field").hidden = !needed;
      });
      if (field("stability_evidence")) field("stability_evidence").minLength = needed ? 10 : 0;
      const review = field("stability_basis")?.closest("[data-regime-review]");
      if (review) review.hidden = !needed;
    };
    const updateStatus = () => {
      if (!projection) return;
      const messages = {
        review: `${projection.units} años computables: indemnización ordinaria de referencia ${projection.ordinary_days} días; doble ${projection.ordinary_days * 2} días. Seleccioná el régimen por estabilidad y documentá su fundamento para incluirlo en el total.`,
        special: "Hay protección adicional o contrato no indefinido. Revisá su régimen: esta proyección no incorpora indemnización ni preaviso.",
        probation: "Confirmá si se cumplió el período de prueba para calcular los conceptos de despido.",
        not_applicable: "La causal elegida no activa automáticamente indemnización ni preaviso a cargo del empleador.",
        ordinary: "Días calculados automáticamente. Pulsá Calcular o Recalcular para incorporarlos al resultado.",
        stability_double: hasConfirmation()
          ? "Doble indemnización confirmada para el cálculo. Pulsá Calcular o Recalcular para sumar ambos conceptos al resultado."
          : "Proyección de doble indemnización. Completá el fundamento y el respaldo y confirmá su revisión para incluirla en el total."
      };
      status.textContent = messages[projection.status] || "Revisá el régimen antes de calcular.";
      if (projection.multiplier && !(Number(projection.average) > 0)) {
        status.textContent += " Ingresá el promedio salarial para obtener los importes.";
      }
    };
    const clearProjection = () => {
      projection = null;
      panel.querySelectorAll("output").forEach(output => { output.textContent = "—"; });
    };
    const load = async () => {
      const current = ++sequence;
      controller?.abort();
      clearProjection();
      if (!field("start_date")?.value || !field("end_date")?.value) {
        panel.setAttribute("aria-busy", "false");
        status.textContent = "Completá las fechas de ingreso y egreso para calcular los días automáticamente.";
        return;
      }
      controller = new AbortController();
      panel.setAttribute("aria-busy", "true");
      status.textContent = "Calculando días e importes…";
      const body = new URLSearchParams({kind: "settlement"});
      body.set("csrf_token", form.elements.namedItem("csrf_token")?.value || "");
      projectionFields.forEach(name => {
        const input = field(name);
        body.set(name, input?.type === "checkbox" ? (input.checked ? "on" : "") : input?.value || "");
      });
      try {
        const response = await fetch("/herramientas/liquidacion/previsualizar", {
          method: "POST", body, credentials: "same-origin", signal: controller.signal,
          headers: {"Accept": "application/json"}
        });
        const data = await response.json();
        if (current !== sequence) return;
        if (!response.ok) {
          status.textContent = data.error || "Revisá los datos o pulsá Recalcular para ver el detalle.";
          return;
        }
        projection = data;
        ["units", "days", "notice_due", "notice_payable"].forEach(key => write(key, data[key] ?? "Pendiente"));
        write("daily_base", Number(data.average) > 0 ? "Gs. " + data.daily_base : "Pendiente");
        ["severance", "notice"].forEach(key => write(key, data[key] == null ? "Pendiente" : money(data[key])));
        updateStatus();
      } catch (error) {
        if (error.name !== "AbortError" && current === sequence) {
          status.textContent = "No se pudo actualizar la vista previa. Podés pulsar Calcular o Recalcular para obtener el resultado.";
        }
      } finally {
        if (current === sequence) panel.setAttribute("aria-busy", "false");
      }
    };
    const changed = event => {
      if (event.detail?.copiedScenario && event.detail.copiedScenario !== prefix) return;
      const name = event.target.name?.startsWith(prefix) ? event.target.name.slice(prefix.length) : "";
      if (!confirmationFields.has(name) && name !== "stability_confirmed" && !event.detail?.copiedScenario) return;
      if (confirmationFields.has(name) || event.detail?.copiedScenario) field("stability_confirmed").checked = false;
      syncFields();
      if (["stability_basis", "stability_evidence", "stability_confirmed"].includes(name)) {
        updateStatus();
        return;
      }
      clearTimeout(timer);
      ++sequence;
      controller?.abort();
      panel.setAttribute("aria-busy", "false");
      clearProjection();
      status.textContent = "Actualizando la proyección…";
      timer = setTimeout(load, 300);
    };
    form.addEventListener("input", changed);
    form.addEventListener("change", changed);
    form.addEventListener("reset", () => {
      clearTimeout(timer);
      ++sequence;
      controller?.abort();
      setTimeout(() => { syncFields(); load(); }, 0);
    });
    syncFields();
    load();
  });
})();
