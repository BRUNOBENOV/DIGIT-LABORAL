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
  frameId: 0, documentId: 'source-doc', tab: {id: 4, windowId: 1},
};
const portal = {
  url: 'https://regobpat.mtess.gov.py/liquidacion_salario_list.php',
  frameId: 0, documentId: 'portal-doc', tab: {id: 5, windowId: 2},
};
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
  const openTabs = new Map();
  const tabActions = [];
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
    tabs: {
      get: async id => {
        if (!openTabs.has(id)) throw new Error('Tab closed');
        return openTabs.get(id);
      },
      update: async (id, update) => { tabActions.push(['update', id, update.active]); },
      create: async ({url}) => { tabActions.push(['open', url]); },
      onRemoved: event('removed'), onUpdated: event('updated'),
    },
    windows: {update: async (id, update) => { tabActions.push(['focus', id, update.focused]); }},
  };
  vm.runInNewContext(worker, {chrome, URL, atob, crypto: webcrypto, Date: {now: () => time}});
  const send = (eventName, message, sender) => new Promise(resolve => {
    assert.equal(listeners[eventName](message, sender, resolve), true);
  });
  return {
    external: (message, sender = source) => send('external', message, sender),
    internal: (message, sender = portal) => send('internal', message, sender),
    click: (sender = portal) => {
      const tab = {...sender.tab, url: sender.url};
      openTabs.set(tab.id, tab);
      return listeners.click(tab);
    },
    revoke: id => { openTabs.get(id).url = undefined; },
    navigate: tabId => listeners.updated(tabId, {status: 'loading'}),
    expire: () => { time += 10 * 60 * 1000; listeners.alarm({name: 'digit-reop-expiry'}); },
    injected,
    tabActions,
  };
}

test('la planilla sale a la pestaña REOP activada, incluso en otra ventana, con la patronal correcta', async () => {
  const bridge = extension();
  const secondWindow = {...portal, tab: {id: 6, windowId: 2}};
  assert.equal((await bridge.external(stage, {...source, frameId: 1})).ok, false);
  assert.equal((await bridge.external(stage, {...source, url: source.url.replace('https:', 'http:')})).ok, false);
  assert.equal((await bridge.external({...stage, sha256: '0'.repeat(64)})).ok, false);
  assert.equal((await bridge.external(stage)).ok, true);
  const capabilities = await bridge.external({type: 'ping'});
  assert.equal(capabilities.separateWindows, true);
  assert.equal(capabilities.directPrevalidation, true);
  assert.equal((await bridge.external(stage)).ok, false);
  assert.equal((await bridge.internal({type: 'info'})).ok, false);
  await bridge.click({...portal, url: 'https://regobpat.mtess.gov.py.example.test/salary'});
  await bridge.click({...portal, tab: {...portal.tab, incognito: true}});
  assert.deepEqual(bridge.injected, []);
  await bridge.click();
  assert.equal((await bridge.internal({type: 'info'})).ok, true);
  assert.equal((await bridge.internal({type: 'info'}, secondWindow)).ok, false);
  await bridge.click(secondWindow);
  const info = await bridge.internal({type: 'info'}, secondWindow);
  assert.equal(info.patronal, '000123');
  assert.equal(info.base64, undefined);
  const take = {type: 'take', batchId: stage.batchId, patronal: stage.patronal};
  assert.equal((await bridge.internal({...take, patronal: '123'}, secondWindow)).ok, false);
  assert.equal((await bridge.internal(take)).ok, false);
  const results = await Promise.all([bridge.internal(take, secondWindow), bridge.internal(take, secondWindow)]);
  assert.equal(results.filter(result => result.ok).length, 1);
  assert.equal(results.find(result => result.ok).base64, stage.base64);
  assert.equal(results.find(result => result.ok).filename, 'reop_salarios_800000-0_2026-10_lote-7.xlsx');
  assert.equal((await bridge.external({type: 'ping'})).busy, false);
  const resumed = await bridge.internal({type: 'info'}, secondWindow);
  assert.equal(resumed.tracking, true);
  assert.equal(resumed.base64, undefined);
});

