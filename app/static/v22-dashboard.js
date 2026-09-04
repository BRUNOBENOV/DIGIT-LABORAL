(() => {
  const openModal = id => {
    if (!id) return false;
    const modal = document.getElementById(id);
    if (!modal) return false;
    modal.classList.add('show');
    modal.setAttribute('aria-hidden', 'false');
    const focusable = modal.querySelector('input:not([type="hidden"]),select,textarea,button');
    window.setTimeout(() => focusable?.focus(), 40);
    return true;
  };

  // Permite que los accesos rápidos del dashboard abran directamente el alta correspondiente.
  const params = new URLSearchParams(window.location.search);
  const requestedModal = params.get('open');
  if (requestedModal && openModal(requestedModal)) {
    params.delete('open');
    const clean = `${window.location.pathname}${params.toString() ? `?${params}` : ''}${window.location.hash}`;
    window.history.replaceState({}, '', clean);
  }

  // Confirmación visual para enlaces que descargan respaldos/exportaciones.
  document.querySelectorAll('[data-download-action]').forEach(link => {
    link.addEventListener('click', () => {
      link.classList.add('is-working');
      const original = link.textContent;
      link.textContent = 'Preparando…';
      window.setTimeout(() => {
        link.classList.remove('is-working');
        link.textContent = original;
      }, 3000);
    });
  });

  // Evita dobles clics accidentales en accesos del dashboard, sin afectar navegación normal.
  document.querySelectorAll('.dashboard-shell a[href]').forEach(link => {
    link.addEventListener('click', () => {
      if (link.dataset.allowRepeat === 'true') return;
      link.setAttribute('aria-busy', 'true');
    }, { once: true });
  });
})();
