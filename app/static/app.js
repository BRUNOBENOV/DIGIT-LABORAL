const sidebar = document.querySelector('#sidebar');
document.querySelector('[data-menu]')?.addEventListener('click', () => sidebar?.classList.toggle('open'));

const modernNav = document.querySelector('#modernMobileNav');
document.querySelector('[data-modern-menu]')?.addEventListener('click', () => modernNav?.classList.toggle('open'));
modernNav?.querySelectorAll('a').forEach(link => link.addEventListener('click', () => modernNav.classList.remove('open')));

document.querySelectorAll('[data-modal-open]').forEach(btn => btn.addEventListener('click', () => {
  const modal = document.getElementById(btn.dataset.modalOpen);
  modal?.classList.add('show');
  modal?.setAttribute('aria-hidden', 'false');
}));
document.querySelectorAll('[data-modal-close]').forEach(btn => btn.addEventListener('click', () => {
  const modal = btn.closest('.modal');
  modal?.classList.remove('show');
  modal?.setAttribute('aria-hidden', 'true');
}));
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') {
    document.querySelectorAll('.modal.show').forEach(modal => modal.classList.remove('show'));
    modernNav?.classList.remove('open');
  }
});

const formatGs = value => `Gs. ${Math.round(Number(value || 0)).toLocaleString('es-PY')}`;

// Centro de cálculos
const calculatorWorkbench = document.querySelector('#calculatorWorkbench');
if (calculatorWorkbench) {
  const panels = [...document.querySelectorAll('[data-calculator-panel]')];
  const toolButtons = [...document.querySelectorAll('[data-calculation-tool]')];
  toolButtons.forEach(button => button.addEventListener('click', () => {
    const tool = button.dataset.calculationTool;
    toolButtons.forEach(item => item.classList.toggle('active', item === button));
    panels.forEach(panel => panel.classList.toggle('active', panel.dataset.calculatorPanel === tool));
    calculatorWorkbench.scrollIntoView({behavior: 'smooth', block: 'start'});
  }));

  const numberValue = id => Number(document.getElementById(id)?.value || 0);
  const setMoney = (id, value) => { const element = document.getElementById(id); if (element) element.textContent = formatGs(value); };
  const calculateAll = () => {
    const ipsRate = Number(calculatorWorkbench.dataset.ipsRate || 9) / 100;
    const gross = numberValue('calcSalaryGross') + numberValue('calcSalaryIncome');
    const ips = document.getElementById('calcSalaryIps')?.checked ? gross * ipsRate : 0;
    const salaryNet = Math.max(0, gross - ips - numberValue('calcSalaryDiscount'));
    setMoney('calcSalaryGrossResult', gross); setMoney('calcSalaryIpsResult', ips); setMoney('calcSalaryNetResult', salaryNet);

    const monthlyHours = Math.max(1, numberValue('calcHoursMonthly'));
    const hourBase = numberValue('calcHoursSalary') / monthlyHours;
    const hourTotal = hourBase * numberValue('calcHoursQuantity') * numberValue('calcHoursMultiplier');
    setMoney('calcHoursBaseResult', hourBase); setMoney('calcHoursTotalResult', hourTotal);

    setMoney('calcAguinaldoResult', numberValue('calcAguinaldoTotal') / 12);

    const vacationDaily = numberValue('calcVacationSalary') / 30;
    setMoney('calcVacationDailyResult', vacationDaily); setMoney('calcVacationResult', vacationDaily * numberValue('calcVacationDays'));

    const noticeDaily = numberValue('calcNoticeSalary') / 30;
    setMoney('calcNoticeDailyResult', noticeDaily); setMoney('calcNoticeResult', noticeDaily * numberValue('calcNoticeDays'));
  };
  calculatorWorkbench.querySelectorAll('input').forEach(input => input.addEventListener('input', calculateAll));
  calculatorWorkbench.querySelectorAll('input[type="checkbox"]').forEach(input => input.addEventListener('change', calculateAll));
  calculateAll();
}

