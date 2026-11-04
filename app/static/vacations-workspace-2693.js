/* Vacaciones · balance visual y validación de formulario sin alterar cálculos guardados */
(() => {
  "use strict";
  const init = () => {
    const form = document.getElementById("vacationFormV24");
    if (!form || form.dataset.vacationsUxReady === "true") return;
    form.dataset.vacationsUxReady = "true";
    const entitled = form.elements.namedItem("entitled_days");
    const used = form.elements.namedItem("used_days");
    const start = form.elements.namedItem("start_date");
    const end = form.elements.namedItem("end_date");
    const status = form.elements.namedItem("status");
    const balance = form.querySelector("[data-vac-balance-preview]");
    const note = form.querySelector("[data-vac-balance-note]");
    const panel = form.querySelector(".vac-modal-balance");
    const update = () => {
      if (!entitled || !used || !balance || !note) return;
      const hasEntitled = entitled.value.trim() !== "";
      const hasUsed = used.value.trim() !== "";
      const rights = Number(entitled.value);
      const taken = Number(used.value);
      const valid = hasEntitled && hasUsed &&
        Number.isInteger(rights) && Number.isInteger(taken) &&
        rights >= 0 && taken >= 0 && rights <= 365 && taken <= 365;
      const remainder = rights - taken;
      const negative = valid && remainder < 0;
      const isCompleted = status?.value === "Completada";
      const requiresDates = ["Aprobada", "Completada"].includes(status?.value);
      const datesMissing = requiresDates && (!start?.value || !end?.value);
      const datesIncomplete = Boolean(start?.value) !== Boolean(end?.value);
      const invalidUsage = isCompleted ? valid && taken === 0 : valid && taken > 0;
      balance.textContent = valid ? String(remainder) + (remainder === 1 ? " día" : " días") : "—";
      panel?.classList.toggle("is-negative", negative || invalidUsage);
      note.textContent = !hasEntitled
        ? "Completá los días concedidos para visualizar el saldo."
        : negative
          ? "Los días utilizados superan los concedidos. Revisá el movimiento."
          : invalidUsage
            ? (isCompleted ? "Para completar el movimiento indicá los días efectivamente usados."
                : "Los días utilizados solo se registran cuando el estado es Completada.")
            : "Saldo de este registro; no incluye otros períodos ni antecedentes DOS.";
      used.setCustomValidity(
        negative ? "Los días usados no pueden superar los días concedidos." :
        invalidUsage ? (isCompleted ? "Completá los días utilizados." : "Solo un movimiento completado puede tener días utilizados.") : ""
      );
      if (end) end.setCustomValidity(
        datesIncomplete ? "Completá ambas fechas o dejá ambas sin ingresar." :
        datesMissing ? "El estado seleccionado requiere ambas fechas." :
        start?.value && end.value && end.value < start.value
          ? "La fecha de fin debe ser igual o posterior a la fecha de inicio."
          : ""
      );
    };
    ["input","change"].forEach(eventName => {
      [entitled, used, start, end, status].forEach(field => field?.addEventListener(eventName, update));
    });
    // La sugerencia legal de v24.js escribe el valor de días en el mismo select.
    [form.elements.namedItem("employee_id"), form.elements.namedItem("period_year")]
      .forEach(field => field?.addEventListener("change", update));
    form.addEventListener("submit", event => {
      update();
      if (!form.checkValidity()) {
        event.preventDefault();
        form.reportValidity();
      }
    });
    update();
  };
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", init, {once:true});
  else init();
  window.addEventListener("pageshow", init);
})();
