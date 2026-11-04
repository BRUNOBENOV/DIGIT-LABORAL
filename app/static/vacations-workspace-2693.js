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
      balance.textContent = valid ? String(remainder) + (remainder === 1 ? " día" : " días") : "—";
      panel?.classList.toggle("is-negative", negative);
      note.textContent = !hasEntitled
        ? "Completá los días concedidos para visualizar el saldo."
        : negative
          ? "Los días utilizados superan los concedidos. Revisá el movimiento."
          : "Saldo de este registro; no incluye otros períodos ni antecedentes DOS.";
      used.setCustomValidity(negative ? "Los días usados no pueden superar los días concedidos." : "");
      if (end) end.setCustomValidity(
        start?.value && end.value && end.value < start.value
          ? "La fecha de fin debe ser igual o posterior a la fecha de inicio."
          : ""
      );
    };
    ["input","change"].forEach(eventName => {
      [entitled, used, start, end].forEach(field => field?.addEventListener(eventName, update));
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
