(() => {
  const form = document.getElementById('loginForm');
  const email = document.getElementById('email');
  const password = document.getElementById('password');
  const error = document.getElementById('loginError');
  const toggle = document.getElementById('togglePassword');
  const fill = document.getElementById('fillDemo');
  const DEMO_EMAIL = 'admin@digitlaboral.com.py';
  const DEMO_PASSWORD = 'demo123';

  toggle?.addEventListener('click', () => {
    const visible = password.type === 'text';
    password.type = visible ? 'password' : 'text';
    toggle.textContent = visible ? 'Mostrar' : 'Ocultar';
    toggle.setAttribute('aria-label', visible ? 'Mostrar contraseña' : 'Ocultar contraseña');
  });
  fill?.addEventListener('click', () => {
    email.value = DEMO_EMAIL;
    password.value = DEMO_PASSWORD;
    error.textContent = '';
    email.focus();
  });
  form?.addEventListener('submit', event => {
    event.preventDefault();
    error.textContent = '';
    const normalized = email.value.trim().toLowerCase();
    if (normalized !== DEMO_EMAIL || password.value !== DEMO_PASSWORD) {
      error.textContent = 'En la demostración pública usá el correo y la contraseña indicados debajo del formulario.';
      password.focus();
      return;
    }
    localStorage.setItem('digit_session', JSON.stringify({
      name: 'Administrador Digit Laboral', role: 'Administrador', email: normalized, at: new Date().toISOString()
    }));
    location.href = 'app.html?demo=1';
  });
})();
