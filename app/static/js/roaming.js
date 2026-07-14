(() => {
  "use strict";
  document.addEventListener("DOMContentLoaded", () => {
    if (!document.querySelector("#roaming-intro")) return;
    const { $, $$, delay, api, toast, confirmAction } = window.App;
    const trip = { destination: "", start: "", end: "", duration: 0, requirements: "", rejected_ids: [], currentPackage: null };
    const flags = { "United Kingdom":"🇬🇧", France:"🇫🇷", Egypt:"🇪🇬", "Saudi Arabia":"🇸🇦", Turkey:"🇹🇷", India:"🇮🇳", "United States":"🇺🇸", Canada:"🇨🇦", Germany:"🇩🇪", Italy:"🇮🇹", Japan:"🇯🇵", Singapore:"🇸🇬" };
    const intro = $("#roaming-intro"), planner = $("#roaming-planner"), loading = $("#roaming-loading"), result = $("#roaming-result"), empty = $("#roaming-empty");
    const tomorrow = new Date(); tomorrow.setDate(tomorrow.getDate() + 1); const minDate = tomorrow.toISOString().slice(0, 10);
    $("#trip-start").min = minDate; $("#trip-end").min = minDate;

    function showPlanner() { intro.hidden = true; planner.hidden = false; goStep(1); }
    $("#start-roaming").addEventListener("click", showPlanner);
    $("[data-roaming-example]").addEventListener("click", () => {
      trip.destination = "United Kingdom"; const start = new Date(); start.setDate(start.getDate() + 14); const end = new Date(start); end.setDate(end.getDate() + 6); trip.start = start.toISOString().slice(0,10); trip.end = end.toISOString().slice(0,10); trip.duration = 7; trip.requirements = "Maps, messaging, browsing, and daily calls home";
      showPlanner(); selectCountry("United Kingdom"); $("#trip-start").value = trip.start; $("#trip-end").value = trip.end; validateDates(); $("#roaming-requirements").value = trip.requirements; goStep(3);
    });
    function goStep(step) {
      $$("[data-roaming-step]").forEach((panel) => { panel.hidden = Number(panel.dataset.roamingStep) !== step; panel.classList.toggle("active", Number(panel.dataset.roamingStep) === step); });
      loading.hidden = true; result.hidden = true; empty.hidden = true;
      $$("[data-step-dot]").forEach((dot) => { const n = Number(dot.dataset.stepDot); dot.classList.toggle("active", n === step); dot.classList.toggle("done", n < step); });
      $("#app-scroll").scrollTop = 0;
    }
    $$('[data-edit-roaming]').forEach((button) => button.addEventListener("click", () => goStep(Number(button.dataset.editRoaming))));
    $("#edit-trip").addEventListener("click", () => goStep(1));

    function selectCountry(country) {
      trip.destination = country;
      $$("#country-list button").forEach((button) => button.classList.toggle("selected", button.dataset.country === country));
      $("#destination-next").disabled = false; $("#selected-country").textContent = country; $("#selected-flag").textContent = flags[country] || "🌍";
    }
    $("#country-list").addEventListener("click", (event) => { const button = event.target.closest("button[data-country]"); if (button) selectCountry(button.dataset.country); });
    $("#country-search").addEventListener("input", (event) => { const query = event.target.value.toLowerCase(); $$("#country-list button").forEach((button) => button.hidden = !button.dataset.country.toLowerCase().includes(query)); });
    $("#destination-next").addEventListener("click", () => goStep(2));

    function validateDates() {
      const start = new Date(`${$("#trip-start").value}T12:00:00`), end = new Date(`${$("#trip-end").value}T12:00:00`); const error = $("#date-error");
      if (!$("#trip-start").value || !$("#trip-end").value) { $("#dates-next").disabled = true; $("#trip-duration").hidden = true; return false; }
      const today = new Date(); today.setHours(0,0,0,0);
      if (start < today || end < start) { error.hidden = false; error.textContent = end < start ? "Return date must be after the departure date." : "Choose travel dates in the future."; $("#dates-next").disabled = true; $("#trip-duration").hidden = true; return false; }
      trip.start = $("#trip-start").value; trip.end = $("#trip-end").value; trip.duration = Math.round((end - start) / 86400000) + 1; $("#trip-days").textContent = trip.duration; $("#trip-duration").hidden = false; error.hidden = true; $("#dates-next").disabled = false; return true;
    }
    $("#trip-start").addEventListener("change", () => { $("#trip-end").min = $("#trip-start").value || minDate; validateDates(); }); $("#trip-end").addEventListener("change", validateDates);
    $("#dates-next").addEventListener("click", () => { if (validateDates()) goStep(3); });
    $(".planner-step .requirement-chips").addEventListener("click", (event) => { const button = event.target.closest("button"); if (!button) return; const field = $("#roaming-requirements"); field.value = field.value ? `${field.value}, ${button.textContent.toLowerCase()}` : button.textContent; field.focus(); });
    $("#requirements-send").addEventListener("click", () => requestRecommendation(false));

    async function requestRecommendation(alternative, feedback = "") {
      if (!alternative) { trip.requirements = $("#roaming-requirements").value.trim(); if (trip.requirements.length < 5) { toast("Describe how you expect to use your phone.", "error"); return; } }
      else { trip.requirements = `${trip.requirements}. ${feedback}`; if (trip.currentPackage) trip.rejected_ids.push(trip.currentPackage.id); }
      const demoState = window.DemoStates?.roaming || "normal";
      if (alternative && demoState === "exhausted") { result.hidden = true; empty.hidden = false; toast("No further fictional alternatives are available.", "error"); return; }
      $$("[data-roaming-step]").forEach((panel) => panel.hidden = true); result.hidden = true; empty.hidden = true; loading.hidden = false;
      const phases = ["Checking destination coverage", "Comparing trip duration", "Estimating usage", "Reviewing eligible packages", "Preparing recommendation"];
      const wait = demoState === "long" ? 1000 : 580;
      for (const phase of phases) { $("#roaming-phase").textContent = phase; await delay(wait); }
      try {
        const response = await api("/api/roaming/recommend", { method: "POST", body: { destination: trip.destination, duration: trip.duration, requirements: trip.requirements, rejected_ids: demoState === "none" ? [1,2,3,4,5] : trip.rejected_ids, simulate: demoState === "database" ? "database" : "" } });
        trip.currentPackage = response.package; renderPackage(response.package); loading.hidden = true; result.hidden = false; $$("[data-step-dot]").forEach((dot) => { dot.classList.remove("active"); dot.classList.add("done"); });
        toast(alternative ? "A different fictional package is ready." : "Recommendation prepared from the local catalogue.");
      } catch (error) { loading.hidden = true; if (error.status === 404) { empty.hidden = false; } else { goStep(3); } toast(error.message, "error"); }
    }
    function renderPackage(pkg) {
      $("#package-name").textContent = pkg.name; $("#package-price").textContent = Number(pkg.price).toFixed(0); $("#package-validity").textContent = `${pkg.validity_days} days`; $("#package-data").textContent = pkg.data_allowance; $("#package-voice").textContent = `${pkg.voice_minutes} min`; $("#package-sms").textContent = pkg.sms_allowance; $("#package-destination").textContent = pkg.destination; $("#package-network").textContent = pkg.preferred_network; $("#package-why").textContent = pkg.why; $("#package-updated").textContent = `Demo catalogue updated ${pkg.updated_at}`; $("#activation-code").textContent = pkg.activation_code; $("#activation-instructions").textContent = pkg.activation_instructions;
    }
    $(".followup-chips").addEventListener("click", (event) => { const button = event.target.closest("button"); if (button) requestRecommendation(true, button.textContent); });
    $("#send-followup").addEventListener("click", () => { const value = $("#roaming-followup").value.trim(); if (!value) return; $("#roaming-followup").value = ""; requestRecommendation(true, value); });
    $("#copy-code").addEventListener("click", async (event) => {
      const code = $("#activation-code").textContent;
      try { await navigator.clipboard.writeText(code); } catch { const area = document.createElement("textarea"); area.value = code; document.body.append(area); area.select(); document.execCommand("copy"); area.remove(); }
      const button = event.currentTarget; button.textContent = "Copied"; toast("Fictional activation code copied."); setTimeout(() => button.textContent = "Copy code", 1500);
    });
    $("#open-dialer").addEventListener("click", () => confirmAction({ title: "Open your dialer?", message: "The fictional code will be placed in the dialer where supported. No package will be activated automatically.", action: "Open dialer", onConfirm: () => { window.location.href = `tel:${$("#activation-code").textContent.replace(/#/g, "%23")}`; } }));
    $("#save-recommendation").addEventListener("click", () => { if (!trip.currentPackage) return; localStorage.setItem("saved-roaming-recommendation", JSON.stringify({ trip, savedAt: new Date().toISOString() })); toast("Recommendation saved in this browser."); });
    $("#start-over-roaming").addEventListener("click", () => { Object.assign(trip, { destination:"", start:"", end:"", duration:0, requirements:"", rejected_ids:[], currentPackage:null }); $("#country-search").value=""; $("#roaming-requirements").value=""; $$("#country-list button").forEach((button)=>{button.hidden=false;button.classList.remove("selected")}); $("#destination-next").disabled=true; goStep(1); });
  });
})();