test('el resultado observado queda vinculado al lote y a los documentos de origen y destino', async () => {
  const bridge = extension();
  const poll = {type: 'status', batchId: stage.batchId};
  const report = {type: 'progress', batchId: stage.batchId};
  assert.equal((await bridge.external(stage)).ok, true);
  assert.equal((await bridge.external(poll)).active, true);
  await bridge.click();
  assert.equal((await bridge.internal({type: 'info'})).ok, true);
  assert.equal((await bridge.internal({type: 'take', batchId: stage.batchId, patronal: stage.patronal})).ok, true);
  assert.equal((await bridge.internal({...report, phase: 'attached'}, {...portal, documentId: 'other-doc'})).ok, false);
  assert.equal((await bridge.internal({...report, phase: 'attached'})).ok, true);
  assert.equal((await bridge.external({...poll, batchId: '9'})).active, false);
  assert.equal((await bridge.external(poll, {...source, documentId: 'other-doc'})).active, false);
  assert.equal((await bridge.external(poll, {...source, tab: {id: 20, windowId: 1}})).active, false);
  assert.equal((await bridge.internal({...report, phase: 'imported', valid: 2, errors: 0, imported: 3})).ok, false);
  assert.equal((await bridge.internal({...report, phase: 'corrections', valid: 1, errors: 1, imported: 0, detail: 'dato no transferible'})).ok, true);
  const observed = (await bridge.external(poll)).progress;
  assert.equal(observed.errors, 1);
  assert.equal(observed.detail, undefined);
  assert.equal((await bridge.internal({...report, phase: 'imported', valid: 2, errors: 0, imported: 2})).ok, true);
  await bridge.internal({...report, phase: 'attached'});
  assert.equal((await bridge.external(poll)).progress.phase, 'imported');
  bridge.navigate(portal.tab.id);
  assert.equal((await bridge.external(poll)).active, false);
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

test('publica la cola del lote y descarta detalles o conteos que no corresponden a esa etapa', async () => {
  const bridge = extension();
  const batch = {batchId: stage.batchId};
  const poll = {type: 'status', ...batch};
  const report = {type: 'progress', phase: 'processing', valid: 0, errors: 0, imported: 0, ...batch};
  assert.equal((await bridge.external(stage)).ok, true);
  await bridge.click();
  assert.equal((await bridge.internal({type: 'info'})).ok, true);
  assert.equal((await bridge.internal({type: 'take', patronal: stage.patronal, ...batch})).ok, true);
  assert.equal((await bridge.internal({...report, step: 'validation-queued', jobsAhead: 3, valid: 1})).ok, false);
  assert.equal((await bridge.internal({...report, step: 'validation-queued', jobsAhead: 3, detail: 'texto ajeno'})).ok, true);
  const queued = (await bridge.external(poll)).progress;
  assert.equal(queued.step, 'validation-queued');
  assert.equal(queued.jobsAhead, 3);
  assert.equal(queued.detail, undefined);
  assert.equal((await bridge.internal({...report, step: 'validation-queued', jobsAhead: -1})).ok, true);
  assert.equal((await bridge.external(poll)).progress.jobsAhead, undefined);
  assert.equal((await bridge.internal({...report, step: 'validating', valid: 1, jobsAhead: 3})).ok, true);
  assert.equal((await bridge.external(poll)).progress.jobsAhead, undefined);
  assert.equal((await bridge.internal({...report, step: 'import-queued', valid: 2, jobsAhead: 1})).ok, true);
  assert.equal((await bridge.external(poll)).progress.step, 'import-queued');
});

test('prevalida desde Digit Laboral en la pestaña elegida y entrega el lote a un solo documento', async () => {
  const bridge = extension();
  const batch = {batchId: stage.batchId};
  const open = {type: 'open-portal', ...batch};
  await bridge.click();
  assert.equal((await bridge.internal({type: 'info'})).ready, true);
  assert.equal((await bridge.external({...stage, prevalidate: true})).autoStarted, true);
  assert.deepEqual(bridge.injected, [portal.tab.id, portal.tab.id]);
  assert.equal((await bridge.internal({type: 'info'}, {...portal, url: new URL('/login.php', portal.url).href})).ok, false);
  assert.equal((await bridge.internal({type: 'info'})).autoPrevalidate, true);
  assert.equal((await bridge.internal({type: 'info'})).autoPrevalidate, false);
  const take = {type: 'take', ...batch, patronal: stage.patronal};
  assert.equal((await bridge.internal(take, {...portal, documentId: 'new-doc'})).ok, false);
  assert.equal((await bridge.internal({type: 'review-needed', ...batch, reason: 'active-job'})).ok, true);
  assert.equal((await bridge.external({type: 'status', ...batch})).review, 'active-job');
  assert.equal((await bridge.external(open, {...source, documentId: 'other-doc'})).ok, false);
  assert.equal((await bridge.internal(take)).ok, true);
  assert.equal((await bridge.external(open)).ok, true);
  assert.deepEqual(bridge.tabActions, [['update', portal.tab.id, true], ['focus', portal.tab.windowId, true]]);
});

test('conserva el lote si Chrome revocó el acceso y arranca al pulsar el ícono en REOP', async () => {
  const bridge = extension();
  await bridge.click();
  bridge.revoke(portal.tab.id);
  assert.equal((await bridge.external({...stage, prevalidate: true})).autoStarted, false);
  assert.deepEqual(bridge.injected, [portal.tab.id]);
  assert.equal((await bridge.internal({type: 'info'})).ok, false);
  assert.equal((await bridge.external({type: 'open-portal', batchId: stage.batchId})).ok, true);
  assert.deepEqual(bridge.tabActions, [['open', portal.url]]);
  await bridge.click();
  assert.equal((await bridge.internal({type: 'info'})).autoPrevalidate, true);
  bridge.navigate(portal.tab.id);
  assert.equal((await bridge.external({type: 'status', batchId: stage.batchId})).review, 'portal');
});
