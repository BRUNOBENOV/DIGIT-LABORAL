/* Progressive GET navigation shared by all server-paginated lists. */
(() => {
  "use strict";
  const focusKey = "digit-pagination-focus";
  const urlFromForm = form => {
    const url = new URL(form.action || window.location.href);
    url.search = "";
    for (const [key, value] of new FormData(form)) {
      if (String(value).trim() !== "") url.searchParams.set(key, String(value));
    }
    form.querySelectorAll("select[data-sort-signed]").forEach(select => {
      const key = select.value || select.options[1]?.value || "";
      url.searchParams.set(select.name, (select.dataset.sortDirection === "desc" ? "-" : "") + key);
    });
    url.searchParams.delete("page");
    return url;
  };
  const navigate = (url, form) => {
    form?.dispatchEvent(new Event("digit:page-navigation"));
    const pager = Array.from(document.querySelectorAll("[data-pagination]")).find(node => !form || node.dataset.filterForm === form.id);
    const loading = pager?.querySelector("[data-list-loading]");
    if (loading) loading.hidden = false;
    document.getElementById(pager?.dataset.pageTarget || "")?.setAttribute("aria-busy", "true");
    // Let the loading indicator paint before the full-page GET starts.
    window.requestAnimationFrame(() => window.setTimeout(() => window.location.assign(String(url)), 0));
  };
  const rememberFocus = (form, field) => {
    try { sessionStorage.setItem(focusKey, JSON.stringify({path:window.location.pathname, form:form.id, name:field.name, start:field.selectionStart, end:field.selectionEnd})); } catch (_) { /* Storage can be disabled. */ }
  };
  const init = () => {
    document.querySelectorAll("[data-pagination]").forEach(pager => {
      if (pager.dataset.paginationReady) return;
      pager.dataset.paginationReady = "true";
      const form = document.getElementById(pager.dataset.filterForm);
      if (!form) return;
      let timer;
      form.addEventListener("digit:page-navigation", () => window.clearTimeout(timer));
      form.addEventListener("digit:entity-interaction", () => window.clearTimeout(timer));
      const search = form.querySelector('[name="q"]');
      const submitFilters = () => { window.clearTimeout(timer); const url = urlFromForm(form); url.searchParams.set("page", "1"); navigate(url, form); };
      form.addEventListener("submit", event => {
        window.clearTimeout(timer);
        if (event.defaultPrevented) return;
        event.preventDefault(); submitFilters();
      });
      if (search) search.addEventListener("input", () => {
        window.clearTimeout(timer);
        timer = window.setTimeout(() => { rememberFocus(form, search); submitFilters(); }, 650);
      });
      document.querySelectorAll('[data-list-filter][data-filter-form="'+form.id+'"]').forEach(link => {
        link.addEventListener("click", event => {
          if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button) return;
          event.preventDefault();
          const field = form.elements.namedItem(link.dataset.listFilter);
          if (field) field.value = link.dataset.filterValue;
          submitFilters();
        });
      });
      pager.querySelectorAll("nav a").forEach(link => link.addEventListener("click", event => {
        if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button) return;
        event.preventDefault(); window.clearTimeout(timer);
        const url = urlFromForm(form); url.searchParams.set("page", new URL(link.href).searchParams.get("page")); navigate(url, form);
      }));
      const sizeForm = pager.querySelector("[data-page-size-form]");
      sizeForm?.querySelector("select").addEventListener("change", event => {
        window.clearTimeout(timer);
        const url = urlFromForm(form); url.searchParams.set("page_size", event.target.value); url.searchParams.set("page", "1"); navigate(url, form);
      });
      const jumpForm = pager.querySelector("[data-page-jump-form]");
      jumpForm?.addEventListener("submit", event => {
        event.preventDefault(); window.clearTimeout(timer);
        const url = urlFromForm(form); url.searchParams.set("page", jumpForm.elements.namedItem("page").value); navigate(url, form);
      });
    });
    try {
      const focus = JSON.parse(sessionStorage.getItem(focusKey) || "null");
      sessionStorage.removeItem(focusKey);
      if (focus?.path === window.location.pathname) {
        const field = document.getElementById(focus.form)?.elements.namedItem(focus.name);
        if (field) { field.focus(); field.setSelectionRange(focus.start, focus.end); }
      }
    } catch (_) { /* Focus restoration is optional. */ }
  };
  window.DigitPagination = {navigate, urlFromForm};
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, {once:true}); else init();
  window.addEventListener("pageshow", () => {
    document.querySelectorAll("[data-list-loading]").forEach(node => { node.hidden = true; });
    document.querySelectorAll('[aria-busy="true"]').forEach(node => node.removeAttribute("aria-busy"));
    init();
  });
  window.addEventListener("pagehide", () => {
    document.querySelectorAll("[data-paginated-filters]").forEach(form => form.dispatchEvent(new Event("digit:page-navigation")));
  });
})();
