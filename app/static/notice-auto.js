/* Preaviso: server-calculated calendar days; exact money, no automatic writes. */
(() => {
  'use strict';
  const form = document.querySelector('[data-notice-auto]');
  if (!form) return;
  const byId = id => document.getElementById(id);
  const salary = byId('calcNoticeSalary');
  const days = byId('calcNoticeDays');
  const reference = byId('calcNoticeReference');
  const tenure = byId('noticeTenure');
  const status = byId('noticeProposalStatus');
  const save = byId('noticeSave');
  const fingerprint = form.elements.notice_fingerprint;
  const override = byId('noticeOverride');
  const reason = byId('noticeOverrideReason');
  const company = byId('calculationCompanyFilter');
  const employee = byId('calculationEmployeeFilter');
  const contextDate = document.querySelector('[data-notice-context-date]');
  let proposal = JSON.parse(byId('noticeInitialProposal').textContent);
  let ready = Boolean(proposal), contextChanged = false, requestId = 0, timer, controller;
  const money = value => `Gs. ${value.toLocaleString('es-PY')}`;
  const cents = raw => {
    if (!/^\d+(?:\.\d{1,2})?$/.test(raw)) return null;
    const [whole, fraction = ''] = raw.split('.');
    return BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'));
  };
  const message = (text, error = false) => {
    status.textContent = text;
    status.dataset.error = String(error);
  };
  const renderTotal = () => {
    const base = cents(salary.value);
    const manual = override?.checked;
    const validDays = /^\d+$/.test(days.value) && Number(days.value) <= 365;
    const valid = ready && !contextChanged && base !== null && base <= 214748364700n && validDays;
    byId('calcNoticeDailyResult').textContent = valid ? money((base + 1500n) / 3000n) : '—';
    byId('calcNoticeResult').textContent = valid ? money((base * BigInt(days.value) + 1500n) / 3000n) : '—';
    save.disabled = !valid || (manual && reason.value.trim().length < 10);
  };
  const invalidate = text => {
    ready = false;
    fingerprint.value = '';
    if (!override?.checked) days.value = '';
    message(text, true);
    renderTotal();
  };
  const showProposal = data => {
    proposal = data;
    ready = true;
    fingerprint.value = data.fingerprint;
    if (!override?.checked) days.value = String(data.days);
    const t = data.tenure;
    tenure.textContent = `Calculado automáticamente según una antigüedad de ${t.years} años y ${t.months} meses (${t.days} días adicionales).`;
    byId('noticeScaleText').textContent = data.rule.bands.map(band =>
      `${band.max_service_months === null ? 'Tramo siguiente' : `Hasta ${band.max_service_months} meses`}: ${band.notice_days} días`
    ).join(' · ') + '. Límites inclusivos por aniversario.';
    const warnings = byId('noticeProposalWarnings');
    warnings.replaceChildren();
    for (const warning of data.warnings || []) {
      const p = document.createElement('p');
      p.className = 'legal-warning';
      p.textContent = warning;
      warnings.append(p);
    }
    message(`Escala vigente: ${data.rule.code}. Días verificados en el servidor.`);
    renderTotal();
  };
  const refresh = async sequence => {
    if (contextChanged || !form.dataset.employee || !reference.validity.valid || !reference.value) return;
    controller = new AbortController();
    try {
      const params = new URLSearchParams({company_id: form.dataset.company, employee_id: form.dataset.employee, reference_date: reference.value});
      const response = await fetch(`/api/calculations/preaviso-proposal?${params}`, {credentials: 'same-origin', cache: 'no-store', signal: controller.signal, headers: {'Accept': 'application/json'}});
      if (response.redirected) throw new Error('Session redirected');
      const data = await response.json();
      if (sequence !== requestId || contextChanged) return;
      if (!response.ok) {
        const error = new Error(typeof data.detail === 'string' ? data.detail : 'No se pudo calcular el plazo. Revisá los datos.');
        error.noticeMessage = true;
        throw error;
      }
      showProposal(data);
    } catch (error) {
      if (sequence === requestId && error.name !== 'AbortError') invalidate(error.noticeMessage ? error.message : 'No se pudo consultar la escala. Revisá la conexión o la sesión y volvé a aplicar la selección.');
    }
  };
  const dateChanged = () => {
    clearTimeout(timer);
    controller?.abort();
    const sequence = ++requestId;
    form.elements.reference_period.value = reference.value.slice(0, 7);
    if (contextDate) contextDate.value = reference.value;
    invalidate('Actualizando antigüedad y plazo…');
    if (contextChanged || !form.dataset.employee) {
      message('Seleccioná un funcionario y aplicá la selección.', true);
    } else if (!reference.validity.valid || !reference.value) {
      message('Ingresá una fecha de referencia válida.', true);
    } else {
      timer = setTimeout(() => refresh(sequence), 300);
    }
  };
  reference.addEventListener('input', dateChanged);
  salary.addEventListener('input', renderTotal);
  days.addEventListener('input', renderTotal);
  reason?.addEventListener('input', renderTotal);
  override?.addEventListener('change', () => {
    days.readOnly = !override.checked;
    reason.disabled = !override.checked;
    reason.required = override.checked;
    byId('noticeOverrideFields').hidden = !override.checked;
    if (!override.checked) days.value = ready ? String(proposal.days) : '';
    renderTotal();
    if (override.checked) days.focus();
  });
  for (const selector of [company, employee]) {
    selector?.addEventListener('change', () => {
      contextChanged = true;
      ++requestId;
      clearTimeout(timer);
      controller?.abort();
      invalidate('La selección cambió. Presioná Aplicar para cargar el legajo y su salario.');
    });
  }
  form.addEventListener('submit', event => {
    renderTotal();
    if (save.disabled) event.preventDefault();
  });
  renderTotal();
})();
