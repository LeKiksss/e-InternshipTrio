(() => {
  "use strict";
  document.addEventListener("DOMContentLoaded", () => {
    if (!window.App || !document.querySelector(".app-shell")) return;
    const { $, $$, closeSheet, animateView } = window.App;
    const screenOrder = ["home", "network-bill", "complaints", "roaming", "profile"];
    const titles = {
      home: ["Good afternoon", `Hi, ${$("#header-title").textContent.replace("Hi, ", "")}`],
      "network-bill": ["Smart insights", "Network & bill"],
      complaints: ["Assisted support", "Complaints"],
      roaming: ["Travel planning", "Roaming Recommender"],
      profile: ["Your account", "Profile"],
    };

    function navigate(screen, targetSegment, { historyMode = "push", direction = null } = {}) {
      const incoming = document.querySelector(`.screen[data-screen="${screen}"]`);
      if (!incoming) return;
      const previous = $(".app-shell").dataset.currentScreen;
      const previousIndex = screenOrder.indexOf(previous);
      const index = screenOrder.indexOf(screen);
      const resolvedDirection = direction || (previousIndex < 0 || previous === screen ? "none" : index >= previousIndex ? "forward" : "back");
      $$(".screen").forEach((panel) => panel.classList.toggle("active", panel.dataset.screen === screen));
      animateView(incoming, resolvedDirection);
      $$(".bottom-nav button").forEach((button) => button.classList.toggle("active", button.dataset.nav === screen));
      $(".nav-indicator").style.left = `calc(${index * 20 + 10}% - 18px)`;
      $(".app-shell").dataset.currentScreen = screen;
      $("#header-eyebrow").textContent = titles[screen][0];
      $("#header-title").textContent = titles[screen][1];
      $("#app-scroll").scrollTop = 0;
      if (targetSegment) document.querySelector(`[data-segment="${targetSegment}"]`)?.click();
      $$(".modal-backdrop:not([hidden])").forEach(closeSheet);
      const state = { screen };
      if (historyMode === "replace") history.replaceState(state, "", `#${screen}`);
      else if (historyMode === "push") history.pushState(state, "", `#${screen}`);
    }
    window.App.navigate = navigate;
    $$('[data-nav]').forEach((button) => button.addEventListener("click", () => navigate(button.dataset.nav, button.dataset.targetSegment)));
    $$("[data-notification-nav]").forEach((button) => button.addEventListener("click", () => {
      button.classList.remove("unread");
      navigate(button.dataset.notificationNav, button.dataset.targetSegment);
    }));
    $$("[data-segment]").forEach((button) => button.addEventListener("click", () => {
      $$("[data-segment]").forEach((item) => item.classList.toggle("active", item === button));
      $$("[data-panel]").forEach((panel) => { const active = panel.dataset.panel === button.dataset.segment; panel.classList.toggle("active", active); panel.hidden = !active; });
    }));
    window.addEventListener("popstate", (event) => {
      if (event.state?.workflow) return;
      const screen = event.state?.screen || location.hash.slice(1).split("/")[0] || "home";
      if (titles[screen]) navigate(screen, null, { historyMode: "none", direction: "back" });
    });
    const initial = location.hash.slice(1).split("/")[0];
    navigate(titles[initial] ? initial : "home", null, { historyMode: "replace", direction: "none" });
  });
})();
