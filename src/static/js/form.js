(() => {
  "use strict";

  const slider = document.querySelector("#sanity");
  const output = document.querySelector("#sanity-value");
  if (slider && output) {
    slider.addEventListener("input", () => {
      output.value = slider.value;
      output.textContent = slider.value;
    });
  }

  for (const form of document.querySelectorAll("form[data-confirm]")) {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm || "Continue?")) {
        event.preventDefault();
      }
    });
  }
})();
