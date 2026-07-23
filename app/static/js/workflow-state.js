(() => {
  "use strict";

  const controllers = new Map();
  const clone = (value) => JSON.parse(JSON.stringify(value));

  class WorkflowController {
    constructor({ name, initialState, initialView = "landing", render, serializeState = null, viewOrder = [] }) {
      this.name = name;
      this.initialState = clone(initialState);
      this.state = clone(initialState);
      this.view = initialView;
      this.initialView = initialView;
      this.render = render;
      this.serializeState = serializeState;
      this.viewOrder = viewOrder;
      this.stack = [initialView];
      this.saveTimer = null;
      controllers.set(name, this);
    }

    async restore() {
      try {
        const response = await window.App.api(`/api/workflows/${this.name}`);
        this.state = { ...clone(this.initialState), ...(response.state || {}) };
        this.view = response.view && response.view !== "landing" ? response.view : this.initialView;
        this.stack = [this.initialView];
        if (this.view !== this.initialView) this.stack.push(this.view);
      } catch {
        this.state = clone(this.initialState);
        this.view = this.initialView;
        this.stack = [this.initialView];
      }
      this.render(this.view, this.state, { direction: "none", previousView: null });
      return this.state;
    }

    update(values, persist = true) {
      Object.assign(this.state, values);
      if (persist) this.scheduleSave();
      return this.state;
    }

    transitionDirection(previousView, nextView, requestedDirection, push) {
      if (requestedDirection) return requestedDirection;
      const previousIndex = this.viewOrder.indexOf(previousView);
      const nextIndex = this.viewOrder.indexOf(nextView);
      if (previousIndex >= 0 && nextIndex >= 0 && previousIndex !== nextIndex) {
        return nextIndex > previousIndex ? "forward" : "back";
      }
      return push ? "forward" : "back";
    }

    go(view, { push = true, save = true, replace = false, direction = null } = {}) {
      if (!view) return;
      const previousView = this.view;
      const resolvedDirection = this.transitionDirection(previousView, view, direction, push);
      this.view = view;
      if (push && this.stack.at(-1) !== view) this.stack.push(view);
      this.render(view, this.state, { direction: resolvedDirection, previousView });
      if (save) void this.save();
      const screen = document.querySelector(".app-shell")?.dataset.currentScreen;
      const historyState = { screen, workflow: this.name, step: view };
      if (replace) history.replaceState(historyState, "", `#${screen || this.name}/${view}`);
      else if (push) history.pushState(historyState, "", `#${screen || this.name}/${view}`);
    }

    back(fallback = this.initialView) {
      if (this.stack.length > 1) this.stack.pop();
      this.go(this.stack.at(-1) || fallback, { push: false });
    }

    scheduleSave() {
      clearTimeout(this.saveTimer);
      this.saveTimer = setTimeout(() => this.save(), 120);
    }

    async save() {
      clearTimeout(this.saveTimer);
      try {
        await window.App.api(`/api/workflows/${this.name}`, {
          method: "PUT",
          keepalive: true,
          body: { view: this.view, state: this.serializeState ? this.serializeState(this.state) : this.state },
        });
      } catch (error) {
        window.App.toast(error.message || "Draft state could not be saved.", "error");
      }
    }

    async reset({ view = this.initialView, render = true } = {}) {
      clearTimeout(this.saveTimer);
      this.state = clone(this.initialState);
      this.view = view;
      this.stack = [view];
      try { await window.App.api(`/api/workflows/${this.name}`, { method: "DELETE" }); } catch { /* The fresh local state is still usable. */ }
      if (render) this.render(view, this.state, { direction: "none", previousView: null });
      return this.state;
    }
  }

  window.WorkflowState = {
    create(options) { return new WorkflowController(options); },
    get(name) { return controllers.get(name); },
  };

  window.addEventListener("popstate", (event) => {
    const state = event.state;
    if (!state?.workflow || !state.step) return;
    const controller = controllers.get(state.workflow);
    if (!controller) return;
    const previousView = controller.view;
    controller.view = state.step;
    if (controller.stack.at(-1) !== state.step) controller.stack.push(state.step);
    const direction = controller.transitionDirection(previousView, state.step, "back", false);
    controller.render(state.step, controller.state, { direction, previousView });
    controller.scheduleSave();
  });
})();
