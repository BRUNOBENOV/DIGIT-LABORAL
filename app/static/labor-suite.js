(() => {
  "use strict";
  const form = document.getElementById("labor-form");
  const result = document.getElementById("labor-result");
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
  if (company) company.addEventListener("change", () => {
    const employee = document.getElementById("ctx-employee");
    employee.value = "";
    employee.querySelectorAll("option:not(:first-child)").forEach(option => option.remove());
  });
  const error = document.getElementById("labor-error");
  if (error) {
    document.querySelectorAll(".dl-invalid").forEach(field => {
      const details = field.closest("details");
      if (details) details.open = true;
    });
    error.focus();
  }
})();

document.querySelectorAll("[data-payroll-edit]").forEach(form => {
  const card = form.closest("[data-payroll-person]");
  form.addEventListener("input", () => {
    card.querySelector("[data-payroll-dirty]").hidden = false;
    card.querySelector("[data-payroll-download]").setAttribute("aria-disabled","true");
  });
  card.querySelector("[data-payroll-download]").addEventListener("click", event => {
    if (event.currentTarget.getAttribute("aria-disabled") === "true") event.preventDefault();
  });
});
