const sidebar = document.querySelector('#sidebar');
document.querySelector('[data-menu]')?.addEventListener('click', () => sidebar?.classList.toggle('open'));
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
  if (event.key === 'Escape') document.querySelectorAll('.modal.show').forEach(modal => modal.classList.remove('show'));
});

// Digit Laboral v13: formulario dinámico de solicitudes.
const requestType = document.querySelector('#requestType');
const requestCompany = document.querySelector('#requestCompany');
const requestEmployee = document.querySelector('#requestEmployee');
const requestGroups = document.querySelectorAll('[data-request-group]');
function updateRequestFields(){
  if(!requestType) return;
  const value = requestType.value;
  const visible = new Set();
  if(value === 'Alta de funcionario') visible.add('alta');
  if(['Baja de funcionario','Cambio salarial','Cambio de cargo','Vacaciones','Ausencia o reposo','Horas extra','Bonificación o descuento'].includes(value)) visible.add('employee');
  if(value === 'Cambio de cargo') visible.add('cargo');
  if(['Cambio salarial','Horas extra','Bonificación o descuento'].includes(value)) visible.add('amount');
  if(['Ausencia o reposo','Horas extra','Bonificación o descuento'].includes(value)) visible.add('period');
  if(['Vacaciones','Ausencia o reposo'].includes(value)) visible.add('dates');
  if(value === 'Vacaciones') visible.add('vacation');
  requestGroups.forEach(group => group.classList.toggle('show', visible.has(group.dataset.requestGroup)));
  document.querySelector('[data-movement-kind]')?.toggleAttribute('hidden', value !== 'Bonificación o descuento');
}
function filterRequestEmployees(){
  if(!requestEmployee || !requestCompany) return;
  const company = requestCompany.value;
  [...requestEmployee.options].forEach(option => {
    if(!option.value) return;
    option.hidden = option.dataset.company !== company;
  });
  if(requestEmployee.selectedOptions[0]?.hidden) requestEmployee.value = '';
}
requestType?.addEventListener('change', updateRequestFields);
requestCompany?.addEventListener('change', filterRequestEmployees);
updateRequestFields();
filterRequestEmployees();
