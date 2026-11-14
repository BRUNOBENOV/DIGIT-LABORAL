(() => {
  "use strict";
  const root = document.querySelector(".dl-quick"), form = root?.querySelector("#labor-form");
  if (!form || form.elements.namedItem("kind")?.value !== "settlement") return;
  const field = name => form.elements.namedItem(name);
  const reason = field("reason"), regime = field("severance_regime"), average = field("average_salary");
  const salary = field("salary"), suggested = field("average_from_salary");
  const automaticStability = field("settlement_preset_version")?.value === "2";
  const stabilityNote = form.querySelector("[data-stability-detected]"), judicialPanel = form.querySelector("[data-judicial-review]");
  const judicial = field("judicial_confirmed"), judicialFiles = form.querySelector("[data-judicial-files]");
  const step = form.querySelector('[data-quick-step="2"]'), hint = form.querySelector("[data-average-salary-hint]");
  if (!reason || !regime || !average || !salary || !suggested) return;
  const initial = {suggested:suggested.value, hint:hint?.textContent || ""};
  let previousReason = reason.value, manuallyEdited = Boolean(average.value && suggested.value !== "on");
  const noIndemnity = () => ["resignation","justified"].includes(reason.value);
  const serviceYears = () => {
    const start = field("start_date")?.value, end = field("end_date")?.value;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(start || "") || !/^\d{4}-\d{2}-\d{2}$/.test(end || "") || end < start) return null;
    const [year,month,day] = start.split("-").map(Number), endYear = Number(end.slice(0,4));
    const anniversary = new Date(Date.UTC(endYear,month-1,Math.min(day,new Date(Date.UTC(endYear,month,0)).getUTCDate()))).toISOString().slice(0,10);
    return endYear-year-(end < anniversary ? 1 : 0);
  };
  const stable = () => (serviceYears() ?? -1) >= 10;
  const chooseRegime = () => {
    regime.value = automaticStability && reason.value === "dismissal" && stable()
      ? (field("indefinite")?.checked && field("trial_completed")?.checked && !field("protected")?.checked ? "stability_double" : "auto")
      : "ordinary";
  };
  const sync = () => {
    const inactive = noIndemnity() && regime.value !== "stability_double";
    const daily = field("pay_basis")?.value === "daily";
    average.disabled = inactive || daily;
    for (const name of ["indemnity_daily_base","indemnity_daily_evidence"]) {
      const input = field(name);
      if (!input) continue;
      input.disabled = inactive || !daily;
      input.required = !input.disabled;
      input.closest(".dl-field").hidden = !daily;
    }
    field("notice_served").disabled = inactive;
    if (step) {
      step.hidden = inactive && !field("protected")?.checked && !(automaticStability && stable() && reason.value === "justified");
      if (step.hidden) step.open = false;
    }
    if (stabilityNote) {
      stabilityNote.hidden = !stable();
      stabilityNote.textContent = `${serviceYears()} años completos según las fechas declaradas. Revisá continuidad con el mismo empleador (art. 94). `
        + (regime.value === "stability_double" ? "Se muestra el escenario doble; su procedencia requiere confirmación y respaldo."
          : reason.value === "justified" ? "La causa justa del trabajador estable exige sentencia firme previa al despido. La indemnización y el preaviso por despido injustificado quedan en cero, pendientes de revisión."
          : "La estabilidad por antigüedad se revisa automáticamente y es independiente de la casilla de otras protecciones.");
    }
    const judicialVisible = automaticStability && stable() && ["dismissal","justified"].includes(reason.value);
    if (judicialPanel) judicialPanel.hidden = !judicialVisible;
    if (judicial) { judicial.disabled = !judicialVisible; judicial.closest(".dl-field").hidden = !judicialVisible; }
    const judicialNeeded = judicialVisible && judicial?.checked && reason.value === "justified";
    for (const name of ["judicial_date","judicial_reference","judicial_document_id"]) {
      const input = field(name);
      if (!input) continue;
      input.disabled = !judicialNeeded || (name === "judicial_document_id" && !field("employee_id"));
      input.required = judicialNeeded && !input.disabled;
      input.closest(".dl-field").hidden = !judicialNeeded;
    }
    if (judicialFiles) judicialFiles.hidden = !judicialNeeded;
    if (hint) hint.hidden = suggested.value !== "on" || field("average_origin")?.value === "payroll";
    for (const name of ["protection_basis","protection_evidence"]) {
      const input = field(name);
      if (input) { input.disabled = !field("protected")?.checked; input.closest(".dl-field").hidden = input.disabled; }
    }
  };
  const suggest = () => {
    if (field("pay_basis")?.value === "daily" || field("average_origin")?.value === "payroll" || noIndemnity()) return;
    if ((suggested.value === "on" || (!manuallyEdited && !average.value)) && salary.value) {
      average.value = salary.value;
      suggested.value = "on";
      if (hint) hint.textContent = "Sugerido del salario ingresado. Modificar si es necesario";
      average.dispatchEvent(new CustomEvent("input", {bubbles:true, detail:{salarySuggestion:true}}));
    }
  };
  const changeReason = (preserveJudicial = false) => {
    if (reason.value !== previousReason) {
      previousReason = reason.value;
      chooseRegime();
      field("notice_served").value = "0";
      for (const name of ["stability_basis","stability_evidence"]) if (field(name)) field(name).value = "";
      if (field("stability_confirmed")) field("stability_confirmed").checked = false;
      if (!preserveJudicial && judicial) {
        judicial.checked = false;
        for (const name of ["judicial_date","judicial_reference","judicial_document_id","judicial_document_sha256"]) if (field(name)) field(name).value = "";
      }
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
    if (event.target === field("pay_basis") && field("pay_basis")?.value === "daily" && suggested.value === "on") {
      average.value = "";
      suggested.value = "";
    }
    if (event.target === salary) suggest();
    if (event.target === judicial && judicial.checked && automaticStability && stable()) {
      reason.value = "justified";
      reason.dispatchEvent(new CustomEvent("change", {bubbles:true,detail:{judicialPreset:true}}));
    }
    if (event.target === reason) changeReason(Boolean(event.detail?.judicialPreset));
    if (automaticStability && ["start_date","end_date","indefinite","trial_completed","protected"].includes(event.target.name)) {
      chooseRegime();
      if (judicial) judicial.checked = false;
    }
    if (automaticStability && event.target === regime && ((stable() && regime.value === "ordinary" && reason.value === "dismissal") || (!stable() && regime.value === "stability_double"))) chooseRegime();
    if (event.target.name === "judicial_document_id" && field("judicial_document_sha256")) field("judicial_document_sha256").value = "";
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
  if (field("pay_basis")?.value !== "daily" && !average.value && salary.value) suggest();
  let documentsSequence = 0, documentsController;
  form.querySelector("[data-refresh-judicial]")?.addEventListener("click", async () => {
    const current = ++documentsSequence; documentsController?.abort(); documentsController = new AbortController();
    const status = form.querySelector("[data-judicial-status]"), select = field("judicial_document_id");
    status.textContent = "Consultando documentos del funcionario…";
    try {
      const params = new URLSearchParams({company_id:field("company_id").value,employee_id:field("employee_id").value});
      if (select.value) params.set("document_id",select.value);
      const response = await fetch("/api/liquidaciones/documentos-judiciales?" + params, {credentials:"same-origin",signal:documentsController.signal,headers:{Accept:"application/json"}});
      const data = await response.json();
      if (current !== documentsSequence) return;
      if (!response.ok) throw new Error("Documents unavailable");
      const previous = select.value;
      select.replaceChildren(new Option("Seleccioná un documento del funcionario",""));
      for (const item of data.items) select.add(new Option(item.label,String(item.id)));
      select.value = previous;
      if (select.value !== previous) select.dispatchEvent(new Event("change",{bubbles:true}));
      status.textContent = data.items.length ? "Documentos actualizados. Seleccioná la sentencia revisada." : "No hay PDF o imágenes adjuntos para este funcionario.";
    } catch (error) {
      if (error.name !== "AbortError" && current === documentsSequence) status.textContent = "No se pudieron actualizar los documentos. Podés volver a intentarlo.";
    }
  });
})();
