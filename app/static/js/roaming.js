(() => {
  "use strict";
  document.addEventListener("DOMContentLoaded", async () => {
    if (!window.App || !window.WorkflowState || !document.querySelector("#roaming-planner")) return;
    const { $, $$, api, delay, toast, confirmAction } = window.App;
    const intro = $("#roaming-intro"), planner = $("#roaming-planner"), loading = $("#roaming-loading"), result = $("#roaming-result"), empty = $("#roaming-empty");
    const tomorrow = new Date(); tomorrow.setDate(tomorrow.getDate() + 1); const minDate = tomorrow.toISOString().slice(0, 10);
    $("#trip-start").min = minDate; $("#trip-end").min = minDate;

    const controller = window.WorkflowState.create({
      name: "roaming",
      initialState: {
        destination: "", start: "", end: "", duration: 0,
        recommendationId: null, recommendation: null, chat: [], savedId: null,
        completed: false, viewingSaved: false, carrierAcknowledged: false,
      },
      serializeState(state) {
        return {
          destination: state.destination, start: state.start, end: state.end,
          duration: state.duration, recommendationId: state.recommendationId,
          savedId: state.savedId, completed: state.completed,
          viewingSaved: state.viewingSaved, carrierAcknowledged: false,
        };
      },
      render(view, state) {
        intro.hidden = view !== "landing";
        planner.hidden = view === "landing";
        $$('[data-roaming-step]').forEach((panel) => {
          const active = panel.dataset.roamingStep === view.replace("step", "");
          panel.hidden = !active; panel.classList.toggle("active", active);
        });
        loading.hidden = view !== "loading";
        result.hidden = view !== "result";
        empty.hidden = view !== "empty";
        const stepNumber = view === "result" ? 4 : Number(view.replace("step", "")) || 0;
        $$('[data-step-dot]').forEach((dot) => dot.classList.toggle("active", Number(dot.dataset.stepDot) <= stepNumber));
        if (view === "step3") { renderRecommendation(); renderChat(); }
        if (view === "result") renderFinal();
        if (view === "landing") { renderRecent(); void loadSavedRecommendations(); }
        restoreInputs();
        $("#app-scroll").scrollTop = 0;
      },
    });

    function cleanRecommendation(response) {
      const recommendation = { ...response };
      delete recommendation.ok; delete recommendation.response_type; delete recommendation.history_action;
      return recommendation;
    }
    function resetRecommendationState() {
      return {
        recommendationId: null, recommendation: null, chat: [], savedId: null,
        completed: false, viewingSaved: false, carrierAcknowledged: false,
      };
    }
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
      controller.update({ destination: country, ...(changed ? resetRecommendationState() : {}) });
      restoreInputs();
    }
    function renderCountryCount(count) {
      $("#country-count").textContent = `${count} ${count === 1 ? "country" : "countries"}`;
      $("#country-empty").hidden = count > 0;
    }
    function validateDates({ update = true } = {}) {
      const startValue = $("#trip-start").value, endValue = $("#trip-end").value, error = $("#date-error");
      if (!startValue || !endValue) { $("#dates-next").disabled = true; $("#trip-duration").hidden = true; return false; }
      const start = new Date(`${startValue}T12:00:00`), end = new Date(`${endValue}T12:00:00`), today = new Date(); today.setHours(0, 0, 0, 0);
      if (start < today || end < start) { error.hidden = false; error.textContent = end < start ? "Return date must be on or after the departure date." : "Choose travel dates in the future."; $("#dates-next").disabled = true; $("#trip-duration").hidden = true; return false; }
      const duration = Math.round((end - start) / 86400000) + 1;
      const changed = controller.state.start !== startValue || controller.state.end !== endValue;
      if (update) controller.update({ start: startValue, end: endValue, duration, ...(changed ? resetRecommendationState() : {}) });
      $("#trip-days").textContent = duration; $("#trip-duration").hidden = false; error.hidden = true; $("#dates-next").disabled = false; return true;
    }

    async function loadRecommendation() {
      if (!controller.state.destination || !validateDates()) return;
      controller.go("loading");
      const phases = ["Checking destination coverage", "Analysing recent usage", "Comparing all active packages", "Validating the recommendation"];
      for (const phase of phases) { $("#roaming-phase").textContent = phase; await delay(window.PROTOTYPE?.testing ? 20 : 280); }
      try {
        const response = await api("/api/roaming/recommend", { method: "POST", body: { destination: controller.state.destination, start_date: controller.state.start, end_date: controller.state.end } });
        const recommendation = cleanRecommendation(response);
        controller.update({ duration: recommendation.trip.trip_days, recommendationId: recommendation.recommendation_id, recommendation, chat: [], savedId: null, viewingSaved: false, carrierAcknowledged: false });
        controller.go("step3");
      } catch (error) { controller.go("step2"); toast(error.message, "error"); }
    }

    function planItemHTML(item, { final = false } = {}) {
      const quantity = item.quantity > 1 ? ` × ${item.quantity}` : "";
      const codeCopy = final ? `<span class="plan-code">${escapeHTML(item.activation_code)}</span>` : "";
      return `<article class="plan-item" data-package-code="${escapeHTML(item.package_code)}"><div class="plan-order">${item.activation_order}</div><div class="plan-item-copy"><div><h3>${escapeHTML(item.package_name)}${quantity}</h3><span class="family-pill">${escapeHTML(item.family)}</span></div><p>Days ${item.coverage_start_day}–${item.coverage_end_day} · AED ${Number(item.price_per_package_aed).toFixed(0)} each</p><small>${escapeHTML(item.reason_for_item)}</small><div class="plan-allowances"><span>${Number(item.data_gb_per_package).toFixed(1)} GB</span><span>${item.local_minutes_per_package} local min</span><span>${item.international_minutes_per_package} intl min</span><span>${item.sms_per_package} SMS</span></div>${codeCopy}</div></article>`;
    }

    function renderItems(container, recommendation, options = {}) {
      container.innerHTML = recommendation.selection.items.map((item) => planItemHTML(item, options)).join("");
    }
    function renderSegments(container, recommendation) {
      const segments = recommendation.segments || [];
      container.hidden = !segments.length;
      container.innerHTML = segments.map((segment) => {
        const names = recommendation.selection.items.filter((item) => item.assigned_segment_id === segment.segment_id).map((item) => `${item.package_name}${item.quantity > 1 ? ` × ${item.quantity}` : ""}`).join(" + ");
        return `<article class="segment-card"><span>Days ${segment.start_day}–${segment.end_day}</span><h3>${escapeHTML(names)}</h3><p>${escapeHTML(segment.usage_interpretation)}</p></article>`;
      }).join("");
    }
    function renderTotals(prefix, recommendation) {
      const selection = recommendation.selection;
      $(`#${prefix}-package-price`).textContent = Number(selection.total_price_aed).toFixed(0);
      $(`#${prefix}-package-validity`).textContent = selection.total_validity_days;
      $(`#${prefix}-package-data`).textContent = `${Number(selection.total_data_gb).toFixed(1)} GB`;
      $(`#${prefix}-package-local`).textContent = `${selection.total_local_minutes} min`;
      $(`#${prefix}-package-international`).textContent = `${selection.total_international_minutes} min`;
      $(`#${prefix}-package-sms`).textContent = selection.total_sms;
    }
    function renderRecommendation() {
      const recommendation = controller.state.recommendation; if (!recommendation) return;
      $("#usage-package-explanation").textContent = recommendation.modification_summary || recommendation.tradeoff_summary || recommendation.reason;
      $("#usage-package-destination").textContent = recommendation.destination;
      $("#usage-package-duration").textContent = recommendation.trip.trip_days;
      renderItems($("#usage-plan-items"), recommendation);
      renderSegments($("#usage-segment-timeline"), recommendation);
      renderTotals("usage", recommendation);
      $("#usage-activation-count").textContent = recommendation.selection.activation_count;
      const usage = recommendation.usage_analysis.trip_estimate;
      $("#usage-average-days").textContent = recommendation.trip.trip_days;
      $("#average-data").textContent = `${Number(usage.data_gb).toFixed(1)} GB`;
      $("#average-local").textContent = `${Math.round(usage.local_minutes)} min`;
      $("#average-international").textContent = `${Math.round(usage.international_minutes)} min`;
      $("#average-sms").textContent = Math.round(usage.sms);
      const why = recommendation.why_it_fits?.length ? recommendation.why_it_fits : [recommendation.reason];
      $("#usage-why-list").innerHTML = why.map((item) => `<li>${escapeHTML(item)}</li>`).join("");
    }
    function renderFinal() {
      const recommendation = controller.state.recommendation; if (!recommendation) return;
      const selection = recommendation.selection;
      $("#final-trip-dates").textContent = `${recommendation.destination} · ${formatDate(recommendation.trip.start_date)} to ${formatDate(recommendation.trip.end_date)} · ${recommendation.trip.trip_days} days`;
      renderItems($("#final-plan-items"), recommendation, { final: true });
      renderSegments($("#final-segment-timeline"), recommendation);
      $("#package-price").textContent = Number(selection.total_price_aed).toFixed(0);
      $("#package-validity").textContent = `${selection.total_validity_days} days`;
      $("#package-data").textContent = `${Number(selection.total_data_gb).toFixed(1)} GB`;
      $("#package-voice").textContent = `${selection.total_local_minutes} min`;
      $("#package-international").textContent = `${selection.total_international_minutes} min`;
      $("#package-sms").textContent = selection.total_sms;
      $("#package-destination").textContent = recommendation.destination;
      $("#package-trip-duration").textContent = `${recommendation.trip.trip_days} days`;
      $("#package-activation-count").textContent = selection.activation_count;
      $("#package-network").textContent = "Automatic partner selection";
      renderActivationSequence();
      renderAcknowledgement();
    }
    function expandedActivations() {
      const recommendation = controller.state.recommendation; if (!recommendation) return [];
      return recommendation.selection.items.flatMap((item) => Array.from({ length: item.quantity }, (_, index) => ({
        order: item.activation_order + index,
        name: item.package_name,
        code: item.activation_code,
        start: item.coverage_start_day + index * item.validity_days_per_package,
        end: Math.min(item.coverage_end_day, item.coverage_start_day + (index + 1) * item.validity_days_per_package - 1),
      })));
    }
    function renderActivationSequence() {
      const acknowledged = Boolean(controller.state.carrierAcknowledged);
      const activations = expandedActivations();
      $("#activation-sequence").innerHTML = activations.map((activation) => `<div class="activation-step"><b>${activation.order}</b><span><strong>${escapeHTML(activation.name)}</strong><small>Days ${activation.start}–${activation.end}</small></span><code>${acknowledged ? escapeHTML(activation.code) : "••••••••"}</code></div>`).join("");
      $("#activation-code").textContent = activations.map((activation) => activation.code).join("\n");
    }
    function renderAcknowledgement() {
      const acknowledged = Boolean(controller.state.carrierAcknowledged);
      $("#carrier-acknowledgement").checked = acknowledged;
      $("#activation-card").classList.toggle("locked", !acknowledged);
      $("#activation-code").setAttribute("aria-hidden", String(!acknowledged));
      $("#copy-code").disabled = !acknowledged; $("#open-dialer").disabled = !acknowledged; $("#roaming-done").disabled = !acknowledged;
      $("#activation-lock-message").hidden = acknowledged;
      renderActivationSequence();
    }
    function renderChat() {
      const box = $("#roaming-chat-messages"); box.innerHTML = "";
      controller.state.chat.forEach((message) => { const node = document.createElement("div"); node.className = `chat-message ${message.who}`; node.textContent = message.text; box.append(node); });
      if (controller.state.chat.length) box.scrollTop = box.scrollHeight;
    }
    function syncAdjustmentButton() {
      $("#send-roaming-adjustment").disabled = !$("#roaming-adjustment").value.trim();
    }
    function renderRecent() {
      const recommendation = controller.state.recommendation;
      if (!controller.state.completed || !recommendation) return;
      const names = recommendation.selection.items.map((item) => item.package_name).join(" + ");
      $("#recent-roaming-title").textContent = `${recommendation.destination} · ${recommendation.trip.trip_days} days`;
      $("#recent-roaming-meta").textContent = `${names} · AED ${Number(recommendation.selection.total_price_aed).toFixed(0)}`;
      $("#view-recent-roaming").disabled = false;
    }
    function formatDate(value) { if (!value) return ""; return new Date(`${value}T12:00:00`).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" }); }
    function escapeHTML(value) { const node = document.createElement("div"); node.textContent = value ?? ""; return node.innerHTML; }

    async function submitAdjustment(text) {
      const value = (text || $("#roaming-adjustment").value).trim();
      if (!value || !controller.state.recommendationId) { toast("Enter an adjustment first.", "error"); return; }
      $("#roaming-adjustment").value = "";
      syncAdjustmentButton();
      controller.update({ chat: [...controller.state.chat, { who: "user", text: value }, { who: "assistant", text: "Reviewing that adjustment…" }] }, false); renderChat();
      await delay(window.PROTOTYPE?.testing ? 20 : 400);
      try {
        const response = await api("/api/roaming/refine", { method: "POST", body: { current_recommendation_id: controller.state.recommendationId, message: value } });
        if (response.response_type === "message") {
          const updatedChat = [...controller.state.chat.slice(0, -1), { who: "assistant", text: response.message }];
          controller.update({ chat: updatedChat }, false); renderChat();
          return;
        }
        const recommendation = cleanRecommendation(response);
        const updatedChat = [...controller.state.chat.slice(0, -1), { who: "assistant", text: recommendation.chat_message || recommendation.modification_summary || recommendation.tradeoff_summary || recommendation.reason }];
        controller.update({ recommendation, recommendationId: recommendation.recommendation_id, chat: updatedChat, savedId: null, completed: false, carrierAcknowledged: false });
        renderRecommendation(); renderChat(); toast(response.history_action ? "Recommendation restored." : "Recommendation reviewed.");
      } catch (error) {
        controller.update({ chat: [...controller.state.chat.slice(0, -1), { who: "assistant", text: error.message }] }, false); renderChat(); toast(error.message, "error");
      }
    }
    async function saveSelection() {
      if (!controller.state.recommendationId) return;
      try {
        const response = await api("/api/roaming/saved", { method: "POST", body: { recommendation_id: controller.state.recommendationId } });
        controller.update({ savedId: response.recommendation.saved_id });
        restoreInputs();
        renderSavedRecommendations(response.recommendations); toast(response.duplicate ? "Recommendation already saved." : "Recommendation saved.");
      } catch (error) { toast(error.message, "error"); }
    }
    async function loadSavedRecommendations() {
      try { const response = await api("/api/roaming/saved"); renderSavedRecommendations(response.recommendations); } catch (error) { toast(error.message, "error"); }
    }
    function renderSavedRecommendations(recommendations) {
      const section = $("#saved-recommendations-section"), list = $("#saved-recommendations-list"); list.innerHTML = ""; section.hidden = !recommendations.length;
      recommendations.forEach((saved) => {
        if (!saved.selection?.items?.length) return;
        const names = saved.selection.items.map((item) => `${item.package_name}${item.quantity > 1 ? ` × ${item.quantity}` : ""}`).join(" + ");
        const card = document.createElement("article"); card.className = "card saved-roaming-card"; card.dataset.savedId = saved.saved_id;
        card.innerHTML = `<div><span class="demo-tag">SAVED</span><h3>${escapeHTML(names)}</h3><p>${escapeHTML(saved.destination)} · ${escapeHTML(formatDate(saved.trip.start_date))} to ${escapeHTML(formatDate(saved.trip.end_date))}</p><div class="saved-summary"><b>AED ${Number(saved.selection.total_price_aed).toFixed(0)}</b><span>${Number(saved.selection.total_data_gb).toFixed(1)} GB · ${saved.selection.activation_count} activations</span></div></div><div class="button-row"><button class="button button-secondary" type="button" data-view-saved>View Details</button><button class="button button-danger-soft" type="button" data-remove-saved>Remove</button></div>`;
        card._recommendation = saved; list.append(card);
      });
      section.hidden = list.children.length === 0;
    }
    function viewSaved(saved) {
      controller.update({ destination: saved.destination, start: saved.trip.start_date, end: saved.trip.end_date, duration: saved.trip.trip_days, recommendationId: saved.recommendation_id, recommendation: saved, savedId: saved.saved_id, viewingSaved: true, completed: true, carrierAcknowledged: false });
      controller.go("result");
    }
    async function restoreCurrentRecommendation() {
      if (!controller.state.recommendationId) return;
      try {
        const response = await api("/api/roaming/current");
        if (response.recommendation.recommendation_id !== controller.state.recommendationId) return;
        const chat = (response.conversation || []).map((item) => ({ who: item.role === "user" ? "user" : "assistant", text: item.message }));
        controller.update({ recommendation: response.recommendation, chat }, false);
        controller.render(controller.view, controller.state);
      } catch { controller.update(resetRecommendationState(), false); }
    }

    $("#start-roaming").addEventListener("click", async () => { if (controller.state.completed) await controller.reset(); controller.go("step1"); });
    $("#roaming-step1-back").addEventListener("click", () => controller.go("landing"));
    $$('[data-roaming-exit]').forEach((button) => button.addEventListener("click", () => controller.go("landing")));
    $$('[data-edit-roaming]').forEach((button) => button.addEventListener("click", () => controller.go(`step${button.dataset.editRoaming}`)));
    $("#country-list").addEventListener("click", (event) => { const button = event.target.closest("button[data-country]"); if (button) selectCountry(button.dataset.country); });
    $("#country-search").addEventListener("input", (event) => {
      const term = event.target.value.trim().toLowerCase(); let visibleCount = 0;
      $$('[data-country-group]').forEach((group) => { const buttons = $$("button[data-country]", group); buttons.forEach((button) => { const visible = !term || button.dataset.country.toLowerCase().startsWith(term); button.hidden = !visible; if (visible) visibleCount += 1; }); group.hidden = !buttons.some((button) => !button.hidden); });
      renderCountryCount(visibleCount);
    });
    $("#destination-next").addEventListener("click", () => { if (controller.state.destination) controller.go("step2"); });
    $("#trip-start").addEventListener("change", () => { $("#trip-end").min = $("#trip-start").value || minDate; validateDates(); }); $("#trip-end").addEventListener("change", () => validateDates());
    $("#dates-next").addEventListener("click", loadRecommendation);
    $("#usage-more-details").addEventListener("click", (event) => { const open = $("#usage-details-panel").classList.toggle("open"); event.currentTarget.setAttribute("aria-expanded", String(open)); event.currentTarget.firstChild.textContent = open ? "Hide details " : "More details "; });
    $("#send-roaming-adjustment").addEventListener("click", () => submitAdjustment());
    $("#roaming-adjustment").addEventListener("input", syncAdjustmentButton);
    $("#roaming-adjustment").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submitAdjustment(); } });
    $("#carrier-acknowledgement").addEventListener("change", (event) => { controller.update({ carrierAcknowledged: event.currentTarget.checked }); renderAcknowledgement(); if (event.currentTarget.checked) toast("Network note acknowledged. Activation codes are now available."); });
    $("#continue-roaming-plan").addEventListener("click", () => { controller.update({ completed: true, viewingSaved: false }); controller.go("result"); });
    $("#roaming-result-back").addEventListener("click", () => controller.go(controller.state.viewingSaved ? "landing" : "step3"));
    $("#save-recommendation").addEventListener("click", saveSelection);
    $("#roaming-done").addEventListener("click", () => { if (!controller.state.carrierAcknowledged) { toast("Acknowledge the network note before finishing.", "error"); return; } controller.update({ completed: true }); controller.go("landing"); });
    $("#start-over-roaming").addEventListener("click", async () => { await controller.reset(); $("#country-search").value = ""; $$('[data-country-group]').forEach((group) => group.hidden = false); const buttons = $$("#country-list button[data-country]"); buttons.forEach((button) => { button.hidden = false; button.classList.remove("selected"); }); renderCountryCount(buttons.length); controller.go("step1", { replace: true }); });
    $("#view-recent-roaming").addEventListener("click", () => { if (controller.state.recommendation) controller.go("result"); });
    $("#saved-recommendations-list").addEventListener("click", (event) => { const card = event.target.closest(".saved-roaming-card"); if (!card) return; if (event.target.closest("[data-view-saved]")) viewSaved(card._recommendation); if (event.target.closest("[data-remove-saved]")) confirmAction({ title: "Remove saved recommendation?", message: "This removes the saved plan from the current session.", action: "Remove", tone: "danger", onConfirm: async () => { try { const response = await api(`/api/roaming/saved/${card.dataset.savedId}`, { method: "DELETE" }); renderSavedRecommendations(response.recommendations); if (controller.state.savedId === card.dataset.savedId) controller.update({ savedId: null }); toast("Saved recommendation removed."); } catch (error) { toast(error.message, "error"); } } }); });
    $("#copy-code").addEventListener("click", async (event) => { if (!controller.state.carrierAcknowledged) return; const button = event.currentTarget; const codes = expandedActivations().map((item) => `${item.order}. ${item.code}`).join("\n"); try { await navigator.clipboard.writeText(codes); } catch { const area = document.createElement("textarea"); area.value = codes; document.body.append(area); area.select(); document.execCommand("copy"); area.remove(); } button.textContent = "Copied"; toast("Activation codes copied in order."); setTimeout(() => button.textContent = "Copy activation codes", 1500); });
    $("#open-dialer").addEventListener("click", () => { if (!controller.state.carrierAcknowledged) return; const first = expandedActivations()[0]; if (!first) return; confirmAction({ title: "Open your dialer?", message: "The first activation code will be placed in the dialer. Nothing is activated automatically.", action: "Open dialer", onConfirm: () => { window.location.href = `tel:${first.code.replace(/#/g, "%23")}`; } }); });

    await controller.restore();
    syncAdjustmentButton();
    await restoreCurrentRecommendation();
    await loadSavedRecommendations();
  });
})();
