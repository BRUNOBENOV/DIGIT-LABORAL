(() => {
  "use strict";

  const REOP = "https://regobpat.mtess.gov.py";
  if (location.origin !== REOP || window.top !== window) return;
  globalThis.digitReopClose?.();

  const host = document.createElement("div");
  const shadow = host.attachShadow({mode: "closed"});
  shadow.innerHTML = `
    <style>
      :host { all: initial; position: fixed; right: 16px; bottom: 16px; z-index: 2147483647; }
      section { box-sizing: border-box; width: min(360px, calc(100vw - 32px)); padding: 16px; border: 1px solid #9badc6; border-radius: 12px; background: #fff; color: #16243b; box-shadow: 0 10px 32px #15263b40; font: 14px/1.45 system-ui, sans-serif; }
      header { display: flex; justify-content: space-between; align-items: start; gap: 12px; }
      h2 { margin: 0; font: 700 17px/1.35 system-ui, sans-serif; }
      p { margin: 8px 0; }
      label { display: grid; gap: 5px; margin: 12px 0; font-weight: 650; }
      input, button { box-sizing: border-box; border: 1px solid #a6b7cb; border-radius: 7px; padding: 8px 10px; font: inherit; }
      button { color: #172945; background: #f3f7fc; cursor: pointer; }
      button[type=submit] { color: #fff; background: #123e80; border-color: #123e80; font-weight: 700; }
      button:disabled { opacity: .55; cursor: default; }
      .actions { display: flex; gap: 8px; flex-wrap: wrap; }
      [hidden] { display: none !important; }
    </style>
    <section role="region" aria-label="Asistente REOP de Digit Laboral">
      <header><h2>Digit Laboral · Asistente REOP</h2><button type="button" id="close" aria-label="Cerrar asistente">×</button></header>
      <p id="summary" hidden></p>
      <p id="status" role="status" aria-live="polite">Buscando la planilla preparada…</p>
      <form hidden>
        <label>N.º patronal abierto en REOP
          <input name="patronal" type="text" inputmode="numeric" pattern="[0-9]{1,20}" maxlength="20" required>
        </label>
        <div class="actions">
          <button type="submit">Adjuntar planilla</button>
          <button type="button" id="discard">Descartar</button>
        </div>
      </form>
    </section>`;
  document.documentElement.append(host);

  const status = shadow.querySelector("#status");
  const summary = shadow.querySelector("#summary");
  const form = shadow.querySelector("form");
  const attach = shadow.querySelector("button[type=submit]");
  const discard = shadow.querySelector("#discard");
  let pending;
  let armedDocs = [];
  let armTimer;
  let pickerUntil = 0;
  let pickerDocument;
  let busy = false;

  const normalized = value => (value || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/\s+/g, " ").trim();
  const visible = node => node && node.getClientRects().length > 0 &&
    !node.closest('[hidden], [aria-hidden="true"]') && node.ownerDocument.defaultView.getComputedStyle(node).visibility === "visible";
  const dialogs = '[role="dialog"], dialog[open], .modal.show, .modal.in, .swal2-popup, .sweet-alert.visible';
  const isImportDialog = node => visible(node) && /\b(importar planilla|planilla de recibo salarial)\b/.test(normalized(node.innerText));
  const isSalaryScreen = doc => /\bliquidacion(?:es)? (?:de )?salarios?\b/.test(normalized(doc.body?.innerText));
  const login = doc => /\/login(?:\.php)?\/?$/i.test(doc.location.pathname) ||
    [...doc.querySelectorAll('input[type="password"]')].some(visible);
  const officialDocument = doc => doc?.location?.origin === REOP && !login(doc);

  function docs() {
    const result = [document];
    for (const frame of document.querySelectorAll("iframe")) {
      if (visible(frame) && frame.contentDocument?.location?.origin === REOP) result.push(frame.contentDocument);
    }
    return result.filter(officialDocument);
  }

  function eligible(input) {
    if (!input?.matches?.('input[type="file"]') || input.disabled || input.files?.length || !input.isConnected ||
        !officialDocument(input.ownerDocument)) return false;
    if (input.form?.action && new URL(input.form.action).origin !== REOP) return false;
    const accept = input.accept.toLowerCase();
    return !accept || /xlsx|spreadsheetml|excel|octet-stream|\*\//.test(accept);
  }

  async function message(type, payload = {}) {
    const result = await chrome.runtime.sendMessage({type, ...payload});
    if (!result?.ok) throw new Error(result?.message || "El asistente dejó de estar disponible.");
    return result;
  }

  function disarm() {
    clearTimeout(armTimer);
    for (const doc of armedDocs) doc.removeEventListener("click", capturePicker, true);
    armedDocs = [];
    pickerUntil = 0;
    pickerDocument = undefined;
  }

  globalThis.digitReopClose = () => {
    disarm();
    host.remove();
  };
  shadow.querySelector("#close").addEventListener("click", globalThis.digitReopClose);

  async function transfer(input, patronal) {
    if (busy || !eligible(input)) return;
    busy = true;
    disarm();
    attach.disabled = true;
    discard.disabled = true;
    try {
      const workbook = await message("take", {batchId: pending.batchId, patronal});
      if (!eligible(input)) throw new Error("El formulario cambió. Prepará el lote otra vez en Digit Laboral.");
      const bytes = Uint8Array.from(atob(workbook.base64), char => char.charCodeAt(0));
      const selected = new DataTransfer();
      selected.items.add(new File([bytes], workbook.filename, {
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      }));
      input.files = selected.files;
      if (input.files?.[0]?.size !== bytes.length) throw new Error("El formulario de REOP no recibió el archivo.");
      input.dispatchEvent(new Event("change", {bubbles: true}));
      form.hidden = true;
      status.textContent = "Excel adjuntado. Revisá el resultado de la importación y confirmá en REOP.";
    } catch (error) {
      status.textContent = error.message;
      attach.disabled = false;
      discard.disabled = false;
    } finally {
      busy = false;
    }
  }

  function capturePicker(event) {
    const target = event.target;
    const doc = target?.ownerDocument;
    if (!officialDocument(doc) || !target.closest) return;
    const dialog = target.closest(dialogs);
    if (eligible(target) && (
      (event.isTrusted && isImportDialog(dialog)) ||
      (pickerDocument === doc && Date.now() < pickerUntil)
    )) {
      event.preventDefault();
      event.stopImmediatePropagation();
      void transfer(target, form.elements.patronal.value.trim());
      return;
    }
    if (!event.isTrusted) return;
    const control = target.closest("button, a, label, [role='button'], input[type='button'], input[type='submit']");
    if (!visible(control)) return;
    const name = normalized(control.innerText || control.value || control.getAttribute("aria-label"));
    if ((name === "importar planilla" && isSalaryScreen(doc)) ||
        (isImportDialog(dialog) && /^(ok|aceptar|seleccionar archivo|examinar)$/.test(name))) {
      pickerDocument = doc;
      pickerUntil = Date.now() + 2500;
    }
  }

  form.addEventListener("submit", event => {
    event.preventDefault();
    if (!event.isTrusted || busy) return;
    disarm();
    const patronal = form.elements.patronal.value.trim();
    if (patronal !== pending.patronal) {
      status.textContent = "El número patronal no coincide con el lote. Verificá la patronal que abriste.";
      return;
    }
    const documents = docs();
    const importDialogs = documents.flatMap(doc => [...doc.querySelectorAll(dialogs)].filter(isImportDialog));
    const inputs = [...new Set(importDialogs.flatMap(node => [...node.querySelectorAll('input[type="file"]')].filter(eligible)))];
    if (inputs.length === 1) {
      void transfer(inputs[0], patronal);
      return;
    }
    if (!documents.some(isSalaryScreen) && !importDialogs.length) {
      status.textContent = "Abrí Comunicaciones → Liquidación Salario y pulsá Adjuntar planilla otra vez.";
      return;
    }
    armedDocs = documents;
    for (const doc of armedDocs) doc.addEventListener("click", capturePicker, true);
    status.textContent = "Pulsá Importar Planilla en REOP. Si aparece un aviso de importación, continuá en ese aviso.";
    armTimer = setTimeout(() => {
      disarm();
      status.textContent = "No se detectó un selector de Excel. Podés volver a pulsar Adjuntar planilla.";
    }, 60_000);
  });
  form.elements.patronal.addEventListener("input", () => {
    if (armedDocs.length) {
      disarm();
      status.textContent = "Volvé a confirmar el número patronal para adjuntar.";
    }
  });

  discard.addEventListener("click", async event => {
    if (!event.isTrusted || busy) return;
    disarm();
    try {
      await message("discard", {batchId: pending.batchId});
      form.hidden = true;
      summary.hidden = true;
      status.textContent = "Planilla descartada de esta sesión de Chrome.";
    } catch (error) {
      status.textContent = error.message;
    }
  });

  if (login(document)) {
    status.textContent = "Ingresá a tu cuenta en REOP. Después abrí el asistente en Liquidación Salario.";
    return;
  }
  message("info").then(result => {
    pending = result;
    summary.textContent = `Lote #${result.batchId} · período ${result.period} · patronal ${result.patronal} · ${result.rows} registros.`;
    summary.hidden = false;
    form.hidden = false;
    status.textContent = "Compará la patronal del lote con la que está abierta en REOP.";
  }).catch(error => { status.textContent = error.message; });
})();
