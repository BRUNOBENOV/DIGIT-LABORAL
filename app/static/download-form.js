/* Deliver an audited file without leaving the validated form. */
(() => {
  'use strict';
  const types = {xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', txt: 'text/plain'};
  const unavailable = 'Instalá o actualizá el asistente de Chrome desde «Cargar en REOP con el asistente de Chrome».';
  const protocol = 1;

  function extensionMessage(id, message) {
    return new Promise((resolve, reject) => {
      const runtime = globalThis.chrome?.runtime;
      if (!runtime?.sendMessage) { reject(new Error(unavailable)); return; }
      const timer = window.setTimeout(() => reject(new Error('El asistente tardó en responder. Revisá su estado en REOP.')), 7000);
      try {
        runtime.sendMessage(id, message, result => {
          window.clearTimeout(timer);
          if (runtime.lastError || !result) reject(new Error(unavailable));
          else if (!result.ok) reject(new Error(result.message || 'El asistente no recibió la planilla.'));
          else resolve(result);
        });
      } catch (_) {
        window.clearTimeout(timer);
        reject(new Error(unavailable));
      }
    });
  }

  function encodeFile(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result.split(',', 2)[1]);
      reader.onerror = () => reject(new Error('No se pudo leer la planilla generada.'));
      reader.readAsDataURL(blob);
    });
  }

  document.querySelectorAll('form[data-download-form]').forEach(form => {
    const buttons = [...form.querySelectorAll('button[type="submit"]')];
    const assistantId = form.dataset.reopAssistantId;
    const bridgeButton = form.querySelector('[data-reop-browser]');
    const portalLink = form.querySelector('[data-reop-open]');
    const status = form.querySelector('[data-download-status]');
    const batchLink = form.querySelector('[data-download-batch]');
    if (!buttons.length || !status) return;
    if (bridgeButton && assistantId) bridgeButton.hidden = false;
    let busy = false;
    const notify = (text, state) => {
      status.hidden = false;
      status.textContent = text;
      status.dataset.state = state;
    };
    const filename = (header, fallback) => {
      const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(header);
      const plain = /filename="([^"]+)"|filename=([^;]+)/i.exec(header);
      let value = plain?.[1] || plain?.[2] || fallback;
      if (utf8) { try { value = decodeURIComponent(utf8[1]); } catch (_) { /* Use plain filename. */ } }
      return value.replace(/[\\/\x00-\x1f\x7f]/g, '-').trim().slice(0, 180) || fallback;
    };
    form.addEventListener('submit', async event => {
      if (event.defaultPrevented) return;
      event.preventDefault();
      if (busy || !form.reportValidity()) return;
      const button = event.submitter || buttons[0];
      const bridge = Boolean(assistantId && bridgeButton && button === bridgeButton);
      busy = true;
      const original = button.textContent;
      const previousDisabled = buttons.map(submitter => submitter.disabled);
      buttons.forEach(submitter => { submitter.disabled = true; });
      button.textContent = bridge ? 'Preparando carga…' : 'Preparando descarga…';
      button.setAttribute('aria-busy', 'true');
      if (batchLink) batchLink.hidden = true;
      notify('Generando el archivo. Conservamos los datos y las confirmaciones de esta pantalla.', 'loading');
      const controller = new AbortController();
      const timer = window.setTimeout(() => controller.abort(), 30000);
      let objectUrl;
      let separateWindows = false;
      try {
        if (bridge) {
          const state = await extensionMessage(assistantId, {type: 'ping'});
          if (state.protocol !== protocol) throw new Error(unavailable);
          separateWindows = state.separateWindows === true;
          if (state.busy) {
            if (portalLink) portalLink.hidden = false;
            throw new Error('Ya hay un lote pendiente. Adjuntalo o descartalo desde el asistente en REOP.');
          }
        }
        const action = new URL(form.action, window.location.href);
        if (action.origin !== window.location.origin) throw new Error('Destino de descarga inválido. Recargá la pantalla.');
        const body = new FormData(form);
        if (bridge) body.set('delivery', 'reop-browser');
        const response = await fetch(action.href, {
          method: 'POST', body, credentials: 'same-origin',
          headers: {'Accept': 'application/json'}, signal: controller.signal,
        });
        if (response.redirected) throw new Error('La sesión cambió o venció. Ingresá nuevamente y volvé a verificar la planilla.');
        const contentType = (response.headers.get('content-type') || '').split(';')[0].trim().toLowerCase();
        if (!response.ok) {
          let detail;
          if (contentType === 'application/json') {
            const data = await response.json();
            if (typeof data.detail === 'string') detail = data.detail;
          }
          throw new Error(detail || (response.status === 403
            ? 'La sesión o el permiso de descarga no son válidos. Recargá la pantalla y volvé a verificar.'
            : 'No se pudo generar el archivo. Tus datos siguen en esta pantalla; podés reintentar la descarga.'));
        }
        const format = form.dataset.downloadFormat;
        const disposition = response.headers.get('content-disposition') || '';
        if (!types[format] || contentType !== types[format] || !/^attachment\b/i.test(disposition)) {
          throw new Error('El servidor no devolvió el archivo esperado. Volvé a verificar la planilla antes de reintentar.');
        }
        const blob = await response.blob();
        if (!blob.size) throw new Error('El archivo recibido está vacío. Volvé a verificar la planilla.');
        const fileName = filename(disposition, `salarios.${format}`);
        const batchId = response.headers.get('X-Integration-Batch-Id');
        if (batchLink && /^\d+$/.test(batchId || '')) {
          const url = new URL(batchLink.href, window.location.origin);
          url.searchParams.set('batch_id', batchId);
          url.hash = `lote-${batchId}`;
          batchLink.href = url.href;
          batchLink.hidden = false;
        }
        if (bridge) {
          if (format !== 'xlsx' || blob.size > 5 * 1024 * 1024 || !/^\d+$/.test(batchId || '')) {
            throw new Error('El archivo generado no es apto para el asistente de Chrome. Revisá el lote.');
          }
          await extensionMessage(assistantId, {
            type: 'stage', protocol, batchId, filename: fileName, base64: await encodeFile(blob),
            period: response.headers.get('X-REOP-Period'), patronal: response.headers.get('X-REOP-Patronal'),
            rows: response.headers.get('X-REOP-Rows'), sha256: response.headers.get('X-REOP-SHA256'),
          });
          if (portalLink) portalLink.hidden = false;
          const reopWindow = separateWindows ? 'en este perfil de Chrome' : 'en esta misma ventana de Chrome';
          notify(`Lote #${batchId} preparado por 10 minutos. Dejá esta pestaña abierta. En REOP, ${reopWindow}, abrí Liquidación Salario y pulsá la extensión de Digit Laboral.`, 'success');
        } else {
          objectUrl = URL.createObjectURL(blob);
          const link = document.createElement('a');
          link.href = objectUrl;
          link.download = fileName;
          document.body.append(link);
          try { link.click(); } finally { link.remove(); }
          notify('Archivo generado. Revisá la carpeta de descargas. Confirmá la presentación en el portal oficial.', 'success');
        }
      } catch (error) {
        notify(error.name === 'AbortError'
          ? 'La descarga tardó demasiado. Conservamos la planilla y podés volver a intentar.'
          : (error instanceof TypeError ? 'No se pudo conectar con el servidor. Revisá la conexión y volvé a intentar.' : error.message), 'error');
      } finally {
        window.clearTimeout(timer);
        if (objectUrl) window.setTimeout(() => URL.revokeObjectURL(objectUrl), 15000);
        busy = false;
        buttons.forEach((submitter, index) => { submitter.disabled = previousDisabled[index]; });
        button.textContent = original;
        button.removeAttribute('aria-busy');
      }
    });
  });
})();
