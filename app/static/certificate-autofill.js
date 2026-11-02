(() => {
  'use strict';
  const form = document.querySelector('#certificateForm[data-employee-autofill]');
  if (!form) return;
  const field = name => form.elements.namedItem(name);
  const company = field('company_id');
  const employee = field('employee_id');
  const issuedOn = field('issue_date');
  const type = field('document_type');
  const status = document.querySelector('#certificateAutofillStatus');
  const generationStatus = document.querySelector('#contractGenerationStatus');
  const fullText = field('contract_text');
  const names = [
    'employee_name', 'employee_document', 'employee_address', 'employee_section', 'employee_profession',
    'position', 'admission_date', 'salary', 'city', 'contract_worker_age', 'contract_worker_gender',
    'contract_worker_civil_status', 'contract_worker_nationality', 'contract_modality', 'workplace',
    'job_functions', 'work_schedule', 'weekly_rest', 'payment_frequency', 'contract_payment_method',
    'nationality', 'civil_status'
  ];
  const required = {
    employee_name: 'Nombre completo', employee_document: 'Cédula', employee_address: 'Dirección del funcionario',
    position: 'Cargo', admission_date: 'Fecha de ingreso', salary: 'Salario',
    contract_worker_age: 'Edad', contract_worker_gender: 'Sexo', contract_worker_civil_status: 'Estado civil',
    contract_worker_nationality: 'Nacionalidad', contract_modality: 'Modalidad del contrato', workplace: 'Lugar de trabajo',
    job_functions: 'Funciones y tareas', work_schedule: 'Jornada y horario', weekly_rest: 'Descanso semanal',
    payment_frequency: 'Frecuencia de pago', contract_payment_method: 'Forma de pago'
  };
  let context = `${company.value}:${employee.value}`;
  let current = null;
  let controller = null;
  let sequence = 0;
  let timer = null;
  let loading = false;
  const edited = new Set();
  const hints = new Map();
  const notify = () => form.dispatchEvent(new Event('certificate:updated'));
  const hasValue = (name, value) => {
    if (!String(value).trim() || /^(no especificad[oa]|no consignad[oa]|sin datos|n\/a|-)$/i.test(String(value).trim())) return false;
    if (/\[\s*(completar|pendiente)\b[^\]]*\]/i.test(String(value)) || /\bCOMPLETAR(?::|(?=\s*(?:$|\n)))/.test(String(value))) return false;
    return name !== 'salary' || Number(value) > 0;
  };

  function mark(name, source = '') {
    const input = field(name);
    if (!input) return;
    let hint = hints.get(name);
    if (!hint) {
      hint = document.createElement('small');
      hint.className = 'dossier-field-status';
      hint.id = `dossier-${name}-status`;
      input.insertAdjacentElement('afterend', hint);
      const descriptions = new Set((input.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean));
      descriptions.add(hint.id);
      input.setAttribute('aria-describedby', [...descriptions].join(' '));
      hints.set(name, hint);
    }
    if (!hasValue(name, input.value)) {
      input.dataset.dossierState = 'missing';
      hint.textContent = required[name] ? 'Dato pendiente' : 'Sin dato registrado (opcional)';
      hint.title = required[name] ? 'Completá este dato antes de generar el contrato.' : 'Completá si corresponde a este documento.';
    } else if (edited.has(name)) {
      input.dataset.dossierState = 'manual';
      hint.textContent = 'Editado para este documento';
      hint.title = 'Esta edición no modifica el legajo.';
    } else {
      input.dataset.dossierState = 'sourced';
      hint.textContent = source === 'Versión guardada' ? '✓ Versión guardada' : name === 'salary' ? '✓ Salario a la fecha' : name === 'contract_worker_age' ? '✓ Según nacimiento' : name === 'city' ? '✓ Empresa' : '✓ Del legajo';
      hint.title = `${source || 'Versión guardada'}. Podés modificarlo solo para este documento.`;
    }
  }

  function invalidateText() {
    if (!fullText?.value.trim()) return;
    field('contract_text_stale').value = '1';
    if (generationStatus) generationStatus.textContent = 'Cambiaste datos del documento. Volvé a generar el contrato o revisá y actualizá su texto antes de aprobar.';
  }

  function apply(data) {
    current = data;
    for (const name of names) {
      const input = field(name);
      if (!input || edited.has(name)) continue;
      const value = String(data.fields[name] ?? '');
      if (input instanceof HTMLSelectElement && value && ![...input.options].some(option => option.value === value)) {
        input.add(new Option(value, value));
      }
      input.value = value;
      mark(name, data.sources[name]);
    }
    // Keep the shared preview/header in sync even for remotely searched options.
    const option = employee.selectedOptions[0];
    if (option) Object.assign(option.dataset, {
      name: data.fields.employee_name, document: data.fields.employee_document, address: data.fields.employee_address,
      position: data.fields.position, salary: data.fields.salary, admission: data.fields.admission_date
    });
    const companyOption = company.selectedOptions[0];
    if (companyOption) Object.assign(companyOption.dataset, data.company);
    status.dataset.error = 'false';
    status.textContent = 'Legajo cargado. ✓ Datos registrados · Amarillo: dato pendiente. Los cambios se aplican solo a este documento.';
    notify();
  }

  function resetSubject() {
    current = null;
    edited.clear();
    names.forEach(name => {
      const input = field(name);
      if (input) { input.value = ''; mark(name); }
    });
    // A document body and version parent always belong to the original subject.
    if (fullText) fullText.value = '';
    field('contract_parent_id').value = '';
    field('contract_text_stale').value = '';
    field('contract_signature_acknowledged').checked = false;
    ['contract_benefits', 'contract_additional_terms', 'contract_cause', 'contract_end_date',
      'probation_period', 'previous_contract_number', 'observations', 'document_number',
      'last_period_salary_amount'].forEach(name => { const input = field(name); if (input) input.value = ''; });
    document.querySelector('#contractFullEditorWrap')?.classList.add('hidden');
    form.dataset.editingContract = 'false';
    document.querySelector('.contract-version-banner')?.remove();
    if (generationStatus) generationStatus.textContent = 'Revisá los datos del nuevo funcionario antes de generar el contrato.';
    notify();
  }

  function load() {
    const key = `${company.value}:${employee.value}`;
    const changed = key !== context;
    if (changed) { context = key; resetSubject(); }
    const request = ++sequence;
    controller?.abort();
    window.clearTimeout(timer);
    loading = false;
    if (!company.value || !employee.value) {
      status.textContent = 'Seleccioná empresa y funcionario para cargar el legajo.';
      return;
    }
    if (!issuedOn.value || !issuedOn.checkValidity()) {
      status.textContent = 'Indicá una fecha de emisión válida para consultar el legajo.';
      return;
    }
    loading = true;
    status.dataset.error = 'false';
    status.textContent = 'Cargando datos del legajo…';
    timer = window.setTimeout(async () => {
      controller = new AbortController();
      const params = new URLSearchParams({company_id: company.value, employee_id: employee.value, issue_date: issuedOn.value});
      try {
        const response = await fetch(`/api/certificates/autofill?${params}`, {
          signal: controller.signal, credentials: 'same-origin', headers: {Accept: 'application/json'}
        });
        if (!response.ok) throw new Error('dossier');
        const data = await response.json();
        if (request !== sequence || key !== context || String(data.employee_id) !== employee.value || String(data.company_id) !== company.value) return;
        loading = false;
        apply(data);
      } catch (error) {
        if (request !== sequence || error.name === 'AbortError') return;
        loading = false;
        current = null;
        status.dataset.error = 'true';
        status.textContent = 'No se pudo cargar el legajo. Volvé a seleccionar el funcionario o completá y revisá los datos manualmente.';
      }
    }, 300);
  }

  function validate(event) {
    if (type.value !== 'contrato_trabajo') return;
    const missing = Object.entries(required).filter(([name]) => !hasValue(name, field(name)?.value ?? ''));
    const companyMissing = Object.entries(current?.missing_fields || {}).filter(([name]) => name.startsWith('company_'));
    let message = '';
    if (loading) message = 'Esperá a que termine la carga del legajo y revisá los datos.';
    else if (missing.length || companyMissing.length) message = 'Faltan datos obligatorios: ' + [...missing, ...companyMissing].map(([, label]) => label).join(', ') + '. Completalos en el formulario o en el legajo del funcionario / empresa.';
    else if (event.type === 'submit' && field('contract_text_stale').value === '1') message = 'El texto del contrato quedó pendiente de actualizar. Volvé a generarlo o revisá y actualizá su texto.';
    if (!message) return;
    event.preventDefault();
    if (generationStatus) generationStatus.textContent = message;
    if (missing.length) {
      const input = field(missing[0][0]);
      input?.closest('details')?.setAttribute('open', '');
      input?.focus();
    }
  }

  names.forEach(name => {
    const onEdit = () => { edited.add(name); mark(name); invalidateText(); };
    field(name)?.addEventListener('input', onEdit);
    field(name)?.addEventListener('change', onEdit);
  });
  form.addEventListener('input', event => {
    if (event.target === fullText) { field('contract_text_stale').value = ''; return; }
    if (event.target.name && !names.includes(event.target.name) && event.target !== company && event.target !== employee && event.target.type !== 'checkbox') invalidateText();
  });
  form.addEventListener('certificate:context', load);
  issuedOn.addEventListener('change', load);
  form.addEventListener('certificate:validate', validate);
  form.addEventListener('submit', validate, true);
  let initial = null;
  try { initial = JSON.parse(document.querySelector('#certificateAutofillData').textContent); } catch (_) { /* Load from the scoped API below. */ }
  if (form.dataset.editingContract === 'true') {
    current = initial;
    names.forEach(name => { mark(name, 'Versión guardada'); edited.add(name); });
    notify();
  } else if (initial && String(initial.company_id) === company.value && String(initial.employee_id) === employee.value && initial.issue_date === issuedOn.value) {
    apply(initial);
  } else load();
})();
