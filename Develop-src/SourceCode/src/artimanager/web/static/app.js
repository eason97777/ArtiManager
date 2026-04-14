document.addEventListener("DOMContentLoaded", () => {
  const forms = document.querySelectorAll("form[data-confirm]");
  for (const form of forms) {
    form.addEventListener("submit", (event) => {
      const message = form.getAttribute("data-confirm") || "Proceed?";
      if (!window.confirm(message)) {
        event.preventDefault();
      }
    });
  }
});
