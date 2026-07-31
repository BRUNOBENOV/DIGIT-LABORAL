(() => {
  const root = document.documentElement;
  const toggleTheme = () => {
    const next = root.dataset.theme === 'dark' ? 'light' : 'dark';
    root.dataset.theme = next;
    localStorage.setItem('digit_theme', next);
  };
  const saved = localStorage.getItem('digit_theme');
  if (saved) root.dataset.theme = saved;
  document.querySelectorAll('[data-theme-toggle]').forEach(btn => btn.addEventListener('click', toggleTheme));

  const menuBtn = document.getElementById('siteMenuToggle');
  const menu = document.getElementById('siteMenu');
  if (menuBtn && menu) {
    menuBtn.addEventListener('click', () => {
      const open = menu.classList.toggle('open');
      menuBtn.setAttribute('aria-expanded', String(open));
      menuBtn.textContent = open ? '×' : '☰';
    });
    menu.querySelectorAll('a').forEach(a => a.addEventListener('click', () => {
      menu.classList.remove('open');
      menuBtn.setAttribute('aria-expanded', 'false');
      menuBtn.textContent = '☰';
    }));
  }

  if ('serviceWorker' in navigator && location.protocol.startsWith('http')) {
    navigator.serviceWorker.register('./sw.js').catch(() => {});
  }
})();
