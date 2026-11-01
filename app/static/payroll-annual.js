(() => {
  "use strict";
  const panel = document.querySelector("[data-payroll-annual-panel]"), form = panel?.closest("form");
  if (!form) return;
  const field = name => form.elements.namedItem(name);
  const annual = field("annual_remuneration"), origin = field("annual_origin"), fingerprint = field("annual_payroll_fingerprint");
  const status = panel.querySelector("[data-annual-status]"), manual = panel.querySelector("[data-annual-manual]");
  const isPrivate = panel.dataset.private === "true";
  const initial = {origin:origin.value, fingerprint:fingerprint.value};
  const money = value => value == null ? "—" : "Gs. " + new Intl.NumberFormat("es-PY", {maximumFractionDigits:0}).format(value);
  let sequence = 0, controller, timer, accrualSequence = 0, accrualController, accrualTimer, applying = false, known = null;
  const emit = () => form.dispatchEvent(new CustomEvent("settlement:annual", {detail:known}));
  const sync = () => {
    annual.readOnly = origin.value === "payroll";
    if (manual) manual.hidden = origin.value !== "payroll";
  };
  const editor = () => form.querySelector('[data-concept-editor="aguinaldo"]');
  const invalidateAccrual = () => {
    clearTimeout(accrualTimer); ++accrualSequence; accrualController?.abort();
    known = null; emit();
  };
  const updateAccrual = async () => {
    const current = ++accrualSequence, value = annual.value;
    accrualController?.abort();
    if (!value || !annual.validity.valid) return;
    accrualController = new AbortController();
    const body = new URLSearchParams({kind:"settlement", annual_remuneration:value, csrf_token:field("csrf_token")?.value || ""});
    try {
      const response = await fetch("/herramientas/aguinaldo/previsualizar", {method:"POST", body, credentials:"same-origin", signal:accrualController.signal, headers:{Accept:"application/json"}});
      const data = await response.json();
      if (current !== accrualSequence || value !== annual.value || !response.ok) return;
      known = {value, accrued:data.aguinaldo_accrued}; emit();
    } catch (error) {
      if (error.name !== "AbortError" && current === accrualSequence && status) status.textContent = "No se pudo actualizar el aguinaldo. Pulsá Recalcular para verificar el importe.";
    }
  };
  const makeManual = () => { origin.value = "manual"; fingerprint.value = ""; sync(); };
  const apply = data => {
    const unchanged = origin.value === "payroll" && fingerprint.value === data.fingerprint && annual.value === String(data.annual_remuneration);
    invalidateAccrual();
    applying = true;
    annual.value = String(data.annual_remuneration);
    origin.value = "payroll"; fingerprint.value = data.fingerprint;
    sync();
    if (!unchanged) annual.dispatchEvent(new Event("input", {bubbles:true}));
    applying = false;
    known = {value:annual.value, accrued:data.aguinaldo_accrued}; emit();
    editor().querySelector("summary").textContent = "Ver remuneración anual y pagos previos";
  };
  const showSources = data => {
    const body = panel.querySelector("[data-annual-periods]"); body.replaceChildren();
    for (const row of data.periods) {
      const tr = document.createElement("tr");
      for (const value of [row.period, money(row.remuneration), row.status]) {
        const td = document.createElement("td"); td.textContent = value; tr.appendChild(td);
      }
      if (Number.isInteger(row.payroll_id) && row.payroll_id > 0) {
        const link = document.createElement("a"); link.href = "/app/payrolls/" + row.payroll_id; link.textContent = row.period;
        tr.firstChild.replaceChildren(link);
      }
      body.appendChild(tr);
    }
    panel.querySelector("[data-annual-coverage]").textContent = `${data.window_start} a ${data.window_end} · ${data.included_count} de ${data.expected_count} períodos computables · ${data.is_complete ? "Cobertura completa" : "Cobertura parcial"}`;
    panel.querySelector("[data-annual-methodology]").textContent = data.methodology;
  };
  const load = async (force = false) => {
    clearTimeout(timer);
    const current = ++sequence; controller?.abort();
    const names = ["company_id","employee_id","start_date","end_date"];
    if (names.some(name => !field(name)?.value || field(name).value === "0")) {
      status.textContent = "Seleccioná empresa y funcionario y completá las fechas para consultar las nóminas del año.";
      return;
    }
    controller = new AbortController(); panel.setAttribute("aria-busy","true");
    status.textContent = "Consultando remuneraciones del año…";
    const params = new URLSearchParams(names.map(name => [name,field(name).value]));
    try {
      const response = await fetch("/api/liquidaciones/remuneracion-anual?" + params, {credentials:"same-origin", signal:controller.signal, headers:{Accept:"application/json"}});
      const data = await response.json();
      if (current !== sequence) return;
      if (!response.ok) { status.textContent = typeof data.detail === "string" ? data.detail : "No se pudieron consultar las nóminas. Revisá las fechas."; return; }
      showSources(data);
      if (data.is_available && (force || origin.value !== "manual")) {
        apply(data);
        status.textContent = data.is_complete
          ? "Remuneración anual calculada desde nóminas cerradas. Podés desbloquearla para editar."
          : data.warnings.join(" ");
      } else {
        status.textContent = data.is_available
          ? "Ingreso manual conservado. Pulsá Calcular desde nóminas para reemplazarlo por la suma disponible. " + data.warnings.join(" ")
          : data.warnings.join(" ") || "No hay períodos computables. Revisá el detalle e ingresá el monto según los recibos.";
        if (!annual.value) editor().open = true;
      }
    } catch (error) {
      if (error.name !== "AbortError" && current === sequence) status.textContent = "No se pudieron consultar las nóminas. Podés ingresar el monto manualmente según los recibos.";
    } finally { if (current === sequence) panel.setAttribute("aria-busy","false"); }
  };
  panel.querySelector("[data-annual-load]")?.addEventListener("click", () => load(true));
  manual?.addEventListener("click", () => {
    ++sequence; controller?.abort(); panel.setAttribute("aria-busy","false"); makeManual();
    editor().open = true; annual.focus();
    status.textContent = "Ingreso manual habilitado. Revisá el total anual según los recibos.";
    applying = true; annual.dispatchEvent(new Event("input", {bubbles:true})); applying = false;
  });
  form.addEventListener("input", event => {
    if (event.target !== annual || applying) return;
    ++sequence; controller?.abort(); panel.setAttribute("aria-busy","false");
    makeManual(); invalidateAccrual();
    if (status) status.textContent = "Remuneración anual ingresada manualmente según los recibos.";
    accrualTimer = setTimeout(updateAccrual,500);
  });
  const changedContext = event => {
    if (!["start_date","end_date","company_id","employee_id"].includes(event.target.name)) return;
    clearTimeout(timer); ++sequence; controller?.abort();
    if (origin.value === "payroll") {
      annual.value = ""; origin.value = "auto"; fingerprint.value = ""; sync(); invalidateAccrual();
      applying = true; annual.dispatchEvent(new Event("input", {bubbles:true})); applying = false;
    }
    if (isPrivate) {
      panel.querySelector("[data-annual-periods]").replaceChildren();
      panel.querySelector("[data-annual-coverage]").textContent = "Actualizando intervalo…";
      status.textContent = "Cambiaste el intervalo. Consultando sus nóminas; revisá cualquier importe manual.";
      timer = setTimeout(() => load(),300);
    }
  };
  form.addEventListener("input", changedContext); form.addEventListener("change", changedContext);
  form.addEventListener("settlement:request-annual", emit);
  form.addEventListener("reset", () => {
    clearTimeout(timer); ++sequence; controller?.abort(); invalidateAccrual();
    setTimeout(() => {
      origin.value = initial.origin; fingerprint.value = initial.fingerprint;
      if (origin.value === "auto" && annual.value) makeManual();
      sync(); updateAccrual(); if (isPrivate) load();
    },0);
  });
  if (origin.value === "auto" && annual.value) makeManual();
  sync(); updateAccrual(); if (isPrivate) load();
})();
