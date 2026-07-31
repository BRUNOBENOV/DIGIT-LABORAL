(() => {
  const $ = (s, r=document) => r.querySelector(s);
  const $$ = (s, r=document) => [...r.querySelectorAll(s)];
  const download = (name, content, type='application/octet-stream') => {
    const url = URL.createObjectURL(new Blob([content], {type}));
    const a = Object.assign(document.createElement('a'), {href:url, download:name});
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1200);
  };
  const escCsv = v => `"${String(v ?? '').replaceAll('"','""')}"`;
  const session = (() => { try { return JSON.parse(localStorage.getItem('digit_session') || 'null'); } catch { return null; } })();
  if (session?.name) {
    $('#currentUserName') && ($('#currentUserName').textContent = session.name);
    const initials = session.name.split(/\s+/).slice(0,2).map(x => x[0]).join('').toUpperCase();
    $('.user-avatar') && ($('.user-avatar').textContent = initials || 'DL');
  }

  const banner = $('#demoBanner');
  if (localStorage.getItem('digit_demo_banner') === 'hidden') banner?.classList.add('hidden');
  $('#dismissDemoBanner')?.addEventListener('click', () => {
    banner?.classList.add('hidden');
    localStorage.setItem('digit_demo_banner','hidden');
  });

  const setOnline = () => {
    const el = $('#onlineStatus'); if (!el) return;
    const online = navigator.onLine;
    el.textContent = online ? 'En línea' : 'Sin conexión';
    el.classList.toggle('offline', !online);
  };
  addEventListener('online', setOnline); addEventListener('offline', setOnline); setOnline();

  const clock = $('#footerClock');
  const tick = () => { if (clock) clock.textContent = new Date().toLocaleString('es-PY'); };
  tick(); setInterval(tick, 30000);

  const companies = () => { try { return JSON.parse(localStorage.getItem('digit_companies') || '[]'); } catch { return []; } };
  const requests = () => { try { return JSON.parse(localStorage.getItem('digit_requests') || '[]'); } catch { return []; } };
  const audit = () => { try { return JSON.parse(localStorage.getItem('digit_audit') || '[]'); } catch { return []; } };
  const workspace = $('#workspaceSelect');
  if (workspace) {
    companies().forEach(c => workspace.insertAdjacentHTML('beforeend', `<option value="${String(c.id).replace(/"/g,'')}">${String(c.legalName).replace(/[<>]/g,'')}</option>`));
    workspace.value = localStorage.getItem('digit_workspace') || 'all';
    workspace.addEventListener('change', () => localStorage.setItem('digit_workspace', workspace.value));
  }

  const drawer = $('#notificationDrawer');
  const renderNotifications = () => {
    const items = requests().filter(r => r.status !== 'Resuelta');
    $('#notificationCount') && ($('#notificationCount').textContent = items.length);
    const list = $('#notificationList'); if (!list) return;
    list.innerHTML = items.length ? items.map(r => `<article class="notification-item"><b>${String(r.subject).replace(/[<>]/g,'')}</b><small>${String(r.company).replace(/[<>]/g,'')} · ${String(r.type).replace(/[<>]/g,'')}</small><span class="status ${r.priority === 'Alta' ? 'red' : 'blue'}">${String(r.status).replace(/[<>]/g,'')}</span></article>`).join('') : '<div class="notice">No hay tareas pendientes.</div>';
  };
  const closeDrawer = () => { drawer?.classList.remove('open'); drawer?.setAttribute('aria-hidden','true'); $('#notificationToggle')?.setAttribute('aria-expanded','false'); };
  $('#notificationToggle')?.addEventListener('click', () => {
    renderNotifications(); const open = !drawer?.classList.contains('open');
    drawer?.classList.toggle('open', open); drawer?.setAttribute('aria-hidden', String(!open));
    $('#notificationToggle')?.setAttribute('aria-expanded', String(open));
  });
  $('#notificationClose')?.addEventListener('click', closeDrawer);
  renderNotifications();

  const updateStorage = async () => {
    const label = $('#storageUsage'); if (!label) return;
    try {
      if (navigator.storage?.estimate) {
        const {usage=0, quota=0} = await navigator.storage.estimate();
        label.textContent = `${(usage/1024).toFixed(0)} KB de ${(quota/1024/1024).toFixed(0)} MB`;
      } else {
        const bytes = Object.keys(localStorage).reduce((n,k) => n + k.length + (localStorage.getItem(k)?.length || 0), 0) * 2;
        label.textContent = `${(bytes/1024).toFixed(1)} KB`;
      }
    } catch { label.textContent = 'Disponible'; }
  };
  updateStorage();
  const last = localStorage.getItem('digit_last_backup');
  if (last && $('#lastBackupLabel')) $('#lastBackupLabel').textContent = new Date(last).toLocaleString('es-PY');

  $('#exportBackupBtn')?.addEventListener('click', () => {
    const payload = {
      format:'digit-laboral-demo-backup', version:1, exportedAt:new Date().toISOString(),
      companies:companies(),
      employees:JSON.parse(localStorage.getItem('digit_employees') || '[]'),
      requests:requests(), audit:audit()
    };
    download(`digit-laboral-respaldo-${new Date().toISOString().slice(0,10)}.json`, JSON.stringify(payload,null,2), 'application/json');
    localStorage.setItem('digit_last_backup', new Date().toISOString());
    $('#lastBackupLabel') && ($('#lastBackupLabel').textContent = 'Ahora');
    $('#backupMessage') && ($('#backupMessage').textContent = 'Respaldo descargado correctamente.');
  });

  $('#importBackupInput')?.addEventListener('change', async event => {
    const file = event.target.files?.[0]; if (!file) return;
    try {
      const data = JSON.parse(await file.text());
      if (data.format !== 'digit-laboral-demo-backup' || !Array.isArray(data.companies) || !Array.isArray(data.employees)) throw new Error('Formato inválido');
      localStorage.setItem('digit_companies', JSON.stringify(data.companies));
      localStorage.setItem('digit_employees', JSON.stringify(data.employees));
      localStorage.setItem('digit_requests', JSON.stringify(Array.isArray(data.requests) ? data.requests : []));
      localStorage.setItem('digit_audit', JSON.stringify(Array.isArray(data.audit) ? data.audit : []));
      $('#backupMessage').textContent = 'Respaldo restaurado. Recargando…';
      setTimeout(() => location.reload(), 700);
    } catch (err) {
      $('#backupMessage').textContent = 'No se pudo restaurar: el archivo no corresponde a un respaldo válido.';
    } finally { event.target.value=''; }
  });

  $('#resetDemoBtn')?.addEventListener('click', () => {
    if (!confirm('¿Reiniciar todos los datos ficticios de esta demostración?')) return;
    ['digit_companies','digit_employees','digit_requests','digit_audit','digit_workspace','digit_last_backup'].forEach(k => localStorage.removeItem(k));
    location.reload();
  });
  $('#exportAuditBtn')?.addEventListener('click', () => {
    const rows = audit();
    const csv = ['Fecha,Usuario,Acción,Entidad,Detalle', ...rows.map(x => [x.date,x.user,x.action,x.entity,x.detail].map(escCsv).join(','))].join('\n');
    download('digit-laboral-auditoria.csv', '\uFEFF'+csv, 'text/csv;charset=utf-8');
  });

  $('#printDocBtn')?.addEventListener('click', () => window.print());
  $('#logoutBtn')?.addEventListener('click', () => { localStorage.removeItem('digit_session'); location.href='login.html'; });

  $$('[data-open-maint]').forEach(btn => btn.addEventListener('click', () => {
    setTimeout(() => document.querySelector(`[data-maint="${btn.dataset.openMaint}"]`)?.click(), 80);
  }));
  document.addEventListener('keydown', event => {
    if (event.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || '')) { event.preventDefault(); $('#globalSearch')?.focus(); }
    if (event.key === 'Escape') closeDrawer();
  });

  if ('serviceWorker' in navigator && location.protocol.startsWith('http')) navigator.serviceWorker.register('./sw.js').catch(() => {});
})();
