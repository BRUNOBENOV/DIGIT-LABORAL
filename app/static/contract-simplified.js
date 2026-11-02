/* Contrato de Trabajo: interfaz progresiva sobre el formulario Jinja existente.
   No duplica valores ni modifica el legajo. El backend sigue siendo la autoridad. */
(() => {
  'use strict';
  const form = document.getElementById('certificateForm');
  if (!form || !form.hasAttribute('data-employee-autofill')) return;
  const field = name => form.elements.namedItem(name);
  const typeField = field('document_type');
  const company = field('company_id');
  const employee = field('employee_id');
  const card = form.querySelector('.certificate-form-card');
  const status = document.getElementById('certificateAutofillStatus');
  if (!typeField || !card || !status) return;

  const panel = document.createElement('section');
  panel.className = 'contract-simple-ui';
  panel.id = 'contractSimpleUI';
  panel.hidden = true;
  panel.innerHTML = `
    <section class="contract-simple-card" aria-labelledby="contractSimpleTitle">
      <div class="contract-simple-heading">
        <h3 id="contractSimpleTitle">Datos del legajo</h3>
        <button class="btn ghost" id="contractEditBase" type="button" aria-controls="contractBaseDetails">Editar datos</button>
      </div>
      <div id="contractSimpleSummary" class="contract-simple-grid" aria-live="polite"></div>
      <p>Los datos provienen del registro vigente o de esta versión. Los cambios realizados aquí afectan solo al documento.</p>
    </section>
    <details id="contractBaseDetails" class="contract-simple-detail">
      <summary>Datos personales y fechas · edición avanzada</summary>
      <div id="contractBaseContent" class="contract-simple-detail-content"></div>
    </details>
    <section class="contract-simple-card">
      <div class="contract-simple-heading"><h3>Condiciones que debés confirmar</h3></div>
      <p class="contract-simple-note">Las sugerencias no se incorporan como condiciones acordadas hasta que las confirmes.</p>
      <div id="contractSimpleOptions" class="contract-simple-options">
        <div class="contract-simple-option" data-option="payment_frequency">
          <div><b>Frecuencia de pago</b><span class="contract-simple-suggestion" data-suggestion="payment_frequency">Mensual</span></div>
          <label><input type="checkbox" name="contract_confirm_payment_frequency" value="on"> Confirmo</label>
        </div>
        <div class="contract-simple-option" data-option="weekly_rest">
          <div><b>Descanso semanal</b><span class="contract-simple-suggestion" data-suggestion="weekly_rest">Domingo</span></div>
          <label><input type="checkbox" name="contract_confirm_weekly_rest" value="on"> Confirmo</label>
        </div>
        <div class="contract-simple-option" data-option="contract_payment_method">
          <div><b>Forma de pago</b><span class="contract-simple-suggestion" data-suggestion="contract_payment_method">Transferencia bancaria</span></div>
          <label><input type="checkbox" name="contract_confirm_payment_method" value="on"> Confirmo</label>
        </div>
      </div>
      <button type="button" class="btn ghost" id="contractChangeConditions">Cambiar condiciones sugeridas</button>
    </section>
    <details id="contractTasksDetails" class="contract-simple-detail">
      <summary>Funciones y tareas principales</summary><div id="contractTasksContent" class="contract-simple-detail-content"></div>
    </details>
    <details id="contractSpecialDetails" class="contract-simple-detail">
      <summary>+ Añadir beneficios o cláusulas especiales</summary><div id="contractSpecialContent" class="contract-simple-detail-content"></div>
    </details>
    <details id="contractAdvancedDetails" class="contract-simple-detail">
      <summary>Modalidad, horario y condiciones adicionales</summary>
      <div id="contractAdvancedContent" class="contract-simple-detail-content">
        <label class="inline-check"><input id="contractEnableProbation" type="checkbox"> Consignar período de prueba, si legalmente corresponde</label>
      </div>
    </details>
    <details id="contractTextDetails" class="contract-simple-detail">
      <summary>Editar texto completo (opcional)</summary><div id="contractTextContent" class="contract-simple-detail-content"></div>
    </details>
    <p class="contract-simple-alert" id="contractSimpleReadiness" role="status" aria-live="polite">Seleccioná empresa y funcionario para comenzar.</p>
  `;
  status.insertAdjacentElement('afterend', panel);

  const actions = document.createElement('div');
  actions.id = 'contractSimpleActions';
  actions.className = 'contract-simple-actions';
  actions.hidden = true;
  actions.innerHTML = '<strong>Acciones del contrato</strong>';
  card.appendChild(actions);
  const simpleSubmission = document.createElement('input');
  simpleSubmission.type = 'hidden';
  simpleSubmission.name = 'contract_simplified_submission';
  simpleSubmission.value = '0';
  form.appendChild(simpleSubmission);

  const targets = {
    base: document.getElementById('contractBaseContent'),
    advanced: document.getElementById('contractAdvancedContent'),
    tasks: document.getElementById('contractTasksContent'),
    special: document.getElementById('contractSpecialContent'),
    text: document.getElementById('contractTextContent'),
    actions
  };
  const savedPlaces = new Map();
  const source = name => {
    const el = field(name);
    return el && el.nodeType === 1 ? el : null;
  };
  const labelOf = name => source(name)?.closest('label');
  const groupOf = name => source(name)?.closest('.document-form-grid');
  const move = (node, destination) => {
    if (!node || !destination || savedPlaces.has(node)) return;
    const mark = document.createComment('contract original position');
    node.parentNode.insertBefore(mark, node);
    savedPlaces.set(node, mark);
    destination.appendChild(node);
  };
  const originalNodes = {
    baseGrids: [...card.querySelectorAll(':scope > .document-form-grid')].slice(0, 2),
    salary: labelOf('salary'),
    identity: card.querySelector('.dossier-identity'),
    personal: groupOf('contract_worker_age'),
    modality: groupOf('contract_modality'),
    workplace: groupOf('workplace'),
    schedule: labelOf('work_schedule'),
    probation: groupOf('probation_period'),
    cause: labelOf('contract_cause'),
    jobs: labelOf('job_functions'),
    benefits: labelOf('contract_benefits'),
    terms: labelOf('contract_additional_terms'),
    notes: labelOf('observations'),
    editor: card.querySelector('.contract-editor-control'),
    stateActions: card.querySelector('.contract-state-actions'),
    standardActions: card.querySelector('.certificate-actions')
  };
  const docNumberLabel = labelOf('document_number');
  const fieldset = document.getElementById('documentSpecificFields');
  const sectionHeadings = [...fieldset.querySelectorAll('.document-field-section.specific-field')]
    .filter(node => (node.dataset.specific || '').includes('contrato_trabajo'));
  const conditionalEnd = labelOf('contract_end_date');
  const conditionalCause = originalNodes.cause;
  const probationLabel = labelOf('probation_period');
  const probationSwitch = document.getElementById('contractEnableProbation');
  const baseDetails = document.getElementById('contractBaseDetails');
  const advancedDetails = document.getElementById('contractAdvancedDetails');
  const taskDetails = document.getElementById('contractTasksDetails');
  const textDetails = document.getElementById('contractTextDetails');
  const readiness = document.getElementById('contractSimpleReadiness');
  const checkboxes = {
    payment_frequency: form.querySelector('[name="contract_confirm_payment_frequency"]'),
    weekly_rest: form.querySelector('[name="contract_confirm_weekly_rest"]'),
    contract_payment_method: form.querySelector('[name="contract_confirm_payment_method"]')
  };
  const defaults = {
    payment_frequency: 'Mensual',
    weekly_rest: 'Domingo',
    contract_payment_method: 'Transferencia bancaria'
  };
  const candidates = {...defaults};
  const required = {
    employee_name: 'Nombre', employee_document: 'Cédula', employee_address: 'Domicilio',
    position: 'Cargo', admission_date: 'Ingreso', salary: 'Salario',
    contract_worker_age: 'Edad', contract_worker_gender: 'Sexo',
    contract_worker_civil_status: 'Estado civil',
    contract_worker_nationality: 'Nacionalidad',
    contract_modality: 'Modalidad', workplace: 'Lugar de trabajo',
    job_functions: 'Funciones', work_schedule: 'Jornada',
    weekly_rest: 'Descanso', payment_frequency: 'Frecuencia',
    contract_payment_method: 'Medio de pago'
  };
  let active = false;
  let employeeContext = '';
  let loadedContext = '';
  let previousModality = '';
  const valid = value => {
    const raw = String(value == null ? '' : value).trim();
    return Boolean(raw) && !/^(sin datos|no especificad[oa]|no consignad[oa]|n\\/?a|-)$/i.test(raw)
      && !/\\[\\s*(?:COMPLETAR|PENDIENTE)/i.test(raw);
  };
  const displayValue = name => {
    const input = source(name);
    if (!input || !valid(input.value)) return 'Por completar';
    if (name === 'salary') {
      const amount = Number(input.value);
      return amount > 0 ? 'Gs. ' + new Intl.NumberFormat('es-PY').format(amount) : 'Por completar';
    }
    if (['admission_date', 'issue_date'].includes(name) && /^\\d{4}-\\d{2}-\\d{2}$/.test(input.value)) {
      const [y, m, d] = input.value.split('-');
      return d + '/' + m + '/' + y;
    }
    return input.value;
  };
  const facts = [
    ['employee_name','Funcionario'],['employee_document','Cédula'],
    ['position','Cargo'],['salary','Salario registrado'],
    ['admission_date','Fecha de ingreso'],['issue_date','Fecha de emisión'],
    ['contract_worker_age','Edad'],['contract_worker_nationality','Nacionalidad'],
    ['work_schedule','Jornada'],['workplace','Lugar de trabajo']
  ];
  function redrawFacts() {
    const host = document.getElementById('contractSimpleSummary');
    host.replaceChildren();
    for (const [name, label] of facts) {
      const box = document.createElement('div');
      box.className = 'contract-simple-fact';
      const value = displayValue(name);
      box.dataset.missing = value === 'Por completar' ? 'true' : 'false';
      const heading = document.createElement('small');
      heading.textContent = label;
      const main = document.createElement('strong');
      main.textContent = value;
      box.append(heading, main);
      if (value !== 'Por completar') {
        const meta = document.createElement('small');
        meta.className = 'contract-simple-fact-source';
        meta.textContent = '✓ Dato registrado o revisado';
        box.appendChild(meta);
      }
      host.appendChild(box);
    }
  }
  function drawSuggestions() {
    for (const key of Object.keys(checkboxes)) {
      const display = panel.querySelector('[data-suggestion="' + key + '"]');
      const wrapper = panel.querySelector('[data-option="' + key + '"]');
      if (display) display.textContent = candidates[key];
      if (wrapper) wrapper.dataset.confirmed = String(checkboxes[key].checked);
    }
  }
  function updateConditionalFields() {
    const mode = source('contract_modality')?.value || '';
    const needsEnd = ['plazo_fijo','mipyme_plazo_fijo','mipyme_80','prorroga'].includes(mode);
    if (conditionalEnd) conditionalEnd.classList.toggle('contract-simple-hidden', !needsEnd);
    if (conditionalCause) conditionalCause.classList.toggle('contract-simple-hidden', !needsEnd);
    if (!needsEnd && previousModality && previousModality !== mode) {
      if (source('contract_end_date')) source('contract_end_date').value = '';
      if (source('contract_cause')) source('contract_cause').value = '';
    }
    previousModality = mode;
    if (probationLabel) probationLabel.classList.toggle('contract-simple-hidden', !probationSwitch.checked);
  }
  function missingFields() {
    const missing = [];
    if (!company.value || !employee.value) missing.push('Empresa / funcionario');
    const companyInfo = company.selectedOptions?.[0]?.dataset || {};
    if (!companyInfo.ruc || !companyInfo.address) missing.push('RUC / dirección de la empresa');
    for (const [name, label] of Object.entries(required)) {
      const input = source(name);
      if (!valid(input?.value) || (name === 'salary' && Number(input?.value) <= 0)) missing.push(label);
    }
    const mode = source('contract_modality')?.value || '';
    if (['plazo_fijo','mipyme_plazo_fijo','mipyme_80','prorroga'].includes(mode)) {
      if (!source('contract_end_date')?.value) missing.push('Fecha final');
      if (!valid(source('contract_cause')?.value)) missing.push('Causa del plazo');
    }
    for (const check of Object.values(checkboxes)) if (!check.checked) missing.push('Confirmaciones de pago y descanso');
    if (source('contract_text_stale')?.value === '1') missing.push('Texto contractual desactualizado');
    if (status?.dataset.error === 'true' || /cargando datos/i.test(status?.textContent || '')) missing.push('Datos del legajo en carga');
    return [...new Set(missing)];
  }
  function redrawReadiness() {
    if (!active) return;
    const missing = missingFields();
    readiness.dataset.ready = String(missing.length === 0);
    readiness.textContent = missing.length
      ? 'Para emitir el contrato: ' + missing.join(', ') + '.'
      : '✓ Datos críticos y condiciones confirmadas. El contrato está listo para revisión.';
    for (const btn of actions.querySelectorAll('button[type="submit"]')) {
      const intent = btn.value;
      if (['approve','signed','docx','pdf','print','save'].includes(intent)) {
        const signedAck = source('contract_signature_acknowledged');
        btn.disabled = Boolean(missing.length) || (intent === 'signed' && !signedAck?.checked);
      }
    }
    taskDetails.dataset.missing = String(!valid(source('job_functions')?.value));
    advancedDetails.dataset.missing = String(!valid(source('contract_modality')?.value) || !valid(source('work_schedule')?.value));
  }
  function refresh() {
    if (!active) return;
    redrawFacts();
    updateConditionalFields();
    drawSuggestions();
    redrawReadiness();
  }
  function resetSuggestions() {
    for (const key of Object.keys(checkboxes)) checkboxes[key].checked = false;
    for (const key of Object.keys(defaults)) candidates[key] = defaults[key];
    probationSwitch.checked = false;
    previousModality = '';
    [baseDetails, advancedDetails, taskDetails, textDetails, document.getElementById('contractSpecialDetails')].forEach(d => { if (d) d.open = false; });
  }
  function acceptDossier() {
    if (!active) return;
    const now = company.value + ':' + employee.value;
    if (now !== loadedContext) {
      resetSuggestions();
      loadedContext = now;
    }
    for (const key of Object.keys(checkboxes)) {
      const input = source(key);
      if (!input) continue;
      if (valid(input.value)) candidates[key] = input.value;
      if (!checkboxes[key].checked) input.value = '';
    }
    refresh();
    document.getElementById('refreshCertificatePreview')?.click();
  }
  function activate() {
    if (active) return;
    active = true;
    panel.hidden = false;
    actions.hidden = false;
    form.classList.add('contract-simplified-active');
    simpleSubmission.value = '1';
    for (const n of originalNodes.baseGrids) move(n, targets.base);
    move(originalNodes.salary, targets.base);
    move(originalNodes.identity, targets.base);
    move(originalNodes.personal, targets.base);
    move(originalNodes.modality, targets.advanced);
    move(originalNodes.workplace, targets.advanced);
    move(originalNodes.schedule, targets.advanced);
    move(originalNodes.probation, targets.advanced);
    move(originalNodes.cause, targets.advanced);
    move(originalNodes.jobs, targets.tasks);
    move(originalNodes.benefits, targets.special);
    move(originalNodes.terms, targets.special);
    move(originalNodes.notes, targets.special);
    move(originalNodes.stateActions, targets.actions);
    move(originalNodes.standardActions, targets.actions);
    move(originalNodes.editor, targets.text);
    docNumberLabel?.classList.add('contract-simple-hidden');
    sectionHeadings.forEach(n => n.classList.add('contract-simple-hidden'));
    if (originalNodes.identity) originalNodes.identity.open = false;
    resetSuggestions();
    acceptDossier();
  }
  function deactivate() {
    if (!active) return;
    active = false;
    for (const [node, mark] of [...savedPlaces.entries()].reverse()) {
      mark.parentNode.insertBefore(node, mark);
      mark.remove();
      savedPlaces.delete(node);
    }
    panel.hidden = true;
    actions.hidden = true;
    form.classList.remove('contract-simplified-active');
    simpleSubmission.value = '0';
    docNumberLabel?.classList.remove('contract-simple-hidden');
    sectionHeadings.forEach(n => n.classList.remove('contract-simple-hidden'));
    conditionalEnd?.classList.remove('contract-simple-hidden');
    conditionalCause?.classList.remove('contract-simple-hidden');
    probationLabel?.classList.remove('contract-simple-hidden');
    for (const btn of originalNodes.standardActions?.querySelectorAll('button[type="submit"]') || []) btn.disabled = false;
    for (const btn of originalNodes.stateActions?.querySelectorAll('button[type="submit"]') || []) btn.disabled = false;
  }
  function syncType() {
    if (typeField.value === 'contrato_trabajo') activate();
    else deactivate();
  }
  document.getElementById('contractEditBase')?.addEventListener('click', () => {
    baseDetails.open = !baseDetails.open;
    if (baseDetails.open) baseDetails.scrollIntoView({block:'nearest',behavior:'smooth'});
  });
  document.getElementById('contractChangeConditions')?.addEventListener('click', () => {
    advancedDetails.open = true;
    advancedDetails.scrollIntoView({block:'nearest',behavior:'smooth'});
  });
  for (const [key, checkbox] of Object.entries(checkboxes)) {
    checkbox.addEventListener('change', () => {
      const input = source(key);
      if (input) {
        if (checkbox.checked) input.value = candidates[key];
        else {
          if (valid(input.value)) candidates[key] = input.value;
          input.value = '';
        }
        input.dispatchEvent(new Event('input', {bubbles:true}));
      }
      refresh();
    });
  }
  probationSwitch.addEventListener('change', () => {
    if (!probationSwitch.checked && source('probation_period')) {
      source('probation_period').value = '';
      source('probation_period').dispatchEvent(new Event('input', {bubbles:true}));
    }
    updateConditionalFields();
    refresh();
  });
  const modalityInput = source('contract_modality');
  modalityInput?.addEventListener('change', () => {
    updateConditionalFields();
    refresh();
  });
  for (const key of Object.keys(checkboxes)) {
    source(key)?.addEventListener('change', () => {
      if (checkboxes[key].checked && valid(source(key)?.value)) candidates[key] = source(key).value;
      refresh();
    });
  }
  const signatureAck = source('contract_signature_acknowledged');
  signatureAck?.addEventListener('change', redrawReadiness);
  form.addEventListener('certificate:updated', acceptDossier);
  form.addEventListener('input', refresh);
  form.addEventListener('change', refresh);
  for (const button of document.querySelectorAll('[data-certificate-type]')) {
    button.addEventListener('click', syncType);
  }
  company.addEventListener('change', () => { employeeContext = ''; loadedContext = ''; resetSuggestions(); refresh(); });
  employee.addEventListener('change', () => { employeeContext = ''; loadedContext = ''; resetSuggestions(); refresh(); });
  const issue = source('issue_date');
  issue?.addEventListener('change', () => {refresh();});
  form.addEventListener('submit', event => {
    if (!active) return;
    if (missingFields().length) {
      event.preventDefault();
      redrawReadiness();
      readiness.scrollIntoView({block:'nearest'});
    }
  }, true);
  syncType();
  if (active) {
    for (const key of Object.keys(checkboxes)) {
      if (valid(source(key)?.value)) candidates[key] = source(key).value;
      source(key).value = '';
    }
    probationSwitch.checked = Boolean(source('probation_period')?.value);
    refresh();
    document.getElementById('refreshCertificatePreview')?.click();
  }
})();