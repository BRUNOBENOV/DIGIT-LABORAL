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
      :host([hidden]) { display: none !important; }
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
          <button type="submit" id="prevalidate" hidden>Adjuntar y prevalidar</button>
          <button type="button" id="discard">Descartar</button>
        </div>
      </form>
    </section>`;
  document.documentElement.append(host);

  const status = shadow.querySelector("#status");
  const summary = shadow.querySelector("#summary");
  const form = shadow.querySelector("form");
  const attach = shadow.querySelector("button[type=submit]");
  const prevalidate = shadow.querySelector("#prevalidate");
  const discard = shadow.querySelector("#discard");
  const employer = form.elements.patronal;
  let pending;
  let armedDocs = [];
  let armTimer;
  let pickerUntil = 0;
  let pickerDocument;
  let busy = false;
  let detected = "";
  let tracking;
  let lastProgress = "";
  let observer;
  let scanTimer;
  let observationTimer;

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

  function currentImporters(doc) {
    if (location.pathname !== "/liquidacion_salario_list.php" || !doc.body) return [];
    const panels = new Set();
    const titles = doc.body.querySelectorAll('h1,h2,h3,h4,h5,h6,[role="heading"],div,p,span,strong');
    for (const title of titles) {
      if (normalized(title.textContent) !== "revisa tu planilla antes de importar" || !visible(title)) continue;
      // Use the closest panel containing the title and the importer steps, even without a dialog role.
      for (let panel = title.parentElement; panel && panel !== doc.body; panel = panel.parentElement) {
        const text = normalized(panel.innerText);
        if (!text.includes("seleccionar archivo") || !/\bprevalidar\b/.test(text)) continue;
        panels.add(panel);
        break;
      }
    }
    return [...panels];
  }

  function importerFiles(panel) {
    return [...panel.querySelectorAll('input[type="file"]')].filter(input => visible(input) && eligible(input));
  }

  function importerPatronal(panel) {
    const values = new Set([...normalized(panel?.innerText).matchAll(/\bpatronal\s+(\d{1,20})\s*[·•|–-]\s*prevalidacion\b/g)]
      .map(match => match[1]));
    return values.size === 1 ? [...values][0] : "";
  }

  function visibleText(container) {
    const nodes = container.ownerDocument.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    const parts = [];
    for (let node = nodes.nextNode(); node; node = nodes.nextNode()) {
      if (node.textContent.trim() && visible(node.parentElement)) parts.push(node.textContent);
    }
    return normalized(parts.join(" "));
  }

  function importerResult(panel, batch) {
    const filename = batch.filename.toLowerCase();
    const titles = panel.querySelectorAll('div,span,strong,p,h2,h3,h4');
    for (const title of titles) {
      if (title.textContent.trim().toLowerCase() !== filename || !visible(title)) continue;
      for (let card = title.parentElement; card && card !== panel; card = card.parentElement) {
        if (!normalized(card.innerText).includes("filas del archivo")) continue;
        const text = visibleText(card);
        if ((text.match(/[a-z0-9][a-z0-9_.-]*\.xlsx?\b/g) || []).some(name => name !== filename)) break;
        const values = [
          /\bfilas del archivo\s*([\d.,]+)\b/,
          /\bsin errores detectados\s*([\d.,]+)\b/,
          /\bfilas con errores\s*([\d.,]+)\b/,
          /\bimportadas\s*([\d.,]+)\b/,
        ].map(pattern => {
          const count = text.match(pattern)?.[1];
          return count ? Number(count.replace(/[.,]/g, "")) : NaN;
        });
        const [rows, valid, errors, imported] = values;
        if (rows !== Number(batch.rows) || !values.every(Number.isSafeInteger) || valid + errors > rows || imported > valid) continue;
        const completed = /\bprevalidacion (?:terminada|completa|finalizada|exitosa)\b|\blist[ao] para importar\b/.test(text);
        let phase = "processing";
        if (imported === rows && /\bimportacion completa\b/.test(text)) phase = "imported";
        else if (errors > 0 && (completed || /\brequiere correcciones\b/.test(text))) phase = "corrections";
        else if (valid === rows && imported === 0 && completed) phase = "prevalidated";
        return {phase, valid, errors, imported};
      }
    }
    return null;
  }

  async function message(type, payload = {}) {
    const result = await chrome.runtime.sendMessage({type, ...payload});
    if (!result?.ok) throw new Error(result?.message || "El asistente dejó de estar disponible.");
    return result;
  }

  function visibleImporter() {
    const panels = docs().flatMap(currentImporters);
    return panels.length === 1 ? panels[0] : null;
  }

  function showProgress(progress) {
    const labels = {
      attached: "Excel adjuntado. Continuá la revisión en REOP.",
      "validation-requested": "Prevalidación solicitada. Revisá el resultado en REOP.",
      processing: `REOP muestra ${progress.valid} sin errores y ${progress.errors} con errores. Revisá el estado en el importador.`,
      corrections: `REOP informa ${progress.errors} fila(s) con errores. Revisá las correcciones en el importador.`,
      prevalidated: "Prevalidación completa. Revisá las filas y decidí si las importás en REOP.",
      imported: `REOP importó ${progress.imported} fila(s). Revisá y confirmá las comunicaciones en el portal.`,
    };
    status.textContent = labels[progress.phase];
  }

  function reportProgress(progress) {
    const fingerprint = JSON.stringify(progress);
    if (fingerprint === lastProgress) return;
    lastProgress = fingerprint;
    showProgress(progress);
    void message("progress", {batchId: pending.batchId, ...progress}).catch(() => {});
    if (progress.phase === "imported") stopObservation();
  }

  function updateView() {
    if (!tracking && (busy || form.hidden)) return;
    const panel = visibleImporter();
    const actual = importerPatronal(panel);
    if (tracking) {
      if (!panel || actual !== pending.patronal) return;
      const result = importerResult(panel, tracking);
      if (result) reportProgress(result);
      return;
    }
    if (actual !== detected) {
      if (actual || employer.value === detected) employer.value = actual;
      employer.readOnly = Boolean(actual);
      detected = actual;
      status.textContent = actual
        ? (actual === pending.patronal
          ? "La patronal abierta en REOP coincide con el lote."
          : `REOP muestra la patronal ${actual}. Abrí la patronal ${pending.patronal} del lote.`)
        : "Compará la patronal del lote con la que está abierta en REOP.";
    }
    attach.disabled = Boolean(actual && actual !== pending.patronal);
    prevalidate.hidden = !actual || actual !== pending.patronal || importerFiles(panel).length !== 1;
  }

  function stopObservation() {
    observer?.disconnect();
    observer = undefined;
    clearTimeout(scanTimer);
    clearTimeout(observationTimer);
    scanTimer = undefined;
  }

  function watchPage(expiresAt) {
    stopObservation();
    observer = new MutationObserver(() => {
      if (scanTimer) return;
      scanTimer = setTimeout(() => {
        scanTimer = undefined;
        updateView();
      }, 150);
    });
    for (const doc of docs()) {
      if (doc.body) observer.observe(doc.body, {subtree: true, childList: true, characterData: true,
        attributes: true, attributeFilter: ["class", "style", "hidden", "aria-hidden", "disabled"]});
    }
    observationTimer = setTimeout(stopObservation, Math.max(0, expiresAt - Date.now()));
    updateView();
  }

  async function requestPrevalidation(panel, input, file) {
    for (let attempt = 0; attempt < 20; attempt++) {
      await new Promise(resolve => setTimeout(resolve, 125));
      const selected = input.files?.[0];
      const sameFile = input.files?.length === 1 && selected.name === file.name &&
        selected.size === file.size && selected.lastModified === file.lastModified;
      if (!host.isConnected || host.hidden || !visible(panel) || !panel.contains(input) || !visible(input) ||
          !officialDocument(input.ownerDocument) || importerPatronal(panel) !== pending.patronal || !sameFile) return false;
      if (importerResult(panel, tracking)) return true;
      const controls = [...panel.querySelectorAll('button,input[type="button"],input[type="submit"]')].filter(control =>
        visible(control) && !control.matches(':disabled,[aria-disabled="true"]') &&
        normalized(control.innerText || control.value || control.getAttribute("aria-label")) === "cargar y prevalidar");
      if (controls.length === 1) {
        const control = controls[0];
        const action = control.getAttribute("formaction") || control.form?.action;
        if (action && new URL(action, control.ownerDocument.location.href).origin !== REOP) return false;
        control.click();
        reportProgress({phase: "validation-requested"});
        return true;
      }
    }
    return false;
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
    stopObservation();
    host.remove();
  };
  shadow.querySelector("#close").addEventListener("click", () => {
    if (tracking) host.hidden = true;
    else globalThis.digitReopClose();
  });

  async function transfer(input, patronal, runPrevalidation = false) {
    if (busy || !eligible(input)) return;
    const panel = currentImporters(input.ownerDocument).find(candidate => candidate.contains(input));
    const actual = importerPatronal(panel);
    if ((actual && actual !== pending.patronal) || (runPrevalidation && actual !== pending.patronal)) {
      status.textContent = "Verificá que la patronal abierta en REOP sea la del lote.";
      return;
    }
    busy = true;
    disarm();
    attach.disabled = true;
    prevalidate.disabled = true;
    discard.disabled = true;
    try {
      const workbook = await message("take", {batchId: pending.batchId, patronal});
      if (!host.isConnected || !eligible(input) || (panel && (!visible(input) || !panel.contains(input) || importerPatronal(panel) !== actual))) {
        throw new Error("El formulario cambió. Prepará el lote otra vez en Digit Laboral.");
      }
      const bytes = Uint8Array.from(atob(workbook.base64), char => char.charCodeAt(0));
      const file = new File([bytes], workbook.filename, {
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      });
      const selected = new DataTransfer();
      selected.items.add(file);
      input.files = selected.files;
      if (input.files?.[0]?.size !== bytes.length) throw new Error("El formulario de REOP no recibió el archivo.");
      input.dispatchEvent(new Event("change", {bubbles: true}));
      form.hidden = true;
      tracking = {filename: workbook.filename, rows: pending.rows};
      reportProgress({phase: "attached"});
      watchPage(workbook.expiresAt);
      if (runPrevalidation && !(await requestPrevalidation(panel, input, file))) {
        status.textContent = "Excel adjuntado. Pulsá «Cargar y prevalidar» en REOP para continuar.";
      }
    } catch (error) {
      status.textContent = error.message;
      attach.disabled = false;
      prevalidate.disabled = false;
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
      (event.isTrusted && (isImportDialog(dialog) || currentImporters(doc).some(panel => visible(target) && panel.contains(target)))) ||
      (pickerDocument === doc && Date.now() < pickerUntil)
    )) {
      event.preventDefault();
      event.stopImmediatePropagation();
      void transfer(target, employer.value.trim());
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
    const documents = docs();
    const importers = documents.flatMap(currentImporters);
    const actual = importerPatronal(importers.length === 1 ? importers[0] : null);
    const patronal = actual || employer.value.trim();
    if (patronal !== pending.patronal) {
      status.textContent = "El número patronal no coincide con el lote. Verificá la patronal que abriste.";
      return;
    }
    const importerInputs = importers.flatMap(importerFiles);
    if (event.submitter === prevalidate) {
      if (!actual || importerInputs.length !== 1) {
        status.textContent = "Abrí el importador de la patronal del lote para adjuntar y prevalidar.";
        return;
      }
      void transfer(importerInputs[0], patronal, true);
      return;
    }
    const importDialogs = documents.flatMap(doc => [...doc.querySelectorAll(dialogs)].filter(isImportDialog));
    const dialogFiles = importDialogs.flatMap(node => [...node.querySelectorAll('input[type="file"]')].filter(eligible));
    const inputs = [...new Set([...dialogFiles, ...importerInputs])];
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
    status.textContent = "Abrí «Importar Planilla» en REOP. Cuando veas el selector de Excel, pulsá «Adjuntar planilla» de nuevo.";
    armTimer = setTimeout(() => {
      disarm();
      status.textContent = "No se detectó un selector de Excel. Podés volver a pulsar Adjuntar planilla.";
    }, 60_000);
  });
  employer.addEventListener("input", () => {
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
      stopObservation();
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
    if (result.tracking) {
      tracking = {filename: result.filename, rows: result.rows};
      if (result.progress) showProgress(result.progress);
      else status.textContent = "Revisá el estado del lote en el importador de REOP.";
      if (result.progress?.phase === "imported") return;
    } else {
      form.hidden = false;
      status.textContent = "Compará la patronal del lote con la que está abierta en REOP.";
    }
    watchPage(result.expiresAt);
  }).catch(error => { status.textContent = error.message; });
})();
