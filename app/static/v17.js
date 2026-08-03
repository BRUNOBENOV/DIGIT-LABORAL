(() => {
  const openModal = id => {
    const modal = document.getElementById(id);
    if (!modal) return false;
    modal.classList.add('show');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('modal-open');
    const focusable = modal.querySelector('input,select,textarea,button');
    window.setTimeout(() => focusable?.focus(), 30);
    return true;
  };
  const closeModal = modal => {
    if (!modal) return;
    modal.classList.remove('show');
    modal.setAttribute('aria-hidden', 'true');
    if (!document.querySelector('.modal.show')) document.body.classList.remove('modal-open');
  };

  // Delegación robusta: funciona aunque el contenido haya sido agregado luego de cargar app.js.
  document.addEventListener('click', event => {
    const opener = event.target.closest('[data-modal-open]');
    if (opener) {
      event.preventDefault();
      openModal(opener.dataset.modalOpen);
      return;
    }
    const closer = event.target.closest('[data-modal-close]');
    if (closer) {
      event.preventDefault();
      closeModal(closer.closest('.modal'));
    }
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') document.querySelectorAll('.modal.show').forEach(closeModal);
  });

  const logoInput = document.querySelector('#brandingModal input[name="logo"]');
  if (logoInput) {
    const label = logoInput.closest('label');
    if (label && !label.classList.contains('logo-upload-enhanced')) {
      label.classList.add('logo-upload-enhanced');
      const preview = document.createElement('div');
      preview.className = 'logo-upload-preview';
      preview.innerHTML = '<span>Vista previa<br>del logo</span>';
      const copy = document.createElement('div');
      copy.className = 'logo-upload-copy';
      copy.innerHTML = '<b>Arrastrá o elegí una imagen</b><span>PNG o JPG, máximo 2 MB. Se utilizará en Word, PDF e informes.</span><em>Ningún archivo seleccionado</em>';
      label.prepend(copy);
      label.prepend(preview);

      const error = document.createElement('div');
      error.className = 'logo-upload-error';
      label.append(error);
      const filename = copy.querySelector('em');

      const loadFile = file => {
        error.textContent = '';
        if (!file) return;
        if (!['image/png', 'image/jpeg'].includes(file.type)) {
          logoInput.value = '';
          error.textContent = 'El archivo debe ser PNG o JPG.';
          return;
        }
        if (file.size > 2 * 1024 * 1024) {
          logoInput.value = '';
          error.textContent = 'El logo supera el límite de 2 MB.';
          return;
        }
        filename.textContent = `${file.name} · ${(file.size / 1024).toFixed(0)} KB`;
        const reader = new FileReader();
        reader.onload = () => { preview.innerHTML = `<img src="${reader.result}" alt="Vista previa del logo">`; };
        reader.readAsDataURL(file);
      };
      logoInput.addEventListener('change', () => loadFile(logoInput.files?.[0]));
      ['dragenter', 'dragover'].forEach(type => label.addEventListener(type, event => {
        event.preventDefault(); label.classList.add('dragging');
      }));
      ['dragleave', 'drop'].forEach(type => label.addEventListener(type, event => {
        event.preventDefault(); label.classList.remove('dragging');
      }));
      label.addEventListener('drop', event => {
        const file = event.dataTransfer?.files?.[0];
        if (!file) return;
        const transfer = new DataTransfer();
        transfer.items.add(file);
        logoInput.files = transfer.files;
        loadFile(file);
      });
    }
  }

  document.querySelectorAll('[data-legal-auto-submit]').forEach(select => {
    select.addEventListener('change', () => document.getElementById('legalFilters')?.submit());
  });

  document.addEventListener('click', async event => {
    const button = event.target.closest('[data-copy-article]');
    if (!button) return;
    const anchor = button.dataset.copyArticle;
    const url = `${location.origin}${location.pathname}${location.search}#${anchor}`;
    try {
      await navigator.clipboard.writeText(url);
      const original = button.textContent;
      button.textContent = 'Enlace copiado';
      button.classList.add('copied');
      setTimeout(() => { button.textContent = original; button.classList.remove('copied'); }, 1600);
    } catch (_) {
      location.hash = anchor;
    }
  });
})();
