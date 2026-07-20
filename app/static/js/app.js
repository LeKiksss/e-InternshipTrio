(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  async function api(url, options = {}) {
    const config = { credentials: "same-origin", ...options };
    config.headers = { ...(config.headers || {}) };
    if (window.PROTOTYPE?.csrf) config.headers["X-CSRFToken"] = window.PROTOTYPE.csrf;
    if (config.body && typeof config.body !== "string" && !(config.body instanceof FormData)) {
      config.headers["Content-Type"] = "application/json";
      config.body = JSON.stringify(config.body);
    }
    const response = await fetch(url, config);
    let data;
    try { data = await response.json(); } catch { data = { ok: false, message: "The app returned an unexpected response." }; }
    if (!response.ok) {
      const error = new Error(data.message || "Something went wrong. Please try again.");
      error.status = response.status;
      error.data = data;
      throw error;
    }
    return data;
  }

  function toast(message, type = "success") {
    const region = $(".toast-region");
    if (!region) return;
    const node = document.createElement("div");
    node.className = `toast ${type === "error" ? "error" : ""}`;
    node.textContent = message;
    region.append(node);
    setTimeout(() => node.remove(), 3900);
  }

  function openSheet(id) {
    const sheet = document.getElementById(id);
    if (!sheet) return;
    sheet.hidden = false;
    const focusTarget = $("button, input, select, textarea, summary", sheet);
    setTimeout(() => focusTarget?.focus(), 50);
  }

  function closeSheet(target) {
    const backdrop = typeof target === "string" ? document.getElementById(target) : target?.closest?.(".modal-backdrop");
    if (backdrop) backdrop.hidden = true;
  }

  let confirmCallback = null;
  function confirmAction({ title, message, action = "Continue", tone = "primary", onConfirm }) {
    $("#confirm-title").textContent = title;
    $("#confirm-message").textContent = message;
    const button = $("#confirm-action");
    button.textContent = action;
    button.className = `button button-wide ${tone === "danger" ? "button-danger-soft" : "button-primary"}`;
    confirmCallback = onConfirm;
    openSheet("confirm-sheet");
  }

  window.App = { $, $$, delay, api, toast, openSheet, closeSheet, confirmAction };

  document.addEventListener("DOMContentLoaded", () => {
    const time = $("#status-time");
    if (time) time.textContent = new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

    $$(".preview-mode").forEach((button) => button.addEventListener("click", () => {
      $$(".preview-mode").forEach((item) => item.classList.toggle("active", item === button));
      $(".desktop-stage").dataset.preview = button.dataset.mode;
      localStorage.setItem("prototype-preview", button.dataset.mode);
    }));
    const savedMode = localStorage.getItem("prototype-preview");
    if (savedMode && document.querySelector(`.preview-mode[data-mode="${savedMode}"]`)) document.querySelector(`.preview-mode[data-mode="${savedMode}"]`).click();

    $$('[data-open-sheet]').forEach((button) => button.addEventListener("click", () => openSheet(button.dataset.openSheet)));
    $$('[data-close-sheet], [data-close-modal]').forEach((button) => button.addEventListener("click", () => closeSheet(button)));
    $$(".modal-backdrop").forEach((backdrop) => backdrop.addEventListener("click", (event) => { if (event.target === backdrop) closeSheet(backdrop); }));
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        const open = $$(".modal-backdrop:not([hidden])").pop();
        if (open) closeSheet(open);
      }
    });

    $("#confirm-action")?.addEventListener("click", async () => {
      const callback = confirmCallback;
      confirmCallback = null;
      closeSheet("confirm-sheet");
      if (callback) await callback();
    });

    $$('[data-password-toggle]').forEach((button) => button.addEventListener("click", () => {
      const input = button.closest(".password-wrap").querySelector("input");
      const showing = input.type === "text";
      input.type = showing ? "password" : "text";
      button.textContent = showing ? "Show" : "Hide";
      button.setAttribute("aria-label", `${showing ? "Show" : "Hide"} password`);
    }));

    $("#demo-fill")?.addEventListener("click", () => {
      $("#identity").value = "demo@prototype.local";
      $("#password").value = "Demo123!";
      toast("Sign-in details filled. Select Sign in when ready.");
    });

    $$(".auth-card").forEach((form) => form.addEventListener("submit", () => {
      const button = $('input[type="submit"]', form);
      if (button) { button.value = button.dataset.loadingText || "Please wait…"; button.disabled = true; }
    }));

    const newPassword = $("#new-password");
    newPassword?.addEventListener("input", () => {
      const value = newPassword.value;
      const tests = [value.length >= 8, /[a-z]/.test(value), /[A-Z]/.test(value), /\d/.test(value)];
      const score = tests.filter(Boolean).length;
      const bar = $("#strength-bar");
      const label = $("#strength-label");
      bar.style.width = `${score * 25}%`;
      bar.style.background = score < 3 ? "#c62828" : score === 3 ? "#d97706" : "#198754";
      label.textContent = ["Use 8+ characters with uppercase, lowercase, and a number.", "Keep going", "Getting stronger", "Almost there", "Strong password"][score];
    });

    $("[data-open-forgot]")?.addEventListener("click", () => { $("#forgot-modal").hidden = false; });
    $("#forgot-form")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const result = $("#forgot-result");
      try {
        const body = new URLSearchParams(new FormData(event.currentTarget));
        const response = await fetch("/auth/forgot", { method: "POST", body, headers: { "X-CSRFToken": $("meta[name='csrf-token']")?.content || "" } });
        const data = await response.json();
        result.hidden = false;
        result.classList.toggle("error", !response.ok);
        result.textContent = data.message;
      } catch { result.hidden = false; result.classList.add("error"); result.textContent = "The request could not be completed."; }
    });

    $("#refresh-account")?.addEventListener("click", async (event) => {
      const button = event.currentTarget;
      button.textContent = "Refreshing…";
      const card = button.closest(".account-health");
      card.style.opacity = ".72";
      await delay(850);
      card.style.opacity = "1";
      button.textContent = "↻ Refresh";
      $(".last-updated", card).textContent = `Updated ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
      toast("Account status refreshed.");
    });

    $$("[data-alert]").forEach((button) => button.addEventListener("click", () => {
      const [title, copy, category] = button.dataset.alert.split("|");
      $("#alert-title").textContent = title; $("#alert-copy").textContent = copy; $("#alert-category").textContent = category;
      openSheet("alert-sheet");
    }));

    $("#mark-all-read")?.addEventListener("click", () => {
      $$(".notification-row").forEach((item) => item.classList.remove("unread"));
      $(".notification-dot")?.remove();
      toast("All notifications marked as read.");
    });
    $$("[data-demo-message]").forEach((button) => button.addEventListener("click", () => toast(button.dataset.demoMessage)));
    $("[data-start-tour]")?.addEventListener("click", () => {
      closeSheet("help-sheet");
      toast("Tour 1 of 3: Start with the three equal smart-assistance cards.");
      setTimeout(() => toast("Tour 2 of 3: Use the bottom bar to move between workflows."), 1500);
      setTimeout(() => toast("Tour 3 of 3: UI states are available from the desktop gear."), 3000);
    });

    $("#edit-profile")?.addEventListener("click", () => openSheet("profile-sheet"));
    $("#reveal-phone")?.addEventListener("click", (event) => {
      const hidden = $("#masked-phone").textContent.includes("•");
      $("#masked-phone").textContent = hidden ? event.currentTarget.dataset.phone : "+971 50 ••• 4567";
      event.currentTarget.textContent = hidden ? "Hide" : "Reveal";
    });
    $("#profile-form")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      try {
        const data = await api("/api/profile", { method: "POST", body: Object.fromEntries(new FormData(form)) });
        $("#profile-name-display").textContent = $("#profile-name").value;
        $("#notification-pref-display").textContent = $("#profile-notifications").value;
        $("#contact-pref-display").textContent = $("#profile-contact").value;
        $("#reveal-phone").dataset.phone = $("#profile-phone").value;
        $("#masked-phone").textContent = "+971 50 ••• " + $("#profile-phone").value.slice(-4);
        closeSheet("profile-sheet"); toast(data.message);
      } catch (error) { toast(error.message, "error"); }
    });
    $("#logout-button")?.addEventListener("click", () => confirmAction({ title: "Log out?", message: "You’ll return to the sign-in screen.", action: "Log out", tone: "danger", onConfirm: () => $("#logout-form").submit() }));

    let mapScale = 1;
    $$("[data-map-layer]").forEach((input) => input.addEventListener("change", () => {
      const group = $(`[data-layer-group="${input.dataset.mapLayer}"]`);
      if (group) group.style.display = input.checked ? "" : "none";
    }));
    $$("[data-zoom]").forEach((button) => button.addEventListener("click", () => {
      mapScale = Math.max(1, Math.min(2.2, mapScale + (button.dataset.zoom === "in" ? .2 : -.2)));
      $("#map-svg").style.transform = `scale(${mapScale})`;
    }));
    $$('[data-open-map]').forEach((button) => button.addEventListener("click", () => openSheet("map-sheet")));
  });
})();
