(() => {
  "use strict";
  const root = document.querySelector(".dl-quick"), form = root?.querySelector("#labor-form");
  if (!form || form.elements.namedItem("kind")?.value !== "settlement") return;
  const field = name => form.elements.namedItem(name);
  const reason = field("reason"), regime = field("severance_regime"), average = field("average_salary");
  const salary = field("salary"), suggested = field("average_from_salary");
  const step = form.querySelector('[data-quick-step="2"]'), hint = form.querySelector("[data-average-salary-hint]");
  if (!reason || !regime || !average || !salary || !suggested) return;
  const initial = {suggested:suggested.value, hint:hint?.textContent || ""};
  let previousReason = reason.value, manuallyEdited = Boolean(average.value && suggested.value !== "on");
  const noIndemnity = () => ["resignation","justified"].includes(reason.value);
  const sync = () => {
    const inactive = noIndemnity() && regime.value !== "stability_double";
    average.disabled = inactive;
    field("notice_served").disabled = inactive;
    if (step) {
      step.hidden = inactive && !field("protected")?.checked;
      if (step.hidden) step.open = false;
    }
    if (hint) hint.hidden = suggested.value !== "on" || field("average_origin")?.value === "payroll";
    for (const name of ["protection_basis","protection_evidence"]) {
      const input = field(name);
      if (input) { input.disabled = !field("protected")?.checked; input.closest(".dl-field").hidden = input.disabled; }
    }
  };
  const suggest = () => {
    if (field("average_origin")?.value === "payroll" || noIndemnity()) return;
    if ((suggested.value === "on" || (!manuallyEdited && !average.value)) && salary.value) {
      average.value = salary.value;
      suggested.value = "on";
      if (hint) hint.textContent = "Sugerido del salario ingresado. Modificar si es necesario";
      average.dispatchEvent(new CustomEvent("input", {bubbles:true, detail:{salarySuggestion:true}}));
    }
  };
  const changeReason = () => {
    if (reason.value !== previousReason) {
      previousReason = reason.value;
      regime.value = "ordinary";
      field("notice_served").value = "0";
      for (const name of ["stability_basis","stability_evidence"]) if (field(name)) field(name).value = "";
      if (field("stability_confirmed")) field("stability_confirmed").checked = false;
      form.dispatchEvent(new CustomEvent("settlement:preset", {detail:{reason:reason.value}}));
      suggest();
    }
    sync();
  };
  const changed = event => {
    if (event.target === average && !event.detail?.salarySuggestion) {
      suggested.value = "";
      manuallyEdited = true;
    }
    if (event.target === salary) suggest();
    if (event.target === reason) changeReason();
    sync();
  };
  form.addEventListener("input", changed);
  form.addEventListener("change", changed);
  form.addEventListener("reset", () => setTimeout(() => {
    suggested.value = initial.suggested;
    if (hint) hint.textContent = initial.hint;
    previousReason = reason.value;
    manuallyEdited = Boolean(average.value && suggested.value !== "on");
    sync();
  },0));
  // Initial values may be copied from a saved calculation: preserve them.
  sync();
  if (!average.value && salary.value) suggest();
})();
