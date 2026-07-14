(() => {
  "use strict";
  document.addEventListener("DOMContentLoaded", () => {
    if (!document.querySelector("#complaint-landing")) return;
    const { $, $$, delay, api, toast, openSheet, closeSheet, confirmAction } = window.App;
    const state = { step: 0, summary: "", category: "", when: "", location: "", occurring: "", severity: "Standard", human: false, latestTicketId: null };
    const landing = $("#complaint-landing"), chat = $("#complaint-chat"), formSection = $("#complaint-form-section"), diagnosis = $("#diagnosis-view"), success = $("#complaint-success");
    const questionSets = [
      { text: "Which category best matches the issue?", replies: ["Network", "Billing", "Service", "SIM or account", "Other"] },
      { text: "When did this happen?", replies: ["Today", "Yesterday", "This week"] },
      { text: "Where did it happen? You can share only the area or city.", replies: ["Dubai", "Abu Dhabi", "Sharjah", "Location not relevant"] },
      { text: "Is the issue still occurring?", replies: ["Still happening", "Resolved temporarily", "No longer happening"] },
      { text: "How serious is the impact?", replies: ["Unable to use service", "Major disruption", "Minor inconvenience", "Billing amount incorrect"] },
    ];

    function showOnly(section) {
      [landing, chat, formSection, diagnosis, success].forEach((item) => { item.hidden = item !== section; });
      $("#app-scroll").scrollTop = 0;
    }
    $("#start-complaint").addEventListener("click", () => openSheet("complaint-consent-sheet"));
    $("#consent-chat").addEventListener("click", () => {
      closeSheet("complaint-consent-sheet");
      if ((window.DemoStates?.complaints || "open") === "unavailable") { toast("The guided assistant is unavailable in this demo state. Your structured form is ready.", "error"); showForm(); }
      else showOnly(chat);
    });
    $("#consent-form").addEventListener("click", () => { closeSheet("complaint-consent-sheet"); showForm(); });
    $$('[data-exit-complaint]').forEach((button) => button.addEventListener("click", () => showOnly(landing)));
    $("#use-form").addEventListener("click", showForm); $("#form-instead").addEventListener("click", showForm);
    $("#back-to-chat").addEventListener("click", () => { preserveFromForm(); showOnly(chat); });
    function showForm() {
      $("#complaint-description").value = state.summary || $("#complaint-description").value;
      if (state.category) $("#complaint-category").value = state.category;
      $("#complaint-location").value = state.location || $("#complaint-location").value;
      $("#request-human").checked = state.human;
      showOnly(formSection);
    }
    function preserveFromForm() {
      state.summary = $("#complaint-description").value; state.category = $("#complaint-category").value; state.location = $("#complaint-location").value; state.severity = $("#complaint-severity").value; state.human = $("#request-human").checked;
    }
    $("#human-agent").addEventListener("click", () => { state.human = true; toast("Human review requested. Your details are preserved."); showForm(); });

    function addMessage(text, who = "assistant") {
      const wrapper = document.createElement("div"); wrapper.className = `message ${who}`;
      wrapper.innerHTML = who === "assistant" ? `<span class="assistant-avatar">e&amp;</span><div><p></p><time>Now</time></div>` : `<div><p></p><time>Now</time></div>`;
      $("p", wrapper).textContent = text; $("#complaint-messages").append(wrapper); wrapper.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
    async function assistantReply(text, replies = []) {
      const typing = document.createElement("div"); typing.className = "message assistant typing-message"; typing.innerHTML = '<span class="assistant-avatar">e&amp;</span><div class="typing-bubble"><span></span><span></span><span></span></div>';
      $("#complaint-messages").append(typing); typing.scrollIntoView({ behavior: "smooth" }); await delay(650); typing.remove(); addMessage(text);
      const chips = $("#complaint-quick-replies"); chips.innerHTML = "";
      replies.forEach((reply) => { const button = document.createElement("button"); button.type = "button"; button.textContent = reply; chips.append(button); });
    }
    async function sendMessage(text) {
      const value = (text || $("#complaint-input").value).trim(); if (!value) return;
      addMessage(value, "user"); $("#complaint-input").value = "";
      if (state.step === 0) state.summary = value;
      else if (state.step === 1) state.category = ["Network", "Billing", "Service", "SIM or account", "Other"].find((c) => value.toLowerCase().includes(c.toLowerCase())) || "Other";
      else if (state.step === 2) state.when = value;
      else if (state.step === 3) state.location = value;
      else if (state.step === 4) state.occurring = value;
      else if (state.step === 5) state.severity = /unable|major|incorrect/i.test(value) ? "High" : "Standard";
      state.step += 1;
      const progress = Math.min(100, 20 + state.step * 16); $("#complaint-progress").style.width = `${progress}%`; $("#complaint-progress-label").textContent = `${progress}% complete`;
      if (state.step <= 5) { const next = questionSets[state.step - 1]; await assistantReply(next.text, next.replies); }
      else { await assistantReply("Thanks — I’ve prepared a preliminary summary for your review."); await delay(350); renderDiagnosis(); }
    }
    $("#send-complaint-message").addEventListener("click", () => sendMessage());
    $("#complaint-input").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendMessage(); } });
    $("#complaint-quick-replies").addEventListener("click", (event) => { const button = event.target.closest("button"); if (button) sendMessage(button.textContent); });

    $("#complaint-attachment").addEventListener("change", async (event) => {
      const file = event.target.files[0]; if (!file) return;
      $("#complaint-attachment-name").textContent = file.name; $("#attachment-status").textContent = "Analysing attachment…"; $("#complaint-attachment-preview").hidden = false;
      await delay(900); $("#attachment-status").textContent = "Demo detail: service screenshot detected"; toast("Attachment analysed locally with placeholder logic.");
    });
    $("#remove-attachment").addEventListener("click", () => { $("#complaint-attachment").value = ""; $("#complaint-attachment-preview").hidden = true; });

    $("#complaint-form").addEventListener("submit", (event) => { event.preventDefault(); preserveFromForm(); if (state.summary.trim().length < 10) { toast("Please add at least 10 characters of detail.", "error"); return; } renderDiagnosis(); });
    function renderDiagnosis() {
      const category = state.category || "Service"; const route = category === "Network" ? "Network Operations" : category === "Billing" ? "Billing Care" : "Customer Care";
      $("#diagnosis-category").textContent = category; $("#diagnosis-issue").textContent = state.summary.slice(0, 90); $("#diagnosis-location").textContent = state.location || "Not provided"; $("#diagnosis-severity").textContent = state.severity || "Standard"; $("#diagnosis-route").textContent = route;
      $("#diagnosis-explanation").textContent = category === "Network" ? "Your report appears consistent with a temporary area network interruption. The complaint will be routed to Network Operations." : "Your report needs an account-level review by the appropriate support team.";
      showOnly(diagnosis);
    }
    $("#edit-complaint").addEventListener("click", showForm);
    $("#request-human-review").addEventListener("click", () => { state.human = true; toast("Human review added to the routing request."); });
    $("#submit-complaint").addEventListener("click", async () => {
      const button = $("#submit-complaint"); button.disabled = true; button.textContent = "Submitting securely…";
      try {
        const response = await api("/api/complaints", { method: "POST", body: { summary: state.summary, category: state.category, severity: state.severity, location: state.location, simulate_failure: (window.DemoStates?.complaints || "open") === "failure" } });
        state.latestTicketId = response.ticket.id; $("#success-ticket-number").textContent = response.ticket.ticket_number; showOnly(success); toast("Complaint ticket created and saved locally.");
      } catch (error) { toast(error.message, "error"); }
      button.disabled = false; button.textContent = "Confirm and submit";
    });
    $("[data-copy-ticket]").addEventListener("click", async () => { await navigator.clipboard?.writeText($("#success-ticket-number").textContent); toast("Ticket number copied."); });
    $("#view-new-ticket").addEventListener("click", () => openTicket(state.latestTicketId));

    async function openTicket(id) {
      if (!id) return;
      try {
        const response = await api(`/api/complaints/${id}`); const ticket = response.ticket;
        $("#ticket-detail-number").textContent = ticket.ticket_number; $("#ticket-detail-status").textContent = ticket.status; $("#ticket-detail-summary").textContent = ticket.summary; $("#ticket-detail-category").textContent = ticket.category; $("#ticket-detail-severity").textContent = ticket.severity; $("#ticket-detail-expected").textContent = ticket.expected_resolution; $("#ticket-detail-department").textContent = ticket.assigned_department; $("#ticket-detail-update").textContent = ticket.latest_update;
        $("#ticket-sheet").dataset.ticketId = id; openSheet("ticket-sheet");
      } catch (error) { toast(error.message, "error"); }
    }
    $("#ticket-list").addEventListener("click", (event) => { const row = event.target.closest("[data-ticket-id]"); if (row) openTicket(row.dataset.ticketId); });
    $(".open-ticket-card [data-ticket-id]")?.addEventListener("click", (event) => openTicket(event.currentTarget.dataset.ticketId));
    $("#track-complaint").addEventListener("click", () => { const first = $("[data-ticket-id]"); if (first) openTicket(first.dataset.ticketId); else toast("There are no local complaint tickets to track."); });
    $$("[data-ticket-filter]").forEach((button) => button.addEventListener("click", () => { $$("[data-ticket-filter]").forEach((item) => item.classList.toggle("active", item === button)); $$(".ticket-row").forEach((row) => { const value = button.dataset.ticketFilter; row.hidden = value !== "all" && (value === "resolved" ? row.dataset.ticketStatus !== "resolved" : row.dataset.ticketStatus === "resolved"); }); }));
    $("#add-ticket-note").addEventListener("click", () => confirmAction({ title: "Add a supporting note?", message: "A demonstration note stating that more evidence is available will be added to the ticket.", action: "Add note", onConfirm: async () => { try { const id = $("#ticket-sheet").dataset.ticketId; const data = await api(`/api/complaints/${id}/note`, { method: "POST", body: { note: "Additional supporting information is available on request." } }); $("#ticket-detail-update").textContent = data.ticket.latest_update; toast("Supporting note added locally."); } catch (error) { toast(error.message, "error"); } } }));
    $("#close-ticket").addEventListener("click", () => confirmAction({ title: "Close this ticket?", message: "This demonstration action marks the local ticket as resolved.", action: "Close ticket", tone: "danger", onConfirm: async () => { try { const id = $("#ticket-sheet").dataset.ticketId; const data = await api(`/api/complaints/${id}/close`, { method: "POST" }); $("#ticket-detail-status").textContent = data.ticket.status; $("#ticket-detail-update").textContent = data.ticket.latest_update; toast("Ticket marked resolved in the prototype."); } catch (error) { toast(error.message, "error"); } } }));
  });
})();
