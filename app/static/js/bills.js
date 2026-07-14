(() => {
  "use strict";
  document.addEventListener("DOMContentLoaded", () => {
    if (!document.querySelector("#bill-input-choice")) return;
    const { $, $$, delay, api, toast, confirmAction } = window.App;
    const choice = $("#bill-input-choice"), upload = $("#bill-upload-flow"), fields = $("#bill-fields"), analysis = $("#bill-analysis");
    const due = new Date(); due.setDate(due.getDate() + 5);
    $("#bill-due").value = due.toISOString().slice(0, 10);

    function resetFlows() { upload.hidden = true; fields.hidden = true; analysis.hidden = true; choice.hidden = false; $("#bill-processing").hidden = true; $(".drop-zone").hidden = false; }
    function openMode(mode) {
      choice.hidden = true; analysis.hidden = true;
      if (mode === "upload") { upload.hidden = false; fields.hidden = true; }
      else { upload.hidden = true; fields.hidden = false; $("#bill-form-kicker").textContent = "MANUAL ENTRY"; }
      $("#app-scroll").scrollTop = $("[data-panel='bill']").offsetTop;
    }
    $$('[data-bill-mode]').forEach((button) => button.addEventListener("click", () => openMode(button.dataset.billMode)));
    $$('[data-close-bill-flow]').forEach((button) => button.addEventListener("click", resetFlows));
    $("#analyse-another")?.addEventListener("click", resetFlows);
    $("#new-bill-analysis")?.addEventListener("click", resetFlows);
    $("#view-current-analysis")?.addEventListener("click", () => { choice.hidden = true; upload.hidden = true; fields.hidden = true; analysis.hidden = false; });

    $("#bill-file").addEventListener("change", (event) => {
      const file = event.target.files[0];
      if (!file) return;
      const allowed = file.type.startsWith("image/") || file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
      if (!allowed || file.size > 10 * 1024 * 1024) { toast("Choose an image or PDF smaller than 10 MB.", "error"); event.target.value = ""; return; }
      $("#bill-filename").textContent = file.name; $("#bill-file-preview").hidden = false; $("#parse-bill").disabled = false;
    });
    $("#remove-bill-file").addEventListener("click", () => { $("#bill-file").value = ""; $("#bill-file-preview").hidden = true; $("#parse-bill").disabled = true; });
    $("#parse-bill").addEventListener("click", async () => {
      $(".drop-zone").hidden = true; $("#bill-file-preview").hidden = true; $("#parse-bill").hidden = true; $("#bill-processing").hidden = false;
      const phases = ["Uploading document", "Extracting information", "Organising charges", "Analysing spending"];
      for (let i = 0; i < phases.length; i += 1) { $("#bill-phase").textContent = phases[i]; $("#bill-progress").style.width = `${(i + 1) * 25}%`; await delay(650); }
      if ((window.DemoStates?.bill || "normal") === "error") {
        $("#bill-processing").hidden = true; $(".drop-zone").hidden = false; $("#parse-bill").hidden = false;
        toast("Simulated parsing failed. Try another file or enter the bill manually.", "error"); return;
      }
      upload.hidden = true; fields.hidden = false; $("#bill-form-kicker").textContent = "CONFIRM EXTRACTED DETAILS"; toast("Document fields extracted for confirmation.");
    });
    $("#bill-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const payload = Object.fromEntries(new FormData(event.currentTarget));
      const totalParts = ["data_charges", "call_charges", "roaming_charges", "addon_charges"].reduce((sum, key) => sum + Number(payload[key] || 0), 0);
      if (Math.abs(Number(payload.total_amount) - totalParts) > 1) { toast("Charge categories should add up to the total amount.", "error"); return; }
      try {
        const response = await api("/api/bills", { method: "POST", body: payload });
        renderAnalysis(response.bill, response.analysis); fields.hidden = true; analysis.hidden = false; toast("Bill analysis saved locally.");
      } catch (error) { toast(error.message, "error"); }
    });
    function renderAnalysis(bill, result) {
      $("#analysis-total").textContent = Number(bill.total_amount).toFixed(0); $("#analysis-due").textContent = bill.due_date;
      $("#legend-data").textContent = `AED ${bill.data_charges}`; $("#legend-calls").textContent = `AED ${bill.call_charges}`; $("#legend-roaming").textContent = `AED ${bill.roaming_charges}`; $("#legend-addons").textContent = `AED ${bill.addon_charges}`;
      $("#anomaly-title").textContent = result.anomaly ? "Your bill is 28% higher than usual" : "No unusual charges detected";
      $("#anomaly-copy").textContent = result.summary;
      $(".anomaly-card .overline").textContent = result.anomaly ? "ANOMALY DETECTED" : "NO ANOMALY";
    }
    $(".expand-explanation")?.addEventListener("click", (event) => { const copy = $(".expand-copy"); copy.classList.toggle("open"); event.currentTarget.textContent = copy.classList.contains("open") ? "Hide explanation" : "See explanation"; });
    $("#switch-plan")?.addEventListener("click", () => confirmAction({ title: "Continue to plan page?", message: "This is a prototype. In the production application, this action would open the correct e& plan page.", action: "Continue demo", onConfirm: () => toast("Demo complete — no real plan was changed.") }));
  });
})();
