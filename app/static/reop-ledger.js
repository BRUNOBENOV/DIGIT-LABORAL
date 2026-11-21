(() => {
  'use strict';
  const panel = document.getElementById('control-reop');
  if (!panel) return;
  const status = panel.querySelector('[data-ledger-status]');
  const buttons = [...panel.querySelectorAll('[data-read-ledger]')];
  const install = 'Actualizá el asistente de Chrome a la versión 1.7.0 desde esta pantalla y habilitá la pestaña Liquidación Salario.';
  let reading = false;

  function askExtension(message, timeout) {
    return new Promise((resolve, reject) => {
      const runtime = globalThis.chrome?.runtime;
      if (!runtime?.sendMessage) return reject(new Error(install));
      const timer = setTimeout(() => reject(new Error('La consulta del listado tardó demasiado. Volvé a consultar REOP.')), timeout);
      try {
        runtime.sendMessage(panel.dataset.extension, message, result => {
          clearTimeout(timer);
          if (runtime.lastError || !result) reject(new Error(install));
          else if (!result.ok) reject(new Error(result.message || 'REOP no devolvió el listado completo.'));
          else resolve(result);
        });
      } catch (_) { clearTimeout(timer); reject(new Error(install)); }
    });
  }

  function showReview() {
    const url = new URL(window.location.href);
    url.hash = 'control-reop';
    window.history.replaceState(null, '', url);
    window.location.reload();
  }

  async function refresh(patronal) {
    const button = buttons.find(item => item.dataset.patronal === patronal);
    if (!button) throw new Error('Revisá la patronal y volvé a verificar la planilla.');
    if (reading) throw new Error('Ya hay una consulta del listado en curso.');
    reading = true;
    buttons.forEach(item => { item.disabled = true; });
    status.textContent = 'Leyendo el listado completo de Liquidación Salario en REOP…';
    try {
      const capabilities = await askExtension({type:'ping'}, 7000);
      if (!capabilities.salaryList) throw new Error(install);
      const {period, company, worker, source, category, csrf} = panel.dataset;
      const {snapshot} = await askExtension({type:'read-salary-list', protocol:1, period, patronal}, 120000);
      const response = await fetch('/app/compliance/salary-import/' + company + '/' + period + '/ledger', {
        method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json', 'X-CSRF-Token':csrf, Accept:'application/json'},
        body:JSON.stringify({snapshot, patronal, previous:button.dataset.digest, source_type:source,
          employee_id:worker ? Number(worker) : null, other_category:category}),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.digest) throw new Error(result.detail || 'No se pudo guardar la lectura del listado en Digit Laboral.');
      button.dataset.digest = result.digest;
      status.textContent = 'Consulta guardada. Faltan ' + result.missing + ' de ' + result.checked_rows + ' trabajadores.';
      return result;
    } catch (error) {
      status.textContent = error.message;
      throw error;
    } finally {
      reading = false;
      buttons.forEach(item => { item.disabled = false; });
    }
  }
  buttons.forEach(button => button.addEventListener('click', async () => {
    try { await refresh(button.dataset.patronal); showReview(); } catch (_) { /* The panel shows the error. */ }
  }));
  panel.querySelectorAll('time[datetime]').forEach(time => {
    const date = new Date(time.dateTime);
    if (!Number.isNaN(date.getTime())) time.textContent = date.toLocaleString('es-PY', {timeZone:'America/Asuncion'});
  });
  window.DigitReopLedger = {refresh, showReview};
})();
