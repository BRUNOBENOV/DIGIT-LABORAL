/* Download an audited file without leaving the validated form or a stuck button. */
(() => {
  'use strict';
  const types = {xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', txt: 'text/plain'};
  document.querySelectorAll('form[data-download-form]').forEach(form => {
    const button = form.querySelector('button[type="submit"]');
    const status = form.querySelector('[data-download-status]');
    if (!button || !status) return;
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
      busy = true;
      const original = button.textContent;
      button.disabled = true;
      button.textContent = 'Preparando descarga…';
      button.setAttribute('aria-busy', 'true');
      notify('Generando el archivo. Conservamos los datos y las confirmaciones de esta pantalla.', 'loading');
      const controller = new AbortController();
      const timer = window.setTimeout(() => controller.abort(), 30000);
      let objectUrl;
      try {
        const action = new URL(form.action, window.location.href);
        if (action.origin !== window.location.origin) throw new Error('Destino de descarga inválido. Recargá la pantalla.');
        const response = await fetch(action.href, {
          method: 'POST', body: new FormData(form), credentials: 'same-origin',
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
        objectUrl = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = objectUrl;
        link.download = filename(disposition, `salarios.${format}`);
        document.body.append(link);
        try { link.click(); } finally { link.remove(); }
        notify('Archivo generado. Revisá la carpeta de descargas. Esto no equivale a una presentación oficial.', 'success');
      } catch (error) {
        notify(error.name === 'AbortError'
          ? 'La descarga tardó demasiado. Conservamos la planilla y podés volver a intentar.'
          : (error instanceof TypeError ? 'No se pudo conectar con el servidor. Revisá la conexión y volvé a intentar.' : error.message), 'error');
      } finally {
        window.clearTimeout(timer);
        if (objectUrl) window.setTimeout(() => URL.revokeObjectURL(objectUrl), 15000);
        busy = false;
        button.disabled = false;
        button.textContent = original;
        button.removeAttribute('aria-busy');
      }
    });
  });
})();
