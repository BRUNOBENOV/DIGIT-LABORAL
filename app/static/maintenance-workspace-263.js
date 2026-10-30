/* DigIT-Laboral 2.6.3 — controles de usabilidad de mantenimientos */
(() => {
  const start = () => {
    const setPressed = (buttons, current) => buttons.forEach(button => {
      const active = button === current;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
    const normalized = value => String(value || "").trim().toLocaleLowerCase("es");

    // Directorio de empresas: búsqueda inmediata, filtros rápidos y orden estable del DOM.
    const companyGrid = document.querySelector("[data-company-directory]");
    if (companyGrid) {
      const cards = Array.from(companyGrid.querySelectorAll("[data-company-card]"));
      const query = document.querySelector(".company-maintenance-filters [name='q']");
      const sort = document.getElementById("companySort");
      const count = document.getElementById("companyVisibleCount");
      const empty = document.getElementById("companyQuickEmpty");
      const buttons = Array.from(document.querySelectorAll("[data-company-filter]"));
      let quickFilter = "all";

      const sortCards = () => {
        if (!sort) return;
        const key = sort.value;
        const multiplier = sort.dataset.sortDirection === "desc" ? -1 : 1;
        cards.sort((a, b) => {
          if (key === "code") return ((Number(a.dataset.companyCode) || 0) - (Number(b.dataset.companyCode) || 0))*multiplier;
          if (key === "employees") return ((Number(a.dataset.companyEmployees) || 0) - (Number(b.dataset.companyEmployees) || 0))*multiplier;
          return normalized(a.dataset.companyName).localeCompare(normalized(b.dataset.companyName), "es", {sensitivity:"base"})*multiplier;
        });
        cards.forEach(card => companyGrid.appendChild(card));
      };
      const apply = () => {
        const term = normalized(query && query.value);
        let visible = 0;
        cards.forEach(card => {
          const text = normalized(card.textContent);
          const status = normalized(card.dataset.companyStatus);
          const hasLogo = card.dataset.companyLogo === "yes";
          const matchesFilter = quickFilter === "all" ||
            (quickFilter === "active" && status === "activa") ||
            (quickFilter === "archived" && status === "archivada") ||
            (quickFilter === "no-logo" && !hasLogo);
          const matchesTerm = !term || text.includes(term);
          const show = matchesFilter && matchesTerm;
          card.hidden = !show;
          if (show) visible += 1;
        });
        if (count) count.textContent = String(visible);
        if (empty) empty.hidden = !(cards.length > 0 && visible === 0);
      };
      buttons.forEach(button => button.addEventListener("click", () => {
        quickFilter = button.dataset.companyFilter || "all";
        setPressed(buttons, button);
        apply();
      }));
      if (query) query.addEventListener("input", apply);
      if (sort) sort.addEventListener("change", () => { sortCards(); apply(); });
      sortCards();
      apply();
    }

    // Directorio de funcionarios: ordenación y filtros locales sin descartar los filtros de servidor.
    const employeeTable = document.getElementById("employeeTable");
    if (employeeTable) {
      const body = employeeTable.querySelector("tbody");
      const rows = Array.from(employeeTable.querySelectorAll("tbody tr[data-employee-row]"));
      const query = document.querySelector(".employee-maintenance-filters [name='q']");
      const sort = document.getElementById("employeeSort");
      const count = document.getElementById("employeeVisibleCount");
      const resultCount = document.getElementById("employeeResultCount");
      const empty = document.getElementById("employeeClientEmpty");
      const buttons = Array.from(document.querySelectorAll("[data-employee-filter]"));
      let quickFilter = new URLSearchParams(window.location.search).get("employee_quick") || "all";
      const filterForm = document.getElementById("employeeFilters");
      const quickField = document.createElement("input");
      quickField.type="hidden"; quickField.name="employee_quick"; quickField.value=quickFilter;
      if (filterForm) filterForm.append(quickField);
      const selectedQuickButton = buttons.find(button=>button.dataset.employeeFilter===quickFilter);
      if (selectedQuickButton) setPressed(buttons,selectedQuickButton);

      const sortRows = () => {
        if (!body || !sort || sort.dataset.sortServer) return;
        const key = sort.value;
        const numericKeys = new Set(["code", "salary"]);
        rows.sort((a, b) => {
          const av = a.dataset["employee" + key[0].toUpperCase() + key.slice(1)] || "";
          const bv = b.dataset["employee" + key[0].toUpperCase() + key.slice(1)] || "";
          if (numericKeys.has(key)) return (Number(av) || 0) - (Number(bv) || 0);
          return normalized(av).localeCompare(normalized(bv), "es", {numeric:true, sensitivity:"base"});
        });
        rows.forEach(row => body.appendChild(row));
      };
      const apply = () => {
        const term = normalized(query && query.value);
        let visible = 0;
        rows.forEach(row => {
          const status = normalized(row.dataset.employeeStatus);
          const section = normalized(row.dataset.employeeSection);
          const ips = row.dataset.employeeIps === "yes";
          const matchesFilter = quickFilter === "all" ||
            (quickFilter === "active" && status === "activo") ||
            (quickFilter === "ips" && ips) ||
            (quickFilter === "no-section" && (!section || section === "sin sección"));
          const haystack = normalized([
            row.dataset.employeeName, row.dataset.employeeCode, row.dataset.employeeCompany,
            row.dataset.employeeDocument, row.dataset.employeeSection, row.dataset.employeePosition,
            row.textContent
          ].join(" "));
          const show = matchesFilter && (!term || haystack.includes(term));
          row.hidden = !show;
          if (show) visible += 1;
        });
        if (count) count.textContent = String(visible) + (visible === 1 ? " funcionario visible" : " funcionarios visibles");
        if (resultCount) resultCount.textContent = String(visible);
        if (empty) empty.hidden = !(rows.length > 0 && visible === 0);
      };
      buttons.forEach(button => button.addEventListener("click", () => {
        quickFilter = button.dataset.employeeFilter || "all";
        quickField.value = quickFilter;
        setPressed(buttons, button);
        apply();
      }));
      if (query) query.addEventListener("input", apply);
      if (sort) sort.addEventListener("change", () => { sortRows(); apply(); });
      sortRows();
      apply();
    }

    // Mensajes de validación junto al campo, una vez que el usuario lo visitó o modificó.
    document.querySelectorAll("#companyForm, #employeeForm, #editCompanyModal form.form-grid, #branchModal form.form-grid, #editEmployeeDetail form.form-grid, #eventModal form.form-grid").forEach(form => {
      const controls = Array.from(form.querySelectorAll("input, select, textarea")).filter(field =>
        !["hidden","submit","button","reset","file","checkbox","radio"].includes((field.type || "").toLowerCase())
      );
      controls.forEach(field => {
        let touched = false;
        let message = null;
        const messageFor = () => {
          if (field.validity.valueMissing) return "Este campo es obligatorio.";
          if (field.validity.typeMismatch && field.type === "email") return "Ingresá un correo electrónico válido.";
          if (field.validity.patternMismatch) return "Revisá el formato indicado para este campo.";
          if (field.validity.rangeUnderflow || field.validity.rangeOverflow || field.validity.stepMismatch) return "Revisá el valor ingresado.";
          if (field.validity.tooLong || field.validity.tooShort) return "La longitud del valor no es válida.";
          return field.validationMessage || "Revisá este campo.";
        };
        const validate = () => {
          if (!touched) return;
          const invalid = !field.checkValidity();
          field.classList.toggle("is-invalid", invalid);
          field.classList.toggle("is-valid", !invalid && Boolean(field.value));
          if (invalid) {
            field.setAttribute("aria-invalid", "true");
            if (!message) {
              message = document.createElement("small");
              message.className = "field-validation-message";
              message.setAttribute("role", "status");
              message.setAttribute("aria-live", "polite");
              field.insertAdjacentElement("afterend", message);
            }
            message.textContent = messageFor();
          } else {
            field.removeAttribute("aria-invalid");
            if (message) message.remove();
            message = null;
          }
        };
        field.addEventListener("blur", () => { touched = true; validate(); });
        field.addEventListener("input", validate);
        field.addEventListener("change", () => { touched = true; validate(); });
      });
    });

    // Los tabs de ancla mantienen su estado visual al navegar por una ficha.
    document.querySelectorAll(".maintenance-detail-nav a[href^='#']").forEach(link => {
      link.addEventListener("click", () => {
        const nav = link.closest(".maintenance-detail-nav");
        if (!nav) return;
        nav.querySelectorAll("a").forEach(item => {
          item.classList.remove("is-active");
          item.removeAttribute("aria-current");
        });
        link.classList.add("is-active");
        link.setAttribute("aria-current", "location");
      });
    });
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, {once:true});
  else start();
})();
