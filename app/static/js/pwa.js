(() => {
  "use strict";

  const INSTALL_DISMISSAL_KEY = "ecare-ios-install-dismissed-v1";
  const UPDATE_RELOAD_KEY = "ecare-pwa-update-reload";
  const EDITABLE_SELECTOR = "input:not([type='checkbox']):not([type='radio']), select, textarea, [contenteditable='true']";
  const standaloneQuery = window.matchMedia("(display-mode: standalone)");
  let waitingWorker = null;
  let refreshRequested = false;
  let stableViewportHeight = 0;
  let focusAlignmentTimer = null;

  function isStandalone() {
    return standaloneQuery.matches || window.navigator.standalone === true;
  }

  function syncStandaloneClass() {
    document.documentElement.classList.toggle("is-standalone", isStandalone());
  }

  function isIphoneSafari() {
    const userAgent = navigator.userAgent;
    const iphone = /iPhone|iPod/i.test(userAgent);
    const safari = /Safari/i.test(userAgent) && !/CriOS|FxiOS|EdgiOS|OPiOS/i.test(userAgent);
    return iphone && safari && navigator.vendor === "Apple Computer, Inc.";
  }

  function isMobileLayout() {
    return window.matchMedia("(max-width: 760px)").matches;
  }

  function syncInstallGuidance() {
    const prompt = document.querySelector("[data-ios-install-prompt]");
    if (!prompt) return;
    let dismissed = false;
    try { dismissed = localStorage.getItem(INSTALL_DISMISSAL_KEY) === "1"; } catch { /* Storage may be unavailable. */ }
    prompt.hidden = !(isIphoneSafari() && isMobileLayout() && !isStandalone() && !dismissed);
  }

  function dismissInstallGuidance() {
    try { localStorage.setItem(INSTALL_DISMISSAL_KEY, "1"); } catch { /* Dismiss for this view only. */ }
    document.querySelector("[data-ios-install-prompt]")?.setAttribute("hidden", "");
    document.querySelector("#ios-install-sheet")?.setAttribute("hidden", "");
  }

  function showUpdate(worker) {
    waitingWorker = worker;
    const notice = document.querySelector("[data-pwa-update]");
    if (notice) notice.hidden = false;
  }

  function watchRegistration(registration) {
    if (registration.waiting && navigator.serviceWorker.controller) showUpdate(registration.waiting);
    registration.addEventListener("updatefound", () => {
      const installing = registration.installing;
      if (!installing) return;
      installing.addEventListener("statechange", () => {
        if (installing.state === "installed" && navigator.serviceWorker.controller) {
          showUpdate(installing);
        }
      });
    });
  }

  async function registerServiceWorker() {
    if (!("serviceWorker" in navigator)) return;
    try {
      const registration = await navigator.serviceWorker.register("/service-worker.js", { scope: "/" });
      watchRegistration(registration);
    } catch (error) {
      console.warn("Service worker registration was not available.", error);
    }
  }

  function isEditable(element) {
    return Boolean(element?.matches?.(EDITABLE_SELECTOR) && !element.disabled && !element.readOnly);
  }

  function alignFocusedControl(control) {
    if (!isEditable(control)) return;
    const target = control.closest(".adjustment-chat") || control;
    const behavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
    target.scrollIntoView({ block: target === control ? "nearest" : "start", inline: "nearest", behavior });
  }

  function scheduleFocusAlignment(control) {
    clearTimeout(focusAlignmentTimer);
    focusAlignmentTimer = setTimeout(() => alignFocusedControl(control), 140);
  }

  function syncVisualViewport({ resetHeight = false } = {}) {
    const visualHeight = Math.round(window.visualViewport?.height || window.innerHeight);
    const active = document.activeElement;
    const editing = isMobileLayout() && isEditable(active);
    const candidateHeight = Math.round(Math.max(window.innerHeight, visualHeight));

    if (resetHeight || !stableViewportHeight) stableViewportHeight = candidateHeight;
    else if (!editing && candidateHeight >= stableViewportHeight * 0.75) stableViewportHeight = candidateHeight;

    document.documentElement.style.setProperty("--app-viewport-height", `${stableViewportHeight}px`);
    document.documentElement.style.setProperty("--visual-viewport-height", `${visualHeight}px`);
    document.documentElement.classList.toggle("keyboard-open", editing);
    if (editing) scheduleFocusAlignment(active);
  }

  document.addEventListener("DOMContentLoaded", () => {
    syncStandaloneClass();
    syncInstallGuidance();
    syncVisualViewport();
    void registerServiceWorker();

    document.querySelector("[data-ios-install-open]")?.addEventListener("click", () => {
      document.querySelector("#ios-install-sheet").hidden = false;
    });
    document.querySelectorAll("[data-ios-install-dismiss]").forEach((button) => {
      button.addEventListener("click", dismissInstallGuidance);
    });
    document.querySelector("[data-ios-install-close]")?.addEventListener("click", () => {
      document.querySelector("#ios-install-sheet").hidden = true;
    });
    document.querySelector("#ios-install-sheet")?.addEventListener("click", (event) => {
      if (event.target === event.currentTarget) event.currentTarget.hidden = true;
    });
    document.querySelector("[data-pwa-refresh]")?.addEventListener("click", () => {
      if (!waitingWorker) return;
      refreshRequested = true;
      sessionStorage.setItem(UPDATE_RELOAD_KEY, "1");
      waitingWorker.postMessage({ type: "SKIP_WAITING" });
    });
    document.querySelector("[data-pwa-update-later]")?.addEventListener("click", () => {
      document.querySelector("[data-pwa-update]").hidden = true;
    });
  });

  standaloneQuery.addEventListener?.("change", () => {
    syncStandaloneClass();
    syncInstallGuidance();
  });
  window.addEventListener("resize", () => {
    syncVisualViewport();
    syncInstallGuidance();
  });
  window.visualViewport?.addEventListener("resize", () => {
    syncVisualViewport();
  });
  window.addEventListener("orientationchange", () => {
    setTimeout(() => syncVisualViewport({ resetHeight: true }), 250);
  });
  document.addEventListener("focusin", (event) => {
    if (!isEditable(event.target) || !isMobileLayout()) return;
    syncVisualViewport();
    scheduleFocusAlignment(event.target);
  });
  document.addEventListener("focusout", () => {
    setTimeout(() => {
      if (isEditable(document.activeElement)) return;
      document.documentElement.classList.remove("keyboard-open");
      syncVisualViewport();
    }, 180);
  });
  navigator.serviceWorker?.addEventListener("controllerchange", () => {
    if (!refreshRequested || sessionStorage.getItem(UPDATE_RELOAD_KEY) !== "1") return;
    refreshRequested = false;
    sessionStorage.removeItem(UPDATE_RELOAD_KEY);
    window.location.replace(window.location.href);
  });
})();
