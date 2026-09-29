(() => {
  "use strict";
  const form = document.getElementById("labor-form");
  const result = document.getElementById("labor-result");
  let formChanged = false;
  if (form) form.addEventListener("input", () => { formChanged = true; });
  if (form && result) {
    const markDirty = () => {
      document.body.classList.add("dl-form-dirty");
      document.querySelectorAll("[data-result-action]").forEach(button => button.disabled = true);
      const notice = document.querySelector(".dl-stale");
      if (notice) notice.hidden = false;
    };
    form.addEventListener("input", markDirty);
    form.addEventListener("change", markDirty);
  }
  document.querySelectorAll("[data-print]").forEach(button => {
    button.addEventListener("click", () => {
      if (!document.body.classList.contains("dl-form-dirty")) window.print();
    });
  });
  if (form) form.addEventListener("invalid", event => {
    const details = event.target.closest("details");
    if (details) details.open = true;
  }, true);
  const company = document.getElementById("ctx-company");
  const employee = document.getElementById("ctx-employee");
  // An explicit button remains available without JavaScript. Avoid reloading
  // a form with unsaved edits automatically.
  if (company && employee) {
    company.addEventListener("change", () => {
      employee.value = "";
      employee.querySelectorAll("option:not(:first-child)").forEach(option => option.remove());
      if (!formChanged) company.form.requestSubmit();
    });
    employee.addEventListener("change", () => {
      if (!formChanged) employee.form.requestSubmit();
    });
  }
  const error = document.getElementById("labor-error");
  if (error) {
    document.querySelectorAll(".dl-invalid").forEach(field => {
      const details = field.closest("details");
      if (details) details.open = true;
    });
    error.focus();
  } else if (form && result) {
    // On a phone the result is below the whole form. Bring it into view.
    result.focus({preventScroll: true});
    if (window.matchMedia("(max-width: 860px)").matches) result.scrollIntoView({block: "start"});
  }
})();

document.querySelectorAll("[data-payroll-edit]").forEach(form => {
  const card = form.closest("[data-payroll-person]");
  form.addEventListener("input", () => {
    const notice = card.querySelector("[data-payroll-dirty]");
    if (notice) notice.hidden = false;
    card.querySelector("[data-payroll-download]")?.setAttribute("aria-disabled","true");
    document.querySelector("[data-payroll-bulk-download]")?.setAttribute("aria-disabled","true");
    const bulkNotice = document.querySelector("[data-payroll-bulk-dirty]");
    if (bulkNotice) bulkNotice.hidden = false;
  });
});
document.querySelectorAll("[data-payroll-download], [data-payroll-bulk-download]").forEach(link => {
  link.addEventListener("click", event => {
    if (event.currentTarget.getAttribute("aria-disabled") === "true") event.preventDefault();
  });
});
