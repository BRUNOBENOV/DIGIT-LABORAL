(() => {
  'use strict';
  const form = document.querySelector('#certificateForm[data-employee-autofill]');
  if (!form) return;
  const field = name => form.elements.namedItem(name);
  const type = field('document_type'), company = field('company_id'), employee = field('employee_id');
  const card = form.querySelector('.certificate-form-card');
  const preview = form.querySelector('.certificate-preview-shell');
  const nativeStatus = document.querySelector('#preavisoCalculationStatus');
  if (!card || !preview || !nativeStatus || !type || !company || !employee) return;
  const canRegister = form.dataset.noticeCanRegister === 'true';
  const panel = document.createElement('section');
  panel.className = 'notice-simple-ui'; panel.id = 'noticeSimpleUI'; panel.hidden = true;
  panel.innerHTML = `
    <section class="notice-simple-card">
      <div class="notice-simple-heading"><h3>Datos del legajo</h3><button type="button" class="btn ghost" id="noticeEditData" aria-controls="noticeBaseDetails" aria-expanded="false">Editar datos</button></div>
      <div class="notice-simple-facts" id="noticeSimpleFacts"></div>
      <p class="notice-simple-caption"><span id="noticeDossierBadge" class="notice-simple-active-label">Datos registrados</span> Las ediciones afectan solo al documento.</p>
    </section>
    <section class="notice-simple-card">
      <h3>Cálculo de preaviso</h3>
      <p class="notice-simple-alert" id="noticeSimpleStatus" role="status" aria-live="polite"></p>
      <div id="noticePeriodSlot"></div>
      <div class="notice-simple-empty">
        <h3>Falta registrar el cálculo</h3>
        <p id="noticeEmptyHelp"></p>
        <a class="btn primary" id="noticeRegisterCalculation" target="_blank" rel="noopener">Registrar cálculo de preaviso ↗</a>
      </div>
      <div class="notice-simple-refresh"><button type="button" class="btn ghost" id="noticeRefreshRecords" title="Volver a consultar los cálculos guardados">Actualizar registros</button></div>
    </section>
    <section class="notice-simple-card notice-simple-dates-card">
      <div class="notice-simple-heading"><h3>Fechas de la notificación</h3><span id="noticeDatesBadge" class="notice-simple-active-label"></span></div>
      <div id="noticeDatesSlot" class="notice-simple-dates"></div>
      <p class="notice-simple-caption">Revisá las fechas antes de emitir. El plazo mostrado se obtiene del intervalo entre inicio y salida.</p>
    </section>
    <details class="notice-simple-detail" id="noticeBaseDetails"><summary>Datos del legajo · edición</summary><div class="notice-simple-content" id="noticeBaseSlot"></div></details>
    <details class="notice-simple-detail" id="noticeOptionsDetails"><summary>Número y observaciones · opcional</summary><div class="notice-simple-content" id="noticeOptionsSlot"><p class="notice-simple-caption">Si dejás el número vacío, se asignará al guardar.</p></div></details>
    <details class="notice-simple-detail" id="noticeTechnicalDetails"><summary>Ver cálculo y criterios de revisión</summary><div class="notice-simple-content" id="noticeTechnicalSlot"></div></details>`;
  employee.closest('label').after(panel);
  const actions = document.createElement('section');
  actions.className = 'notice-simple-actions'; actions.hidden = true;
  actions.innerHTML = '<div class="notice-simple-heading"><h3>Tu notificación</h3><span class="notice-simple-active-label" id="noticeReadyBadge"></span></div><p class="notice-simple-caption" id="noticeActionHint"></p>';
  const placeholder = document.createElement('section');
  placeholder.className = 'notice-preview-empty'; placeholder.hidden = true;
  placeholder.innerHTML = '<h3>La carta se verá aquí</h3><p>Vinculá un cálculo guardado y revisá sus fechas. Luego podrás imprimir o descargar el documento.</p>';
  preview.prepend(actions, placeholder);
  const element = id => document.getElementById(id);
  const labelOf = name => field(name)?.closest('label');
  const places = new Map(), hiddenSources = new Set();
  let active = false;
  let identityWasOpen = false;
  let nativeLive = null;
  let state = 'selection';
  const value = name => String(field(name)?.value || '').trim();
  const selection = select => select.selectedOptions[0];
  function move(node, target) {
    if (!node || !target || places.has(node)) return;
    const mark = document.createComment('notice original position');
    node.before(mark); places.set(node, mark); target.appendChild(node);
  }
  function hideSource(node) { if (node) { hiddenSources.add(node); node.classList.add('notice-source-hidden'); } }
  function reveal(input) {
    let ancestor = input?.parentElement;
    while (ancestor && ancestor !== form) { if (ancestor.tagName === 'DETAILS') ancestor.open = true; ancestor = ancestor.parentElement; }
    input?.focus();
  }
  function facts() {
    const host = element('noticeSimpleFacts'); host.replaceChildren();
    const signatory = selection(company)?.dataset.signature || '';
    for (const [title, text] of [['Funcionario', value('employee_name')], ['Cédula', value('employee_document')], ['Firmante de la empresa', signatory]]) {
      const box = document.createElement('div'); box.className = 'notice-simple-fact'; box.dataset.missing = text ? 'false' : 'true';
      const label = document.createElement('small'); label.textContent = title;
      const content = document.createElement('strong'); content.textContent = text || 'Por completar';
      box.append(label, content); host.appendChild(box);
    }
    const dossierError = document.querySelector('#certificateAutofillStatus')?.dataset.error === 'true';
    const missing = !value('employee_name') || dossierError;
    element('noticeDossierBadge').textContent = dossierError ? 'Revisá los datos del legajo' : missing ? 'Datos pendientes' : 'Datos cargados';
    element('noticeDossierBadge').dataset.missing = String(missing);
  }
  function refresh() {
    if (!active) return;
    state = !company.value || !employee.value ? 'selection' : nativeStatus.dataset.state || 'loading';
    panel.dataset.state = state;
    const hasRecord = Boolean(value('calculation_id'));
    panel.dataset.hasRecord = String(hasRecord);
    form.dataset.noticePreview = String(hasRecord && Boolean(value('notice_start_date') && value('effective_date')));
    const text = {
      selection: 'Elegí una empresa y un funcionario.', loading: 'Buscando cálculos guardados…',
      empty: 'Este funcionario todavía no tiene un cálculo de preaviso guardado.',
      error: 'No se pudo consultar el cálculo. Reintentá la búsqueda.',
      ready: 'Cálculo vinculado. Revisá las fechas y la carta antes de emitir.',
      review: nativeStatus.textContent || 'Revisá las fechas y el plazo antes de emitir.'
    }[state] || 'Revisá los datos antes de emitir.';
    const status = element('noticeSimpleStatus');
    if (status.textContent !== text) status.textContent = text;
    status.dataset.state = state;
    const create = element('noticeRegisterCalculation');
    create.hidden = !canRegister || !company.value || !employee.value;
    if (!create.hidden) create.href = '/app/calculations?' + new URLSearchParams({tipo:'notice',company_id:company.value,employee_id:employee.value});
    else create.removeAttribute('href');
    element('noticeEmptyHelp').textContent = canRegister
      ? 'Se abrirá Cálculo → Preaviso con esta empresa y este funcionario. Guardá el cálculo, regresá a esta pestaña y pulsá Actualizar registros.'
      : 'Pedí al contador del estudio que registre el cálculo. Después pulsá Actualizar registros para vincularlo.';
    element('noticeRefreshRecords').disabled = state === 'loading' || !company.value || !employee.value;
    const available = [...form.querySelectorAll('.certificate-actions button[type="submit"]')].every(button => !button.disabled);
    element('noticeReadyBadge').textContent = available ? 'Para revisión' : state === 'loading' ? 'Consultando' : 'Pendiente';
    element('noticeReadyBadge').dataset.missing = String(!available);
    element('noticeActionHint').textContent = available ? 'Revisá el contenido antes de imprimir o descargar.' : 'Vinculá un cálculo vigente y completá sus fechas para habilitar la emisión.';
    element('noticeDatesBadge').textContent = field('effective_date')?.dataset.preavisoAuto === 'true' ? 'Fecha propuesta' : 'Fechas registradas o editadas';
    element('noticeDatesBadge').title = 'La fecha propuesta se obtiene del inicio y del plazo guardado; requiere revisión.';
    facts();
    element('noticeEditData').setAttribute('aria-expanded', String(element('noticeBaseDetails').open));
  }
  function activate() {
    if (active) return;
    active = true; panel.hidden = false; actions.hidden = false; placeholder.hidden = false;
    form.classList.add('notice-simplified-active');
    const base = element('noticeBaseSlot'), dates = element('noticeDatesSlot'), options = element('noticeOptionsSlot'), technical = element('noticeTechnicalSlot');
    const dateGrid = field('issue_date')?.closest('.document-form-grid');
    const employmentGrid = field('position')?.closest('.document-form-grid');
    const timingGrid = field('notice_start_date')?.closest('.document-form-grid');
    const calculationGrid = field('notice_reference_period')?.closest('.document-form-grid');
    const identity = card.querySelector('.dossier-identity');
    identityWasOpen = Boolean(identity?.open);
    move(labelOf('city'), base); move(employmentGrid, base); move(labelOf('salary'), base);
    move(identity, base); if (identity) identity.open = true;
    move(labelOf('issue_date'), dates); move(labelOf('notice_start_date'), dates);
    move(labelOf('effective_date'), dates); move(labelOf('notice_days'), dates);
    const period = labelOf('notice_reference_period'); move(period, element('noticePeriodSlot')); period?.classList.add('notice-period-field');
    const live = card.querySelector('.preaviso-calculation-status-wrap');
    nativeLive = live?.getAttribute('aria-live'); if (live) live.setAttribute('aria-live', 'off');
    move(live, technical); move(card.querySelector('[data-notice-legal]'), technical);
    move(labelOf('document_number'), options); move(labelOf('last_worked_date'), options); move(labelOf('observations'), options);
    move(card.querySelector('.certificate-actions'), actions);
    [dateGrid, timingGrid, calculationGrid, card.querySelector('[data-notice-intro]')].forEach(hideSource);
    [element('noticeBaseDetails'), element('noticeOptionsDetails'), element('noticeTechnicalDetails')].forEach(detail => { detail.open = false; });
    refresh();
  }
  function deactivate() {
    if (!active) return;
    active = false;
    const identity = panel.querySelector('.dossier-identity'); if (identity) identity.open = identityWasOpen;
    labelOf('notice_reference_period')?.classList.remove('notice-period-field');
    const live = panel.querySelector('.preaviso-calculation-status-wrap');
    if (live) { if (nativeLive === null) live.removeAttribute('aria-live'); else live.setAttribute('aria-live', nativeLive); }
    for (const [node, mark] of [...places.entries()].reverse()) { mark.before(node); mark.remove(); }
    places.clear(); hiddenSources.forEach(node => node.classList.remove('notice-source-hidden')); hiddenSources.clear();
    panel.hidden = true; actions.hidden = true; placeholder.hidden = true;
    form.classList.remove('notice-simplified-active'); delete form.dataset.noticePreview;
  }
  function syncType() { if (type.value === 'notificacion_preaviso') activate(); else deactivate(); }
  for (const button of form.querySelectorAll('[data-certificate-type]')) {
    // Restore controls before the contract enhancement takes ownership of them.
    button.addEventListener('click', () => { if (button.dataset.certificateType !== 'notificacion_preaviso') deactivate(); }, true);
    button.addEventListener('click', syncType);
  }
  element('noticeEditData').addEventListener('click', () => { const detail = element('noticeBaseDetails'); detail.open = !detail.open; refresh(); });
  element('noticeBaseDetails').addEventListener('toggle', refresh);
  element('noticeRefreshRecords').addEventListener('click', () => form.dispatchEvent(new Event('certificate:notice-refresh')));
  form.addEventListener('certificate:notice-state', refresh);
  form.addEventListener('certificate:updated', refresh);
  form.addEventListener('input', refresh); form.addEventListener('change', refresh);
  form.addEventListener('invalid', event => { if (active) reveal(event.target); }, true);
  form.addEventListener('submit', event => {
    if (!active) return;
    const missing = ['employee_name','city','issue_date'].find(name => !value(name));
    if (missing) {
      event.preventDefault();
      element('noticeSimpleStatus').textContent = 'Completá el nombre, la ciudad y la fecha de emisión antes de emitir.';
      reveal(field(missing));
    }
  }, true);
  syncType();
})();
