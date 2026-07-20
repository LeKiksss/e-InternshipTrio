(() => {
  "use strict";
  document.addEventListener("DOMContentLoaded", async () => {
    const runButton = document.querySelector("#run-speed-test");
    if (!runButton) return;
    const { $, $$, delay, api, toast, openSheet, closeSheet, confirmAction } = window.App;
    let runGeneration = 0;
    const controller = window.WorkflowState.create({
      name: "network",
      initialState: { locationChoice: null, lastResult: null },
      render(view) {
        const landing = view === "landing" || view === "permission";
        $("#speed-test-card").hidden = view !== "testing";
        $("#network-result").hidden = view !== "result";
        runButton.hidden = !landing;
        if (controller.state.lastResult) renderLatest(controller.state.lastResult);
        $("#app-scroll").scrollTop = 0;
      },
    });
    await controller.restore();

    function renderLatest(record) {
      $("#network-latest-result").hidden = false;
      $("#network-latest-verdict").textContent = record.verdict;
      $("#network-latest-speed").textContent = `${Math.round(record.download_speed)} Mbps`;
      $("#network-latest-meta").textContent = `${record.created_at} · ${record.location_label}`;
    }

    function openPermission() {
      controller.go("permission");
      openSheet("location-sheet");
    }

    async function runTest(choice) {
      const generation = ++runGeneration;
      closeSheet("location-sheet");
      const demoState = window.DemoStates?.network || "strong";
      const noLocation = choice === "deny" || demoState === "denied";
      controller.update({ locationChoice: noLocation ? "denied" : "allowed" });
      controller.go("testing");
      runButton.disabled = true;
      const phases = ["Connecting", "Measuring latency", "Measuring download", "Measuring upload", "Analysing result"];
      const targets = [9, demoState === "weak" ? 18 : 52, demoState === "weak" ? 8.4 : 184, demoState === "weak" ? 1.8 : 32, demoState === "weak" ? 8.4 : 184];
      const phaseDelay = window.PROTOTYPE?.testing ? 35 : 800;
      for (let i = 0; i < phases.length; i += 1) {
        if (generation !== runGeneration) return;
        $("#test-phase").textContent = phases[i];
        $("#gauge-number").textContent = targets[i];
        $("#gauge-value").style.strokeDashoffset = String(220 - Math.min(210, Number(targets[i]) * 1.08));
        $$(".phase-dots span").forEach((dot, dotIndex) => dot.classList.toggle("done", dotIndex <= i));
        await delay(phaseDelay);
      }
      if (generation !== runGeneration) return;
      if (demoState === "failure") {
        controller.go("landing"); runButton.disabled = false;
        toast("The test could not complete. Existing history is safe.", "error");
        return;
      }
      try {
        const data = await api("/api/diagnostics", { method: "POST", body: { state: demoState === "weak" ? "weak" : "strong", location: noLocation ? "Location not saved" : "Downtown Dubai" } });
        const record = data.result;
        $("#metric-download").textContent = record.download_speed;
        $("#metric-upload").textContent = record.upload_speed;
        $("#metric-latency").textContent = record.latency;
        $("#network-verdict").textContent = record.download_speed > 50 ? "Excellent connection" : "Connection needs attention";
        $("#network-verdict-copy").textContent = record.verdict;
        controller.update({ lastResult: record });
        prependHistory(record);
        controller.go("result");
        toast(noLocation ? "Result saved without a map location." : "Diagnostic result saved locally.");
      } catch (error) {
        controller.go("landing");
        toast(error.message, "error");
      }
      runButton.disabled = false;
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

    runButton.addEventListener("click", openPermission);
    $("#test-again").addEventListener("click", openPermission);
    $("#network-done").addEventListener("click", () => controller.go("landing"));
    $("#network-result-back").addEventListener("click", () => controller.go("landing"));
    $("#network-test-back").addEventListener("click", () => { runGeneration += 1; runButton.disabled = false; controller.go("landing"); });
    $$('[data-network-exit]').forEach((button) => button.addEventListener("click", () => { runGeneration += 1; controller.go("landing"); }));
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
