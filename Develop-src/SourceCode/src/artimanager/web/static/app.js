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

  const copyButtons = document.querySelectorAll("button[data-copy-text]");
  for (const button of copyButtons) {
    const originalText = button.textContent;
    button.addEventListener("click", async () => {
      const text = button.getAttribute("data-copy-text") || "";
      if (!navigator.clipboard) {
        return;
      }
      try {
        await navigator.clipboard.writeText(text);
        button.textContent = "Copied";
        window.setTimeout(() => {
          button.textContent = originalText;
        }, 1200);
      } catch {
        button.textContent = "Copy failed";
        window.setTimeout(() => {
          button.textContent = originalText;
        }, 1600);
      }
    });
  }
});
