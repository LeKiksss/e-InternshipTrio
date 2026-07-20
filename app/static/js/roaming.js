(() => {
  "use strict";
  document.addEventListener("DOMContentLoaded", async () => {
    if (!document.querySelector("#roaming-intro")) return;
    const { $, $$, delay, api, toast, confirmAction } = window.App;
    const intro = $("#roaming-intro"), planner = $("#roaming-planner"), loading = $("#roaming-loading"), result = $("#roaming-result"), empty = $("#roaming-empty");
    const tomorrow = new Date(); tomorrow.setDate(tomorrow.getDate() + 1); const minDate = tomorrow.toISOString().slice(0, 10);
    $("#trip-start").min = minDate; $("#trip-end").min = minDate;

    const controller = window.WorkflowState.create({
      name: "roaming",
      initialState: {
        destination: "", start: "", end: "", duration: 0, usage: null, basePackage: null,
        currentPackage: null, chat: [], rejectedIds: [], savedId: null, completed: false,
        viewingSaved: false, carrierAcknowledged: false,
      },
      render(view, state) {
        intro.hidden = view !== "landing";
        planner.hidden = view === "landing";
        $$("[data-roaming-step]").forEach((panel) => { const active = panel.dataset.roamingStep === view.replace("step", ""); panel.hidden = !active; panel.classList.toggle("active", active); });
        loading.hidden = view !== "loading";
        result.hidden = view !== "result";
        empty.hidden = view !== "empty";
        $$("[data-step-dot]").forEach((dot) => { const current = view === "result" ? 4 : Number(view.replace("step", "")) || 0; const number = Number(dot.dataset.stepDot); dot.classList.toggle("active", number === current); dot.classList.toggle("done", number < current); });
        restoreInputs();
        if (state.currentPackage) { renderUsageRecommendation(); renderFinal(); }
        renderChat(); renderRecent();
        $("#app-scroll").scrollTop = 0;
      },
    });
    await controller.restore();
    await loadSavedRecommendations();

    function restoreInputs() {
      const state = controller.state;
      $$("#country-list button[data-country]").forEach((button) => button.classList.toggle("selected", button.dataset.country === state.destination));
      $("#destination-next").disabled = !state.destination;
      $("#selected-country").textContent = state.destination || "Choose a destination";
      const selectedButton = $$("#country-list button[data-country]").find((button) => button.dataset.country === state.destination);
      $("#selected-flag").textContent = selectedButton?.dataset.flag || "🌍";
      $("#trip-start").value = state.start || ""; $("#trip-end").value = state.end || "";
      $("#trip-end").min = state.start || minDate;
      $("#trip-duration").hidden = !state.duration; $("#trip-days").textContent = state.duration || 0;
      $("#dates-next").disabled = !state.duration;
      const save = $("#save-recommendation"); save.textContent = state.savedId ? "Saved" : "Save Selection"; save.disabled = Boolean(state.savedId);
      renderAcknowledgement();
    }
    function selectCountry(country) {
      const changed = controller.state.destination && controller.state.destination !== country;
      controller.update({ destination: country, ...(changed ? { usage: null, basePackage: null, currentPackage: null, chat: [], rejectedIds: [], savedId: null, completed: false, carrierAcknowledged: false } : {}) });
      restoreInputs();
    }
    function renderCountryCount(count) {
      $("#country-count").textContent = `${count} ${count === 1 ? "country" : "countries"}`;
      $("#country-empty").hidden = count > 0;
    }
    function validateDates({ update = true } = {}) {
      const startValue = $("#trip-start").value, endValue = $("#trip-end").value, error = $("#date-error");
      if (!startValue || !endValue) { $("#dates-next").disabled = true; $("#trip-duration").hidden = true; return false; }
      const start = new Date(`${startValue}T12:00:00`), end = new Date(`${endValue}T12:00:00`), today = new Date(); today.setHours(0,0,0,0);
      if (start < today || end < start) { error.hidden = false; error.textContent = end < start ? "Return date must be on or after the departure date." : "Choose travel dates in the future."; $("#dates-next").disabled = true; $("#trip-duration").hidden = true; return false; }
      const duration = Math.round((end - start) / 86400000) + 1;
      const changed = controller.state.start !== startValue || controller.state.end !== endValue;
      if (update) controller.update({ start: startValue, end: endValue, duration, ...(changed ? { usage: null, basePackage: null, currentPackage: null, chat: [], rejectedIds: [], savedId: null, completed: false, carrierAcknowledged: false } : {}) });
      $("#trip-days").textContent = duration; $("#trip-duration").hidden = false; error.hidden = true; $("#dates-next").disabled = false; return true;
    }

    async function loadCurrentUsage() {
      if (!controller.state.destination || !validateDates()) return;
      controller.go("loading");
      const phases = ["Checking destination coverage", "Scaling current usage", "Matching trip duration", "Preparing recommendation"];
      for (const phase of phases) { $("#roaming-phase").textContent = phase; await delay(window.PROTOTYPE?.testing ? 25 : 360); }
      try {
        const response = await api("/api/roaming/current-usage", { method: "POST", body: { destination: controller.state.destination, start_date: controller.state.start, end_date: controller.state.end } });
        controller.update({ duration: response.trip_days, usage: response.usage, basePackage: response.package, currentPackage: response.package, chat: [], rejectedIds: [], savedId: null, viewingSaved: false, carrierAcknowledged: false });
        controller.go("step3");
      } catch (error) { controller.go("step2"); toast(error.message, "error"); }
    }

    function renderUsageRecommendation() {
      const pkg = controller.state.currentPackage, usage = controller.state.usage;
      if (!pkg) return;
      $("#usage-package-name").textContent = pkg.name; $("#usage-package-explanation").textContent = pkg.why;
      $("#usage-package-price").textContent = Number(pkg.price).toFixed(0); $("#usage-package-destination").textContent = controller.state.destination;
      $("#usage-package-duration").textContent = controller.state.duration; $("#usage-package-validity").textContent = pkg.validity_days;
      $("#usage-package-data").textContent = pkg.data_allowance; $("#usage-package-local").textContent = `${pkg.local_minutes} min`;
      $("#usage-package-international").textContent = `${pkg.international_minutes} min`; $("#usage-package-sms").textContent = pkg.sms_allowance;
      if (usage) {
        $("#usage-average-days").textContent = usage.trip_days; $("#average-data").textContent = `${usage.data_gb.toFixed(1)} GB`;
        $("#average-local").textContent = `${usage.local_minutes} min`; $("#average-international").textContent = `${usage.international_minutes} min`; $("#average-sms").textContent = usage.sms;
      }
    }
    function renderFinal() {
      const pkg = controller.state.currentPackage; if (!pkg) return;
      $("#package-name").textContent = pkg.name; $("#package-price").textContent = Number(pkg.price).toFixed(0); $("#package-validity").textContent = `${pkg.validity_days} days`;
      $("#package-data").textContent = pkg.data_allowance; $("#package-voice").textContent = `${pkg.local_minutes} min`; $("#package-international").textContent = `${pkg.international_minutes} min`; $("#package-sms").textContent = pkg.sms_allowance;
      const network = pkg.preferred_network || "Preferred Partner 1";
      $("#package-destination").textContent = controller.state.destination; $("#package-trip-duration").textContent = `${controller.state.duration} days`; $("#package-network").textContent = network; $("#package-why").textContent = pkg.why;
      $("#carrier-note-network").textContent = network; $("#carrier-ack-network-label").textContent = network;
      $("#package-updated").textContent = `Prototype catalogue updated ${pkg.updated_at || "today"}`; $("#activation-code").textContent = pkg.activation_code; $("#activation-instructions").textContent = pkg.activation_instructions;
      $("#final-trip-dates").textContent = `${controller.state.destination} · ${formatDate(controller.state.start)} to ${formatDate(controller.state.end)} · ${controller.state.duration} days`;
      renderAcknowledgement();
    }
    function renderAcknowledgement() {
      const acknowledged = Boolean(controller.state.carrierAcknowledged);
      $("#carrier-acknowledgement").checked = acknowledged;
      $("#activation-card").classList.toggle("locked", !acknowledged);
      $("#activation-code").setAttribute("aria-hidden", String(!acknowledged));
      $("#copy-code").disabled = !acknowledged;
      $("#open-dialer").disabled = !acknowledged;
      $("#roaming-done").disabled = !acknowledged;
    }
    function renderChat() {
      const container = $("#roaming-chat-messages"); container.innerHTML = "";
      controller.state.chat.forEach((message) => { const node = document.createElement("div"); node.className = `message ${message.who}`; node.innerHTML = message.who === "assistant" ? '<span class="assistant-avatar">e&amp;</span><div><p></p></div>' : '<div><p></p></div>'; $("p", node).textContent = message.text; container.append(node); });
    }
    function renderRecent() {
      const pkg = controller.state.currentPackage;
      if (!controller.state.completed || !pkg) return;
      $("#recent-roaming-title").textContent = `${controller.state.destination} · ${controller.state.duration} days`;
      $("#recent-roaming-meta").textContent = `${pkg.name} · AED ${Number(pkg.price).toFixed(0)}`;
      $("#view-recent-roaming").disabled = false;
    }
    function formatDate(value) { if (!value) return ""; return new Date(`${value}T12:00:00`).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" }); }

    async function submitAdjustment(text) {
      const value = (text || $("#roaming-adjustment").value).trim();
      if (!value) { toast("Enter an adjustment first.", "error"); return; }
      $("#roaming-adjustment").value = "";
      const chat = [...controller.state.chat, { who: "user", text: value }, { who: "assistant", text: "Reviewing that adjustment…" }]; controller.update({ chat }); renderChat();
      await delay(window.PROTOTYPE?.testing ? 25 : 500);
      try {
        const response = await api("/api/roaming/adjust", { method: "POST", body: { destination: controller.state.destination, trip_days: controller.state.duration, message: value } });
        const updatedChat = [...controller.state.chat.slice(0, -1), { who: "assistant", text: response.package.change_summary }];
        const rejected = controller.state.currentPackage ? [...controller.state.rejectedIds, controller.state.currentPackage.id] : controller.state.rejectedIds;
        controller.update({ currentPackage: response.package, chat: updatedChat, rejectedIds: rejected, savedId: null, completed: false, carrierAcknowledged: false }); renderUsageRecommendation(); renderChat(); toast("Recommendation updated.");
      } catch (error) {
        const updatedChat = [...controller.state.chat.slice(0, -1), { who: "assistant", text: error.message }]; controller.update({ chat: updatedChat }); renderChat(); toast(error.message, "error");
      }
    }

    async function saveSelection() {
      const pkg = controller.state.currentPackage; if (!pkg) return;
      try {
        const response = await api("/api/roaming/saved", { method: "POST", body: {
          package_id: pkg.id, package_name: pkg.name, recommendation_name: pkg.recommendation_name || "Roam Like Home", destination: controller.state.destination,
          start_date: controller.state.start, end_date: controller.state.end, trip_days: controller.state.duration,
          price: pkg.price, currency: pkg.currency || "AED", validity_days: pkg.validity_days,
          data_allowance: pkg.data_allowance, local_minutes: pkg.local_minutes,
          international_minutes: pkg.international_minutes, sms_allowance: pkg.sms_allowance,
          preferred_network: pkg.preferred_network, activation_code: pkg.activation_code,
          activation_instructions: pkg.activation_instructions, explanation: pkg.why,
        }});
        controller.update({ savedId: response.recommendation.saved_id });
        $("#save-recommendation").textContent = "Saved"; $("#save-recommendation").disabled = true;
        renderSavedRecommendations(response.recommendations); toast(response.duplicate ? "Recommendation already saved." : "Recommendation saved.");
      } catch (error) { toast(error.message, "error"); }
    }
    async function loadSavedRecommendations() {
      try { const response = await api("/api/roaming/saved"); renderSavedRecommendations(response.recommendations); } catch (error) { toast(error.message, "error"); }
    }
    function renderSavedRecommendations(recommendations) {
      const section = $("#saved-recommendations-section"), list = $("#saved-recommendations-list"); list.innerHTML = ""; section.hidden = !recommendations.length;
      recommendations.forEach((saved) => {
        const card = document.createElement("article"); card.className = "card saved-roaming-card"; card.dataset.savedId = saved.saved_id;
        card.innerHTML = `<div><span class="demo-tag">SAVED</span><h3>${escapeHTML(saved.package_name)}</h3><p>${escapeHTML(saved.destination)} · ${escapeHTML(formatDate(saved.start_date))} to ${escapeHTML(formatDate(saved.end_date))}</p><div class="saved-summary"><b>AED ${Number(saved.price).toFixed(0)}</b><span>${escapeHTML(saved.data_allowance)} · ${saved.local_minutes} local min</span></div></div><div class="button-row"><button class="button button-secondary" type="button" data-view-saved>View Details</button><button class="button button-danger-soft" type="button" data-remove-saved>Remove</button></div>`;
        card._recommendation = saved; list.append(card);
      });
    }
    function escapeHTML(value) { const node = document.createElement("div"); node.textContent = value ?? ""; return node.innerHTML; }
    function viewSaved(saved) {
      controller.update({ destination: saved.destination, start: saved.start_date, end: saved.end_date, duration: Number(saved.trip_days), currentPackage: {
        id: saved.package_id, name: saved.package_name, recommendation_name: saved.recommendation_name || "Roam Like Home", price: saved.price, currency: saved.currency,
        validity_days: saved.validity_days, data_allowance: saved.data_allowance, local_minutes: saved.local_minutes,
        international_minutes: saved.international_minutes, sms_allowance: saved.sms_allowance,
        preferred_network: saved.preferred_network, activation_code: saved.activation_code,
        activation_instructions: saved.activation_instructions, why: saved.explanation, updated_at: saved.saved_at,
      }, savedId: saved.saved_id, viewingSaved: true, completed: true, carrierAcknowledged: false }); controller.go("result");
    }

    $("#start-roaming").addEventListener("click", async () => { if (controller.state.completed) await controller.reset(); controller.go("step1"); });
    $("#roaming-step1-back").addEventListener("click", () => controller.go("landing"));
    $$('[data-roaming-exit]').forEach((button) => button.addEventListener("click", () => controller.go("landing")));
    $$('[data-edit-roaming]').forEach((button) => button.addEventListener("click", () => controller.go(`step${button.dataset.editRoaming}`)));
    $("#country-list").addEventListener("click", (event) => { const button = event.target.closest("button[data-country]"); if (button) selectCountry(button.dataset.country); });
    $("#country-search").addEventListener("input", (event) => {
      const query = event.target.value.trim().toLowerCase();
      let visibleCount = 0;
      $$("[data-country-group]").forEach((group) => {
        const buttons = $$("button[data-country]", group);
        buttons.forEach((button) => button.hidden = !button.dataset.country.toLowerCase().startsWith(query));
        const visibleButtons = buttons.filter((button) => !button.hidden);
        visibleCount += visibleButtons.length;
        group.hidden = visibleButtons.length === 0;
      });
      renderCountryCount(visibleCount);
    });
    $("#destination-next").addEventListener("click", () => { if (controller.state.destination) controller.go("step2"); });
    $("#trip-start").addEventListener("change", () => { $("#trip-end").min = $("#trip-start").value || minDate; validateDates(); }); $("#trip-end").addEventListener("change", () => validateDates());
    $("#dates-next").addEventListener("click", loadCurrentUsage);
    $("#usage-more-details").addEventListener("click", (event) => { const open = $("#usage-details-panel").classList.toggle("open"); event.currentTarget.setAttribute("aria-expanded", String(open)); event.currentTarget.firstChild.textContent = open ? "Hide Details " : "More Details "; });
    $(".adjustment-chips").addEventListener("click", (event) => { const button = event.target.closest("button"); if (button) submitAdjustment(button.textContent); });
    $("#send-roaming-adjustment").addEventListener("click", () => submitAdjustment());
    $("#roaming-adjustment").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submitAdjustment(); } });
    $("#carrier-acknowledgement").addEventListener("change", (event) => {
      controller.update({ carrierAcknowledged: event.currentTarget.checked });
      renderAcknowledgement();
      if (event.currentTarget.checked) toast("Carrier note acknowledged. Activation details are now available.");
    });
    $("#continue-roaming-plan").addEventListener("click", () => { controller.update({ completed: true, viewingSaved: false }); controller.go("result"); });
    $("#roaming-result-back").addEventListener("click", () => controller.go(controller.state.viewingSaved ? "landing" : "step3"));
    $("#save-recommendation").addEventListener("click", saveSelection);
    $("#roaming-done").addEventListener("click", () => { if (!controller.state.carrierAcknowledged) { toast("Acknowledge the preferred-carrier note before finishing.", "error"); return; } controller.update({ completed: true }); controller.go("landing"); });
    $("#start-over-roaming").addEventListener("click", async () => { await controller.reset(); $("#country-search").value = ""; $$("[data-country-group]").forEach((group) => group.hidden = false); const countryButtons = $$("#country-list button[data-country]"); countryButtons.forEach((button) => { button.hidden = false; button.classList.remove("selected"); }); renderCountryCount(countryButtons.length); controller.go("step1", { replace: true }); });
    $("#view-recent-roaming").addEventListener("click", () => { if (controller.state.currentPackage) controller.go("result"); });
    $("#saved-recommendations-list").addEventListener("click", (event) => { const card = event.target.closest(".saved-roaming-card"); if (!card) return; if (event.target.closest("[data-view-saved]")) viewSaved(card._recommendation); if (event.target.closest("[data-remove-saved]")) confirmAction({ title: "Remove saved recommendation?", message: "This removes the session-only saved card. Your completed trip history is unchanged.", action: "Remove", tone: "danger", onConfirm: async () => { try { const response = await api(`/api/roaming/saved/${card.dataset.savedId}`, { method: "DELETE" }); renderSavedRecommendations(response.recommendations); if (controller.state.savedId === card.dataset.savedId) controller.update({ savedId: null }); toast("Saved recommendation removed."); } catch (error) { toast(error.message, "error"); } } }); });
    $("#copy-code").addEventListener("click", async (event) => {
      if (!controller.state.carrierAcknowledged) { toast("Acknowledge the preferred-carrier note before copying the code.", "error"); return; }
      const button = event.currentTarget, code = $("#activation-code").textContent;
      try { await navigator.clipboard.writeText(code); } catch {
        const area = document.createElement("textarea"); area.value = code; document.body.append(area); area.select(); document.execCommand("copy"); area.remove();
      }
      button.textContent = "Copied"; toast("Fictional activation code copied.");
      setTimeout(() => button.textContent = "Copy code", 1500);
    });
    $("#open-dialer").addEventListener("click", () => { if (!controller.state.carrierAcknowledged) { toast("Acknowledge the preferred-carrier note before opening the dialer.", "error"); return; } confirmAction({ title: "Open your dialer?", message: "The fictional code will be placed in the dialer where supported. No package will be activated automatically.", action: "Open dialer", onConfirm: () => { window.location.href = `tel:${$("#activation-code").textContent.replace(/#/g, "%23")}`; } }); });
  });
})();
