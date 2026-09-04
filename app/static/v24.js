(() => {
  const intValue = input => Math.max(0, Number.parseInt(input?.value || '0', 10) || 0);
  const money = value => `Gs. ${Math.round(Number(value || 0)).toLocaleString('es-PY')}`;
  const workbench = document.querySelector('#calculatorWorkbench');

  // Salary calculator: keep the IPS base synchronized with gross earnings until
  // the professional explicitly overrides it for non-computable concepts.
  const salaryForm = document.querySelector('[data-calculator-panel="salary"]');
  if (salaryForm) {
    const gross = salaryForm.querySelector('[name="gross"]');
    const other = salaryForm.querySelector('[name="other_income"]');
    const discount = salaryForm.querySelector('[name="other_discount"]');
    const applyIps = salaryForm.querySelector('[name="apply_ips"]');
    const ipsBase = salaryForm.querySelector('[name="ips_base"]');
    let manual = false;
    const calculate = () => {
      const computable = intValue(gross) + intValue(other);
      if (ipsBase && !manual) ipsBase.value = String(computable);
      const rate = Number(workbench?.dataset.ipsRate || 9) / 100;
      const base = Math.min(computable, intValue(ipsBase));
      const ips = applyIps?.checked ? Math.round(base * rate) : 0;
      const net = Math.max(0, computable - ips - intValue(discount));
      const grossResult = document.getElementById('calcSalaryGrossResult');
      const ipsResult = document.getElementById('calcSalaryIpsResult');
      const netResult = document.getElementById('calcSalaryNetResult');
      if (grossResult) grossResult.textContent = money(computable);
      if (ipsResult) ipsResult.textContent = money(ips);
      if (netResult) netResult.textContent = money(net);
    };
    ipsBase?.addEventListener('input', () => { manual = true; ipsBase.classList.add('manual-control'); calculate(); });
    [gross, other, discount].forEach(input => input?.addEventListener('input', calculate));
    applyIps?.addEventListener('change', calculate);
    calculate();
  }

  // Vacation preview mirrors the server control from art. 220: use at least the
  // minimum general reference loaded in the system when it is higher.
  const vacationCalculator = document.querySelector('[data-calculator-panel="vacation"]');
  if (vacationCalculator) {
    const salary = vacationCalculator.querySelector('[name="salary"]');
    const days = vacationCalculator.querySelector('[name="days"]');
    const dailyResult = document.getElementById('calcVacationDailyResult');
    const totalResult = document.getElementById('calcVacationResult');
    const calculate = () => {
      const minimum = Number(workbench?.dataset.minimumSalary || 0);
      const monthlyBase = Math.max(intValue(salary), minimum);
      const daily = monthlyBase / 30;
      const quantity = Math.max(0, Number(days?.value || 0));
      if (dailyResult) dailyResult.textContent = money(daily);
      if (totalResult) totalResult.textContent = money(daily * quantity);
    };
    salary?.addEventListener('input', calculate);
    days?.addEventListener('input', calculate);
    calculate();
  }

  // Payroll rows use valid external forms. The IPS base follows total earnings
  // until the accountant deliberately edits it.
  document.querySelectorAll('[data-payroll-row]').forEach(row => {
    const earningNames = ['base_salary', 'overtime', 'commissions', 'bonuses', 'other_income'];
    const inputs = earningNames.map(name => row.querySelector(`[name="${name}"]`)).filter(Boolean);
    const ipsBase = row.querySelector('[name="ips_base"]');
    const grossLabel = row.querySelector('[data-gross-preview]');
    let manual = ipsBase?.dataset.manual === 'true';
    const sync = () => {
      const gross = inputs.reduce((sum, input) => sum + intValue(input), 0);
      if (grossLabel) grossLabel.textContent = money(gross);
      if (ipsBase && !manual) ipsBase.value = String(gross);
    };
    inputs.forEach(input => input.addEventListener('input', sync));
    ipsBase?.addEventListener('input', () => { manual = true; ipsBase.dataset.manual = 'true'; ipsBase.classList.add('manual-control'); });
    sync();
  });

  // Vacation reference from art. 218. It is a suggestion/control: the server
  // validates the final value and records deviations for professional review.
  const vacationForm = document.querySelector('#vacationFormV24');
  if (vacationForm) {
    const employee = vacationForm.querySelector('[name="employee_id"]');
    const year = vacationForm.querySelector('[name="period_year"]');
    const entitled = vacationForm.querySelector('[name="entitled_days"]');
    const reference = document.querySelector('#vacationLegalReference');
    let manual = false;
    const yearsAt = (admission, asOf) => {
      let years = asOf.getUTCFullYear() - admission.getUTCFullYear();
      const anniversaryPassed = (asOf.getUTCMonth() > admission.getUTCMonth()) ||
        (asOf.getUTCMonth() === admission.getUTCMonth() && asOf.getUTCDate() >= admission.getUTCDate());
      if (!anniversaryPassed) years -= 1;
      return Math.max(0, years);
    };
    const update = () => {
      const option = employee?.selectedOptions?.[0];
      const admissionText = option?.dataset.admission || '';
      const periodYear = Number.parseInt(year?.value || '', 10);
      if (!admissionText || !periodYear) return;
      const admission = new Date(`${admissionText}T00:00:00Z`);
      const asOf = new Date(Date.UTC(periodYear, 11, 31));
      const years = yearsAt(admission, asOf);
      const days = years < 1 ? 0 : (years <= 5 ? 12 : (years <= 10 ? 18 : 30));
      if (entitled && !manual) entitled.value = String(days);
      if (reference) {
        reference.textContent = years < 1
          ? 'Referencia art. 218: todavía no completa un año al cierre del periodo. Revisá el derecho proporcional o el régimen aplicable.'
          : `Referencia art. 218: ${days} días por ${years} año(s) de antigüedad al cierre del periodo. Podés modificarlo si existe una condición más favorable o un caso especial.`;
        reference.classList.toggle('warning', years < 1);
      }
    };
    entitled?.addEventListener('input', () => { manual = true; });
    employee?.addEventListener('change', () => { manual = false; update(); });
    year?.addEventListener('input', () => { manual = false; update(); });
    update();
  }

  // Clear query-string feedback after it has been rendered so refreshing does
  // not repeat stale success/error notices.
  const params = new URLSearchParams(location.search);
  if (params.has('form_error') || params.has('saved')) {
    window.setTimeout(() => {
      ['form_error', 'saved'].forEach(key => params.delete(key));
      const next = `${location.pathname}${params.toString() ? `?${params}` : ''}${location.hash}`;
      history.replaceState({}, '', next);
    }, 2500);
  }
})();
