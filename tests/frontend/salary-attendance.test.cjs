'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const vm = require('node:vm');

test('un timeout de asistencia libera el formulario y permite carga manual', async () => {
  const listeners = {};
  const values = new Map();
  for (const name of [
    'days_worked', 'hours_worked', 'payment_method', 'period_start', 'period_end',
    'attendance_override', 'month', 'attendance_source_id', 'attendance_source_sha256',
    'company_id', 'employee_id',
  ]) {
    values.set(name, {
      value: '', checked: false, disabled: false, readOnly: false, validity: '',
      setCustomValidity(message) { this.validity = message; },
      addEventListener(type, handler) { listeners[name + ':' + type] = handler; },
    });
  }
  values.get('month').value = '2026-10';
  values.get('company_id').value = '10';
  values.get('employee_id').value = '20';
  const status = {textContent: ''};
  const panel = {querySelector(selector) {
    return selector === '[data-attendance-status]' ? status : null;
  }};
  const form = {
    elements: {namedItem(name) { return values.get(name) || null; }},
    querySelector(selector) {
      return selector === '[data-salary-attendance]' ? panel : null;
    },
    addEventListener(type, handler) { listeners['form:' + type] = handler; },
    dispatchEvent() { return true; },
  };
  let timeout;
  const window = {
    location: {pathname: '/app/liquidaciones', href: 'https://example.test/app/liquidaciones?tipo=salary&month=2026-10'},
    history: {state: null, replaceState() {}},
    setTimeout(handler, ms) {
      assert.equal(ms, 8000);
      timeout = handler;
      return 1;
    },
    clearTimeout() {},
  };
  const document = {
    getElementById(id) { return id === 'labor-form' ? form : null; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
  };
  function fetch(_url, {signal}) {
    return new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => {
        const err = new Error('Request aborted');
        err.name = 'AbortError';
        reject(err);
      });
    });
  }
  const code = readFileSync(join(__dirname, '../../app/static/salary-attendance.js'), 'utf8');
  vm.runInNewContext(code, {document, window, fetch, AbortController, URL, URLSearchParams, Date, Event});
  assert.equal(typeof listeners['month:change'], 'function');
  assert.equal(typeof listeners['form:submit'], 'function');
  listeners['month:change']();
  assert.equal(values.get('attendance_override').disabled, true);
  let prevented = 0;
  listeners['form:submit']({preventDefault() { prevented += 1; }});
  assert.equal(prevented, 1, 'se bloquea únicamente mientras la consulta está pendiente');
  assert.equal(typeof timeout, 'function');
  timeout();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(values.get('attendance_override').disabled, false);
  assert.equal(values.get('attendance_override').checked, true);
  assert.equal(values.get('days_worked').validity, '');
  assert.equal(values.get('period_start').value, '2026-10-01');
  assert.equal(values.get('period_end').value, '2026-10-31');
  assert.match(status.textContent, /carga manual/);
  listeners['form:submit']({preventDefault() { prevented += 1; }});
  assert.equal(prevented, 1, 'el guardado vuelve a permitirse al vencer la consulta');
});
