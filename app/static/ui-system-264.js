/* DigIT-Laboral 2.6.4 — mejoras progresivas globales */
(() => {
  const normalize = value => String(value || "").trim().toLocaleLowerCase("es");
  const safeText = node => normalize(node ? node.textContent : "");

  function enhanceForms(root) {
    const forms = root.querySelectorAll("form:not([data-no-inline-validation])");
    forms.forEach(form => {
      if (form.matches("#companyForm, #employeeForm, #editEmployeeDetail form")) return;
      if (form.dataset.uiValidationReady === "true") return;
      form.dataset.uiValidationReady = "true";
      const fields = Array.from(form.querySelectorAll("input, select, textarea")).filter(field =>
        !["hidden","submit","button","reset","file","checkbox","radio"].includes(String(field.type || "").toLowerCase())
      );
      fields.forEach(field => {
        let touched = false;
        const validate = () => {
          if (!touched || field.disabled) return;
          const invalid = !field.checkValidity();
          field.classList.toggle("is-invalid", invalid);
          field.classList.toggle("is-valid", !invalid && Boolean(field.value));
          if (invalid) field.setAttribute("aria-invalid", "true");
          else field.removeAttribute("aria-invalid");
          let message = field.parentElement?.querySelector(":scope > .ui-field-message");
          if (invalid) {
            if (!message) {
              message = document.createElement("small");
              message.className = "ui-field-message";
              message.setAttribute("role", "status");
              message.setAttribute("aria-live", "polite");
              field.insertAdjacentElement("afterend", message);
            }
            if (field.validity.valueMissing) message.textContent = "Este campo es obligatorio.";
            else if (field.type === "email" && field.validity.typeMismatch) message.textContent = "Ingresá un correo electrónico válido.";
            else if (field.validity.patternMismatch) message.textContent = "El formato ingresado no coincide con el requerido.";
            else if (field.validity.rangeUnderflow || field.validity.rangeOverflow || field.validity.stepMismatch) message.textContent = "Revisá el rango o el valor ingresado.";
            else if (field.validity.tooLong || field.validity.tooShort) message.textContent = "La longitud del valor no es válida.";
            else message.textContent = field.validationMessage || "Revisá este campo.";
          } else if (message) message.remove();
        };
        field.addEventListener("blur", () => { touched = true; validate(); });
        field.addEventListener("input", validate);
        field.addEventListener("change", () => { touched = true; validate(); });
      });
    });
  }

  function enhanceTables(root) {
    root.querySelectorAll(".table-wrap table:not([data-ui-no-enhance]):not([data-ui-enhanced])").forEach(table => {
      if (table.id === "employeeTable" || table.closest(".certificate-preview-shell,.certificate-print,.calendar-grid,.calendar-month,.print-sheet")) return;
      const head = table.tHead;
      const body = table.tBodies && table.tBodies[0];
      if (!head || !body || !head.rows.length) return;
      const sourceRows = Array.from(body.rows).filter(row => !row.querySelector("[colspan]") && !row.classList.contains("empty-state-row"));
      if (sourceRows.length < 3) return;

      table.dataset.uiEnhanced = "true";
      const wrapper = table.closest(".table-wrap") || table.parentElement;
      if (!wrapper || !wrapper.parentElement) return;
      const toolbar = document.createElement("div");
      toolbar.className = "ui-table-toolbar";
      const label = document.createElement("label");
      label.className = "ui-table-search";
      label.textContent = "Buscar en este listado";
      const search = document.createElement("input");
      search.type = "search";
      search.placeholder = "Escribí para filtrar…";
      search.setAttribute("aria-label", "Buscar en la tabla");
      label.appendChild(search);
      const count = document.createElement("p");
      count.className = "ui-table-count";
      count.setAttribute("aria-live", "polite");
      toolbar.append(label, count);
      wrapper.parentElement.insertBefore(toolbar, wrapper);

      const rowCells = row => Array.from(row.cells).map(cell => safeText(cell)).join(" ");
      // Shared header controls keep aria-sort on the column header.
      window.DigitSort?.table(table);

      let empty = table.parentElement.querySelector(":scope > .ui-empty-filter");
      if (!empty) {
        empty = document.createElement("p");
        empty.className = "ui-empty-filter";
        empty.hidden = true;
        empty.textContent = "No hay filas que coincidan con la búsqueda.";
        wrapper.insertAdjacentElement("afterend", empty);
      }
      const applyFilter = () => {
        const term = normalize(search.value);
        let shown = 0;
        sourceRows.forEach(row => {
          const matches = !term || rowCells(row).includes(term);
          row.hidden = !matches;
          if (matches) shown += 1;
        });
        count.textContent = shown + (shown === 1 ? " fila visible" : " filas visibles");
        empty.hidden = shown > 0;
      };
      search.addEventListener("input", applyFilter);
      applyFilter();
    });
  }

  function init(root = document) {
    enhanceForms(root);
    enhanceTables(root);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => init(), {once:true});
  else init();
  window.addEventListener("pageshow", () => init());
})();
