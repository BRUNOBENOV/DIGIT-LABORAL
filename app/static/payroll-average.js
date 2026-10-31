(() => {
  "use strict";
  const panel = document.querySelector("[data-payroll-average-panel]");
  const form = panel?.closest("form");
  if (!form) return;
  const field = name => form.elements.namedItem(name);
  const amount = field("average_salary"), origin = field("average_origin");
  const fingerprint = field("average_payroll_fingerprint"), reviewed = field("average_payroll_reviewed");
  const apply = panel.querySelector("[data-average-apply]"), manual = panel.querySelector("[data-average-manual]");
  const status = panel.querySelector("[data-average-status]"), body = panel.querySelector("[data-average-periods]");
  const initial = {origin:origin.value, fingerprint:fingerprint.value, reviewed:reviewed.checked};
  let proposal = null, sequence = 0, controller, timer, applying = false;
  const money = (value, decimals = 0) => value == null ? "—" : "Gs. " + new Intl.NumberFormat("es-PY", {minimumFractionDigits: decimals, maximumFractionDigits: decimals}).format(Number(value));
  const sync = () => {
    amount.readOnly = origin.value === "payroll";
    manual.hidden = origin.value !== "payroll";
    reviewed.disabled = !proposal?.is_available;
    reviewed.required = origin.value === "payroll";
    apply.disabled = !proposal?.is_available || !reviewed.checked;
  };
  const makeManual = () => {
    origin.value = "manual";
    fingerprint.value = "";
    reviewed.checked = false;
    sync();
  };
  const showRows = data => {
    body.replaceChildren();
    for (const row of data.periods) {
      const tr = document.createElement("tr");
      const values = [row.period, ...["base_salary","overtime","commissions","bonuses","other_income"].map(key => money(row.components?.[key])), money(row.absences), money(row.remuneration), row.status];
      for (const value of values) {
        const td = document.createElement("td");
        td.textContent = value;
        tr.appendChild(td);
      }
      if (Number.isInteger(row.payroll_id) && row.payroll_id > 0) {
        const link = document.createElement("a");
        link.href = "/app/payrolls/" + row.payroll_id;
        link.textContent = row.period;
        tr.firstChild.replaceChildren(link);
      }
      body.appendChild(tr);
    }
  };
  const load = async () => {
    const current = ++sequence;
    controller?.abort();
    proposal = null;
    sync();
    body.replaceChildren();
    panel.querySelector("[data-average-amount]").textContent = "Sin propuesta";
    panel.querySelector("[data-average-coverage]").textContent = "—";
    panel.setAttribute("aria-busy","false");
    const names = ["company_id", "employee_id", "start_date", "end_date"];
    if (names.some(name => !field(name)?.value || field(name).value === "0")) {
      status.textContent = "Seleccioná empresa y funcionario y completá las fechas para consultar los períodos disponibles.";
      return;
    }
    const params = new URLSearchParams(names.map(name => [name, field(name).value]));
    controller = new AbortController();
    panel.setAttribute("aria-busy", "true");
    status.textContent = "Consultando nóminas del funcionario…";
    try {
      const response = await fetch("/api/liquidaciones/promedio-salarial?" + params, {credentials:"same-origin", signal:controller.signal, headers:{Accept:"application/json"}});
      const data = await response.json();
      if (current !== sequence) return;
      if (!response.ok) {
        status.textContent = typeof data.detail === "string" ? data.detail : "Revisá la selección y las fechas para consultar el promedio.";
        return;
      }
      proposal = data;
      if (fingerprint.value !== data.fingerprint) reviewed.checked = false;
      panel.querySelector("[data-average-coverage]").textContent = `${data.closed_count} de ${data.expected_count}`;
      panel.querySelector("[data-average-amount]").textContent = data.is_available ? money(data.average_salary,2) : "No disponible";
      panel.querySelector("[data-average-methodology]").textContent = data.methodology + " " + data.review_note;
      showRows(data);
      status.textContent = data.is_available
        ? `Intervalo: ${data.window_start} a ${data.window_end}. Revisá los conceptos antes de usar la propuesta.`
        : data.blockers.join(" ");
      if (origin.value === "payroll") {
        status.textContent += fingerprint.value === data.fingerprint
          ? " El promedio aplicado conserva estas fuentes."
          : " Las fuentes cambiaron: aplicá nuevamente la propuesta o elegí ingreso manual.";
      }
      sync();
    } catch (error) {
      if (error.name !== "AbortError" && current === sequence) status.textContent = "No se pudieron consultar las nóminas. Podés completar el promedio manualmente con su respaldo.";
    } finally {
      if (current === sequence) panel.setAttribute("aria-busy","false");
    }
  };
  apply.addEventListener("click", () => {
    if (!proposal?.is_available || !reviewed.checked) return;
    applying = true;
    amount.value = proposal.average_salary;
    origin.value = "payroll";
    fingerprint.value = proposal.fingerprint;
    amount.dispatchEvent(new Event("input", {bubbles:true}));
    applying = false;
    sync();
    status.textContent = "Promedio aplicado desde las nóminas revisadas. Pulsá Calcular o Recalcular para actualizar la liquidación.";
  });
  manual.addEventListener("click", () => {
    makeManual();
    amount.dispatchEvent(new Event("input", {bubbles:true}));
    amount.focus();
    status.textContent = "Promedio en modo manual. Revisá el importe y su respaldo antes de recalcular.";
  });
  reviewed.addEventListener("change", sync);
  form.addEventListener("input", event => {
    if (event.target === amount && !applying) makeManual();
  });
  const changed = event => {
    if (!["start_date","end_date"].includes(event.target.name)) return;
    clearTimeout(timer);
    ++sequence;
    controller?.abort();
    makeManual();
    proposal = null;
    sync();
    panel.setAttribute("aria-busy","false");
    panel.querySelector("[data-average-amount]").textContent = "Actualizando…";
    body.replaceChildren();
    status.textContent = "Cambiaste las fechas. Revisá y aplicá una nueva propuesta para ese intervalo.";
    timer = setTimeout(load,300);
  };
  form.addEventListener("input", changed);
  form.addEventListener("change", changed);
  form.addEventListener("reset", () => {
    clearTimeout(timer); ++sequence; controller?.abort();
    setTimeout(() => {
      origin.value = initial.origin;
      fingerprint.value = initial.fingerprint;
      reviewed.checked = initial.reviewed;
      load();
    },0);
  });
  sync();
  load();
})();
