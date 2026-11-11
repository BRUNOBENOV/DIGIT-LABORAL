(() => {
  "use strict";

  const REOP = "https://regobpat.mtess.gov.py";
  const SALARY_PATH = "/liquidacion_salario_list.php";
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
      button, a { box-sizing: border-box; border: 1px solid #a6b7cb; border-radius: 7px; padding: 8px 10px; font: inherit; color: #172945; background: #f3f7fc; cursor: pointer; }
      a { display: inline-block; text-decoration: none; }
      #attach { color: #fff; background: #123e80; border-color: #123e80; font-weight: 700; }
      button:disabled { opacity: .55; cursor: default; }
      .actions { display: flex; gap: 8px; flex-wrap: wrap; }
      [hidden] { display: none !important; }
    </style>
    <section role="region" aria-label="Asistente REOP de Digit Laboral">
      <header><h2>Digit Laboral · Asistente REOP</h2><button type="button" id="close" aria-label="Cerrar asistente">×</button></header>
      <p id="summary" hidden></p>
      <p id="status" role="status" aria-live="polite">Buscando la planilla preparada…</p>
      <a id="salary" href="${REOP}${SALARY_PATH}" hidden>Abrir Liquidación Salario</a>
      <div class="actions" hidden>
        <button type="button" id="attach">Adjuntar y prevalidar</button>
        <button type="button" id="attach-only" hidden>Solo adjuntar</button>
        <button type="button" id="discard">Descartar</button>
      </div>
    </section>`;
  document.documentElement.append(host);

  const status = shadow.querySelector("#status");
  const summary = shadow.querySelector("#summary");
  const actions = shadow.querySelector(".actions");
  const attach = shadow.querySelector("#attach");
  const attachOnly = shadow.querySelector("#attach-only");
  const discard = shadow.querySelector("#discard");
  let pending;
  let armedDocs = [];
  let armTimer;
  let pickerUntil = 0;
  let pickerDocument;
  let busy = false;
  let tracking;
  let lastProgress = "";
  let observer;
  let scanTimer;
  let observationTimer;

  const normalized = value => (value || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/\s+/g, " ").trim();
  const visible = node => node && node.getClientRects().length > 0 &&
    !node.closest('[hidden], [aria-hidden="true"]') && node.ownerDocument.defaultView.getComputedStyle(node).visibility === "visible";
  const dialogs = '[role="dialog"], dialog[open], .modal.show, .modal.in, .swal2-popup, .sweet-alert.visible';
  const controls = 'a, button, [role="button"], input[type="button"], input[type="submit"]';
  const controlName = control => normalized(control.innerText || control.value || control.getAttribute("aria-label"));
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
    if (location.pathname !== SALARY_PATH || !doc.body) return [];
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

  function portalPatronales(panels) {
    const values = new Set();
    if (!officialDocument(document)) return values;
    // Read the account control, never a patronal number in the salary list.
    const account = /^usuario\b.*\bcon (?:n(?:ro|umero)\.?|n\.?[°º])\s+patronal\s*:?\s*(\d{1,20})\s*[▾▼⌄▿]?$/;
    for (const control of document.querySelectorAll(controls + ', [data-toggle="dropdown"], [data-bs-toggle="dropdown"]')) {
      if (!account.test(normalized(control.textContent || control.getAttribute("aria-label"))) || !visible(control)) continue;
      const match = controlName(control).match(account);
      if (match) values.add(match[1]);
    }
    for (const panel of panels) {
      for (const match of normalized(panel.innerText).matchAll(/\bpatronal\s*:?\s+(\d{1,20})\s*[·•|–—-]\s*prevalidacion\b/g)) {
        values.add(match[1]);
      }
    }
    return values;
  }

  function samePortalAction(control) {
    const action = control.getAttribute("formaction") || control.form?.action;
    const href = control.getAttribute("href");
    const base = control.ownerDocument.location.href;
    const inert = !href || /^javascript:\s*void\(0\);?$/i.test(href);
    try {
      return (!action || new URL(action, base).origin === REOP) && (inert || new URL(href, base).origin === REOP);
    } catch (_) {
      return false;
    }
  }

  function importerTrigger() {
    if (location.pathname !== SALARY_PATH || !officialDocument(document)) return null;
    const matches = [...document.querySelectorAll(controls)].filter(control =>
      controlName(control) === "importar planilla" && visible(control) && !control.closest(dialogs) &&
      !control.matches(':disabled,[aria-disabled="true"]') && samePortalAction(control));
    return matches.length === 1 ? matches[0] : null;
  }

  function hasActiveJob(panel) {
    return normalized(panel.innerText).includes("ya existe una carga activa para esta patronal") ||
      [...panel.querySelectorAll(controls)].some(control =>
        controlName(control) === "confirmar importacion" && visible(control));
  }

  function portalState() {
    const documents = docs();
    const panels = documents.flatMap(currentImporters);
    const panel = panels.length === 1 ? panels[0] : null;
    const numbers = portalPatronales(panels);
    const legacy = panel ? [] : documents.flatMap(doc => [...doc.querySelectorAll(dialogs)].filter(isImportDialog));
    const inputs = panel ? importerFiles(panel) : [...new Set(legacy.flatMap(dialog =>
      [...dialog.querySelectorAll('input[type="file"]')].filter(eligible)))];
    return {
      documents, panel, legacy, inputs,
      patronal: numbers.size === 1 ? [...numbers][0] : "",
      ambiguous: panels.length > 1 || numbers.size > 1,
    };
  }

  function patronalIssue(state) {
    if (state.ambiguous) return "REOP muestra patronales distintas o más de un importador. Revisá cuál corresponde al lote.";
    if (state.patronal && state.patronal !== pending.patronal) {
      return `REOP muestra la patronal ${state.patronal}. Abrí la patronal ${pending.patronal} del lote.`;
    }
    return "";
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
    if (!host.isConnected || (!tracking && (busy || actions.hidden))) return;
    const state = portalState();
    const issue = patronalIssue(state);
    if (tracking) {
      if (!state.panel || issue || state.patronal !== pending.patronal) return;
      const result = importerResult(state.panel, tracking);
      if (result) reportProgress(result);
      return;
    }
    attach.disabled = true;
    attachOnly.hidden = true;
    attach.textContent = state.legacy.length ? "Adjuntar planilla" : "Adjuntar y prevalidar";
    if (issue) {
      disarm();
      status.textContent = issue;
      return;
    }
    if (state.panel && hasActiveJob(state.panel)) {
      status.textContent = "REOP ya tiene una carga activa. Continuá con ese trabajo en el importador o revisá su historial.";
      return;
    }
    const opened = state.panel || state.legacy.length;
    const checked = state.patronal === pending.patronal;
    if (!opened) {
      attach.disabled = !importerTrigger();
      status.textContent = attach.disabled ? "Abrí «Importar Planilla» en REOP para continuar."
        : checked ? `Patronal ${state.patronal} verificada. El asistente abrirá el importador.`
        : "El asistente verificará la patronal al abrir el importador.";
    } else if (!checked) {
      status.textContent = `Elegí la patronal ${pending.patronal} en REOP y volvé a abrir el importador para verificarla.`;
    } else if (state.inputs.length > 1 || (state.panel && !state.inputs.length)) {
      status.textContent = "Abrí el importador con el selector de Excel vacío.";
    } else {
      attach.disabled = false;
      attachOnly.hidden = !state.panel;
      if (!armedDocs.length) status.textContent = `Patronal ${state.patronal} verificada en REOP.`;
    }
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
      const state = portalState();
      if (!host.isConnected || host.hidden || state.panel !== panel || !panel.contains(input) || !visible(input) ||
          state.ambiguous || state.patronal !== pending.patronal || !sameFile) return false;
      const result = importerResult(panel, tracking);
      if (result) {
        reportProgress(result);
        return true;
      }
      if (hasActiveJob(panel)) return false;
      const buttons = [...panel.querySelectorAll('button,input[type="button"],input[type="submit"]')].filter(control =>
        visible(control) && !control.matches(':disabled,[aria-disabled="true"]') &&
        controlName(control) === "cargar y prevalidar" && samePortalAction(control));
      if (buttons.length === 1) {
        const control = buttons[0];
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

  function canTransfer(state, input, panel) {
    return !state.ambiguous && state.patronal === pending.patronal && state.panel === panel && eligible(input) &&
      (panel ? state.inputs.length === 1 && state.inputs[0] === input && !hasActiveJob(panel)
        : state.legacy.length > 0 && state.documents.includes(input.ownerDocument));
  }

  function setBusy(value) {
    busy = value;
    attach.disabled = value;
    attachOnly.disabled = value;
    discard.disabled = value;
  }

  async function transfer(input, state, runPrevalidation = false) {
    const {panel, patronal} = state;
    if (busy || !canTransfer(state, input, panel)) return;
    setBusy(true);
    disarm();
    try {
      const workbook = await message("take", {batchId: pending.batchId, patronal});
      if (!host.isConnected || !canTransfer(portalState(), input, panel)) {
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
      actions.hidden = true;
      tracking = {filename: workbook.filename, rows: pending.rows};
      reportProgress({phase: "attached"});
      watchPage(workbook.expiresAt);
      if (runPrevalidation && !(await requestPrevalidation(panel, input, file))) {
        status.textContent = hasActiveJob(panel)
          ? "REOP ya tiene una carga activa. Continuá con ese trabajo en el importador."
          : "Excel adjuntado. Revisá el importador de REOP para continuar.";
      }
    } catch (error) {
      status.textContent = error.message;
    } finally {
      setBusy(false);
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
      const state = portalState();
      if (!canTransfer(state, target, state.panel)) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      void transfer(target, state);
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

  async function start(event, runPrevalidation) {
    if (!event.isTrusted || busy) return;
    disarm();
    if (Date.now() >= pending.expiresAt) {
      status.textContent = "El lote venció. Pulsá «Preparar carga en REOP» en Digit Laboral.";
      return;
    }
    let state = portalState();
    if (patronalIssue(state)) {
      updateView();
      return;
    }
    const trigger = !state.panel && !state.legacy.length ? importerTrigger() : null;
    if (trigger) {
      setBusy(true);
      status.textContent = "Abriendo el importador de REOP…";
      try {
        trigger.click();
        for (let attempt = 0; attempt < 40 && host.isConnected; attempt++) {
          state = portalState();
          if (patronalIssue(state) || (state.panel && hasActiveJob(state.panel)) ||
              (state.patronal && (state.inputs.length || state.legacy.length))) break;
          await new Promise(resolve => setTimeout(resolve, 125));
        }
      } finally {
        setBusy(false);
      }
      if (!host.isConnected) return;
      state = portalState();
    }
    const [input] = state.inputs;
    if (state.inputs.length === 1 && canTransfer(state, input, state.panel)) {
      await transfer(input, state, runPrevalidation && Boolean(state.panel));
      return;
    }
    updateView();
    if (patronalIssue(state) || state.panel || state.patronal !== pending.patronal) return;
    if (!state.legacy.length || state.inputs.length) {
      if (trigger && !state.legacy.length) status.textContent = "Abrí «Importar Planilla» en REOP para continuar.";
      return;
    }
    armedDocs = state.documents;
    for (const doc of armedDocs) doc.addEventListener("click", capturePicker, true);
    status.textContent = "Pulsá el selector de Excel del aviso de REOP.";
    armTimer = setTimeout(() => {
      disarm();
      status.textContent = "No se detectó un selector de Excel. Podés volver a pulsar Adjuntar planilla.";
    }, 60_000);
  }
  attach.addEventListener("click", event => void start(event, true));
  attachOnly.addEventListener("click", event => void start(event, false));

  discard.addEventListener("click", async event => {
    if (!event.isTrusted || busy) return;
    disarm();
    try {
      await message("discard", {batchId: pending.batchId});
      actions.hidden = true;
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
  if (location.pathname !== SALARY_PATH) {
    status.textContent = "Abrí Liquidación Salario y pulsá la extensión para cargar el lote.";
    shadow.querySelector("#salary").hidden = false;
    return;
  }
  message("info").then(result => {
    pending = result;
    summary.textContent = `Lote #${result.batchId} · período ${result.period} · patronal ${result.patronal} · ${result.rows} ${Number(result.rows) === 1 ? "registro" : "registros"}.`;
    summary.hidden = false;
    if (result.tracking) {
      tracking = {filename: result.filename, rows: result.rows};
      if (result.progress) showProgress(result.progress);
      else status.textContent = "Revisá el estado del lote en el importador de REOP.";
      if (result.progress?.phase === "imported") return;
    } else {
      actions.hidden = false;
    }
    watchPage(result.expiresAt);
  }).catch(error => { status.textContent = error.message; });
})();
