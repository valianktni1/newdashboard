(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const state = {links: [], settings: {}, category: "All", search: "", editing: false};
  const categoryIcons = {All: "⌂", Business: "▤", Clients: "♡", Server: "▦", Marketing: "✦", Other: "◇"};

  function esc(value = "") {
    return String(value ?? "").replace(/[&<>'"]/g, char => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"}[char]));
  }

  function attr(value = "") { return esc(value); }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      credentials: "same-origin",
      headers: {"Content-Type": "application/json", ...(options.headers || {})},
      ...options,
    });
    if (response.status === 401 && path !== "/api/auth/login") {
      showLogin();
      throw new Error("Please sign in again");
    }
    if (response.status === 204) return null;
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = Array.isArray(data.detail) ? data.detail.map(item => item.msg).join(", ") : data.detail;
      throw new Error(detail || "Something went wrong");
    }
    return data;
  }

  function toast(message, type = "") {
    const element = $("#toast");
    element.textContent = message;
    element.className = `toast ${type}`;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => element.classList.add("hidden"), 3200);
  }

  function showLogin(message = "") {
    $("#dashboard-app").classList.add("hidden");
    $("#login-screen").classList.remove("hidden");
    $("#login-error").textContent = message;
  }

  function showDashboard() {
    $("#login-screen").classList.add("hidden");
    $("#dashboard-app").classList.remove("hidden");
  }

  function greeting() {
    const hour = new Date().getHours();
    const word = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
    return `${word}, ${state.settings.greeting_name || "Mark"}.`;
  }

  function categories() {
    return [...new Set(state.links.map(link => link.category).filter(Boolean))].sort((a, b) => a.localeCompare(b));
  }

  function visibleLinks() {
    const query = state.search.trim().toLowerCase();
    return state.links.filter(link => {
      if (!state.editing && !link.active) return false;
      if (state.category !== "All" && link.category !== state.category) return false;
      return !query || `${link.name} ${link.description} ${link.category} ${link.url}`.toLowerCase().includes(query);
    });
  }

  function renderNavigation() {
    const allCategories = ["All", ...categories()];
    $("#category-nav").innerHTML = `<p class="nav-label">WORKSPACES</p>${allCategories.map(category => {
      const count = category === "All" ? state.links.filter(link => link.active).length : state.links.filter(link => link.active && link.category === category).length;
      return `<button class="category-button ${state.category === category ? "active" : ""}" data-category="${attr(category)}"><span>${esc(categoryIcons[category] || "◇")}</span><span>${esc(category)}</span><b>${count}</b></button>`;
    }).join("")}`;
    $$('[data-category]').forEach(button => button.onclick = () => selectCategory(button.dataset.category));
  }

  function card(link, index) {
    const tag = state.editing ? "article" : "a";
    const navigation = state.editing ? "" : `href="${attr(link.url)}" ${link.open_new_tab ? 'target="_blank" rel="noopener noreferrer"' : ""}`;
    const editActions = state.editing ? `<div class="card-edit-actions">
      <button type="button" data-move="up" data-id="${link.id}" title="Move earlier" ${index === 0 ? "disabled" : ""}>↑</button>
      <button type="button" data-move="down" data-id="${link.id}" title="Move later" ${index === state.links.length - 1 ? "disabled" : ""}>↓</button>
      <button type="button" data-edit-link="${link.id}" title="Edit shortcut">✎</button>
    </div>` : "";
    return `<${tag} class="link-card ${link.active ? "" : "inactive"}" style="--accent:${attr(link.accent)}" ${navigation}>
      ${editActions}${link.pinned ? '<span class="pin-badge" title="Pinned">◆</span>' : ""}
      <div class="card-top"><span class="service-icon">${esc(link.icon)}</span><span class="card-arrow">↗</span></div>
      <div class="card-copy"><small>${esc(link.category)}${link.active ? "" : " · hidden"}</small><h3>${esc(link.name)}</h3><p>${esc(link.description || link.url)}</p></div>
    </${tag}>`;
  }

  function render() {
    renderNavigation();
    $("#greeting").textContent = greeting();
    $("#dashboard-subtitle").textContent = state.settings.dashboard_subtitle || "Every part of the business, one click away.";
    document.title = state.settings.dashboard_title || "Weddings By Mark Control Centre";
    const activeLinks = state.links.filter(link => link.active);
    $("#visible-count").textContent = activeLinks.length;
    $("#category-count").textContent = categories().length;
    $("#section-eyebrow").textContent = state.category === "All" ? "ALL SERVICES" : state.category.toUpperCase();
    $("#section-title").textContent = state.search ? `Results for “${state.search}”` : state.category === "All" ? "Your control centre" : `${state.category} services`;
    const links = visibleLinks();
    $("#link-grid").innerHTML = links.map(link => card(link, state.links.findIndex(item => item.id === link.id))).join("");
    $("#link-grid").classList.toggle("edit-mode", state.editing);
    $("#empty-state").classList.toggle("hidden", links.length > 0);
    $("#edit-banner").classList.toggle("hidden", !state.editing);
    $("#edit-toggle").classList.toggle("active", state.editing);
    $$('[data-edit-link]').forEach(button => button.onclick = () => openLinkModal(state.links.find(link => link.id === Number(button.dataset.editLink))));
    $$('[data-move]').forEach(button => button.onclick = () => moveLink(Number(button.dataset.id), button.dataset.move));
  }

  function selectCategory(category) {
    state.category = category;
    render();
    closeSidebar();
  }

  function toggleEditing(on = !state.editing) {
    state.editing = on;
    if (on) {
      state.category = "All";
      state.search = "";
      $("#search").value = "";
      toast("Editing is on — every shortcut is now changeable.");
    }
    render();
  }

  async function moveLink(id, direction) {
    const index = state.links.findIndex(link => link.id === id);
    const next = direction === "up" ? index - 1 : index + 1;
    if (index < 0 || next < 0 || next >= state.links.length) return;
    [state.links[index], state.links[next]] = [state.links[next], state.links[index]];
    render();
    try {
      await api("/api/links/reorder", {method: "PUT", body: JSON.stringify({link_ids: state.links.map(link => link.id)})});
      toast("Shortcut order saved");
    } catch (error) {
      await loadDashboard();
      toast(error.message, "error");
    }
  }

  function showModal(content) {
    $("#modal-content").innerHTML = content;
    $("#modal").classList.remove("hidden");
    $("#modal-scrim").classList.remove("hidden");
    $(".modal-close")?.addEventListener("click", closeModal);
  }

  function closeModal() {
    $("#modal").classList.add("hidden");
    $("#modal-scrim").classList.add("hidden");
  }

  function linkForm(link = {}) {
    return `<div class="modal-head"><div><p class="eyebrow">${link.id ? "EDIT SHORTCUT" : "NEW SHORTCUT"}</p><h2 id="modal-title">${link.id ? `Change ${esc(link.name)}` : "Add another service"}</h2><p>Every detail can be changed again whenever you need.</p></div><button type="button" class="modal-close" aria-label="Close">×</button></div>
      <form id="link-form" class="form-grid">
        <label>Shortcut name<input id="link-name" value="${attr(link.name || "")}" placeholder="For example: Online Galleries" required maxlength="60"></label>
        <label>Category<input id="link-category" list="category-options" value="${attr(link.category || "Business")}" required maxlength="40"><datalist id="category-options">${["Business", "Clients", "Server", "Marketing", ...categories()].map(value => `<option value="${attr(value)}">`).join("")}</datalist></label>
        <label class="full">Complete web address<input id="link-url" type="url" value="${attr(link.url || "https://")}" required maxlength="500"><small class="help-text">Use the full https:// address, or http:// for a private local server page.</small></label>
        <label class="full">Short description<textarea id="link-description" maxlength="180" placeholder="What do you use this service for?">${esc(link.description || "")}</textarea></label>
        <label>Icon or initials<input id="link-icon" value="${attr(link.icon || "↗")}" required maxlength="12" placeholder="📅 or WBM"><small class="help-text">Use an emoji, symbol or short initials.</small></label>
        <label>Tile colour<div class="colour-row"><input id="link-accent" type="color" value="${attr(link.accent || "#167a70")}"><input id="link-accent-text" value="${attr(link.accent || "#167a70")}" pattern="#[0-9A-Fa-f]{6}" maxlength="7"></div></label>
        <label class="checkbox-row"><input id="link-pinned" type="checkbox" ${link.pinned ? "checked" : ""}><span>Pin near the top</span></label>
        <label class="checkbox-row"><input id="link-active" type="checkbox" ${link.id && !link.active ? "" : "checked"}><span>Show on dashboard</span></label>
        <label class="checkbox-row full"><input id="link-new-tab" type="checkbox" ${link.id && !link.open_new_tab ? "" : "checked"}><span>Open this service in a new browser tab</span></label>
        <div class="modal-actions full">${link.id ? `<button type="button" id="delete-link" class="secondary danger-button">Delete shortcut</button>` : "<span></span>"}<div><button type="button" class="secondary modal-close-secondary">Cancel</button><button type="submit" class="primary">${link.id ? "Save changes" : "Add shortcut"}</button></div></div>
      </form>`;
  }

  function openLinkModal(link = null) {
    showModal(linkForm(link || {}));
    const colour = $("#link-accent"), colourText = $("#link-accent-text");
    colour.oninput = () => colourText.value = colour.value;
    colourText.oninput = () => { if (/^#[0-9a-f]{6}$/i.test(colourText.value)) colour.value = colourText.value; };
    $(".modal-close-secondary").onclick = closeModal;
    $("#link-form").onsubmit = async event => {
      event.preventDefault();
      const payload = {
        name: $("#link-name").value.trim(), url: $("#link-url").value.trim(),
        description: $("#link-description").value.trim(), category: $("#link-category").value.trim(),
        icon: $("#link-icon").value.trim(), accent: $("#link-accent-text").value.trim(),
        pinned: $("#link-pinned").checked, active: $("#link-active").checked,
        open_new_tab: $("#link-new-tab").checked,
      };
      try {
        if (link) await api(`/api/links/${link.id}`, {method: "PATCH", body: JSON.stringify(payload)});
        else await api("/api/links", {method: "POST", body: JSON.stringify(payload)});
        closeModal();
        await loadDashboard();
        toast(link ? "Shortcut updated" : "New shortcut added");
      } catch (error) { toast(error.message, "error"); }
    };
    if (link) $("#delete-link").onclick = async () => {
      if (!confirm(`Delete “${link.name}” from this dashboard?\n\nThis only removes the shortcut. It does not affect the service itself.`)) return;
      try {
        await api(`/api/links/${link.id}`, {method: "DELETE"});
        closeModal();
        await loadDashboard();
        toast("Shortcut removed");
      } catch (error) { toast(error.message, "error"); }
    };
  }

  function openSettings() {
    showModal(`<div class="modal-head"><div><p class="eyebrow">CONTROL CENTRE SETTINGS</p><h2 id="modal-title">Make it yours</h2><p>Change the dashboard wording without touching any shortcuts.</p></div><button type="button" class="modal-close" aria-label="Close">×</button></div>
      <form id="settings-form" class="form-grid">
        <label class="full">Dashboard title<input id="setting-title" value="${attr(state.settings.dashboard_title || "")}" required maxlength="80"></label>
        <label class="full">Welcome description<textarea id="setting-subtitle" required maxlength="180">${esc(state.settings.dashboard_subtitle || "")}</textarea></label>
        <label class="full">Name used in your greeting<input id="setting-name" value="${attr(state.settings.greeting_name || "Mark")}" required maxlength="40"></label>
        <div class="modal-actions full"><span></span><div><button type="button" class="secondary modal-close-secondary">Cancel</button><button type="submit" class="primary">Save settings</button></div></div>
      </form>`);
    $(".modal-close-secondary").onclick = closeModal;
    $("#settings-form").onsubmit = async event => {
      event.preventDefault();
      try {
        state.settings = await api("/api/settings", {method: "PATCH", body: JSON.stringify({
          dashboard_title: $("#setting-title").value.trim(), dashboard_subtitle: $("#setting-subtitle").value.trim(), greeting_name: $("#setting-name").value.trim(),
        })});
        closeModal(); render(); toast("Control Centre settings saved");
      } catch (error) { toast(error.message, "error"); }
    };
  }

  function openPassword() {
    showModal(`<div class="modal-head"><div><p class="eyebrow">SECURITY</p><h2 id="modal-title">Change your password</h2><p>All signed-in sessions will close after the change.</p></div><button type="button" class="modal-close" aria-label="Close">×</button></div>
      <form id="password-form" class="form-grid">
        <label class="full">Current password<input id="current-password" type="password" autocomplete="current-password" required></label>
        <label class="full">New password<input id="new-password" type="password" autocomplete="new-password" minlength="12" required><small class="help-text">Use at least 12 characters and do not reuse another service password.</small></label>
        <label class="full">Repeat new password<input id="repeat-password" type="password" autocomplete="new-password" minlength="12" required></label>
        <div class="modal-actions full"><span></span><div><button type="button" class="secondary modal-close-secondary">Cancel</button><button type="submit" class="primary">Change password</button></div></div>
      </form>`);
    $(".modal-close-secondary").onclick = closeModal;
    $("#password-form").onsubmit = async event => {
      event.preventDefault();
      if ($("#new-password").value !== $("#repeat-password").value) return toast("The two new passwords do not match", "error");
      try {
        await api("/api/admin/password", {method: "POST", body: JSON.stringify({current_password: $("#current-password").value, new_password: $("#new-password").value})});
        closeModal(); showLogin("Password changed successfully. Please sign in again.");
      } catch (error) { toast(error.message, "error"); }
    };
  }

  function openSidebar() { $(".sidebar").classList.add("open"); $("#sidebar-scrim").classList.remove("hidden"); }
  function closeSidebar() { $(".sidebar").classList.remove("open"); $("#sidebar-scrim").classList.add("hidden"); }

  async function loadDashboard() {
    const data = await api("/api/dashboard");
    state.links = data.links;
    state.settings = data.settings;
    $("#build-label").textContent = data.build.split("-").slice(-1)[0].replace("v", "Version ");
    render();
  }

  function bind() {
    $("#login-form").onsubmit = async event => {
      event.preventDefault();
      const button = $("#login-button");
      button.disabled = true; button.textContent = "Opening…"; $("#login-error").textContent = "";
      try {
        await api("/api/auth/login", {method: "POST", body: JSON.stringify({email: $("#login-email").value.trim(), password: $("#login-password").value})});
        showDashboard(); await loadDashboard(); $("#login-password").value = "";
      } catch (error) { $("#login-error").textContent = error.message; }
      finally { button.disabled = false; button.innerHTML = "Open Control Centre <span>→</span>"; }
    };
    $("#search").oninput = event => { state.search = event.target.value; render(); };
    $("#add-link-top").onclick = $("#add-link-banner").onclick = $("#empty-add").onclick = $("#mobile-add").onclick = () => openLinkModal();
    $("#edit-toggle").onclick = $("#mobile-edit").onclick = () => toggleEditing();
    $("#finish-editing").onclick = () => toggleEditing(false);
    $("#open-settings").onclick = $("#mobile-settings").onclick = openSettings;
    $("#user-menu").onclick = event => { event.stopPropagation(); $("#account-menu").classList.toggle("hidden"); };
    $("#change-password").onclick = () => { $("#account-menu").classList.add("hidden"); openPassword(); };
    $("#logout").onclick = async () => { await api("/api/auth/logout", {method: "POST"}); showLogin(); };
    $("#mobile-menu").onclick = $("#mobile-filter").onclick = openSidebar;
    $("#sidebar-scrim").onclick = closeSidebar;
    $("#mobile-search").onclick = () => { $(".search-shell").classList.toggle("mobile-open"); $("#search").focus(); };
    $("#modal-scrim").onclick = closeModal;
    document.addEventListener("click", event => { if (!event.target.closest("#account-menu") && !event.target.closest("#user-menu")) $("#account-menu").classList.add("hidden"); });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape") { closeModal(); closeSidebar(); $("#account-menu").classList.add("hidden"); }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); $(".search-shell").classList.add("mobile-open"); $("#search").focus(); }
    });
    $("#today-label").textContent = new Intl.DateTimeFormat("en-GB", {weekday: "long", day: "numeric", month: "long"}).format(new Date());
  }

  async function init() {
    bind();
    $("#login-email").value = "mark@perfectweddingsbymark.uk";
    try { await api("/api/me"); showDashboard(); await loadDashboard(); }
    catch (_) { showLogin(); }
  }

  init();
})();
