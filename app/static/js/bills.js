(() => {
  "use strict";
  document.addEventListener("DOMContentLoaded", async () => {
    if (!document.querySelector("#bill-input-choice")) return;
    const { $, $$, delay, api, toast, confirmAction } = window.App;
    const choice = $("#bill-input-choice"), upload = $("#bill-upload-flow"), fields = $("#bill-fields"), analysis = $("#bill-analysis"), usageHistory = $("#bill-usage-history");
    const defaultDue = () => { const value = new Date(); value.setDate(value.getDate() + 5); return value.toISOString().slice(0, 10); };
    const controller = window.WorkflowState.create({
      name: "bill",
      viewOrder: ["landing", "upload", "parsing", "fields", "analysis", "usage"],
      initialState: {
        mode: null, filename: null, previousView: "landing", analysis: null,
        values: { total_amount: "468", due_date: defaultDue(), data_charges: "240", call_charges: "72", roaming_charges: "96", addon_charges: "60" },
      },
      render(view, state) {
        choice.hidden = view !== "landing";
        upload.hidden = !["upload", "parsing"].includes(view);
        fields.hidden = view !== "fields";
        analysis.hidden = view !== "analysis";
        usageHistory.hidden = view !== "usage";
        $("#bill-processing").hidden = view !== "parsing";
        $(".drop-zone").hidden = view === "parsing";
        $("#parse-bill").hidden = view === "parsing";
        if (state.filename) {
          $("#bill-filename").textContent = state.filename;
          $("#bill-file-preview").hidden = view === "parsing";
          $("#parse-bill").disabled = false;
        }
        populateForm(state.values);
        if (state.analysis) renderAnalysis(state.analysis.bill, state.analysis.result);
        $("#app-scroll").scrollTop = 0;
        return {
          landing: choice,
          upload,
          parsing: upload,
          fields,
          analysis,
          usage: usageHistory,
        }[view] || choice;
      },
    });
    await controller.restore();

    function populateForm(values) {
      Object.entries(values || {}).forEach(([name, value]) => { const input = $(`#bill-form [name="${name}"]`); if (input) input.value = value; });
    }
    function captureForm() {
      controller.update({ values: Object.fromEntries(new FormData($("#bill-form"))) });
    }
    function openMode(mode) {
      controller.update({ mode, previousView: mode === "upload" ? "upload" : "landing" });
      $("#bill-form-kicker").textContent = mode === "upload" ? "CONFIRM EXTRACTED DETAILS" : "MANUAL ENTRY";
      controller.go(mode === "upload" ? "upload" : "fields");
    }
    async function startNew() {
      await controller.reset();
      populateForm(controller.state.values);
      $("#bill-file").value = "";
      $("#bill-file-preview").hidden = true;
      $("#parse-bill").disabled = true;
      controller.go("landing", { replace: true });
    }
    function goBack() {
      captureForm();
      if (controller.view === "analysis") controller.go("fields");
      else if (controller.view === "fields" && controller.state.mode === "upload") controller.go("upload");
      else controller.go("landing");
    }

    $$('[data-bill-mode]').forEach((button) => button.addEventListener("click", () => openMode(button.dataset.billMode)));
    $$('[data-bill-back]').forEach((button) => button.addEventListener("click", goBack));
    $$('[data-bill-exit]').forEach((button) => button.addEventListener("click", () => controller.go("landing")));
    $("#analyse-another").addEventListener("click", startNew);
    $("#new-bill-analysis").addEventListener("click", startNew);
    $("#bill-done").addEventListener("click", () => controller.go("landing"));
    $("#bill-result-back").addEventListener("click", goBack);
    $("#view-current-analysis").addEventListener("click", () => controller.go("analysis"));
    $("#view-usage-history").addEventListener("click", () => controller.go("usage"));
    $("#usage-history-back").addEventListener("click", goBack);
    $$("#bill-form input").forEach((input) => input.addEventListener("input", captureForm));

    $("#bill-file").addEventListener("change", (event) => {
      const file = event.target.files[0];
      if (!file) return;
      const allowed = file.type.startsWith("image/") || file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
      if (!allowed || file.size > 10 * 1024 * 1024) { toast("Choose an image or PDF smaller than 10 MB.", "error"); event.target.value = ""; return; }
      controller.update({ filename: file.name });
      $("#bill-filename").textContent = file.name; $("#bill-file-preview").hidden = false; $("#parse-bill").disabled = false;
    });
    $("#remove-bill-file").addEventListener("click", () => { controller.update({ filename: null }); $("#bill-file").value = ""; $("#bill-file-preview").hidden = true; $("#parse-bill").disabled = true; });
    $("#parse-bill").addEventListener("click", async () => {
      controller.go("parsing");
      const phases = ["Uploading document", "Extracting information", "Organising charges", "Analysing spending"];
      for (let i = 0; i < phases.length; i += 1) { $("#bill-phase").textContent = phases[i]; $("#bill-progress").style.width = `${(i + 1) * 25}%`; await delay(window.PROTOTYPE?.testing ? 30 : 650); }
      if ((window.DemoStates?.bill || "normal") === "error") { controller.go("upload"); toast("Document parsing failed. Try another file or enter the bill manually.", "error"); return; }
      controller.update({ previousView: "upload" });
      controller.go("fields");
      toast("Document fields extracted for confirmation.");
    });
    $("#bill-form").addEventListener("submit", async (event) => {
      event.preventDefault(); captureForm();
      const payload = controller.state.values;
      const totalParts = ["data_charges", "call_charges", "roaming_charges", "addon_charges"].reduce((sum, key) => sum + Number(payload[key] || 0), 0);
      if (Math.abs(Number(payload.total_amount) - totalParts) > 1) { toast("Charge categories should add up to the total amount.", "error"); return; }
      try {
        const response = await api("/api/bills", { method: "POST", body: payload });
        controller.update({ analysis: { bill: response.bill, result: response.analysis } });
        renderAnalysis(response.bill, response.analysis); controller.go("analysis");
        updateLanding(response.bill); toast("Bill analysis saved locally.");
      } catch (error) { toast(error.message, "error"); }
    });
    function updateLanding(bill) {
      $("#bill-landing-total").textContent = `AED ${Number(bill.total_amount).toFixed(0)}`;
      $("#bill-landing-due").textContent = `Due ${bill.due_date}`;
      $("#bill-landing-anomaly").textContent = bill.anomaly_summary;
    }
    function renderAnalysis(bill, result) {
      if (!bill || !result) return;
      $("#analysis-total").textContent = Number(bill.total_amount).toFixed(0); $("#analysis-due").textContent = bill.due_date;
      $("#legend-data").textContent = `AED ${bill.data_charges}`; $("#legend-calls").textContent = `AED ${bill.call_charges}`; $("#legend-roaming").textContent = `AED ${bill.roaming_charges}`; $("#legend-addons").textContent = `AED ${bill.addon_charges}`;
      $("#anomaly-title").textContent = result.anomaly ? "Your bill is 28% higher than usual" : "No unusual charges detected";
      $("#anomaly-copy").textContent = result.summary;
      $(".anomaly-card .overline").textContent = result.anomaly ? "ANOMALY DETECTED" : "NO ANOMALY";
    }
    $(".expand-explanation")?.addEventListener("click", (event) => { const copy = $(".expand-copy"); copy.classList.toggle("open"); event.currentTarget.textContent = copy.classList.contains("open") ? "Hide explanation" : "See explanation"; });
    $("#switch-plan")?.addEventListener("click", () => confirmAction({ title: "Continue to plan page?", message: "Review the plan details before confirming any account change.", action: "Continue", onConfirm: () => toast("Plan details are ready for review. No account change was made.") }));
  });
})();