// Generador de documentos laborales
const certificateForm = document.querySelector('#certificateForm');
if (certificateForm) {
  const companySelect = document.querySelector('#certificateCompany');
  const employeeSelect = document.querySelector('#certificateEmployee');
  const typeInput = document.querySelector('#certificateType');
  const typeTitle = document.querySelector('#certificateFormTitle');
  const cityInput = document.querySelector('#certificateCity');
  const issueDateInput = document.querySelector('#certificateIssueDate');
  const positionInput = document.querySelector('#certificatePosition');
  const admissionInput = document.querySelector('#certificateAdmission');
  const salaryInput = document.querySelector('#certificateSalary');
  const observationsInput = document.querySelector('#certificateObservations');
  const documentNumberInput = document.querySelector('#certificateDocumentNumber');
  const periodStartInput = document.querySelector('#certificatePeriodStart');
  const periodEndInput = document.querySelector('#certificatePeriodEnd');
  const amountInput = document.querySelector('#certificateAmount');
  const effectiveDateInput = document.querySelector('#certificateEffectiveDate');
  const leaveStartInput = document.querySelector('#certificateLeaveStart');
  const leaveEndInput = document.querySelector('#certificateLeaveEnd');
  const nationalityInput = document.querySelector('#certificateNationality');
  const civilStatusInput = document.querySelector('#certificateCivilStatus');
  const recipientInput = document.querySelector('#certificateRecipient');

  const longDate = value => {
    if (!value) return 'fecha a confirmar';
    const [year, month, day] = value.split('-').map(Number);
    return new Intl.DateTimeFormat('es-PY', {day:'numeric', month:'long', year:'numeric', timeZone:'UTC'}).format(new Date(Date.UTC(year, month - 1, day)));
  };
  const shortDate = value => {
    if (!value) return '____/____/________';
    const [year, month, day] = value.split('-');
    return `${day}/${month}/${year}`;
  };
  const selectedOption = select => select?.options[select.selectedIndex];
  const labels = {
    certificado_trabajo_a: 'Certificado de Trabajo', certificado_trabajo_b: 'Constancia Laboral',
    constancia: 'Constancia de Trabajo', aguinaldo_anual: 'Recibo de Pago de Aguinaldo',
    aguinaldo_proporcional: 'Liquidación de Aguinaldo Proporcional', permiso_paternidad: 'Solicitud de Permiso por Paternidad',
    contrato_trabajo: 'Contrato de Trabajo', ficha_empleado: 'Ficha de Empleado',
    solicitud_vacacion: 'Solicitud de Vacaciones', usufructo_vacaciones: 'Constancia de Usufructo de Vacaciones',
    notificacion_preaviso: 'Notificación de Preaviso', renuncia: 'Nota de Renuncia', despido: 'Comunicación de Despido'
  };

  const filterEmployees = () => {
    const companyId = companySelect.value;
    let first = null;
    [...employeeSelect.options].forEach(option => {
      const visible = option.dataset.company === companyId;
      option.hidden = !visible;
      option.disabled = !visible;
      if (visible && !first) first = option;
    });
    if (selectedOption(employeeSelect)?.dataset.company !== companyId && first) employeeSelect.value = first.value;
    const company = selectedOption(companySelect);
    if (company?.dataset.city) cityInput.value = company.dataset.city;
    loadEmployee();
  };
  const loadEmployee = () => {
    const employee = selectedOption(employeeSelect);
    if (!employee) return;
    positionInput.value = employee.dataset.position || '';
    admissionInput.value = employee.dataset.admission || '';
    salaryInput.value = employee.dataset.salary || '0';
    if (!amountInput.value) amountInput.value = employee.dataset.salary || '0';
    updatePreview();
  };
  const updateSpecificFields = () => {
    const type = typeInput.value;
    document.querySelectorAll('[data-specific]').forEach(field => {
      const types = (field.dataset.specific || '').split(/\s+/);
      const visible = types.includes('all') || types.includes(type);
      field.classList.toggle('hidden', !visible);
      field.querySelectorAll('input,select,textarea').forEach(input => { input.disabled = !visible; });
    });
  };
  const buildBody = () => {
    const type = typeInput.value;
    const company = selectedOption(companySelect)?.dataset.name || '';
    const employeeOption = selectedOption(employeeSelect);
    const employee = employeeOption?.dataset.name || '';
    const documentNumber = employeeOption?.dataset.document || '';
    const identity = documentNumber ? `${employee}, con C.I. N.º ${documentNumber}` : employee;
    const role = positionInput.value || 'el cargo registrado en su legajo';
    const admission = longDate(admissionInput.value);
    const salary = Number(salaryInput.value || 0) ? formatGs(salaryInput.value) : 'la remuneración registrada';
    const amount = Number(amountInput?.value || salaryInput.value || 0) ? formatGs(amountInput?.value || salaryInput.value) : 'Gs. 0';
    const recipient = recipientInput?.value || 'Encargado/a de Recursos Humanos';
    const bodies = {
      certificado_trabajo_a: `Por medio de la presente, ${company} certifica que ${identity} presta servicios en la empresa en el cargo de ${role}, desde el ${admission}, percibiendo actualmente una remuneración mensual de ${salary}.\n\nSe expide el presente certificado a solicitud de la persona interesada, para los fines que estime convenientes.`,
      certificado_trabajo_b: `Se deja constancia de que ${identity} forma parte del plantel de ${company}, desempeñándose como ${role} desde el ${admission}. La remuneración mensual registrada es de ${salary}.`,
      constancia: `${company} hace constar que ${identity}, de nacionalidad ${nationalityInput?.value || 'paraguaya'}${civilStatusInput?.value ? `, de estado civil ${civilStatusInput.value}` : ''}, presta servicios en la empresa en el cargo de ${role}, desde el ${admission}, y percibe una remuneración mensual de ${salary}.`,
      aguinaldo_anual: `${company} deja constancia de haber abonado a ${identity} la suma de ${amount}, en concepto de aguinaldo correspondiente al período comprendido entre el ${shortDate(periodStartInput?.value)} y el ${shortDate(periodEndInput?.value)}, calculado conforme al artículo 243 del Código del Trabajo.\n\nCon la firma del presente documento, el trabajador declara haber recibido el importe indicado.`,
      aguinaldo_proporcional: `${company} deja constancia de haber abonado a ${identity} la suma de ${amount}, en concepto de aguinaldo proporcional devengado desde el ${shortDate(periodStartInput?.value)} hasta el ${shortDate(periodEndInput?.value)}, conforme al artículo 244 del Código del Trabajo.`,
      permiso_paternidad: `Señor/a\n${recipient}\n${company}\n\nRef.: Solicitud de permiso por paternidad\n\nYo, ${identity}, trabajador de la empresa, solicito el permiso por paternidad correspondiente a dos semanas posteriores al parto, con goce de sueldo, desde el ${shortDate(leaveStartInput?.value)} hasta el ${shortDate(leaveEndInput?.value)}, de conformidad con el artículo 13, inciso b), de la Ley N.º 5508/2015.`,
      contrato_trabajo: `BORRADOR PARA REVISIÓN PROFESIONAL.\n\nEntre ${company}, en carácter de empleador, y ${identity}, en carácter de trabajador/a, se prepara el presente borrador de contrato para el cargo de ${role}, con inicio el ${admission} y remuneración mensual de ${salary}.`,
      ficha_empleado: `EMPRESA: ${company}\nFUNCIONARIO/A: ${employee}\nCÉDULA: ${documentNumber || '—'}\nCARGO: ${role}\nFECHA DE INGRESO: ${admission}\nSALARIO REGISTRADO: ${salary}`,
      solicitud_vacacion: `Yo, ${identity}, solicito a ${company} el usufructo de mis vacaciones desde el ${shortDate(leaveStartInput?.value)} hasta el ${shortDate(leaveEndInput?.value)}. Las fechas quedarán sujetas a aprobación y constancia escrita de la empresa.`,
      usufructo_vacaciones: `${company} deja constancia de que ${identity}, quien se desempeña como ${role}, usufructará o ha usufructuado sus vacaciones desde el ${shortDate(leaveStartInput?.value)} hasta el ${shortDate(leaveEndInput?.value)}.`,
      notificacion_preaviso: `Señor/a\n${employee}\nC.I. N.º ${documentNumber}\nPresente\n\nPor medio de la presente, ${company} le comunica el preaviso de terminación de la relación laboral, con fecha efectiva ${longDate(effectiveDateInput?.value)}.\n\nDurante el período de preaviso podrá optar, sin disminución salarial, por una licencia diaria de dos horas, un día por semana o el uso continuado del tiempo correspondiente para buscar un nuevo empleo, conforme al artículo 89 del Código del Trabajo.`,
      renuncia: `Señor/a\n${recipient}\n${company}\n\nRef.: Comunicación de renuncia\n\nYo, ${identity}, comunico mi decisión de dar por terminada la relación laboral con fecha efectiva ${longDate(effectiveDateInput?.value)}. Solicito se practique la liquidación final y se expida la constancia de trabajo correspondiente.`,
      despido: `BORRADOR PARA REVISIÓN PROFESIONAL.\n\nPor medio de la presente, ${company} comunica a ${identity} la terminación de la relación laboral con fecha efectiva ${longDate(effectiveDateInput?.value)}. La causa, liquidación y documentación respaldatoria deben revisarse antes de su entrega.`
    };
    const extra = observationsInput.value.trim();
    return `${bodies[type] || ''}${extra ? `\n\nObservaciones: ${extra}` : ''}`;
  };
  function updatePreview() {
    const title = labels[typeInput.value] || 'Documento laboral';
    const companyOption = selectedOption(companySelect);
    const company = companyOption?.dataset.name || '';
    document.querySelector('#certificatePreviewTitle').textContent = title.toUpperCase();
    document.querySelector('#certificatePreviewDate').textContent = `${cityInput.value || 'Ciudad del Este'}, ${longDate(issueDateInput.value)}`;
    document.querySelector('#certificatePreviewBody').textContent = buildBody();
    document.querySelector('#certificatePreviewCompany').textContent = company;
    document.querySelector('#certificatePreviewHeaderCompany').textContent = company;
    document.querySelector('#certificatePreviewHeaderDetails').textContent = [companyOption?.dataset.ruc ? `RUC ${companyOption.dataset.ruc}` : '', companyOption?.dataset.address || ''].filter(Boolean).join(' · ');
    document.querySelector('#certificatePreviewNumber').textContent = documentNumberInput?.value ? `Documento N.º ${documentNumberInput.value}` : '';
    typeTitle.textContent = title;
  }

  document.querySelectorAll('[data-certificate-type]').forEach(button => button.addEventListener('click', () => {
    document.querySelectorAll('[data-certificate-type]').forEach(item => item.classList.toggle('active', item === button));
    typeInput.value = button.dataset.certificateType;
    updateSpecificFields();
    updatePreview();
  }));
  companySelect.addEventListener('change', filterEmployees);
  employeeSelect.addEventListener('change', loadEmployee);
  certificateForm.querySelectorAll('input,select,textarea').forEach(input => {
    input.addEventListener('input', updatePreview);
    input.addEventListener('change', updatePreview);
  });
  document.querySelector('#refreshCertificatePreview')?.addEventListener('click', updatePreview);
  updateSpecificFields();
  filterEmployees();
}
