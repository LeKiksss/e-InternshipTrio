(() => {
  "use strict";
  document.addEventListener("DOMContentLoaded", () => {
    const runButton = document.querySelector("#run-speed-test");
    if (!runButton) return;
    const { $, $$, delay, api, toast, openSheet, closeSheet, confirmAction } = window.App;
    let running = false;

    async function runTest(choice) {
      if (running) return;
      running = true;
      closeSheet("location-sheet");
      const state = window.DemoStates?.network || "strong";
      const noLocation = choice === "deny" || state === "denied";
      const testCard = $("#speed-test-card");
      const resultSection = $("#network-result");
      testCard.hidden = false; resultSection.hidden = true; runButton.disabled = true;
      runButton.textContent = "Test in progress…";
      const phases = ["Connecting", "Measuring latency", "Measuring download", "Measuring upload", "Analysing result"];
      const targets = [9, state === "weak" ? 18 : 52, state === "weak" ? 8.4 : 184, state === "weak" ? 1.8 : 32, state === "weak" ? 8.4 : 184];
      for (let i = 0; i < phases.length; i += 1) {
        $("#test-phase").textContent = phases[i];
        $("#gauge-number").textContent = targets[i];
        $("#gauge-value").style.strokeDashoffset = String(220 - Math.min(210, Number(targets[i]) * 1.08));
        $$(".phase-dots span").forEach((dot, dotIndex) => dot.classList.toggle("done", dotIndex <= i));
        await delay(800);
      }
      if (state === "failure") {
        testCard.hidden = true; runButton.disabled = false; runButton.innerHTML = "Run speed test <span>→</span>"; running = false;
        toast("The simulated test could not complete. Existing history is safe.", "error");
        return;
      }
      try {
        const data = await api("/api/diagnostics", { method: "POST", body: { state: state === "weak" ? "weak" : "strong", location: noLocation ? "Location not saved" : "Downtown Dubai — demo location" } });
        const record = data.result;
        $("#metric-download").textContent = record.download_speed;
        $("#metric-upload").textContent = record.upload_speed;
        $("#metric-latency").textContent = record.latency;
        $("#network-verdict").textContent = record.download_speed > 50 ? "Excellent connection" : "Connection needs attention";
        $("#network-verdict-copy").textContent = record.verdict;
        testCard.hidden = true; resultSection.hidden = false;
        prependHistory(record);
        toast(noLocation ? "Result saved without a map location." : "Diagnostic result saved locally.");
      } catch (error) { testCard.hidden = true; toast(error.message, "error"); }
      runButton.disabled = false; runButton.innerHTML = "Run speed test <span>→</span>"; running = false;
    }

    function prependHistory(record) {
      const list = $("#diagnostic-history");
      list.querySelector(".empty-card")?.remove();
      const article = document.createElement("article");
      article.className = "history-card";
      article.dataset.diagnosticId = record.id;
      article.innerHTML = `<button class="history-main" type="button" data-expand><span class="verdict-dot"></span><span><b>${escapeHTML(record.location_label)}</b><small>${escapeHTML(record.created_at)}</small></span><strong>${Math.round(record.download_speed)} Mbps</strong><svg><use href="#i-chevron"/></svg></button><div class="history-details"><div><span>Upload</span><b>${record.upload_speed} Mbps</b></div><div><span>Latency</span><b>${record.latency} ms</b></div><div><span>Verdict</span><b>${escapeHTML(record.verdict)}</b></div><button class="danger-link" type="button" data-delete-diagnostic="${record.id}">Delete local record</button></div>`;
      list.prepend(article);
    }
    function escapeHTML(value) { const div = document.createElement("div"); div.textContent = value ?? ""; return div.innerHTML; }

    runButton.addEventListener("click", () => openSheet("location-sheet"));
    $("#test-again")?.addEventListener("click", () => openSheet("location-sheet"));
    $$('[data-location-choice]').forEach((button) => button.addEventListener("click", () => runTest(button.dataset.locationChoice)));
    $("#diagnostic-history").addEventListener("click", (event) => {
      const expand = event.target.closest("[data-expand]");
      if (expand) expand.closest(".history-card").classList.toggle("expanded");
      const remove = event.target.closest("[data-delete-diagnostic]");
      if (remove) confirmAction({ title: "Delete this result?", message: "This only removes the local diagnostic record and cannot be undone.", action: "Delete record", tone: "danger", onConfirm: async () => {
        try { await api(`/api/diagnostics/${remove.dataset.deleteDiagnostic}`, { method: "DELETE" }); remove.closest(".history-card").remove(); toast("Diagnostic record deleted."); } catch (error) { toast(error.message, "error"); }
      }});
    });
  });
})();

