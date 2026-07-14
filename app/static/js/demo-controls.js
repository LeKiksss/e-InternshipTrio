(() => {
  "use strict";
  window.DemoStates = { dashboard: "normal", network: "strong", bill: "normal", complaints: "open", roaming: "normal" };
  document.addEventListener("DOMContentLoaded", () => {
    if (!document.querySelector("#demo-sheet")) return;
    const { $, $$, api, toast, openSheet, closeSheet, confirmAction } = window.App;
    $("#open-demo-controls")?.addEventListener("click", () => openSheet("demo-sheet"));
    let shortcut = "";
    document.addEventListener("keydown", (event) => {
      if (["INPUT", "TEXTAREA", "SELECT"].includes(event.target.tagName)) return;
      shortcut = (shortcut + event.key.toLowerCase()).slice(-2);
      if (shortcut === "ds") { openSheet("demo-sheet"); shortcut = ""; }
      setTimeout(() => { shortcut = ""; }, 900);
    });

    $$('[data-demo-control]').forEach((select) => select.addEventListener("change", () => {
      const area = select.dataset.demoControl; window.DemoStates[area] = select.value; applyState(area, select.value); toast(`${area[0].toUpperCase() + area.slice(1)} state: ${select.options[select.selectedIndex].text}.`);
    }));
    function applyState(area, value) {
      if (area === "dashboard") {
        const grid = $("#dashboard-widgets"), error = $("#dashboard-error"), alerts = $("#alert-list"), empty = $("#alerts-empty");
        grid.hidden = value === "error"; error.hidden = value !== "error"; alerts.hidden = value === "empty"; empty.hidden = value !== "empty";
        $$(".use-card", grid).forEach((card) => card.classList.toggle("skeleton", value === "loading"));
      }
      if (area === "network") {
        const history = $("#diagnostic-history");
        let empty = $("#demo-empty-diagnostics");
        if (!empty) { empty = document.createElement("div"); empty.id = "demo-empty-diagnostics"; empty.className = "empty-card"; empty.innerHTML = '<div class="empty-icon">⌁</div><h3>No local history</h3><p>Run a test to add the first demonstration result.</p>'; history.append(empty); }
        empty.hidden = value !== "empty"; $$(".history-card", history).forEach((card) => card.hidden = value === "empty");
      }
      if (area === "bill") {
        let empty = $("#demo-empty-bills");
        if (!empty) { empty = document.createElement("div"); empty.id = "demo-empty-bills"; empty.className = "empty-card"; empty.innerHTML = '<div class="empty-icon">▤</div><h3>No billing history</h3><p>Upload or enter a fictional bill to begin.</p>'; $(".bill-summary-card").after(empty); }
        empty.hidden = value !== "empty"; $(".bill-summary-card").hidden = value === "empty";
        if (value === "anomaly") { $("#anomaly-title").textContent = "Your bill is 28% higher than usual"; $("#anomaly-copy").textContent = "Most of the increase came from roaming charges."; }
      }
      if (area === "complaints") {
        const card = $(".open-ticket-card"); if (card) card.hidden = value === "none";
        if (value === "resolved") { $$(".status-badge", $("#complaint-landing")).forEach((badge) => badge.textContent = "Resolved"); }
        if (value === "open") { if (card) card.hidden = false; $$(".status-badge", $("#complaint-landing")).forEach((badge) => { if (badge.textContent === "Resolved") badge.textContent = "Assigned"; }); }
      }
      if (area === "roaming" && value !== "normal") { /* Applied by recommendation flow; selector change is intentionally non-destructive. */ }
    }
    $("[data-demo-retry]")?.addEventListener("click", () => { const control = $('[data-demo-control="dashboard"]'); control.value = "normal"; control.dispatchEvent(new Event("change")); });
    $("#reset-demo-data").addEventListener("click", () => confirmAction({ title: "Reset demonstration data?", message: "Seeded diagnostics, bills, and complaint tickets for the demo account will be restored.", action: "Reset data", tone: "danger", onConfirm: async () => {
      try { const data = await api("/api/demo/reset", { method: "POST" }); toast(data.message); closeSheet("demo-sheet"); setTimeout(() => location.reload(), 800); } catch (error) { toast(error.message, "error"); }
    }}));
  });
})();
