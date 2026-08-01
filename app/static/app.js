const sidebar = document.querySelector('#sidebar');
document.querySelector('[data-menu]')?.addEventListener('click', () => sidebar?.classList.toggle('open'));

const modernNav = document.querySelector('#modernMobileNav');
document.querySelector('[data-modern-menu]')?.addEventListener('click', () => modernNav?.classList.toggle('open'));
modernNav?.querySelectorAll('a').forEach(link => link.addEventListener('click', () => modernNav.classList.remove('open')));

document.querySelectorAll('[data-modal-open]').forEach(btn => btn.addEventListener('click', () => {
  const modal = document.getElementById(btn.dataset.modalOpen);
  modal?.classList.add('show');
  modal?.setAttribute('aria-hidden', 'false');
}));
document.querySelectorAll('[data-modal-close]').forEach(btn => btn.addEventListener('click', () => {
  const modal = btn.closest('.modal');
  modal?.classList.remove('show');
  modal?.setAttribute('aria-hidden', 'true');
}));
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') {
    document.querySelectorAll('.modal.show').forEach(modal => modal.classList.remove('show'));
    modernNav?.classList.remove('open');
  }
});
