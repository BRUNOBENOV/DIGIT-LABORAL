'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const vm = require('node:vm');

const script = readFileSync(join(__dirname, '../../app/static/salary-import.js'), 'utf8');

test('cambiar empresa limpia el trabajador y la revisión anterior antes de verificar', () => {
  const listeners = {};
  const buttons = [{disabled:false}];
  const confirmations = [{checked:true}];
  const exports = {
    dataset:{}, querySelectorAll(selector) { return selector === 'button[type="submit"]' ? buttons : confirmations; },
    addEventListener(type, callback) { listeners['export:' + type] = callback; },
  };
  const status = {textContent:''};
  const form = {
    action:'https://example.test/app/compliance/salary-import',
    elements:{company_id:{value:'20'},employee_id:{value:'7'},period:{value:'2026-10'}},
    addEventListener(type, callback) { listeners[type] = callback; },
    querySelector() { return status; },
  };
  let callback;
  let destination;
  const window = {
    location:{href:form.action + '?company_id=20&period=2026-10',assign(url) { destination = url; }},
    setTimeout(handler) { callback=handler; }, clearTimeout() {},
  };
  const document = {
    querySelector(selector) { return selector === '[data-salary-import-filters]' ? form : null; },
    querySelectorAll(selector) { return selector === '[data-download-form]' ? [exports] : []; },
  };
  class FormData {
    constructor(selected) { this.form=selected; }
    *[Symbol.iterator]() { for (const [name, field] of Object.entries(this.form.elements)) yield [name,field.value]; }
  }
  vm.runInNewContext(script,{window,document,URL,URLSearchParams,FormData});
  listeners.change({target:{name:'company_id'}});
  assert.equal(form.elements.employee_id.value,'');
  assert.equal(exports.dataset.reviewStale,'true');
  assert.equal(confirmations[0].checked,false);
  assert.equal(buttons[0].disabled,true);
  let blocked=false;
  listeners['export:submit']({preventDefault(){blocked=true;}});
  assert.equal(blocked,true);
  callback();
  assert.equal(new URL(destination).searchParams.get('company_id'),'20');
  assert.equal(new URL(destination).searchParams.get('employee_id'),'');
});

test('la búsqueda admite cédulas con puntos, legajos y nombres con acentos', () => {
  let input;
  const search = {value:'',addEventListener(_type,callback){input=callback;}};
  const rows = [{textContent:'1234567 María Gómez Legajo 45'}, {textContent:'7654321 Pedro Pérez Legajo 71'}];
  const count = {textContent:''};
  const empty = {hidden:true};
  const document = {
    querySelector(selector) {
      return {'[data-import-worker-search]':search,'[data-import-worker-count]':count,'[data-import-worker-empty]':empty}[selector] || null;
    },
    querySelectorAll(selector) { return selector === '[data-import-worker-row]' ? rows : []; },
  };
  vm.runInNewContext(script,{document,window:{}});
  for (const query of ['1.234.567','maria gomez','45']) {
    search.value=query; input();
    assert.equal(rows[0].hidden,false);
    assert.equal(rows[1].hidden,true);
  }
  search.value='inexistente'; input();
  assert.equal(empty.hidden,false);
  assert.equal(count.textContent,'0 de 2 trabajadores');
});
