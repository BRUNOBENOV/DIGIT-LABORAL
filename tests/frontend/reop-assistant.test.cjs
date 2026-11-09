'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {createHash, webcrypto} = require('node:crypto');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const vm = require('node:vm');

const worker = readFileSync(join(__dirname, '../../app/reop_browser_extension/worker.js'), 'utf8');
const source = {
  url: 'https://digit-laboral-app.onrender.com/app/compliance/salary-import?period=2026-10',
  frameId: 0, tab: {id: 4, windowId: 1},
};
const portal = {url: 'https://regobpat.mtess.gov.py/salary', frameId: 0, tab: {id: 5, windowId: 1}};
const bytes = Buffer.from('PK\x03\x04 synthetic workbook');
const stage = {
  type: 'stage', protocol: 1, batchId: '7', period: '2026-10', patronal: '000123', rows: '2',
  filename: 'reop_salarios_800000-0_2026-10.xlsx', base64: bytes.toString('base64'),
  sha256: createHash('sha256').update(bytes).digest('hex'),
};

function extension() {
  const listeners = {};
  const event = name => ({addListener: handler => { listeners[name] = handler; }});
  const data = {};
  const injected = [];
  let time = 0;
  const chrome = {
    storage: {session: {
      get: async key => ({[key]: data[key]}),
      set: async values => { Object.assign(data, values); },
      remove: async key => { delete data[key]; },
    }},
    alarms: {clear: async () => true, create: async () => {}, onAlarm: event('alarm')},
    runtime: {onMessageExternal: event('external'), onMessage: event('internal')},
    action: {onClicked: event('click'), setBadgeText: async () => {}, setTitle: async () => {}},
    scripting: {executeScript: async ({target}) => { injected.push(target.tabId); }},
    tabs: {onRemoved: event('removed'), onUpdated: event('updated')},
  };
  vm.runInNewContext(worker, {chrome, URL, atob, crypto: webcrypto, Date: {now: () => time}});
  const send = (eventName, message, sender) => new Promise(resolve => {
    assert.equal(listeners[eventName](message, sender, resolve), true);
  });
  return {
    external: (message, sender = source) => send('external', message, sender),
    internal: (message, sender = portal) => send('internal', message, sender),
    click: (sender = portal) => listeners.click({...sender.tab, url: sender.url}),
    navigate: tabId => listeners.updated(tabId, {status: 'loading'}),
    expire: () => { time += 10 * 60 * 1000; listeners.alarm({name: 'digit-reop-expiry'}); },
    injected,
  };
}

test('la planilla solo sale hacia una pestaña REOP activada y con la patronal correcta', async () => {
  const bridge = extension();
  assert.equal((await bridge.external(stage, {...source, frameId: 1})).ok, false);
  assert.equal((await bridge.external(stage, {...source, url: source.url.replace('https:', 'http:')})).ok, false);
  assert.equal((await bridge.external({...stage, sha256: '0'.repeat(64)})).ok, false);
  assert.equal((await bridge.external(stage)).ok, true);
  assert.equal((await bridge.external(stage)).ok, false);
  assert.equal((await bridge.internal({type: 'info'})).ok, false);
  await bridge.click({...portal, url: 'https://regobpat.mtess.gov.py.example.test/salary'});
  assert.deepEqual(bridge.injected, []);
  await bridge.click({...portal, tab: {id: 6, windowId: 2}});
  assert.equal((await bridge.internal({type: 'info'}, {...portal, tab: {id: 6, windowId: 2}})).ok, false);
  await bridge.click();
  const info = await bridge.internal({type: 'info'});
  assert.equal(info.patronal, '000123');
  assert.equal(info.base64, undefined);
  const take = {type: 'take', batchId: stage.batchId, patronal: stage.patronal};
  assert.equal((await bridge.internal({...take, patronal: '123'})).ok, false);
  assert.equal((await bridge.internal(take, {...portal, tab: {id: 8, windowId: 1}})).ok, false);
  const results = await Promise.all([bridge.internal(take), bridge.internal(take)]);
  assert.equal(results.filter(result => result.ok).length, 1);
  assert.equal(results.find(result => result.ok).base64, stage.base64);
  assert.equal((await bridge.external({type: 'ping'})).busy, false);
});

test('la copia temporal se descarta por vencimiento o al salir de la vista previa', async () => {
  const bridge = extension();
  assert.equal((await bridge.external(stage)).ok, true);
  bridge.expire();
  assert.equal((await bridge.external({type: 'ping'})).busy, false);
  assert.equal((await bridge.external(stage)).ok, true);
  bridge.navigate(source.tab.id);
  assert.equal((await bridge.external({type: 'ping'})).busy, false);
});
