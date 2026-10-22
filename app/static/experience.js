/* Experiencia compartida: filtros locales, envíos protegidos y accesibilidad móvil. */
(() => {
  "use strict";

  const normalize = value => String(value || "")
    .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .toLowerCase().replace(/\s+/g, " ").trim();

  const makeFilter = (insert, kind, items, onFilter) => {
    const bar = document.createElement("div");
    bar.className = "experience-filter";
    const placeholder = kind === "table" ? "Buscar en los registros de esta vista…" :
      kind === "requests" ? "N.º, tipo, empresa o estado…" : "Título, detalle o fecha…";
    const control = document.createElement("label");
    control.className = "experience-filter-control";
    control.innerHTML = '<span aria-hidden="true">⌕</span>';
    const input = document.createElement("input");
    input.type = "search";
    input.placeholder = placeholder;
    input.setAttribute("aria-label", kind === "table" ? "Filtrar registros visibles" :
      kind === "requests" ? "Buscar trámite o empresa" : "Buscar notificación");
    input.autocomplete = "off";
    input.spellcheck = false;
    const count = document.createElement("span");
    count.className = "experience-filter-count";
    count.setAttribute("aria-live", "polite");
    control.appendChild(input);
    bar.append(control, count);

    const empty = document.createElement("div");
    empty.className = "experience-filter-empty";
    empty.hidden = true;
    empty.textContent = "No hay coincidencias. Probá con otro término.";

    const update = () => {
      const term = normalize(input.value);
      const visible = onFilter(term);
      const noun = kind === "table" ? "registros" : kind === "requests" ? "trámites" : "avisos";
      count.textContent = term ? visible + " de " + items.length + " " + noun : items.length + " " + noun;
      empty.hidden = visible > 0;
    };
    input.addEventListener("input", update);
    insert(bar, empty);
    update();
  };

  // Filtro local de tablas: no modifica ni elimina los registros del servidor.
  document.querySelectorAll(".table-panel").forEach(panel => {
    if (panel.querySelector(".experience-filter")) return;
    // Si ya hay un buscador de servidor en esta sección, evitamos duplicar controles.
    if (panel.querySelector("form.search-form")) return;
    const tables = [...panel.querySelectorAll(".table-wrap table")];
    const rows = tables.flatMap(table => [...table.querySelectorAll("tbody tr")])
      .filter(row => !row.querySelector(".empty-state"));
    if (!rows.length) return;
    const wrap = panel.querySelector(".table-wrap");
    if (!wrap) return;

    makeFilter((bar, empty) => {
      const heading = panel.querySelector(":scope > .panel-head");
      if (heading) heading.insertAdjacentElement("afterend", bar);
      else panel.insertBefore(bar, wrap);
      wrap.insertAdjacentElement("afterend", empty);
    }, "table", rows, term => {
      let visible = 0;
      rows.forEach(row => {
        const match = !term || normalize(row.textContent).includes(term);
        row.classList.toggle("experience-filter-item-hidden", !match);
        if (match) visible += 1;
      });
      return visible;
    });
  });

  // Búsqueda por texto en solicitudes y notificaciones; los filtros por estado siguen funcionando.
  const installCardFilter = (selector, kind, itemSelector) => {
    document.querySelectorAll(selector).forEach(container => {
      if (container.querySelector(".experience-filter")) return;
      const items = [...container.querySelectorAll(itemSelector)];
      if (!items.length) return;
      makeFilter((bar, empty) => {
        container.insertAdjacentElement("beforebegin", bar);
        container.appendChild(empty);
      }, kind, items, term => {
        let visible = 0;
        items.forEach(item => {
          const match = !term || normalize(item.textContent).includes(term);
          item.classList.toggle("experience-filter-item-hidden", !match);
          if (match) visible += 1;
        });
        return visible;
      });
    });
  };
  installCardFilter(".request-grid", "requests", ".request-card");
  installCardFilter(".notification-list", "notifications", ".notification-item");

  // Confirma acciones destructivas y evita dobles envíos sin cambiar los datos del formulario.
  document.querySelectorAll("form").forEach(form => {
    form.addEventListener("submit", event => {
      if (event.defaultPrevented) return;
      const submitter = event.submitter || form.querySelector('button[type="submit"],input[type="submit"]');
      const label = (submitter?.innerText || submitter?.value || "") + " " + (form.getAttribute("action") || "");
      const destructive = /\b(eliminar|borrar|anular|revocar|desactivar)\b|logout-all/i.test(label);
      if (destructive && !form.dataset.confirmedByExperience) {
        if (!window.confirm("Esta acción puede cambiar el acceso o el estado de un registro. ¿Deseás continuar?")) {
          event.preventDefault();
          return;
        }
      }
      if (form.dataset.experienceBusy === "true") {
        event.preventDefault();
        return;
      }
      form.dataset.experienceBusy = "true";
      form.classList.add("experience-is-processing");
      if (submitter) {
        submitter.classList.add("experience-submit-processing");
        submitter.setAttribute("aria-busy", "true");
      }
    });
  });

  // Cierra el menú desplegable tras navegar y admite Escape.
  const mobileNav = document.getElementById("modernMobileNav");
  if (mobileNav) {
    mobileNav.querySelectorAll("a").forEach(link => {
      link.addEventListener("click", () => mobileNav.classList.remove("open"));
    });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape") {
        mobileNav.classList.remove("open");
        document.querySelectorAll(".nav-more[open]").forEach(menu => menu.removeAttribute("open"));
      }
    });
  }

  // Sidebar responsive: sincroniza accesibilidad, permite cerrar con fondo y Escape.
  const menuButton = document.querySelector("[data-modern-menu]");
  const sidebarBackdrop = document.querySelector("[data-sidebar-backdrop]");
  const syncSidebarState = () => {
    const opened = Boolean(mobileNav?.classList.contains("open"));
    menuButton?.setAttribute("aria-expanded", String(opened));
  };
  menuButton?.addEventListener("click", () => window.setTimeout(syncSidebarState, 0));
  sidebarBackdrop?.addEventListener("click", () => {
    mobileNav?.classList.remove("open");
    syncSidebarState();
  });
  mobileNav?.querySelectorAll("a").forEach(link => link.addEventListener("click", () => {
    mobileNav.classList.remove("open");
    syncSidebarState();
  }));
  document.addEventListener("keydown", event => {
    if (event.key === "Escape") syncSidebarState();
  });

})();
