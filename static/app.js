// Loading feedback for slow, server-rendered requests (e.g. 알림 미리보기).
// A form or submit button marked with `data-loading` shows a spinner on the
// pressed button plus a full-page veil, and ignores repeat submits.
(() => {
  const veil = () => document.getElementById("loading-veil");
  let busy = false;

  function showLoading(button) {
    busy = true;
    if (button) {
      button.setAttribute("aria-busy", "true");
      const spinner = document.createElement("span");
      spinner.className = "spinner";
      spinner.setAttribute("aria-hidden", "true");
      button.prepend(spinner);
    }
    const element = veil();
    if (element) {
      element.hidden = false;
      requestAnimationFrame(() => element.classList.add("is-visible"));
    }
  }

  function reset() {
    busy = false;
    document.querySelectorAll('[aria-busy="true"]').forEach((button) => {
      button.removeAttribute("aria-busy");
      button.querySelectorAll(".spinner").forEach((spinner) => spinner.remove());
    });
    const element = veil();
    if (element) {
      element.classList.remove("is-visible");
      element.hidden = true;
    }
  }

  document.addEventListener("submit", (event) => {
    const submitter = event.submitter;
    const wantsLoading =
      event.target.hasAttribute("data-loading") ||
      (submitter && submitter.hasAttribute("data-loading"));
    if (!wantsLoading) {
      return;
    }
    if (busy) {
      event.preventDefault();
      return;
    }
    // Keep the submitter enabled so its formaction still applies.
    showLoading(submitter || event.target.querySelector('[type="submit"]'));
  });

  // Coming back via the browser's back button restores a frozen page.
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) {
      reset();
    }
  });
})();
