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

// Generador de certificados
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

  const longDate = value => {
    if (!value) return '—';
    const [year, month, day] = value.split('-').map(Number);
    return new Intl.DateTimeFormat('es-PY', {day:'numeric', month:'long', year:'numeric', timeZone:'UTC'}).format(new Date(Date.UTC(year, month - 1, day)));
  };
  const selectedOption = select => select?.options[select.selectedIndex];
  const labels = {
    certificado_trabajo_a: 'Certificado de Trabajo A', certificado_trabajo_b: 'Certificado de Trabajo B',
    constancia: 'Constancia', contrato_trabajo: 'Contrato de Trabajo', ficha_empleado: 'Ficha de Empleado',
    solicitud_vacacion: 'Solicitud de Vacación', usufructo_vacaciones: 'Usufructo de Vacaciones',
    notificacion_preaviso: 'Notificación de Pre-aviso', renuncia: 'Renuncia', despido: 'Despido'
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
    updatePreview();
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
    const salary = Number(salaryInput.value || 0) ? formatGs(salaryInput.value) : 'el monto registrado en su legajo';
    const bodies = {
      certificado_trabajo_a: `Por medio de la presente, ${company} certifica que el/la señor/a ${identity} presta servicios en la empresa en el cargo de ${role}, desde el ${admission}, percibiendo actualmente un salario mensual de ${salary}.\n\nSe expide el presente certificado a solicitud de la persona interesada, para los fines que estime convenientes.`,
      certificado_trabajo_b: `Se certifica que ${identity} integra el plantel de ${company}, desempeñándose como ${role} desde el ${admission}. La remuneración mensual registrada es de ${salary}.\n\nLa presente constancia se emite a pedido de la persona interesada.`,
      constancia: `Por la presente se deja constancia de que ${identity} mantiene una relación laboral registrada con ${company}, en el cargo de ${role}, con fecha de ingreso ${admission}.`,
      contrato_trabajo: `BORRADOR PARA REVISIÓN PROFESIONAL.\n\nEntre ${company}, en carácter de empleador, y ${identity}, en carácter de trabajador/a, se prepara el presente borrador de contrato para el cargo de ${role}, con inicio previsto o registrado el ${admission} y remuneración mensual de ${salary}.\n\nLas condiciones de jornada, funciones, lugar de trabajo, descansos, beneficios, duración y terminación deberán completarse y revisarse antes de la firma.`,
      ficha_empleado: `EMPRESA: ${company}\nFUNCIONARIO/A: ${employee}\nCÉDULA: ${documentNumber || '—'}\nCARGO: ${role}\nFECHA DE INGRESO: ${admission}\nSALARIO REGISTRADO: ${salary}`,
      solicitud_vacacion: `Yo, ${identity}, solicito a ${company} el usufructo de mis vacaciones correspondientes al periodo que será indicado y aprobado por la empresa. Declaro que las fechas definitivas quedarán sujetas a coordinación y constancia escrita.`,
      usufructo_vacaciones: `${company} deja constancia de que ${identity}, quien se desempeña como ${role}, usufructará o ha usufructuado el periodo de vacaciones indicado en las observaciones de este documento.`,
      notificacion_preaviso: `BORRADOR PARA REVISIÓN PROFESIONAL.\n\nPor medio de la presente, ${company} comunica a ${identity} una notificación de preaviso. Las fechas, plazo, causa y efectos deberán verificarse y consignarse expresamente antes de su entrega.`,
      renuncia: `BORRADOR PARA REVISIÓN PROFESIONAL.\n\nYo, ${identity}, comunico a ${company} mi decisión de dar por terminada la relación laboral. La fecha de efectividad, entrega de funciones y demás extremos deberán completarse antes de la firma.`,
      despido: `BORRADOR PARA REVISIÓN PROFESIONAL.\n\nPor medio de la presente, ${company} comunica a ${identity} la terminación de la relación laboral. La causa, fecha efectiva, liquidación, preaviso y documentación respaldatoria deberán revisarse y detallarse antes de su entrega.`
    };
    const extra = observationsInput.value.trim();
    return `${bodies[type] || ''}${extra ? `\n\nObservaciones: ${extra}` : ''}`;
  };
  function updatePreview() {
    const title = labels[typeInput.value] || 'Documento';
    const company = selectedOption(companySelect)?.dataset.name || '';
    document.querySelector('#certificatePreviewTitle').textContent = title.toUpperCase();
    document.querySelector('#certificatePreviewDate').textContent = `${cityInput.value || 'Ciudad del Este'}, ${longDate(issueDateInput.value)}`;
    document.querySelector('#certificatePreviewBody').textContent = buildBody();
    document.querySelector('#certificatePreviewCompany').textContent = company;
    typeTitle.textContent = title;
  }

  document.querySelectorAll('[data-certificate-type]').forEach(button => button.addEventListener('click', () => {
    document.querySelectorAll('[data-certificate-type]').forEach(item => item.classList.toggle('active', item === button));
    typeInput.value = button.dataset.certificateType;
    updatePreview();
  }));
  companySelect.addEventListener('change', filterEmployees);
  employeeSelect.addEventListener('change', loadEmployee);
  [cityInput, issueDateInput, positionInput, admissionInput, salaryInput, observationsInput].forEach(input => input.addEventListener('input', updatePreview));
  document.querySelector('#refreshCertificatePreview')?.addEventListener('click', updatePreview);
  filterEmployees();
}
