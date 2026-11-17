/* Revalidate selection changes and search the reviewed workers. */
(() => {
  'use strict';
  const form = document.querySelector('[data-salary-import-filters]');
  if (form) {
    const status = form.querySelector('[data-import-validation-status]');
    let timer;
    function invalidate() {
      for (const exportForm of document.querySelectorAll('[data-download-form]')) {
        exportForm.dataset.reviewStale = 'true';
        exportForm.querySelectorAll('button[type="submit"]').forEach(button => { button.disabled = true; });
        exportForm.querySelectorAll('input[type="checkbox"]').forEach(input => { input.checked = false; });
      }
      if (status) status.textContent = 'Actualizando la verificación…';
    }
    function verify() {
      if (!form.elements.company_id.value || !form.elements.period.value) {
        if (status) status.textContent = 'Seleccioná empresa y mes.';
        return;
      }
      const url = new URL(form.action, window.location.href);
      url.search = new URLSearchParams(new FormData(form)).toString();
      window.location.assign(url.href);
    }
    form.addEventListener('change', event => {
      window.clearTimeout(timer);
      if (event.target.name === 'company_id') {
        const employee = form.elements.employee_id;
        if (window.DigitEntitySelect) window.DigitEntitySelect.setValue(employee, '');
        else employee.value = '';
      }
      invalidate();
      timer = window.setTimeout(verify, 450);
    });
    form.addEventListener('submit', () => window.clearTimeout(timer));
    const current = new URL(window.location.href);
    if (!current.searchParams.has('period') && form.elements.company_id.value && form.elements.period.value) {
      timer = window.setTimeout(verify, 450);
    }
  }
  for (const exportForm of document.querySelectorAll('[data-download-form]')) {
    exportForm.addEventListener('submit', event => {
      if (exportForm.dataset.reviewStale === 'true') event.preventDefault();
    }, true);
  }
  const search = document.querySelector('[data-import-worker-search]');
  if (search) {
    const rows = [...document.querySelectorAll('[data-import-worker-row]')];
    const count = document.querySelector('[data-import-worker-count]');
    const empty = document.querySelector('[data-import-worker-empty]');
    const normalize = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
    const entries = rows.map(row => ({row, text: normalize(row.textContent)}));
    search.addEventListener('input', () => {
      const query = normalize(search.value.trim());
      const terms = query.split(/\s+/).filter(Boolean);
      let visible = 0;
      for (const entry of entries) {
        const match = terms.every(term => entry.text.includes(term)
          || (/^[\d.-]+$/.test(term) && entry.text.replace(/[.-]/g, '').includes(term.replace(/[.-]/g, ''))));
        entry.row.hidden = !match;
        if (match) visible++;
      }
      if (count) count.textContent = visible + ' de ' + rows.length + ' trabajadores';
      if (empty) empty.hidden = visible !== 0;
    });
  }
  for (const link of document.querySelectorAll('[data-open-attendance]')) {
    link.addEventListener('click', () => {
      const panel = document.getElementById('asistencia-exportacion');
      if (panel) panel.open = true;
    });
  }
})();
