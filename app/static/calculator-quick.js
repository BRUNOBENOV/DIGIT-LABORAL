(() => {
  "use strict";
  const root = document.querySelector(".dl-quick"), form = root?.querySelector("#labor-form");
  const panel = root?.querySelector("[data-live-summary]");
  if (!form || !panel) return;
  const status = panel.querySelector("[data-summary-status]"), badge = panel.querySelector("[data-summary-badge]");
  const total = panel.querySelector("[data-summary-total]"), review = panel.querySelector("[data-review-field]");
  const warnings = panel.querySelector("[data-summary-warnings]"), warningList = panel.querySelector("[data-summary-warning-list]");
  const money = value => "Gs. " + new Intl.NumberFormat("es-PY", {maximumFractionDigits:0}).format(value);
  const vacationDaysEntered = () => ["pending_days","double_days","proportional_days"].some(name => String(form.elements.namedItem(name)?.value || "").trim() !== "");
  let timer, controller, sequence = 0, pendingField = "", printWasOpen = false;
  const reveal = input => {
    for (let parent = input?.parentElement; parent && parent !== root; parent = parent.parentElement) {
      if (parent.tagName === "DETAILS") parent.open = true;
    }
  };
  const resetSummary = message => {
    panel.querySelectorAll("[data-summary-value]").forEach(output => { output.textContent = "—"; });
    root.querySelectorAll("[data-concept-amount]").forEach(output => { output.textContent = "Pendiente de revisión"; });
    panel.querySelector("[data-summary-label]").textContent = "Total a cobrar";
    total.classList.remove("is-partial");
    badge.textContent = "Pendiente";
    status.textContent = message;
    warnings.hidden = true;
    warningList.replaceChildren();
    pendingField = "";
    review.hidden = true;
  };
  const invalidField = () => Array.from(form.elements).find(input => input.willValidate && !input.validity.valid);
  const showPending = (message, name = "") => {
    resetSummary(message);
    pendingField = name;
    review.hidden = !form.elements.namedItem(name);
  };
  const load = async () => {
    const current = ++sequence;
    controller?.abort();
    const invalid = invalidField();
    if (invalid) {
      const label = form.querySelector(`label[for="${invalid.id}"]`)?.textContent.replace(/\s*\*\s*$/, "").trim() || "el dato indicado";
      showPending("Completá o corregí «" + label + "» para actualizar el resumen.", invalid.name);
      panel.setAttribute("aria-busy", "false");
      return;
    }
    controller = new AbortController();
    panel.setAttribute("aria-busy", "true");
    badge.textContent = "Calculando…";
    status.textContent = "Actualizando el resumen con el motor de cálculo…";
    const body = new URLSearchParams(new FormData(form));
    try {
      const response = await fetch(panel.dataset.previewUrl, {method:"POST", body, credentials:"same-origin", signal:controller.signal, headers:{Accept:"application/json"}});
      const data = await response.json();
      if (current !== sequence) return;
      if (!response.ok) {
        showPending(typeof data.error === "string" ? data.error : "No se pudo actualizar. Pulsá Calcular para revisar el formulario.", data.field || "");
        return;
      }
      panel.querySelectorAll("[data-summary-value]").forEach(output => {
        const key = output.dataset.summaryValue;
        output.textContent = key === "vacations" && !vacationDaysEntered() ? "Revisar días" : money(key === "net" ? data.net : data.values[key]);
      });
      root.querySelectorAll("[data-concept-amount]").forEach(output => {
        const key = output.dataset.conceptAmount;
        output.textContent = key === "vacations" && !vacationDaysEntered() ? "Sin días informados" : money(data.values[key]);
      });
      panel.querySelector("[data-summary-label]").textContent = data.label;
      total.classList.toggle("is-partial", data.partial);
      badge.textContent = data.partial ? "Parcial" : "Vista previa";
      status.textContent = data.partial
        ? "Subtotal parcial: revisá el régimen y los conceptos pendientes antes de emitir."
        : "Vista previa actualizada. Pulsá Calcular o Recalcular para habilitar el documento.";
      warningList.replaceChildren();
      for (const message of data.warnings) {
        const li = document.createElement("li"); li.textContent = message; warningList.appendChild(li);
      }
      warnings.hidden = data.warnings.length === 0;
      warnings.querySelector("[data-summary-warning-count]").textContent = "Revisiones pendientes · " + data.warnings.length;
      pendingField = ""; review.hidden = true;
      // Preview never enables save, print or download of an older document.
    } catch (error) {
      if (error.name !== "AbortError" && current === sequence) showPending("No se pudo actualizar el resumen. Podés pulsar Calcular para obtener el resultado.");
    } finally {
      if (current === sequence) panel.setAttribute("aria-busy", "false");
    }
  };
  const changed = () => {
    clearTimeout(timer); ++sequence; controller?.abort();
    if (panel.dataset.hasResult === "true") {
      document.body.classList.add("dl-form-dirty");
      root.querySelectorAll("[data-result-action]").forEach(button => { button.disabled = true; });
      const notice = panel.querySelector(".dl-stale");
      if (notice) notice.hidden = false;
    }
    resetSummary("Datos modificados. Actualizando vista previa…");
    panel.setAttribute("aria-busy", "false");
    timer = setTimeout(load,300);
  };
  form.addEventListener("input", changed);
  form.addEventListener("change", changed);
  form.addEventListener("reset", () => { clearTimeout(timer); ++sequence; controller?.abort(); setTimeout(changed,0); });
  form.addEventListener("invalid", event => reveal(event.target), true);
  form.addEventListener("submit", () => { clearTimeout(timer); ++sequence; controller?.abort(); });
  review.addEventListener("click", () => {
    const input = form.elements.namedItem(pendingField);
    if (!input) return;
    reveal(input); input.focus(); input.scrollIntoView({block:"center", behavior:"auto"});
  });
  root.querySelectorAll(".dl-help-trigger").forEach(button => {
    button.addEventListener("click", () => button.setAttribute("aria-expanded", String(button.getAttribute("aria-expanded") !== "true")));
    button.addEventListener("blur", () => button.setAttribute("aria-expanded", "false"));
    button.addEventListener("keydown", event => { if (event.key === "Escape") button.setAttribute("aria-expanded", "false"); });
  });
  root.querySelectorAll("[data-open-document]").forEach(button => button.addEventListener("click", () => {
    if (document.body.classList.contains("dl-form-dirty")) return;
    const documentPanel = root.querySelector("#labor-document");
    if (documentPanel) { documentPanel.open = true; documentPanel.scrollIntoView({block:"start",behavior:"auto"}); }
  }));
  document.addEventListener("keydown", event => {
    if (event.key !== "F6" || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey || event.target.closest?.('[role="dialog"],dialog')) return;
    event.preventDefault();
    form.requestSubmit(panel.querySelector("[data-quick-calculate]"));
  });
  window.addEventListener("beforeprint", () => {
    const documentPanel = root.querySelector("#labor-document");
    if (documentPanel) { printWasOpen = documentPanel.open; documentPanel.open = true; }
  });
  window.addEventListener("afterprint", () => {
    const documentPanel = root.querySelector("#labor-document");
    if (documentPanel) documentPanel.open = printWasOpen;
  });
  const compact = window.matchMedia("(max-width: 900px)");
  const syncBreakdown = () => { panel.querySelector(".dl-summary-breakdown").open = !compact.matches; };
  compact.addEventListener("change", syncBreakdown); syncBreakdown();
  root.classList.add("dl-quick-ready");
  const invalid = form.querySelector(".dl-invalid input,.dl-invalid select,.dl-invalid textarea");
  if (invalid) reveal(invalid);
  if (panel.dataset.hasResult !== "true") load();
})();
