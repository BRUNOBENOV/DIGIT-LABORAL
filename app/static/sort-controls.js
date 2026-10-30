/* Shared accessible sorting for server-paginated lists, cards and local tables. */
(() => {
  "use strict";
  const selectors = new WeakMap();
  const tables = new WeakMap();
  const collator = new Intl.Collator("es", {numeric:true, sensitivity:"base"});
  const normalize = value => String(value ?? "").trim();
  const direction = value => value === "desc" ? "desc" : "asc";
  const icons = () => {
    const span = document.createElement("span");
    span.className = "digit-sort-arrows";
    span.setAttribute("aria-hidden", "true");
    span.innerHTML = '<svg class="digit-sort-up" viewBox="0 0 16 10"><path d="m3 7 5-5 5 5"/></svg><svg class="digit-sort-down" viewBox="0 0 16 10"><path d="m3 3 5 5 5-5"/></svg>';
    return span;
  };
  function paint(button, order, active = true) {
    button.dataset.direction = order;
    button.dataset.sortActive = String(active);
    const title = order === "asc" ? "Ordenar de mayor a menor" : "Ordenar de menor a mayor";
    button.title = title;
    button.setAttribute("aria-label", title);
  }
  function compare(left, right, order = "asc") {
    const parse = value => {
      const text = normalize(value);
      if (!text || /^[—–-]$/.test(text)) return null;
      const date = text.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})(?:\s|$)/);
      if (date) return Date.UTC(Number(date[3]), Number(date[2])-1, Number(date[1]));
      const clean = text.replace(/^(?:Gs\.?|₲|\$)\s*/i, "").replace(/\s/g, "");
      if (/^-?\d+(?:\.\d{3})*(?:,\d+)?%?$/.test(clean)) return Number(clean.replace(/\./g, "").replace(",", ".").replace("%", ""));
      return text;
    };
    const a = parse(left), b = parse(right);
    if (a === null || b === null) return a === b ? 0 : a === null ? 1 : -1;
    return (typeof a === "number" && typeof b === "number" ? a-b : collator.compare(String(a),String(b))) * (order === "desc" ? -1 : 1);
  }
  function selector(select) {
    if (selectors.has(select)) return selectors.get(select);
    const control = document.createElement("span");
    control.className = "digit-sort-control";
    select.before(control);
    control.append(select);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "digit-sort-toggle";
    button.append(icons());
    control.append(button);
    let order = direction(select.dataset.sortDirection);
    const form = select.form;
    let field = form?.querySelector('[name="direction"]');
    if (select.dataset.sortServer && !select.hasAttribute("data-sort-signed") && form && !field) {
      field = document.createElement("input"); field.type = "hidden"; field.name = "direction"; field.value = order; form.append(field);
    }
    if (field) order = direction(field.value);
    const update = () => {
      select.dataset.sortDirection = order;
      if (field) field.value = order;
      paint(button,order);
      button.setAttribute("aria-pressed", String(order === "desc"));
      document.querySelectorAll('table[data-sort-selector="'+select.id+'"]').forEach(table => tables.get(table)?.refresh());
    };
    const navigate = () => {
      if (!form) return;
      const url = new URL(form.action || window.location.href);
      url.search = "";
      for (const [key,value] of new FormData(form)) url.searchParams.set(key,String(value));
      const key = select.value || select.options[1]?.value || select.options[0]?.value || "";
      url.searchParams.set(select.name, select.hasAttribute("data-sort-signed") && order === "desc" ? "-"+key : key);
      if (!select.hasAttribute("data-sort-signed")) url.searchParams.set("direction",order);
      const quick = form.querySelector('[name="employee_quick"]');
      if (quick) url.searchParams.set("employee_quick",quick.value);
      url.searchParams.delete("page");
      window.location.assign(url.toString());
    };
    const api = {get direction(){return order;}, set(key,next){select.value=key;order=direction(next);update();select.dispatchEvent(new Event("change",{bubbles:true}));}};
    selectors.set(select,api);
    select.addEventListener("change", () => {update();if(select.dataset.sortServer) navigate();});
    button.addEventListener("click", () => {order=order === "asc" ? "desc" : "asc";update();select.dispatchEvent(new Event("change",{bubbles:true}));});
    if (select.hasAttribute("data-sort-signed") && form) form.addEventListener("submit", event => {event.preventDefault();navigate();});
    update();
    return api;
  }
  function table(tableNode) {
    if (tables.has(tableNode)) return tables.get(tableNode);
    if (tableNode.closest(".certificate-preview-shell,.certificate-print,.calendar-grid,.calendar-month,.print-sheet") || tableNode.hasAttribute("data-ui-no-enhance")) return;
    const head = tableNode.tHead, body = tableNode.tBodies[0];
    if (!head || !body || head.rows.length !== 1) return;
    const rows = Array.from(body.rows).filter(row => !row.querySelector("[colspan]") && !row.hasAttribute("data-no-sort") && !row.classList.contains("empty-state-row"));
    const select = document.getElementById(tableNode.dataset.sortSelector || "");
    const controller = select ? selector(select) : null;
    let current = null, order = "asc";
    const headers = [];
    const labelKey = value => normalize(value).toLocaleLowerCase("es").replace(/\s*\([^)]*\)/g, "").trim();
    const aliases = {"legajo / funcionario":"name","código funcionario":"code","código legajo":"code","legajo":"code","cédula":"document","fecha de ingreso":"admission","ingreso":"admission","salario base":"salary","neto":"amount","bruto":"gross","fecha":"date","ips":"ips"};
    Array.from(head.rows[0].cells).forEach((th,index) => {
      const label = normalize(th.textContent);
      if (!label || th.colSpan > 1 || th.hasAttribute("data-no-sort") || th.querySelector("button,input,select,a")) return;
      const match = select && Array.from(select.options).find(option => labelKey(option.textContent) === labelKey(label));
      let key = th.dataset.sortKey || match?.value || aliases[labelKey(label)];
      if (key === "admission" && select && Array.from(select.options).some(option=>option.value === "date")) key="date";
      if (select && !Array.from(select.options).some(option => option.value && option.value === key)) return;
      key = select ? key : String(index);
      const button = document.createElement("button");
      button.type = "button"; button.className = "ui-table-sort digit-sort-header";
      const text = document.createElement("span"); text.textContent = label;
      button.append(text,icons()); th.textContent = ""; th.append(button); th.scope = "col";
      headers.push({th,button,key,index,label});
      button.addEventListener("click", () => {
        const same = controller ? select.value === key : current === key;
        const next = same && (controller ? controller.direction : order) === "asc" ? "desc" : "asc";
        if (controller) controller.set(key,next);
        else {current=key;order=next;apply();refresh();}
      });
    });
    const refresh = () => headers.forEach(({th,button,key,label}) => {
      const selected = controller ? (select.value || select.options[1]?.value) === key : current === key;
      const activeOrder = controller ? controller.direction : order;
      th.setAttribute("aria-sort",selected ? (activeOrder === "asc" ? "ascending" : "descending") : "none");
      paint(button,activeOrder,selected);
      button.setAttribute("aria-label", "Ordenar por "+label+": "+(selected && activeOrder === "asc" ? "de mayor a menor" : "de menor a mayor"));
      button.title = button.getAttribute("aria-label");
    });
    const apply = () => {
      const header = headers.find(item => item.key === current);
      if (!header) return;
      rows.sort((a,b) => compare(a.cells[header.index]?.dataset.sortValue ?? a.cells[header.index]?.textContent,b.cells[header.index]?.dataset.sortValue ?? b.cells[header.index]?.textContent,order));
      rows.forEach(row => body.append(row));
    };
    const api = {refresh}; tables.set(tableNode,api);
    if (!controller && headers.length) {current=headers[0].key;apply();}
    refresh();
    return api;
  }
  const init = () => {document.querySelectorAll("select[data-sort-control]").forEach(selector);document.querySelectorAll(".table-wrap table,.report-table-scroll table,.salary-report-scroll table").forEach(table);};
  window.DigitSort = {compare,selector,table};
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded",init,{once:true}); else init();
  window.addEventListener("pageshow",init);
})();
