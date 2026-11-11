"use strict";

const APP = "https://digit-laboral-app.onrender.com";
const REOP = "https://regobpat.mtess.gov.py";
const PATH = "/app/compliance/salary-import";
const EXPIRES = "digit-reop-expiry";
const STATE = "digit-reop-pending";
const MAX_BYTES = 5 * 1024 * 1024;
const TTL = 10 * 60 * 1000;
const PROTOCOL = 1;

let pendingOperation = Promise.resolve();
function serialize(operation) {
  const result = pendingOperation.then(operation);
  pendingOperation = result.catch(() => {});
  return result;
}

function parseUrl(value) {
  try { return new URL(value); } catch (_) { return null; }
}

async function clearPending() {
  await chrome.storage.session.remove(STATE);
  await chrome.alarms.clear(EXPIRES);
  await chrome.action.setBadgeText({text: ""});
}

async function readPending() {
  const pending = (await chrome.storage.session.get(STATE))[STATE];
  if (!pending || pending.expiresAt > Date.now()) return pending;
  await clearPending();
  return null;
}

function reply(operation) {
  return (message, sender, sendResponse) => {
    serialize(() => operation(message || {}, sender))
      .then(data => sendResponse({ok: true, ...data}))
      .catch(error => sendResponse({ok: false, message: error.message || "La extensión no pudo completar la operación."}));
    return true;
  };
}

async function prepareWorkbook(message) {
  const {batchId, period, patronal, rows, filename, base64, sha256} = message;
  if (!/^\d{1,12}$/.test(batchId) || !/^20\d{2}-(0[1-9]|1[0-2])$/.test(period) ||
      !/^\d{1,20}$/.test(patronal) || !/^[1-9]\d{0,6}$/.test(rows) ||
      typeof filename !== "string" || !/^reop_salarios_[a-zA-Z0-9_-]{1,150}\.xlsx$/.test(filename) ||
      typeof base64 !== "string" || base64.length > 4 * Math.ceil(MAX_BYTES / 3) ||
      !/^[a-f0-9]{64}$/.test(sha256)) {
    throw new Error("La planilla preparada no es válida para el asistente REOP.");
  }
  let binary;
  try { binary = atob(base64); } catch (_) {
    throw new Error("El contenido de la planilla no se pudo leer.");
  }
  if (!binary.startsWith("PK\x03\x04") || binary.length > MAX_BYTES) {
    throw new Error("El asistente requiere un Excel XLSX de hasta 5 MB.");
  }
  const bytes = Uint8Array.from(binary, char => char.charCodeAt(0));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const hex = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
  if (hex !== sha256) throw new Error("La huella del Excel no coincide con la del lote de Digit Laboral.");
  return {batchId, period, patronal, rows, filename, base64, expiresAt: Date.now() + TTL};
}

chrome.runtime.onMessageExternal.addListener(reply(async (message, sender) => {
  const source = parseUrl(sender.url);
  if (source?.origin !== APP || source.pathname !== PATH || sender.frameId !== 0 ||
      !Number.isInteger(sender.tab?.id) || sender.tab.incognito) {
    throw new Error("Abrí la vista previa de Salarios de Digit Laboral.");
  }
  const existing = await readPending();
  if (message.type === "ping") return {protocol: PROTOCOL, busy: Boolean(existing), separateWindows: true};
  if (message.type !== "stage" || message.protocol !== PROTOCOL) {
    throw new Error("Actualizá la extensión de Digit Laboral.");
  }
  if (existing) throw new Error("Ya hay un lote pendiente. Adjuntalo o descartalo desde el asistente en REOP.");
  const pending = await prepareWorkbook(message);
  await chrome.storage.session.set({[STATE]: {...pending, sourceTab: sender.tab.id}});
  await chrome.alarms.create(EXPIRES, {when: pending.expiresAt});
  await chrome.action.setBadgeText({text: "1"});
  return {batchId: pending.batchId};
}));

function openPortal(tab) {
  if (!Number.isInteger(tab.id) || tab.incognito || parseUrl(tab.url)?.origin !== REOP) {
    if (Number.isInteger(tab.id)) {
      chrome.action.setBadgeText({tabId: tab.id, text: "REOP"}).catch(() => {});
      chrome.action.setTitle({tabId: tab.id, title: "Abrí REOP para usar la planilla preparada"}).catch(() => {});
    }
    return;
  }
  // Grant access to the REOP tab the operator opens, within this Chrome profile.
  return serialize(async () => {
    const pending = await readPending();
    if (pending) {
      await chrome.storage.session.set({[STATE]: {...pending, targetTab: tab.id}});
    }
  }).then(() => chrome.scripting.executeScript({
    target: {tabId: tab.id}, files: ["portal.js"],
  })).catch(() => chrome.action.setBadgeText({tabId: tab.id, text: "!"}).catch(() => {}));
}
chrome.action.onClicked.addListener(openPortal);

chrome.runtime.onMessage.addListener(reply(async (message, sender) => {
  if (parseUrl(sender.url)?.origin !== REOP || sender.frameId !== 0 || !Number.isInteger(sender.tab?.id) || sender.tab.incognito) {
    throw new Error("Abrí el asistente desde la pestaña oficial de REOP.");
  }
  const pending = await readPending();
  if (!pending) throw new Error("En Digit Laboral, marcá la confirmación y pulsá «Preparar carga en REOP». Después volvé a abrir el asistente.");
  if (pending.targetTab !== sender.tab.id) throw new Error("Volvé a abrir el asistente en esta pestaña de REOP.");
  if (message.type === "info") {
    const {batchId, period, patronal, rows, expiresAt} = pending;
    return {batchId, period, patronal, rows, expiresAt};
  }
  if (message.batchId !== pending.batchId) throw new Error("El lote cambió. Abrí el asistente otra vez.");
  if (message.type === "discard") {
    await clearPending();
    return {};
  }
  if (message.type !== "take" || String(message.patronal).trim() !== pending.patronal) {
    throw new Error("El número patronal que confirmaste no coincide con la planilla.");
  }
  await clearPending();
  return {base64: pending.base64, filename: pending.filename};
}));

chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === EXPIRES) serialize(readPending).catch(() => {});
});

function clearForSource(tabId) {
  serialize(async () => {
    const pending = await readPending();
    if (pending?.sourceTab === tabId) await clearPending();
  }).catch(() => {});
}
chrome.tabs.onRemoved.addListener(clearForSource);
chrome.tabs.onUpdated.addListener((tabId, change) => {
  if (change.status === "loading") clearForSource(tabId);
});
