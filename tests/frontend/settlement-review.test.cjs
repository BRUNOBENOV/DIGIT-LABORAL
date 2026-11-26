'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const vm = require('node:vm');

function element(value = '') {
  const handlers = new Map();
  return {
    value, checked: false, disabled: false, hidden: false,
    addEventListener(type, fn) {
      if (!handlers.has(type)) handlers.set(type, []);
      handlers.get(type).push(fn);
    },
    notify(type, event = {target: this}) {
      for (const fn of handlers.get(type) || []) fn(event);
    },
    setAttribute() {}, replaceChildren() {},
  };
}

function workbench() {
  const form = element(), panel = element();
  const names = {
    kind: 'settlement', company_id: '1', employee_id: '2', pay_basis: 'monthly',
    reason: 'dismissal', severance_regime: 'ordinary', settlement_preset_version: '2',
    start_date: '2023-01-13', end_date: '2026-11-21', notice_served: '0',
    salary: '3044000', average_salary: '3044000', average_from_salary: 'on',
    average_salary_reviewed: '', average_origin: 'manual', average_payroll_fingerprint: '',
    average_payroll_reviewed: '', pending_days: '', double_days: '', proportional_days: '10',
  };
  const fields = {};
  for (const [name, value] of Object.entries(names)) {
    fields[name] = Object.assign(element(value), {name, dispatchEvent(event) {
      form.notify(event.type, {target: this, detail: event.detail});
    }});
  }
  form.elements = {namedItem: name => fields[name]};
  const views = {};
  for (const name of ['average-review', 'average-salary-hint', 'zero-vacation-balances',
    'average-apply', 'average-manual', 'average-status', 'average-periods', 'average-coverage',
    'average-amount', 'average-methodology']) views['[data-' + name + ']'] = element();
  form.querySelector = panel.querySelector = selector => views[selector] || null;
  panel.closest = () => form;
  const root = {querySelector: () => form};
  const document = {querySelector: selector => selector === '.dl-quick' ? root : panel};
  const blocked = {is_available: false, fingerprint: null, window_start: '2026-05-22',
    window_end: '2026-11-21', closed_count: 0, expected_count: 7, periods: [], blockers: ['Faltan nóminas.']};
  const available = {...blocked, is_available: true, average_salary: '2950407.80',
    fingerprint: 'revisada', window_start: '2026-06-01', window_end: '2026-11-30', closed_count: 6, expected_count: 6};
  const fetch = async url => ({ok: true, json: async () => url.includes('2026-11-30') ? available : blocked});
  let timer;
  class CustomEvent extends Event {
    constructor(type, options) { super(type, options); this.detail = options?.detail; }
  }
  const context = vm.createContext({document, fetch, URLSearchParams, AbortController, Event, CustomEvent,
    setTimeout: fn => { timer = fn; return 1; }, clearTimeout: () => { timer = null; }});
  for (const file of ['settlement-presets.js', 'payroll-average.js']) {
    vm.runInContext(readFileSync(join(__dirname, '../../app/static', file), 'utf8'), context);
  }
  return {fields, views, input(name, value) {
    fields[name].value = value;
    fields[name].dispatchEvent(new Event('input'));
  }, load: () => timer()};
}

test('la revisión corresponde al sueldo vigente y completar saldos conserva los días ya cargados', () => {
  const {fields, views, input} = workbench();
  fields.average_salary_reviewed.checked = true;
  input('salary', '3100000');
  assert.equal(fields.average_salary.value, '3100000');
  assert.equal(fields.average_salary_reviewed.checked, false);
  views['[data-zero-vacation-balances]'].notify('click');
  assert.deepEqual([fields.pending_days.value, fields.double_days.value, fields.proportional_days.value], ['0','0','10']);
  assert.equal(views['[data-zero-vacation-balances]'].hidden, true);
});

test('cambiar el intervalo descarta el promedio aplicado desde nóminas y muestra las fechas faltantes', async () => {
  const {fields, views, input, load} = workbench();
  input('end_date', '2026-11-30');
  await load();
  fields.average_payroll_reviewed.checked = true;
  fields.average_payroll_reviewed.notify('change');
  views['[data-average-apply]'].notify('click');
  assert.equal(fields.average_salary.value, '2950407.80');
  assert.equal(fields.average_origin.value, 'payroll');
  input('end_date', '2026-11-21');
  assert.equal(fields.average_salary.value, '');
  assert.equal(fields.average_payroll_fingerprint.value, '');
  assert.equal(fields.average_origin.value, 'manual');
  await load();
  assert.match(views['[data-average-status]'].textContent, /22\/05\/2026 al 21\/11\/2026/);
  assert.equal(views['[data-average-coverage]'].textContent, '0 de 7');
  assert.equal(views['[data-average-apply]'].disabled, true);
});
