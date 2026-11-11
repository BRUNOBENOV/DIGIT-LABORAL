(() => {
  'use strict';
  const form = document.getElementById('labor-form');
  const panel = form?.querySelector('[data-salary-attendance]');
  if (!panel) return;
  const field = name => form.elements.namedItem(name);
  const names = ['days_worked','hours_worked','payment_method','period_start','period_end'];
  const status = panel.querySelector('[data-attendance-status]');
  const manual = field('attendance_override'), month = field('month');
  const mtessHoursGuide = panel.querySelector('[data-mtess-hours-guide]');
  // Referencia de calendario: nunca reemplaza marcaciones de entrada/salida.
  function renderMtessHoursGuide() {
    if (!mtessHoursGuide) return;
    const startText = String(field('period_start')?.value || '');
    const endText = String(field('period_end')?.value || '');
    const parse = value => {
      if (!/^\\d{4}-\\d{2}-\\d{2}$/.test(value)) return null;
      const day = new Date(value + 'T00:00:00Z');
      return Number.isFinite(day.getTime()) && day.toISOString().slice(0, 10) === value ? day : null;
    };
    const start = parse(startText), end = parse(endText);
    const selectedMonth = String(month?.value || '');
    if (!start || !end || start > end || startText.slice(0, 7) !== selectedMonth ||
        endText.slice(0, 7) !== selectedMonth) {
      mtessHoursGuide.textContent = 'Indicá fechas válidas del mes para consultar la referencia de calendario. Las horas REOP se obtienen de la asistencia real, no del salario ni de los días remunerados.';
      return;
    }
    let weekdays = 0, saturdays = 0, sundays = 0;
    for (let timestamp = start.getTime(); timestamp <= end.getTime(); timestamp += 86400000) {
      const weekday = new Date(timestamp).getUTCDay();
      if (weekday === 0) sundays += 1;
      else if (weekday === 6) saturdays += 1;
      else weekdays += 1;
    }
    const monFri = weekdays * 8;
    const satHalf = monFri + saturdays * 4;
    const satFull = monFri + saturdays * 8;
    mtessHoursGuide.textContent =
      'Referencia del calendario (no asistencia verificada): ' + weekdays + ' días de lunes a viernes, ' +
      saturdays + ' sábados y ' + sundays + ' domingos. Ejemplos sin ausencias: ' +
      monFri + ' h (lunes a viernes, 8 h), ' + satHalf +
      ' h (lunes a viernes, 8 h + sábado, 4 h) o ' + satFull +
      ' h (lunes a sábado, 8 h). Para el MTESS declarás SOLO las jornadas y horas efectivamente trabajadas, ' +
      'según marcaciones, feriados y horario pactado. No se completan automáticamente.';
  }
  for (const name of ['period_start', 'period_end']) {
    field(name)?.addEventListener('change', renderMtessHoursGuide);
    field(name)?.addEventListener('input', renderMtessHoursGuide);
  }

  let inherited = Object.fromEntries(names.map(name => [name, field(name)?.value || '']));
  let sequence = 0, controller, pending = false;
  function suggestFullMonthDates() {
    const selected = String(month?.value || '');
    if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(selected)) return;
    const [year, number] = selected.split('-').map(Number);
    const lastDay = new Date(Date.UTC(year, number, 0)).getUTCDate();
    if (field('period_start') && !field('period_start').value) field('period_start').value = selected + '-01';
    if (field('period_end') && !field('period_end').value)
      field('period_end').value = selected + '-' + String(lastDay).padStart(2, '0');
  }
  function syncBrowserPeriod() {
    const contextMonth = document.querySelector('.dl-context [name="month"]');
    if (contextMonth) contextMonth.value = month.value;
    if (window.location.pathname !== '/app/liquidaciones' ||
        !/^\d{4}-(0[1-9]|1[0-2])$/.test(month.value)) return;
    const url = new URL(window.location.href);
    if (url.searchParams.get('tipo') !== 'salary' || url.searchParams.get('month') === month.value) return;
    url.searchParams.set('month', month.value);
    // An origin record belongs to a single approved month; do not keep a stale ID.
    url.searchParams.delete('calculation_id');
    window.history.replaceState(window.history.state, '', url.pathname + url.search + url.hash);
  }
  function locks() {
    for (const name of names) {
      const input = field(name);
      if (input) input.readOnly = pending || (!manual.checked && Boolean(field('attendance_source_id').value) && inherited[name] !== '');
    }
    manual.disabled = pending;
    field('days_worked').setCustomValidity(pending ? 'Esperá a que termine la consulta de asistencia.' : '');
  }
  manual.addEventListener('change', () => {
    if (!manual.checked && field('attendance_source_id').value) {
      for (const name of names) if (inherited[name] !== '' && field(name)) field(name).value = inherited[name];
    }
    locks();
    status.textContent = manual.checked ? 'Edición manual para esta liquidación. Se conserva la referencia al cálculo de origen.'
      : field('attendance_source_id').value ? 'Asistencia del cálculo aprobado #' + field('attendance_source_id').value + '. Completá solo los datos faltantes.'
      : 'No hay una aprobación vigente para este mes. Ingresá la asistencia real.';
    form.dispatchEvent(new Event('input', {bubbles:true}));
  });
  async function refresh() {
    const request = ++sequence;
    controller?.abort();
    const requestController = new AbortController();
    controller = requestController;
    field('attendance_source_id').value = ''; field('attendance_source_sha256').value = '';
    manual.checked = false;
    inherited = Object.fromEntries(names.map(name => [name, '']));
    for (const name of names) if (field(name)) field(name).value = '';
    syncBrowserPeriod();
    suggestFullMonthDates();
    if (!month.value || !field('company_id')?.value || !field('employee_id')?.value) {
      pending = false; locks(); renderMtessHoursGuide(); status.textContent = 'Seleccioná empresa, funcionario y mes para cargar la asistencia.'; return;
    }
    pending = true; locks(); status.textContent = 'Buscando la asistencia aprobada del mes…';
    let timeout;
    try {
      // Evitar que la consulta mantenga bloqueado indefinidamente el guardado.
      // La edición manual no altera cálculos aprobados ni inventa asistencias.
      timeout = window.setTimeout(() => requestController.abort(), 8000);
      const query = new URLSearchParams({company_id:field('company_id').value, employee_id:field('employee_id').value, period:month.value});
      const response = await fetch('/api/liquidaciones/asistencia-salarial?' + query, {credentials:'same-origin',signal:requestController.signal,headers:{Accept:'application/json'}});
      if (!response.ok) throw new Error('Consulta no disponible');
      const proposal = await response.json();
      if (request !== sequence) return;
      field('attendance_source_id').value = proposal.calculation_id || '';
      field('attendance_source_sha256').value = proposal.fingerprint || '';
      inherited = Object.fromEntries(names.map(name => [name, String(proposal.values?.[name] ?? '')]));
      for (const name of names) if (field(name)) field(name).value = inherited[name];
      if (!proposal.available) suggestFullMonthDates();
      status.textContent = proposal.available ? 'Asistencia del cálculo aprobado #' + proposal.calculation_id + ' · ' + proposal.period + '. Completá solo los datos faltantes.'
        : 'Sin cálculo aprobado para el mes seleccionado. Se propone el primer y último día del mes; revisá las fechas reales y la asistencia.';
    } catch (error) {
      if (request !== sequence) return;
      manual.checked = true;
      suggestFullMonthDates();
      status.textContent = error.name === 'AbortError'
        ? 'La consulta de asistencia tardó demasiado. Podés continuar con carga manual y verificar los datos reales.'
        : 'No se pudo cargar la asistencia. Se propone el período del mes seleccionado; confirmá las fechas reales y los días trabajados.';
    } finally {
      if (timeout) window.clearTimeout(timeout);
      if (request === sequence) { pending = false; locks(); renderMtessHoursGuide(); form.dispatchEvent(new Event('input', {bubbles:true})); }
    }
  }
  month.addEventListener('change', refresh);
  form.addEventListener('submit', event => { if (pending) { event.preventDefault(); status.textContent = 'Esperá a que termine la consulta de asistencia.'; } }, true);
  locks();
  // Los formularios restaurados por el navegador también deben reflejar su mes real.
  syncBrowserPeriod();
  renderMtessHoursGuide();
})();

(() => {
  for (const form of document.querySelectorAll('[data-salary-import-details]')) {
    const toggle = form.querySelector('[data-edit-attendance]');
    const originals = new Map([...form.querySelectorAll('[data-attendance-inherited]')].map(input => [input, input.value]));
    toggle?.addEventListener('change', () => {
      for (const [input, original] of originals) {
        input.readOnly = !toggle.checked;
        if (!toggle.checked) input.value = original;
      }
    });
  }
})();
