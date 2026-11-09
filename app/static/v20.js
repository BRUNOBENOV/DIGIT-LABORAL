(() => {
  const authority = document.querySelector('[data-authority-select]');
  const eventType = document.querySelector('[data-event-type-select]');
  if (authority && eventType) {
    const rebuild = () => {
      const source = authority.value === 'REI' ? eventType.dataset.reiTypes : eventType.dataset.reopTypes;
      let values = [];
      try { values = JSON.parse(source || '[]'); } catch (_) {}
      const previous = eventType.value;
      eventType.innerHTML = '';
      values.forEach(value => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = value;
        eventType.appendChild(option);
      });
      if (values.includes(previous)) eventType.value = previous;
    };
    authority.addEventListener('change', rebuild);
    rebuild();
  }

  document.querySelectorAll('form').forEach(form => {
    form.addEventListener('submit', () => {
      if (form.hasAttribute('data-download-form')) return;
      const submitter = form.querySelector('button[type="submit"]');
      if (submitter && !submitter.dataset.keepEnabled) {
        submitter.disabled = true;
        submitter.dataset.originalText = submitter.textContent;
        submitter.textContent = 'Procesando…';
      }
    });
  });
})();
