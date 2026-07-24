(() => {
  "use strict";
  document.addEventListener("DOMContentLoaded", async () => {
    if (!document.querySelector("#complaint-landing")) return;
    const { $, $$, delay, api, toast, openSheet, closeSheet, confirmAction } = window.App;
    const landing = $("#complaint-landing"), chat = $("#complaint-chat"), formSection = $("#complaint-form-section"), diagnosis = $("#diagnosis-view"), success = $("#complaint-success");
    const questions = [
      { text: "Tell me what went wrong. Share only what is needed—please avoid sensitive information.", replies: [] },
      { text: "Which category best matches the issue?", replies: ["Network", "Billing", "Service", "SIM or account", "Other"] },
      { text: "When did this happen?", replies: ["Today", "Yesterday", "This week"] },
      { text: "Where did it happen? You can share only the area or city.", replies: ["Dubai", "Abu Dhabi", "Sharjah", "Location not relevant"] },
      { text: "Is the issue still occurring?", replies: ["Still happening", "Resolved temporarily", "No longer happening"] },
      { text: "How serious is the impact?", replies: ["Unable to use service", "Major disruption", "Minor inconvenience", "Billing amount incorrect"] },
    ];
    const initialState = {
      step: 0, answers: [], summary: "", category: "", when: "", location: "", occurring: "",
      severity: "Standard", human: false, attachment: null, latestTicket: null, reviewSource: "chat",
    };
    const controller = window.WorkflowState.create({
      name: "complaints",
      viewOrder: ["landing", "chat", "form", "diagnosis", "success"],
      initialState,
      render(view, state) {
        const sections = { landing, chat, form: formSection, diagnosis, success };
        [landing, chat, formSection, diagnosis, success].forEach((section) => {
          section.hidden = section !== (sections[view] || landing);
        });
        if (view === "chat") renderChat();
        if (view === "form") populateForm();
        if (view === "diagnosis") populateDiagnosis();
        if (view === "success" && state.latestTicket) $("#success-ticket-number").textContent = state.latestTicket.ticket_number;
        renderAttachment();
        $("#app-scroll").scrollTop = 0;
        return sections[view] || landing;
      },
    });
    await controller.restore();

    function startComplaint(useForm = false) {
      controller.update({ reviewSource: useForm ? "form" : "chat" });
      if ((window.DemoStates?.complaints || "open") === "unavailable" && !useForm) {
        toast("The guided assistant is unavailable. Your structured form is ready.", "error");
        controller.go("form");
      } else controller.go(useForm ? "form" : "chat");
    }
    $("#start-complaint").addEventListener("click", () => openSheet("complaint-consent-sheet"));
    $("#consent-chat").addEventListener("click", () => { closeSheet("complaint-consent-sheet"); startComplaint(false); });
    $("#consent-form").addEventListener("click", () => { closeSheet("complaint-consent-sheet"); startComplaint(true); });
    $$('[data-exit-complaint]').forEach((button) => button.addEventListener("click", () => controller.go("landing")));
    $("#use-form").addEventListener("click", showForm); $("#form-instead").addEventListener("click", showForm);
    $("#back-to-chat").addEventListener("click", () => { preserveFromForm(); controller.go("chat"); });
    function showForm() { controller.update({ reviewSource: "form" }); controller.go("form"); }
    function populateForm() {
      $("#complaint-description").value = controller.state.summary || "";
      if (controller.state.category) $("#complaint-category").value = controller.state.category;
      $("#complaint-location").value = controller.state.location || "";
      $("#complaint-severity").value = controller.state.severity || "Standard";
      $("#request-human").checked = controller.state.human;
    }
    function preserveFromForm() {
      controller.update({
        summary: $("#complaint-description").value,
        category: $("#complaint-category").value,
        location: $("#complaint-location").value,
        severity: $("#complaint-severity").value,
        human: $("#request-human").checked,
      });
    }
    $("#human-agent").addEventListener("click", () => { controller.update({ human: true }); toast("Human review requested. Your details are preserved."); showForm(); });

    function messageNode(text, who = "assistant") {
      const wrapper = document.createElement("div"); wrapper.className = `message ${who}`;
      wrapper.innerHTML = who === "assistant" ? `<span class="assistant-avatar">e&amp;</span><div><p></p><time>Now</time></div>` : `<div><p></p><time>Now</time></div>`;
      $("p", wrapper).textContent = text; return wrapper;
    }
    function renderChat() {
      const messages = $("#complaint-messages"); messages.innerHTML = "";
      messages.append(messageNode(questions[0].text));
      controller.state.answers.forEach((answer, index) => {
        messages.append(messageNode(answer, "user"));
        if (questions[index + 1]) messages.append(messageNode(questions[index + 1].text));
      });
      const current = questions[Math.min(controller.state.step, questions.length - 1)];
      const chips = $("#complaint-quick-replies"); chips.innerHTML = "";
      (current?.replies || []).forEach((reply) => { const button = document.createElement("button"); button.type = "button"; button.textContent = reply; chips.append(button); });
      const progress = Math.min(100, 16 + controller.state.step * 14);
      $("#complaint-progress").style.width = `${progress}%`; $("#complaint-progress-label").textContent = `${progress}% complete`;
      messages.lastElementChild?.scrollIntoView({ block: "nearest" });
    }
    function applyAnswer(index, value) {
      if (index === 0) controller.state.summary = value;
      else if (index === 1) controller.state.category = ["Network", "Billing", "Service", "SIM or account", "Other"].find((category) => value.toLowerCase().includes(category.toLowerCase())) || "Other";
      else if (index === 2) controller.state.when = value;
      else if (index === 3) controller.state.location = value;
      else if (index === 4) controller.state.occurring = value;
      else if (index === 5) controller.state.severity = /unable|major|incorrect/i.test(value) ? "High" : "Standard";
    }
    async function sendMessage(text) {
      const value = (text || $("#complaint-input").value).trim(); if (!value) { toast("Enter a response before continuing.", "error"); return; }
      const answers = [...controller.state.answers.slice(0, controller.state.step), value];
      applyAnswer(controller.state.step, value);
      controller.update({ answers, step: controller.state.step + 1, reviewSource: "chat" });
      $("#complaint-input").value = "";
      renderChat();
      if (controller.state.step >= questions.length) {
        await delay(window.PROTOTYPE?.testing ? 20 : 450);
        controller.go("diagnosis");
      }
    }
    $("#send-complaint-message").addEventListener("click", () => sendMessage());
    $("#complaint-input").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendMessage(); } });
    $("#complaint-quick-replies").addEventListener("click", (event) => { const button = event.target.closest("button"); if (button) sendMessage(button.textContent); });
    $("#complaint-chat-back").addEventListener("click", () => {
      if (controller.state.step < 1) { controller.go("landing"); return; }
      const previousIndex = controller.state.step - 1;
      const previousValue = controller.state.answers[previousIndex] || "";
      controller.update({ step: previousIndex, answers: controller.state.answers.slice(0, previousIndex) });
      $("#complaint-input").value = previousValue;
      renderChat();
    });

    $("#complaint-attachment").addEventListener("change", async (event) => {
      const file = event.target.files[0]; if (!file) return;
      controller.update({ attachment: { name: file.name, status: "Analysing attachment…" } }); renderAttachment();
      await delay(window.PROTOTYPE?.testing ? 20 : 900);
      controller.update({ attachment: { name: file.name, status: "Service screenshot detected" } }); renderAttachment();
      toast("Attachment details captured for your review.");
    });
    function renderAttachment() {
      const attachment = controller.state.attachment;
      $("#complaint-attachment-preview").hidden = !attachment;
      if (attachment) { $("#complaint-attachment-name").textContent = attachment.name; $("#attachment-status").textContent = attachment.status; }
    }
    $("#remove-attachment").addEventListener("click", () => { controller.update({ attachment: null }); $("#complaint-attachment").value = ""; renderAttachment(); });

    $("#complaint-form").addEventListener("submit", (event) => { event.preventDefault(); preserveFromForm(); if (controller.state.summary.trim().length < 10) { toast("Please add at least 10 characters of detail.", "error"); return; } controller.go("diagnosis"); });
    function populateDiagnosis() {
      const state = controller.state; const category = state.category || "Service"; const route = category === "Network" ? "Network Operations" : category === "Billing" ? "Billing Care" : "Customer Care";
      $("#diagnosis-category").textContent = category; $("#diagnosis-issue").textContent = state.summary.slice(0, 90); $("#diagnosis-location").textContent = state.location || "Not provided"; $("#diagnosis-severity").textContent = state.severity || "Standard"; $("#diagnosis-route").textContent = route;
      $("#diagnosis-explanation").textContent = category === "Network" ? "Your report appears consistent with a temporary area network interruption. The complaint will be routed to Network Operations." : "Your report needs an account-level review by the appropriate support team.";
    }
    $("#edit-complaint").addEventListener("click", () => controller.go(controller.state.reviewSource === "chat" ? "chat" : "form"));
    $("#request-human-review").addEventListener("click", () => { controller.update({ human: true }); toast("Human review added to the routing request."); });
    $("#submit-complaint").addEventListener("click", async () => {
      const button = $("#submit-complaint"); button.disabled = true; button.textContent = "Submitting securely…";
      try {
        const state = controller.state;
        const response = await api("/api/complaints", { method: "POST", body: { summary: state.summary, category: state.category, severity: state.severity, location: state.location, simulate_failure: (window.DemoStates?.complaints || "open") === "failure" } });
        controller.update({ latestTicket: response.ticket }); updateTicketLanding(response.ticket); controller.go("success"); toast("Complaint ticket created and saved locally.");
      } catch (error) { toast(error.message, "error"); }
      button.disabled = false; button.textContent = "Confirm and submit";
    });
    $("#complaint-success-back").addEventListener("click", () => controller.go("diagnosis"));
    $("#complaint-done").addEventListener("click", () => controller.go("landing"));
    $("#complaint-start-new").addEventListener("click", async () => { await controller.reset(); openSheet("complaint-consent-sheet"); });
    $("[data-copy-ticket]").addEventListener("click", async () => { await navigator.clipboard?.writeText($("#success-ticket-number").textContent); toast("Ticket number copied."); });
    $("#view-new-ticket").addEventListener("click", () => openTicket(controller.state.latestTicket?.id));

    function updateTicketLanding(ticket) {
      let card = $("#complaint-latest-dynamic");
      if (!card) { card = document.createElement("section"); card.id = "complaint-latest-dynamic"; card.className = "card open-ticket-card"; $("#complaint-landing .button-stack").after(card); }
      card.innerHTML = `<div class="card-head"><span class="overline">LATEST TICKET</span><span class="status-badge">${escapeHTML(ticket.status)}</span></div><h3>${escapeHTML(ticket.ticket_number)}</h3><p>${escapeHTML(ticket.summary)}</p><small>${escapeHTML(ticket.latest_update)}</small><button class="card-cta" type="button" data-ticket-id="${ticket.id}">View ticket <svg><use href="#i-arrow"/></svg></button>`;
      const row = document.createElement("button"); row.type = "button"; row.className = "ticket-row"; row.dataset.ticketId = ticket.id; row.dataset.ticketStatus = ticket.status.toLowerCase(); row.innerHTML = `<span class="ticket-icon">${escapeHTML(ticket.category[0])}</span><span><b>${escapeHTML(ticket.ticket_number)}</b><small>${escapeHTML(ticket.category)} · just now</small></span><span class="status-badge">${escapeHTML(ticket.status)}</span>`;
      $("#ticket-list .empty-card")?.remove(); $("#ticket-list").prepend(row);
    }
    function escapeHTML(value) { const div = document.createElement("div"); div.textContent = value ?? ""; return div.innerHTML; }
    async function openTicket(id) {
      if (!id) return;
      try {
        const response = await api(`/api/complaints/${id}`); const ticket = response.ticket;
        $("#ticket-detail-number").textContent = ticket.ticket_number; $("#ticket-detail-status").textContent = ticket.status; $("#ticket-detail-summary").textContent = ticket.summary; $("#ticket-detail-category").textContent = ticket.category; $("#ticket-detail-severity").textContent = ticket.severity; $("#ticket-detail-expected").textContent = ticket.expected_resolution; $("#ticket-detail-department").textContent = ticket.assigned_department; $("#ticket-detail-update").textContent = ticket.latest_update;
        $("#ticket-sheet").dataset.ticketId = id; openSheet("ticket-sheet");
      } catch (error) { toast(error.message, "error"); }
    }
    $("#ticket-list").addEventListener("click", (event) => { const row = event.target.closest("[data-ticket-id]"); if (row) openTicket(row.dataset.ticketId); });
    $("#complaint-landing").addEventListener("click", (event) => { const row = event.target.closest("[data-ticket-id]"); if (row && !row.closest("#ticket-list")) openTicket(row.dataset.ticketId); });
    $("#track-complaint").addEventListener("click", () => { const first = $("#ticket-list [data-ticket-id]"); if (first) openTicket(first.dataset.ticketId); else toast("There are no local complaint tickets to track."); });
    $$("[data-ticket-filter]").forEach((button) => button.addEventListener("click", () => { $$("[data-ticket-filter]").forEach((item) => item.classList.toggle("active", item === button)); $$(".ticket-row").forEach((row) => { const value = button.dataset.ticketFilter; row.hidden = value !== "all" && (value === "resolved" ? row.dataset.ticketStatus !== "resolved" : row.dataset.ticketStatus === "resolved"); }); }));
    $("#add-ticket-note").addEventListener("click", () => confirmAction({ title: "Add a supporting note?", message: "A note stating that more evidence is available will be added to the ticket.", action: "Add note", onConfirm: async () => { try { const id = $("#ticket-sheet").dataset.ticketId; const data = await api(`/api/complaints/${id}/note`, { method: "POST", body: { note: "Additional supporting information is available on request." } }); $("#ticket-detail-update").textContent = data.ticket.latest_update; toast("Supporting note added."); } catch (error) { toast(error.message, "error"); } } }));
    $("#close-ticket").addEventListener("click", () => confirmAction({ title: "Close this ticket?", message: "This marks the ticket as resolved.", action: "Close ticket", tone: "danger", onConfirm: async () => { try { const id = $("#ticket-sheet").dataset.ticketId; const data = await api(`/api/complaints/${id}/close`, { method: "POST" }); $("#ticket-detail-status").textContent = data.ticket.status; $("#ticket-detail-update").textContent = data.ticket.latest_update; toast("Ticket marked as resolved."); } catch (error) { toast(error.message, "error"); } } }));
  });
})();
