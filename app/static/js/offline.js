(() => {
  "use strict";
  const status = document.querySelector("[data-connection-status]");
  const retry = document.querySelector("[data-offline-retry]");

  async function updateStatus() {
    if (!navigator.onLine) {
      status.textContent = "Server unavailable";
      status.classList.remove("online");
      retry.textContent = "Try again";
      return;
    }

    status.textContent = "Checking connection";
    status.classList.remove("online");
    try {
      const response = await fetch("/offline", {
        method: "HEAD",
        cache: "no-store",
        credentials: "same-origin",
      });
      if (!response.ok) throw new Error("Server health check failed");
      status.textContent = "Connection restored";
      status.classList.add("online");
      retry.textContent = "Continue";
    } catch {
      status.textContent = "Server unavailable";
      status.classList.remove("online");
      retry.textContent = "Try again";
    }
  }

  retry.addEventListener("click", () => window.location.assign("/"));
  window.addEventListener("online", () => void updateStatus());
  window.addEventListener("offline", updateStatus);
  void updateStatus();
})();
