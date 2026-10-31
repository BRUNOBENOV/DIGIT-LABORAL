/* Shared asynchronous company/employee comboboxes; native IDs and form values stay intact. */
(() => {
  "use strict";
  const controllers = new WeakMap();
  const valueProperty = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value");
  let nextId = 0, openPicker = null;
  const selector = 'select[data-searchable-entity],select[name="company_id"],select[name="employee_id"],select#sectionCompany,select#sectionEditorCompany';
  const definitions = {
    company: {endpoint:"companies", label:"Empresa", placeholder:"Código o nombre de empresa", plural:"empresas"},
    employee: {endpoint:"employees", label:"Funcionario", placeholder:"Legajo, nombre o cédula", plural:"funcionarios"},
  };

  class EntitySelect {
    constructor(select, kind) {
      if (controllers.has(select)) return controllers.get(select);
      controllers.set(select, this);
      this.select = select; this.kind = kind; this.config = definitions[kind];
      this.sequence = 0; this.selectionSequence = 0; this.active = -1; this.items = []; this.dirty = false;
      select.dataset.searchableEntity = kind;
      if (!select.id) select.id = "entity-select-"+(++nextId);
      const labels = Array.from(select.labels || []);
      const label = labels[0]?.cloneNode(true);
      label?.querySelectorAll("select,input,button,small").forEach(node => node.remove());
      const accessibleName = select.getAttribute("aria-label") || label?.textContent.trim() || this.config.label;
      const original = valueProperty.get.call(select);
      this.initialOptions = new Set(Array.from(select.options));
      this.empty = Array.from(select.options).find(option => !option.value || option.value === "0");
      if (!this.empty) {
        this.empty = new Option("Seleccioná "+(kind === "company" ? "una empresa" : "un funcionario"), "");
        select.prepend(this.empty);
        valueProperty.set.call(select, original);
      }
      this.empty.disabled = false;
      this.wrapper = document.createElement("span"); this.wrapper.className = "entity-select";
      this.control = document.createElement("span"); this.control.className = "entity-select-control";
      this.input = document.createElement("input");
      this.input.id = select.id+"-search"; this.input.type = "text"; this.input.autocomplete = "off";
      this.input.maxLength = 120; this.input.spellcheck = false;
      this.input.className = "entity-select-input"; this.input.placeholder = this.config.placeholder;
      this.input.setAttribute("role", "combobox"); this.input.setAttribute("aria-autocomplete", "list");
      this.input.setAttribute("aria-expanded", "false"); this.input.setAttribute("aria-haspopup", "listbox");
      this.input.setAttribute("aria-label", accessibleName);
      if (select.getAttribute("aria-describedby")) this.input.setAttribute("aria-describedby", select.getAttribute("aria-describedby"));
      if (select.hasAttribute("form")) this.input.setAttribute("form", select.getAttribute("form"));
      labels.forEach(node => node.setAttribute("for", this.input.id));
      this.clear = document.createElement("button"); this.clear.type = "button"; this.clear.className = "entity-select-clear";
      this.clear.textContent = "×"; this.clear.title = "Limpiar "+this.config.label.toLowerCase(); this.clear.setAttribute("aria-label", this.clear.title);
      this.toggle = document.createElement("button"); this.toggle.type = "button"; this.toggle.className = "entity-select-toggle";
      this.toggle.tabIndex = -1; this.toggle.textContent = "⌄"; this.toggle.setAttribute("aria-label", "Mostrar "+this.config.plural);
      this.busy = document.createElement("span"); this.busy.className = "entity-select-spinner"; this.busy.hidden = true; this.busy.setAttribute("aria-hidden", "true");
      this.popover = document.createElement("div"); this.popover.className = "entity-select-popover"; this.popover.hidden = true;
      this.list = document.createElement("div"); this.list.id = select.id+"-options"; this.list.setAttribute("role", "listbox"); this.list.setAttribute("aria-label", "Resultados de "+accessibleName);
      this.status = document.createElement("p"); this.status.className = "entity-select-status"; this.status.setAttribute("role", "status"); this.status.setAttribute("aria-live", "polite");
      this.popover.append(this.list, this.status); document.body.append(this.popover);
      this.input.setAttribute("aria-controls", this.list.id);
      select.before(this.wrapper); this.wrapper.append(select, this.control); this.control.append(this.input, this.busy, this.clear, this.toggle);
      select.classList.add("entity-select-native"); select.tabIndex = -1; select.setAttribute("aria-hidden", "true");
      this.input.addEventListener("focus", () => {
        select.form?.dispatchEvent(new Event("digit:entity-interaction"));
        this.sync(true); if (!this.isEmpty()) this.input.select(); this.open();
      });
      this.input.addEventListener("click", () => { if (!this.dirty && !this.isEmpty()) this.input.select(); });
      this.input.addEventListener("input", () => {
        this.detailAbort?.abort(); this.selectionSequence++; this.selecting = false;
        this.dirty = true; this.input.setCustomValidity("Seleccioná una opción de la lista."); this.input.removeAttribute("aria-invalid");
        window.clearTimeout(this.timer); this.abort?.abort(); this.sequence++;
        this.open(false); this.list.replaceChildren(); this.items = []; this.active = -1;
        this.status.textContent = "Buscando…";
        this.timer = window.setTimeout(() => this.search(this.input.value), 300);
      });
      this.input.addEventListener("keydown", event => this.keydown(event));
      this.input.addEventListener("blur", () => { if (!this.popover.hidden) { this.close(); this.sync(true); } });
      this.clear.addEventListener("click", () => { this.clearSelection(); this.input.focus(); this.open(); });
      this.toggle.addEventListener("mousedown", event => event.preventDefault());
      this.toggle.addEventListener("click", () => { if (this.popover.hidden) { this.input.focus(); this.open(); } else this.close(); });
      this.popover.addEventListener("mousedown", event => event.preventDefault());
      select.addEventListener("change", () => this.sync(true));
      select.addEventListener("invalid", event => {
        event.preventDefault(); this.input.setCustomValidity("Seleccioná "+(kind === "company" ? "una empresa." : "un funcionario."));
        this.input.setAttribute("aria-invalid", "true"); this.input.focus(); this.input.reportValidity();
      });
      select.form?.addEventListener("reset", () => window.setTimeout(() => this.sync(true), 0));
      this.observer = new MutationObserver(() => this.sync());
      this.observer.observe(select, {attributes:true, childList:true, subtree:true, attributeFilter:["disabled","required","selected","label"]});
      this.bindCompanyContext(); this.sync(true);
    }

    bindCompanyContext() {
      if (this.kind !== "employee") return;
      this.company = this.select.form?.querySelector('select[data-searchable-entity="company"],select[name="company_id"]') ||
        document.querySelector('form[method="get" i] select[data-searchable-entity="company"],form[method="get" i] select[name="company_id"]');
      if (!this.company) return;
      this.contextCompany = this.company.value;
      this.company.addEventListener("change", () => {
        const company = this.company.value;
        if (company === this.contextCompany) return;
        this.contextCompany = company; this.abort?.abort(); this.sequence++; this.detailAbort?.abort(); this.selectionSequence++;
        this.selecting = false;
        this.close();
        const selected = this.select.selectedOptions[0];
        if (this.select.value && company && company !== "0" && selected?.dataset.company !== company) this.clearSelection({source:"company-context"});
      }, {capture:true});
    }

    get value() { return valueProperty.get.call(this.select); }
    isEmpty(value = this.value) { return !value || value === "0"; }
    sync(force = false) {
      const option = this.select.selectedOptions[0];
      if (force || !this.dirty || this.lastValue !== this.value) {
        this.input.value = this.isEmpty() ? "" : (option?.textContent.trim() || "");
        this.input.title = this.input.value; this.dirty = false; this.input.setCustomValidity("");
      }
      this.lastValue = this.value;
      this.input.disabled = this.select.disabled; this.toggle.disabled = this.select.disabled; this.clear.disabled = this.select.disabled;
      this.input.required = this.select.required; this.input.setAttribute("aria-required", String(this.select.required));
      this.clear.hidden = this.isEmpty();
      this.wrapper.classList.toggle("is-disabled", this.select.disabled);
      if (this.select.disabled) this.close();
      if (this.selecting) this.input.setCustomValidity("Esperá a que termine de cargar la selección.");
    }

    setValue(value, {emit = false} = {}) {
      this.detailAbort?.abort(); this.selectionSequence++; this.selecting = false;
      value = String(value ?? "");
      const existing = Array.from(this.select.options).find(option => option.value === value);
      if (!existing && /^\d+$/.test(value) && Number(value) > 0) {
        const option = new Option("Cargando selección…", value); this.select.append(option);
        valueProperty.set.call(this.select, value); this.sync(true);
        return this.hydrate(value, emit);
      }
      valueProperty.set.call(this.select, value); this.sync(true);
      if (emit) this.select.dispatchEvent(new Event("change", {bubbles:true}));
      return Promise.resolve();
    }

    parameters(query = "") {
      const url = new URL("/api/selectors/"+this.config.endpoint, window.location.origin);
      url.searchParams.set("q", query); url.searchParams.set("limit", "10");
      url.searchParams.set("scope", this.select.dataset.entityScope || "all");
      const company = this.company?.value;
      if (this.kind === "employee" && company && company !== "0") url.searchParams.set("company_id", company);
      return url;
    }

    async request(url, signal) {
      const response = await fetch(url, {signal, credentials:"same-origin", headers:{Accept:"application/json"}, cache:"no-store"});
      if (response.status === 401 || (response.redirected && new URL(response.url).pathname.startsWith("/login"))) throw new Error("Tu sesión venció. Volvé a ingresar.");
      if (!response.ok) throw new Error("No se pudieron cargar los resultados. Intentá nuevamente.");
      return response.json();
    }

    async search(query) {
      this.abort?.abort(); this.abort = new AbortController(); const sequence = ++this.sequence;
      this.busy.hidden = false; this.input.setAttribute("aria-busy", "true"); this.status.textContent = "Buscando…";
      try {
        const data = await this.request(this.parameters(query), this.abort.signal);
        if (sequence !== this.sequence || this.popover.hidden) return;
        this.items = data.items || [];
        const selected = this.select.selectedOptions[0];
        if (!query && !this.isEmpty() && selected && !this.items.some(item => String(item.id) === this.value)) {
          this.items = [{id:this.value, label:selected.textContent.trim(), description:"Selección actual", company_id:selected.dataset.company}, ...this.items].slice(0,10);
        }
        this.active = this.items.findIndex(item => String(item.id) === this.value);
        if (this.active < 0 && this.items.length) this.active = 0;
        this.renderResults();
        this.status.textContent = !this.items.length ? "No se encontraron resultados" : data.has_more ? "Hay más coincidencias. Seguí escribiendo para acotar." : this.items.length+" resultado(s)";
        this.position();
      } catch (error) {
        if (error.name !== "AbortError" && sequence === this.sequence) { this.list.replaceChildren(); this.items = []; this.active = -1; this.status.textContent = error.message; }
      } finally {
        if (sequence === this.sequence) { this.busy.hidden = true; this.input.removeAttribute("aria-busy"); }
      }
    }

    renderResults() {
      this.list.replaceChildren();
      this.items.forEach((item, index) => {
        const row = document.createElement("div"); row.className = "entity-select-option"; row.id = this.list.id+"-"+index;
        row.setAttribute("role", "option"); row.setAttribute("aria-selected", String(String(item.id) === this.value));
        const title = document.createElement("span"); title.className = "entity-select-option-title"; title.textContent = item.label;
        const details = document.createElement("span"); details.className = "entity-select-option-detail"; details.textContent = item.description || "";
        row.append(title, details); row.addEventListener("click", () => this.choose(item)); this.list.append(row);
      });
      this.paintActive();
    }

    paintActive() {
      Array.from(this.list.children).forEach((row, index) => row.classList.toggle("is-active", index === this.active));
      const row = this.list.children[this.active];
      if (row) { this.input.setAttribute("aria-activedescendant", row.id); row.scrollIntoView?.({block:"nearest"}); }
      else this.input.removeAttribute("aria-activedescendant");
    }

    async hydrate(value, emit = true) {
      this.detailAbort?.abort(); this.detailAbort = new AbortController(); const sequence = ++this.selectionSequence;
      this.selecting = true;
      const url = this.parameters(); url.searchParams.delete("q"); url.searchParams.set("selected_id", value);
      // Retain an existing record when editing history; suggestions still honor the operational scope.
      if (!emit) { url.searchParams.set("scope", "all"); url.searchParams.delete("company_id"); }
      this.busy.hidden = false; this.input.setCustomValidity("Esperá a que termine de cargar la selección.");
      try {
        const data = await this.request(url, this.detailAbort.signal);
        if (sequence !== this.selectionSequence) return;
        const item = data.items?.[0]; if (!item) throw new Error("No se encontró el registro seleccionado.");
        let option = Array.from(this.select.options).find(option => option.value === String(item.id));
        if (!option) { option = new Option(item.label, String(item.id)); this.select.append(option); }
        option.textContent = item.label; option.disabled = false; option.hidden = false;
        Object.entries(item.dataset || {}).forEach(([key, value]) => { option.dataset[key] = String(value ?? ""); });
        if (item.company_id) option.dataset.company = String(item.company_id);
        valueProperty.set.call(this.select, String(item.id));
        Array.from(this.select.options).forEach(old => { if (old !== option && old !== this.empty && !this.initialOptions.has(old)) old.remove(); });
        this.selecting = false;
        this.sync(true); this.close();
        if (emit) {
          this.select.dispatchEvent(new Event("input", {bubbles:true}));
          this.select.dispatchEvent(new Event("change", {bubbles:true}));
        }
        return item;
      } catch (error) {
        if (error.name !== "AbortError" && sequence === this.selectionSequence) {
          this.selecting = false;
          if (!emit && this.value === value) { valueProperty.set.call(this.select, this.empty.value); this.sync(true); }
          this.status.textContent = error.message; this.input.setCustomValidity(error.message);
        }
        throw error;
      } finally { if (sequence === this.selectionSequence) { this.selecting = false; this.busy.hidden = true; } }
    }

    choose(item) { this.hydrate(String(item.id)).catch(() => {}); }
    clearSelection({source = ""} = {}) {
      this.detailAbort?.abort(); this.selectionSequence++; this.empty.disabled = false;
      this.selecting = false;
      valueProperty.set.call(this.select, this.empty.value); this.sync(true); this.close();
      this.select.dispatchEvent(new Event("input", {bubbles:true})); this.select.dispatchEvent(new CustomEvent("change", {bubbles:true, detail:{source}}));
    }
    open(load = true) {
      if (this.select.disabled) return;
      if (openPicker && openPicker !== this) { openPicker.close(); openPicker.sync(true); }
      const wasClosed = this.popover.hidden;
      openPicker = this; this.popover.hidden = false; this.input.setAttribute("aria-expanded", "true"); this.position();
      if (load && wasClosed) {
        this.items = []; this.active = -1; this.list.replaceChildren(); this.input.removeAttribute("aria-activedescendant");
        this.search(this.dirty ? this.input.value : "");
      }
    }
    close() {
      window.clearTimeout(this.timer); this.abort?.abort(); this.sequence++; this.popover.hidden = true;
      this.input.setAttribute("aria-expanded", "false"); this.input.removeAttribute("aria-activedescendant"); this.input.removeAttribute("aria-busy");
      this.busy.hidden = true; if (openPicker === this) openPicker = null;
    }
    position() {
      if (this.popover.hidden) return;
      const rect = this.control.getBoundingClientRect(); const below = window.innerHeight - rect.bottom - 12; const above = rect.top - 12;
      const upward = below < 180 && above > below; const height = Math.min(310, Math.max(100, upward ? above : below));
      this.popover.style.width = Math.min(rect.width, window.innerWidth-24)+"px";
      this.popover.style.left = Math.max(12, Math.min(rect.left, window.innerWidth-rect.width-12))+"px";
      this.popover.style.maxHeight = height+"px";
      this.popover.style.top = (upward ? Math.max(8, rect.top-Math.min(this.popover.scrollHeight, height)-6) : rect.bottom+6)+"px";
    }
    keydown(event) {
      if (event.key === "Escape" && !this.popover.hidden) { event.preventDefault(); event.stopPropagation(); this.close(); this.sync(true); }
      else if (["ArrowDown","ArrowUp"].includes(event.key)) {
        event.preventDefault(); this.open();
        if (this.items.length) { this.active = (this.active+(event.key === "ArrowDown" ? 1 : -1)+this.items.length)%this.items.length; this.paintActive(); }
      } else if (event.key === "Enter" && !this.popover.hidden) {
        event.preventDefault(); event.stopPropagation(); if (this.items[this.active]) this.choose(this.items[this.active]);
      } else if (event.key === "Tab") { this.close(); this.sync(true); }
    }
  }

  class SearchableCompanySelect extends EntitySelect { constructor(select) { super(select, "company"); } }
  class SearchableEmployeeSelect extends EntitySelect { constructor(select) { super(select, "employee"); } }
  const init = (root = document) => {
    const selects = [...(root.matches?.(selector) ? [root] : []), ...root.querySelectorAll(selector)];
    selects.forEach(select => {
      if (controllers.has(select) || select.multiple) return;
      const kind = select.dataset.searchableEntity || (select.name === "employee_id" ? "employee" : "company");
      controllers.set(select, kind === "employee" ? new SearchableEmployeeSelect(select) : new SearchableCompanySelect(select));
    });
  };
  window.SearchableCompanySelect = SearchableCompanySelect; window.SearchableEmployeeSelect = SearchableEmployeeSelect;
  window.DigitEntitySelect = {init, refresh:select => controllers.get(select)?.sync(true), setValue:(select, value, options) => { init(select); return controllers.get(select)?.setValue(value, options); }};
  const start = () => {
    init();
    new MutationObserver(records => records.forEach(record => record.addedNodes.forEach(node => { if (node.nodeType === 1) init(node); }))).observe(document.body, {childList:true, subtree:true});
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, {once:true}); else start();
  document.addEventListener("pointerdown", event => { if (openPicker && !openPicker.wrapper.contains(event.target) && !openPicker.popover.contains(event.target)) { openPicker.sync(true); openPicker.close(); } });
  window.addEventListener("resize", () => openPicker?.position());
  document.addEventListener("scroll", () => openPicker?.position(), true);
})();
