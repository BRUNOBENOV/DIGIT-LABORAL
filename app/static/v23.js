(() => {
  const closeNavMenus = except => {
    document.querySelectorAll('details.nav-more[open]').forEach(menu => {
      if (menu !== except) menu.removeAttribute('open');
    });
  };

  document.addEventListener('click', event => {
    const menu = event.target.closest('details.nav-more');
    if (!menu) closeNavMenus();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') closeNavMenus();
  });

  const zone = document.querySelector('[data-logo-dropzone]');
  const input = zone?.querySelector('input[type="file"][name="logo"]');
  const preview = document.getElementById('companyLogoPreview');
  const placeholder = document.getElementById('companyLogoPlaceholder');
  const filename = document.getElementById('companyLogoFileName');
  const error = document.getElementById('companyLogoClientError');
  const form = zone?.closest('form');
  const submit = form?.querySelector('button[type="submit"]');
  const allowedExtensions = ['png', 'jpg', 'jpeg', 'webp'];
  const maxBytes = 8 * 1024 * 1024;

  const showError = message => {
    if (error) {
      error.textContent = message || '';
      error.hidden = !message;
    }
  };

  const acceptableFile = file => {
    if (!file) return false;
    const ext = (file.name.split('.').pop() || '').toLowerCase();
    const typeOk = !file.type || ['image/png', 'image/jpeg', 'image/webp'].includes(file.type);
    if (!allowedExtensions.includes(ext) && !typeOk) {
      showError('Usá una imagen PNG, JPG/JPEG o WEBP.');
      return false;
    }
    if (file.size > maxBytes) {
      showError('El logo supera 8 MB. Elegí una imagen más liviana.');
      return false;
    }
    if (file.size === 0) {
      showError('El archivo seleccionado está vacío.');
      return false;
    }
    showError('');
    return true;
  };

  const loadPreview = file => {
    if (!acceptableFile(file)) {
      if (input) input.value = '';
      return;
    }
    if (filename) filename.textContent = `${file.name} · ${(file.size / 1024 / 1024).toFixed(file.size > 1024 * 1024 ? 1 : 2)} MB`;
    const reader = new FileReader();
    reader.onload = () => {
      if (preview) {
        preview.src = reader.result;
        preview.classList.remove('hidden');
      }
      placeholder?.classList.add('hidden');
      zone?.classList.add('has-file');
    };
    reader.readAsDataURL(file);
  };

  if (zone && input) {
    zone.addEventListener('click', event => {
      if (event.target === input || event.target.closest('button,a')) return;
      input.click();
    });
    zone.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        input.click();
      }
    });
    input.addEventListener('change', () => loadPreview(input.files?.[0]));

    ['dragenter', 'dragover'].forEach(type => zone.addEventListener(type, event => {
      event.preventDefault();
      zone.classList.add('dragging');
    }));
    ['dragleave', 'drop'].forEach(type => zone.addEventListener(type, event => {
      event.preventDefault();
      zone.classList.remove('dragging');
    }));
    zone.addEventListener('drop', event => {
      const file = event.dataTransfer?.files?.[0];
      if (!file || !acceptableFile(file)) return;
      const transfer = new DataTransfer();
      transfer.items.add(file);
      input.files = transfer.files;
      loadPreview(file);
    });

    form?.addEventListener('submit', event => {
      const file = input.files?.[0];
      if (!file || !acceptableFile(file)) {
        event.preventDefault();
        if (!file) showError('Seleccioná el logo antes de guardar.');
        return;
      }
      if (submit) {
        submit.disabled = true;
        submit.dataset.originalText = submit.textContent;
        submit.textContent = 'Subiendo logo…';
      }
    });
  }

  const params = new URLSearchParams(window.location.search);
  if (params.get('logo_error')) {
    showError(params.get('logo_error'));
  }
})();
