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
  const companyFilter = document.querySelector('#calculationCompanyFilter');
  const employeeFilter = document.querySelector('#calculationEmployeeFilter');
  const syncCalculationContext = () => {
    document.querySelectorAll('[data-sync-company]').forEach(input => { input.value = companyFilter?.value || input.value; });
    document.querySelectorAll('[data-sync-employee]').forEach(input => { input.value = employeeFilter?.value || ''; });
  };
  companyFilter?.addEventListener('change', () => {
    const companyId = companyFilter.value;
    let first = null;
    [...(employeeFilter?.options || [])].forEach(option => {
      if (!option.value) return;
      const visible = !companyId || option.dataset.company === companyId;
      option.hidden = !visible; option.disabled = !visible;
      if (visible && !first) first = option;
    });
    if (employeeFilter && employeeFilter.selectedOptions[0]?.disabled) employeeFilter.value = first?.value || '';
    syncCalculationContext();
  });
  employeeFilter?.addEventListener('change', syncCalculationContext);
  syncCalculationContext();
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
    certificado_trabajo_a: 'Certificado de Trabajo',
    certificado_trabajo_b: 'Certificado de Trabajo B',
    constancia: 'Constancia de Trabajo',
    aguinaldo_anual: 'Recibo de Pago de Aguinaldo',
    aguinaldo_proporcional: 'Liquidación de Aguinaldo Proporcional',
    permiso_paternidad: 'Solicitud de Permiso por Paternidad',
    contrato_trabajo: 'Contrato Individual de Trabajo',
    contrato_tiempo_parcial: 'Contrato Individual de Trabajo a Tiempo Parcial',
    contrato_mipymes_plazo_determinado: 'Contrato a Plazo Determinado para MIE / PE',
    contrato_mipymes_80: 'Contrato a Plazo Determinado MIE — Régimen Salarial Especial',
    adenda_prorroga_contrato: 'Adenda o Prórroga de Contrato de Trabajo',
    ficha_empleado: 'Ficha de Empleado',
    solicitud_vacacion: 'Solicitud de Vacaciones',
    notificacion_vacaciones: 'Notificación de Vacaciones al Trabajador',
    usufructo_vacaciones: 'Constancia de Usufructo de Vacaciones',
    recibo_vacaciones: 'Recibo de Pago de Vacaciones',
    notificacion_preaviso: 'Notificación de Preaviso',
    renuncia: 'Nota de Renuncia',
    despido: 'Comunicación de Despido',
    permiso_laboral: 'Solicitud de Permiso Laboral',
    amonestacion: 'Amonestación Escrita',
    cambio_salarial: 'Comunicación de Cambio Salarial',
    alta_funcionario: 'Constancia de Alta de Funcionario',
    baja_funcionario: 'Constancia de Baja de Funcionario',
    recibo_salario: 'Recibo de Salario',
    liquidacion_final: 'Liquidación Final'
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
  const clearNewVacationRequestFields = () => {
    if (typeInput.value !== 'solicitud_vacacion') return;
    ['#certificateLeaveStart', '#certificateLeaveEnd', '#certificateVacationDays'].forEach(selector => {
      const field = document.querySelector(selector);
      if (field) field.value = '';
    });
    const yearField = document.querySelector('#certificateVacationYear');
    const issueDate = document.querySelector('#certificateIssueDate')?.value || '';
    if (yearField) yearField.value = issueDate.length >= 4 ? issueDate.slice(0, 4) : String(new Date().getFullYear());
  };
  const loadEmployee = () => {
    const employee = selectedOption(employeeSelect);
    if (!employee) return;
    positionInput.value = employee.dataset.position || '';
    admissionInput.value = employee.dataset.admission || '';
    salaryInput.value = employee.dataset.salary || '0';
    const salaryBasic = document.querySelector('#certificateSalaryBasic');
    if (salaryBasic) salaryBasic.value = employee.dataset.salary || '0';
    if (!amountInput.value) amountInput.value = employee.dataset.salary || '0';

    // Reutiliza el último registro guardado de vacaciones del funcionario seleccionado.
    const vacationFields = [
      ['#certificateLeaveStart', 'vacationStart'],
      ['#certificateLeaveEnd', 'vacationEnd'],
      ['#certificateVacationYear', 'vacationYear']
    ];
    vacationFields.forEach(([selector, key]) => {
      const field = document.querySelector(selector);
      if (field && employee.dataset[key] !== undefined) {
        field.value = employee.dataset[key] || '';
      }
    });
    clearNewVacationRequestFields();
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
    clearNewVacationRequestFields();
  };
  const buildBody = () => {
    const type = typeInput.value;
    const company = selectedOption(companySelect)?.dataset.name || '[NOMBRE DE LA EMPRESA]';
    const employeeOption = selectedOption(employeeSelect);
    const employee = employeeOption?.dataset.name || '[NOMBRE COMPLETO DEL FUNCIONARIO]';
    const documentNumber = employeeOption?.dataset.document || '[N.º DE C.I.]';
    const employeeAddress = employeeOption?.dataset.address || '[DOMICILIO DEL FUNCIONARIO]';
    const companyAddress = companySelect.value ? (selectedOption(companySelect)?.dataset.address || '[DOMICILIO DE LA EMPRESA]') : '[DOMICILIO DE LA EMPRESA]';
    const identity = documentNumber ? employee + ', con C.I. N.º ' + documentNumber : employee;
    const role = positionInput.value || '[CARGO]';
    const admission = admissionInput.value ? longDate(admissionInput.value) : '[FECHA DE INGRESO]';
    const salaryRaw = Math.max(0, Number(salaryInput.value || 0));
    const salary = salaryRaw ? 'Gs. ' + formatGs(salaryRaw) : 'remuneración registrada en el legajo';
    const recipient = recipientInput?.value || 'Encargado/a de Recursos Humanos';
    const value = name => (document.querySelector('[name="' + name + '"]')?.value || '').trim();
    const num = name => Math.max(0, Number(value(name) || 0));
    const money = amount => 'Gs. ' + formatGs(amount);
    const from = shortDate(leaveStartInput?.value);
    const until = shortDate(leaveEndInput?.value);
    const startPeriod = shortDate(periodStartInput?.value);
    const endPeriod = shortDate(periodEndInput?.value);
    const amount = num('amount') || salaryRaw;
    const lastPeriodSalary = num('last_period_salary_amount');
    const lastPeriodSalaryDisplay = lastPeriodSalary > 0
      ? money(lastPeriodSalary)
      : 'A COMPLETAR CON EL ÚLTIMO RECIBO DE PAGO';
    const includeSalary = Boolean(document.querySelector('#certificateIncludeSalary')?.checked);
    const extra = observationsInput.value.trim();
    const notes = extra ? '\n\nObservaciones: ' + extra : '';

    const contractText = [
      'BORRADOR CONTRACTUAL — COMPLETAR Y REVISAR ANTES DE FIRMAR.',
      'En ' + (cityInput.value || 'Ciudad del Este') + ', a los ' + longDate(issueDateInput.value) + ', entre ' + company +
        ', RUC ' + (selectedOption(companySelect)?.dataset.ruc || 'a consignar') + ', y ' + identity + ', acuerdan documentar la relación laboral.',
      '1. CARGO, FUNCIONES Y LUGAR. Cargo: ' + role + '. Funciones: ' + (value('job_functions') || 'COMPLETAR FUNCIONES CONCRETAS') +
        '. Lugar: ' + (value('workplace') || 'COMPLETAR ESTABLECIMIENTO') + '.',
      '2. MODALIDAD Y DURACIÓN. Modalidad: ' + (value('contract_modality') || 'según modelo seleccionado') +
        '. Inicio: ' + admission + '. Finalización, si corresponde: ' + (value('contract_end_date') ? shortDate(value('contract_end_date')) : 'No aplica / completar si es plazo determinado') +
        '. Causa temporal documentada: ' + (value('contract_cause') || 'Completar si corresponde') + '.',
      '3. JORNADA Y DESCANSOS. Horario: ' + (value('work_schedule') || 'COMPLETAR DÍAS Y HORARIOS') +
        '. Descanso semanal: ' + (value('weekly_rest') || 'COMPLETAR') +
        '. Período de prueba, si procede: ' + (value('probation_period') || 'según modalidad y ley aplicable') + '.',
      '4. REMUNERACIÓN. Importe mensual: ' + salary + '. Periodicidad: ' + (value('payment_frequency') || 'según legajo') + '.',
      '5. DERECHOS Y REGISTRO. Cumplir la legislación laboral y de seguridad social. El documento interno no sustituye los registros que correspondan ante MTESS o IPS.',
      type === 'adenda_prorroga_contrato' ? 'Contrato anterior: ' + (value('previous_contract_number') || 'COMPLETAR N.º Y FECHA') + '.' : ''
    ].filter(Boolean).join('\n\n');

    const salaryIncomes = [
      ['Salario básico', num('salary_basic_amount') || salaryRaw],
      ['Recargo nocturno', num('night_surcharge_amount')],
      ['Horas extras diurnas (50%)', num('overtime_day_amount')],
      ['Horas extras nocturnas (100%)', num('overtime_night_amount')],
      ['Feriados trabajados', num('holiday_amount')],
      ['Vacaciones pagadas', num('vacation_pay_amount')],
      ['Asignación familiar', num('family_allowance_amount')],
      ['Comisiones', num('commission_amount')],
      ['Gratificaciones', num('gratification_amount')],
      ['Premios', num('prize_amount')],
      ['Bonificaciones', num('bonus_amount')],
      [value('other_income_description') || 'Otros ingresos', num('other_income_amount')]
    ].filter((item, index) => item[1] > 0 || index === 0);
    const salaryDeductions = [
      ['Aporte IPS trabajador/a', num('ips_deduction_amount')],
      ['Anticipo salarial', num('advance_deduction_amount')],
      ['Descuento autorizado por escrito', num('authorized_deduction_amount')],
      ['Orden de autoridad competente', num('authority_deduction_amount')],
      [value('other_deduction_description') || 'Otros descuentos', num('other_deduction_amount')]
    ].filter(item => item[1] > 0);
    const salaryGross = salaryIncomes.reduce((sum, item) => sum + item[1], 0);
    const salaryDeductionsTotal = salaryDeductions.reduce((sum, item) => sum + item[1], 0);
    const salaryDetail = [
      'DETALLE DE HABERES',
      ...salaryIncomes.map(item => item[0] + ': ' + money(item[1])),
      'TOTAL HABERES: ' + money(salaryGross),
      'DESCUENTOS',
      ...(salaryDeductions.length ? salaryDeductions.map(item => item[0] + ': ' + money(item[1])) : ['Sin descuentos consignados']),
      'TOTAL DESCUENTOS: ' + money(salaryDeductionsTotal),
      'NETO A PERCIBIR: ' + money(salaryGross - salaryDeductionsTotal)
    ].join('\n');

    const settlementIncomes = [
      ['Salarios pendientes', num('settlement_salary_due')],
      ['Preaviso', num('settlement_notice_amount')],
      ['Indemnización', num('settlement_indemnity_amount')],
      ['Vacaciones pendientes/proporcionales', num('settlement_vacation_amount')],
      ['Aguinaldo devengado/proporcional', num('settlement_bonus_amount')],
      [value('settlement_other_income_description') || 'Otros haberes', num('settlement_other_income_amount')]
    ].filter(item => item[1] > 0);
    const settlementDeductions = [
      ['Descuentos consignados', num('settlement_ips_deduction')],
      [value('settlement_other_deduction_description') || 'Otros descuentos sujetos a revisión', num('settlement_other_deduction')]
    ].filter(item => item[1] > 0);
    const settlementGross = settlementIncomes.reduce((sum, item) => sum + item[1], 0) || amount;
    const settlementDiscounts = settlementDeductions.reduce((sum, item) => sum + item[1], 0);

    const bodies = {
      certificado_trabajo_a: 'C E R T I F I C O:\n\n' +
        (value('effective_date')
          ? 'Que ' + identity + ' prestó servicios en la firma comercial ' + company + ', desde el ' + admission +
            ' hasta el ' + longDate(value('effective_date')) + ', desempeñándose como ' + role + '.\n' +
            'Salario devengado durante el último período de pago: ' + lastPeriodSalaryDisplay + '.'
          : 'Que ' + identity + ' presta servicios en la firma comercial ' + company + ' desde el ' + admission +
            ', desempeñándose como ' + role + '.' +
            (includeSalary ? ' Percibe una remuneración mensual registrada de ' + money(salaryRaw) + '.' : '')),
      certificado_trabajo_b: 'C E R T I F I C O:\n\n' +
        (value('effective_date')
          ? 'Que ' + identity + ' prestó servicios en la firma comercial ' + company + ', desde el ' + admission +
            ' hasta el ' + longDate(value('effective_date')) + ', desempeñándose como ' + role + '.\n' +
            'Salario devengado durante el último período de pago: ' + lastPeriodSalaryDisplay + '.'
          : 'Que ' + identity + ' presta servicios en la firma comercial ' + company + ' desde el ' + admission +
            ', desempeñándose como ' + role + '.' +
            (includeSalary ? ' Percibe una remuneración mensual registrada de ' + money(salaryRaw) + '.' : '')),
      constancia: 'C E R T I F I C O:\n\n' +
        (value('effective_date')
          ? 'Que ' + identity + ' prestó servicios en la firma comercial ' + company + ', desde el ' + admission +
            ' hasta el ' + longDate(value('effective_date')) + ', desempeñándose como ' + role + '.\n' +
            'Salario devengado durante el último período de pago: ' + lastPeriodSalaryDisplay + '.'
          : 'Que ' + identity + ', de nacionalidad ' + (nationalityInput?.value || 'paraguaya').toUpperCase() +
            (civilStatusInput?.value ? ', de estado civil ' + civilStatusInput.value.toUpperCase() : '') +
            (employeeOption?.dataset.address ? ', domiciliado/a en ' + employeeOption.dataset.address : '') +
            ', es empleado/a de la firma comercial ' + company +
            (selectedOption(companySelect)?.dataset.address ? ', ubicada sobre la calle ' + selectedOption(companySelect).dataset.address : '') +
            ', desde el ' + admission + ', desempeñándose como ' + role + '.' +
            (includeSalary ? ' Percibe una remuneración mensual registrada de ' + money(salaryRaw) + '.' : '') +
            '\n\nSe expide la presente constancia para los fines y efectos a que hubiere lugar.'),
      aguinaldo_anual: 'RECIBO DE PAGO DE AGUINALDO\n\nEmpleador: ' + company + '\nTrabajador/a: ' + identity +
        '\nPeríodo considerado: ' + startPeriod + ' al ' + endPeriod + '\nFecha de pago: ' + shortDate(value('payment_date')) +
        '\n\nImporte abonado: ' + money(amount) + '.\n\nVerificar que el importe coincida con las remuneraciones computables y con el registro de pago comunicado al REOP. La firma acredita recepción del importe consignado.',
      aguinaldo_proporcional: 'LIQUIDACIÓN DE AGUINALDO PROPORCIONAL\n\nTrabajador/a: ' + identity +
        '\nPeríodo de devengo: ' + startPeriod + ' al ' + endPeriod + '\nFecha de pago: ' + shortDate(value('payment_date')) +
        '\n\nImporte consignado: ' + money(amount) + '.\n\nRevisar el período y la base de cálculo antes del pago.',
      permiso_paternidad: 'SOLICITUD DE PERMISO POR PATERNIDAD\n\nA: ' + recipient + '\nEmpresa: ' + company +
        '\nSolicitante: ' + identity + '\nPeríodo solicitado: ' + from + ' al ' + until +
        '\nHecho generador (nacimiento): ' + shortDate(value('birth_event_date')) +
        '\n\nAdjuntar la documentación respaldatoria. El período y los efectos del permiso deben comprobarse con la normativa vigente.',
      contrato_trabajo: contractText,
      contrato_tiempo_parcial: contractText + '\n\nMODELO A TIEMPO PARCIAL: verificar la jornada reducida, remuneración aplicable y registros de seguridad social con el modelo oficial vigente del MTESS.',
      contrato_mipymes_plazo_determinado: contractText + '\n\nMODELO ESPECIAL MIE / PE: comprobar la elegibilidad de la empresa y los requisitos de la Ley N.º 7444/2025, Decreto N.º 4535/2025 y Resolución MTESS N.º 220/2026.',
      contrato_mipymes_80: contractText + '\n\nATENCIÓN: régimen salarial especial sujeto a requisitos legales específicos. No utilizar sin acreditación documental de elegibilidad.',
      adenda_prorroga_contrato: contractText + '\n\nADENDA: adjuntar e identificar el contrato base y verificar los límites legales de contratación a plazo.',
      ficha_empleado: 'FICHA INDIVIDUAL DE PERSONAL\n\nEmpresa: ' + company + '\nFuncionario/a: ' + employee + '\nC.I.: ' + (documentNumber || 'No consignada') +
        '\nCargo: ' + role + '\nIngreso: ' + admission + '\nSalario registrado: ' + salary +
        '\nTipo de contrato: ' + (value('contract_modality') || 'Ver legajo') + '\n\nDocumento interno de administración de personal. Resguardar los datos personales.',
      solicitud_vacacion: 'SOLICITUD DE VACACIONES\n\nA: ' + recipient + '\nEmpresa: ' + company + '\nSolicitante: ' + identity +
        '\nPeríodo anual: ' + (value('vacation_period_year') || String(new Date().getFullYear())) +
        '\nFechas solicitadas: ' + from + ' al ' + until + '\nDías solicitados: ' + (value('vacation_days') || 'A completar') +
        '\nFecha de solicitud: ' + shortDate(value('vacation_request_date') || issueDateInput.value) +
        '\n\nLa solicitud queda sujeta a la verificación del saldo y a la autorización y comunicación escrita del empleador.',
      notificacion_vacaciones: 'NOTIFICACIÓN DE VACACIONES AL TRABAJADOR/A\n\nEmpleador: ' + company + '\nTrabajador/a: ' + identity +
        '\nPeríodo anual: ' + (value('vacation_period_year') || 'A completar') + '\nDesde: ' + from + ' — Hasta: ' + until +
        '\nDías consignados: ' + (value('vacation_days') || 'A completar') + '\nFecha de solicitud: ' + shortDate(value('vacation_request_date')) +
        '\nFecha de comunicación: ' + shortDate(value('vacation_notice_date') || issueDateInput.value) +
        '\nRemuneración por vacaciones: ' + money(num('vacation_amount')) +
        '\n\nConservar esta notificación y el recibo de pago. Verificar el saldo, las fechas e importe antes de entregar.',
      usufructo_vacaciones: 'CONSTANCIA DE USUFRUCTO DE VACACIONES\n\n' + company + ' deja constancia de que ' + identity +
        ', quien se desempeña como ' + role + ', usufructó o usufructará vacaciones del período ' + (value('vacation_period_year') || 'a completar') +
        ', desde ' + from + ' hasta ' + until + '.\n\nDías consignados: ' + (value('vacation_days') || 'A completar') +
        '. Conservar registro del período y documentación de pago.',
      recibo_vacaciones: 'RECIBO DE PAGO DE VACACIONES\n\nEmpleador: ' + company + '\nTrabajador/a: ' + identity +
        '\nPeríodo anual: ' + (value('vacation_period_year') || 'A completar') + '\nVacaciones desde ' + from + ' hasta ' + until +
        '\nDías consignados: ' + (value('vacation_days') || 'A completar') + '\nFecha de pago: ' + shortDate(value('vacation_payment_date')) +
        '\nImporte realmente abonado: ' + money(num('vacation_amount')) +
        '\n\nLa firma acredita recepción del importe efectivamente pagado; conservar original firmado y entregar duplicado al trabajador/a.',
      notificacion_preaviso: 'NOTIFICACIÓN DE PREAVISO\n\nA: ' + identity + '\nEmpleador: ' + company +
        '\nInicio del preaviso: ' + shortDate(value('notice_start_date') || issueDateInput.value) +
        '\nFecha efectiva de terminación: ' + longDate(effectiveDateInput?.value) +
        '\nPlazo consignado: ' + (value('notice_days') || 'A completar') + ' día(s)\nContexto a revisar: ' + (value('termination_reason') || 'A completar') +
        '\n\nVerificar plazos y supuestos legales del caso. La firma acredita recepción y no necesariamente conformidad.',
      renuncia: 'NOTA DE RENUNCIA\n\nA: ' + recipient + '\nEmpresa: ' + company + '\n\nYo, ' + identity +
        ', comunico mi decisión de renunciar al cargo de ' + role + ', con fecha efectiva ' + longDate(effectiveDateInput?.value) +
        '. Solicito que se practique la liquidación y se entreguen los documentos de cierre. Dejar constancia de la fecha de recepción.',
      despido: 'COMUNICACIÓN DE TERMINACIÓN — REVISIÓN LEGAL OBLIGATORIA\n\nA: ' + identity + '\nEmpleador: ' + company +
        '\nFecha efectiva: ' + longDate(effectiveDateInput?.value) + '\nÚltimo día trabajado: ' + shortDate(value('last_worked_date')) +
        '\nMotivo/circunstancias: ' + (value('termination_reason') || 'A completar con hechos específicos y respaldo documental') +
        '\n\nVerificar causal, antecedentes, estabilidad especial, preaviso y liquidación antes de emitir. Este modelo no califica automáticamente la terminación como justificada.',
      permiso_laboral: 'SOLICITUD DE PERMISO LABORAL\n\nA: ' + recipient + '\nEmpresa: ' + company + '\nSolicitante: ' + identity +
        '\nTipo de permiso: ' + (value('leave_type') || 'A especificar') + '\nPeríodo: ' + from + ' al ' + until +
        '\nCantidad: ' + (value('leave_quantity') || 'A completar') + ' ' + value('leave_unit') +
        '\n¿Con goce de sueldo?: ' + (value('paid_leave') || 'A resolver') + '\nCompensación propuesta: ' + (value('compensation_method') || 'A resolver') +
        '\n\nLa autorización y documentación respaldatoria dependen del tipo de licencia o permiso.',
      amonestacion: 'COMUNICACIÓN DE MEDIDA DISCIPLINARIA — REVISIÓN PROFESIONAL\n\nA: ' + identity + '\nEmpleador: ' + company +
        '\nMedida: ' + (value('disciplinary_action') || 'Amonestación escrita') + '\nFecha del hecho: ' + shortDate(value('incident_date')) +
        '\nHechos concretos: ' + (value('incident_details') || 'A completar con datos objetivos y verificables') +
        '\nPeríodo de la medida, si corresponde: ' + shortDate(value('sanction_start_date')) + ' al ' + shortDate(value('sanction_end_date')) +
        '\n\nRevisar reglamento interno, antecedentes, proporcionalidad y derecho de defensa. La firma de recepción no implica admisión de responsabilidad.',
      cambio_salarial: 'COMUNICACIÓN DE CAMBIO SALARIAL\n\n' + company + ' comunica a ' + identity + ' que, a partir del ' +
        longDate(effectiveDateInput?.value) + ', la remuneración mensual consignada será de ' + money(amount) +
        '. Remuneración anterior consignada: ' + money(num('previous_salary')) + '.\n\nDocumentar el acuerdo cuando corresponda y actualizar los registros de nómina.',
      alta_funcionario: 'CONSTANCIA INTERNA DE ALTA\n\n' + company + ' deja constancia interna del ingreso de ' + identity + ' al cargo de ' + role +
        ', a partir del ' + admission + ', con remuneración registrada de ' + money(salaryRaw) +
        '.\n\nEsta constancia no sustituye la comunicación de entrada ni los registros ante instituciones competentes.',
      baja_funcionario: 'CONSTANCIA INTERNA DE BAJA\n\n' + company + ' deja constancia interna del cese de servicios de ' + identity +
        ', con fecha efectiva ' + longDate(effectiveDateInput?.value) + ' y último día trabajado ' + shortDate(value('last_worked_date')) +
        '.\n\nMotivo: ' + (value('termination_reason') || 'A completar') + '. Esta constancia no sustituye la comunicación de salida ni la liquidación final.',
      recibo_salario: 'RECIBO DE SALARIO — DETALLE DEL PERÍODO\n\nEmpleador: ' + company + '\nTrabajador/a: ' + identity +
        '\nPeríodo: ' + startPeriod + ' al ' + endPeriod + '\nFecha de pago: ' + shortDate(value('payment_date')) +
        '\nForma de pago: ' + (value('payment_method') || 'A completar') +
        '\nDías trabajados: ' + (value('days_worked') || 'A completar') + '; horas: ' + (value('hours_worked') || 'A completar') +
        '; piezas/tareas: ' + (value('units_worked') || 'No aplica / completar') + '\n\n' + salaryDetail +
        '\n\nDetalle de ingresos y descuentos conforme al modelo de recibo de salarios del MTESS. Incluir solo descuentos procedentes y respaldados; conservar original firmado y entregar duplicado.',
      liquidacion_final: 'BORRADOR DE LIQUIDACIÓN FINAL — VERIFICAR CÁLCULO\n\nTrabajador/a: ' + identity + '\nEmpleador: ' + company +
        '\nFecha de terminación: ' + longDate(effectiveDateInput?.value) + '\nÚltimo día trabajado: ' + shortDate(value('last_worked_date')) +
        '\n\n' + (settlementIncomes.length ? settlementIncomes.map(item => item[0] + ': ' + money(item[1])).join('\n') : 'Importe general consignado: ' + money(settlementGross)) +
        '\nTotal haberes: ' + money(settlementGross) +
        '\n' + (settlementDeductions.length ? settlementDeductions.map(item => item[0] + ': ' + money(item[1])).join('\n') : 'Sin descuentos consignados') +
        '\nTotal descuentos: ' + money(settlementDiscounts) + '\nNETO REFERENCIAL: ' + money(settlementGross - settlementDiscounts) +
        '\n\nComprobar cada rubro y su fundamento antes de firmar o pagar.'
    };
    return (bodies[type] || '') + notes;
  };

  function renderCertificatePreviewBody(type, bodyText) {
    const previewBody = document.querySelector('#certificatePreviewBody');
    const certifyHeading = 'C E R T I F I C O:\n\n';
    const certificateModelTypes = new Set(['certificado_trabajo_a', 'certificado_trabajo_b', 'constancia']);
    if (certificateModelTypes.has(type) && bodyText.startsWith(certifyHeading)) {
      const heading = document.createElement('div');
      heading.className = 'certificate-a-certify';
      heading.textContent = 'C E R T I F I C O:';
      previewBody.replaceChildren(heading, document.createTextNode('\n\n' + bodyText.slice(certifyHeading.length)));
    } else {
      previewBody.textContent = bodyText;
    }
  }

  let canonicalCertificatePreviewTimer = null;
  let canonicalCertificatePreviewSequence = 0;
  function scheduleCanonicalCertificatePreview(type) {
    const sequence = ++canonicalCertificatePreviewSequence;
    if (canonicalCertificatePreviewTimer !== null) window.clearTimeout(canonicalCertificatePreviewTimer);
    if (!['certificado_trabajo_a', 'certificado_trabajo_b', 'constancia'].includes(type)) return;
    // Sin empresa y funcionario no existe un documento canónico; mantener el modelo local con marcadores claros.
    if (!companySelect.value || !employeeSelect.value) return;
    canonicalCertificatePreviewTimer = window.setTimeout(async () => {
      const formData = new FormData(certificateForm);
      formData.set('intent', 'preview');
      try {
        const response = await fetch(certificateForm.action || '/app/certificates', {
          method: 'POST',
          body: formData,
          credentials: 'same-origin',
          headers: { 'Accept': 'application/json' }
        });
        if (!response.ok) return;
        const result = await response.json();
        if (
          sequence !== canonicalCertificatePreviewSequence ||
          typeInput.value !== type ||
          typeof result.body !== 'string'
        ) return;
        renderCertificatePreviewBody(type, result.body);
        if (result.title) document.querySelector('#certificatePreviewTitle').textContent = result.title.toUpperCase();
      } catch (error) {
        // La vista local sigue disponible si falla la sincronización con el servidor.
      }
    }, 300);
  }

  function updatePreview() {
    const type = typeInput.value;
    const title = labels[type] || 'Documento laboral';
    const companyOption = selectedOption(companySelect);
    const employeeOption = selectedOption(employeeSelect);
    const company = companyOption?.dataset.name || '[NOMBRE DE LA EMPRESA]';
    const employee = employeeOption?.dataset.name || '[NOMBRE COMPLETO DEL FUNCIONARIO]';
    const employeeDocument = employeeOption?.dataset.document || '[N.º DE C.I.]';
    const companyColor = companyOption?.dataset.primary || '#0B2D78';

    document.querySelector('#certificatePreviewTitle').textContent = title.toUpperCase();
    const previewDate = document.querySelector('#certificatePreviewDate');
    const issueCity = cityInput.value || 'Ciudad del Este';
    const issueDate = longDate(issueDateInput.value);
    const certificateModelTypes = new Set(['certificado_trabajo_a', 'certificado_trabajo_b', 'constancia']);
    previewDate.textContent = certificateModelTypes.has(type)
      ? issueCity.toUpperCase() + ', ' + issueDate
      : issueCity + ', ' + issueDate;
    previewDate.style.textAlign = certificateModelTypes.has(type) ? 'right' : '';
    previewDate.style.display = '';
    const bodyText = buildBody();
    renderCertificatePreviewBody(type, bodyText);
    document.querySelector('#certificatePreviewHeaderCompany').textContent = company;
    document.querySelector('#certificatePreviewHeaderDetails').textContent = [
      companyOption?.dataset.ruc ? `RUC ${companyOption.dataset.ruc}` : '',
      companyOption?.dataset.address || '',
      companyOption?.dataset.phone ? 'Tel. ' + companyOption.dataset.phone : ''
    ].filter(Boolean).join(' · ') || 'Datos de la empresa pendientes de selección';
    document.querySelector('#certificatePreviewNumber').textContent = documentNumberInput?.value
      ? `Documento N.º ${documentNumberInput.value}`
      : 'Numeración automática';

    const preview = document.querySelector('#certificatePreview');
    if (preview) preview.style.setProperty('--company-primary', companyColor);

    const logo = document.querySelector('#certificatePreviewLogo');
    const mark = document.querySelector('#certificatePreviewMark');
    if (logo && mark) {
      const logoUrl = companyOption?.dataset.logoUrl || '';
      if (!logoUrl) {
        logo.removeAttribute('src');
        logo.classList.add('hidden');
        mark.classList.remove('hidden');
      } else {
        logo.onload = () => {
          logo.classList.remove('hidden');
          mark.classList.add('hidden');
        };
        logo.onerror = () => {
          logo.classList.add('hidden');
          mark.classList.remove('hidden');
        };
        if (logo.getAttribute('src') !== logoUrl) logo.src = logoUrl;
        else if (logo.complete && logo.naturalWidth > 0) {
          logo.classList.remove('hidden');
          mark.classList.add('hidden');
        }
      }
    }

    const letterhead = document.querySelector('#certificatePreviewLetterhead');
    if (letterhead) letterhead.style.borderColor = companyColor;

    const signature = companyOption?.dataset.signature || 'Firma autorizada';
    const signatureTitle = companyOption?.dataset.signatureTitle || (certificateModelTypes.has(type) ? 'Responsable autorizado' : 'Representante legal');
    const selectedTypeButton = [...document.querySelectorAll('[data-certificate-type]')]
      .find(button => button.dataset.certificateType === type);
    const signatureMode = selectedTypeButton?.dataset.signatureMode || 'employer';
    const receiptMode = selectedTypeButton?.dataset.receiptMode || '';
    const usePair = signatureMode === 'both';
    const employeeOnly = signatureMode === 'employee';
    const singleSignature = document.querySelector('#certificatePreviewSingleSignature');
    const signaturePair = document.querySelector('#certificatePreviewSignaturePair');
    if (singleSignature) {
      singleSignature.classList.toggle('hidden', usePair);
      singleSignature.style.setProperty('display', usePair ? 'none' : 'block', 'important');
    }
    if (signaturePair) {
      signaturePair.classList.toggle('hidden', !usePair);
      signaturePair.style.setProperty('display', usePair ? 'grid' : 'none', 'important');
    }

    const previewAddress = document.querySelector('#certificatePreviewAddress');
    if (previewAddress) previewAddress.textContent = '';

    if (usePair) {
      document.querySelector('#certificatePreviewEmployeeName').textContent = employee;
      document.querySelector('#certificatePreviewEmployeeDocument').textContent = `C.I. N.º ${employeeDocument}`;
      document.querySelector('#certificatePreviewPairedSignature').textContent = signature;
      document.querySelector('#certificatePreviewPairedSignatureTitle').textContent = signatureTitle;
      document.querySelector('#certificatePreviewPairedCompany').textContent = company;
    } else if (employeeOnly) {
      document.querySelector('#certificatePreviewSignature').textContent = employee;
      document.querySelector('#certificatePreviewSignatureTitle').textContent = 'Firma del trabajador/a';
      document.querySelector('#certificatePreviewCompany').textContent = `C.I. N.º ${employeeDocument}`;
    } else {
      document.querySelector('#certificatePreviewSignature').textContent = signature;
      document.querySelector('#certificatePreviewSignatureTitle').textContent = certificateModelTypes.has(type)
        ? (signatureTitle || 'Responsable autorizado')
        : signatureTitle;
      document.querySelector('#certificatePreviewCompany').textContent = company;
      if (previewAddress && certificateModelTypes.has(type)) previewAddress.textContent = companyOption?.dataset.address || '';
      document.querySelector('#certificatePreviewPhone').textContent = certificateModelTypes.has(type) && companyOption?.dataset.phone
        ? 'TEL. ' + companyOption.dataset.phone
        : '';
    }

    const previewReceipt = document.querySelector('#certificatePreviewReceipt');
    if (previewReceipt) {
      const receiptTexts = {
        employee_authorization: 'RECIBIDO / AUTORIZACIÓN: ____________________    FECHA: ____/____/________',
        receipt_date: 'Fecha de recepción: ____/____/________',
        receipt_disclaimer: 'Fecha de recepción: ____/____/________. La firma acredita recepción y no necesariamente conformidad con el contenido.'
      };
      const receiptText = receiptTexts[receiptMode] || '';
      previewReceipt.textContent = receiptText;
      previewReceipt.classList.toggle('hidden', !receiptText);
      previewReceipt.style.setProperty('display', receiptText ? 'block' : 'none', 'important');
    }
    typeTitle.textContent = title;
    scheduleCanonicalCertificatePreview(type);
  }

  document.querySelectorAll('[data-certificate-type]').forEach(button => button.addEventListener('click', () => {
    document.querySelectorAll('[data-certificate-type]').forEach(item => item.classList.toggle('active', item === button));
    typeInput.value = button.dataset.certificateType;
    updateSpecificFields();
    updatePreview();
  }));
  companySelect.addEventListener('change', filterEmployees);
  employeeSelect.addEventListener('change', loadEmployee);
  const includeSalaryCheckbox = document.querySelector('#certificateIncludeSalary');
  includeSalaryCheckbox?.addEventListener('change', () => {
    const hiddenSalaryState = document.querySelector('#certificateIncludeSalaryValue');
    if (hiddenSalaryState) hiddenSalaryState.value = includeSalaryCheckbox.checked ? 'on' : 'off';
    updatePreview();
  });
  certificateForm.querySelectorAll('input,select,textarea').forEach(input => {
    input.addEventListener('input', updatePreview);
    input.addEventListener('change', updatePreview);
  });
  document.querySelector('#refreshCertificatePreview')?.addEventListener('click', updatePreview);
  updateSpecificFields();
  filterEmployees();
}


// Filtro del asistente IA
const aiCompany = document.querySelector('#aiCompany');
const aiEmployee = document.querySelector('#aiEmployee');
if (aiCompany && aiEmployee) {
  const filterAIEmployees = () => {
    const companyId = aiCompany.value;
    [...aiEmployee.options].forEach(option => {
      if (!option.value) return;
      const visible = !companyId || option.dataset.company === companyId;
      option.hidden = !visible; option.disabled = !visible;
    });
    if (aiEmployee.selectedOptions[0]?.disabled) aiEmployee.value = '';
  };
  aiCompany.addEventListener('change', filterAIEmployees);
  filterAIEmployees();
}
