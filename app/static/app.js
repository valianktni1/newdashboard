(() => {
  "use strict";
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const areas = ["Weddings By Mark", "Ivory Digital", "Marketing", "Accounts", "Systems", "Other"];
  const pages = ["Today", ...areas.slice(0, 5), "All apps"];
  const state = {links: [], settings: {}, tasks: [], services: [], activity: [], page: "Today", category: "All", search: "", editing: false, completed: false};
  const categoryIcons = {Today: "⌂", "Weddings By Mark": "W", "Ivory Digital": "ID", Marketing: "↗", Accounts: "£", Systems: "▦", "All apps": "◇"};
  let lastFocus;
  let checking = false;
  const dateFormat = new Intl.DateTimeFormat("en-GB", {day: "numeric", month: "short"});
  const timeFormat = new Intl.DateTimeFormat("en-GB", {day: "numeric", month: "short", hour: "2-digit", minute: "2-digit"});
  function localDate() { const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,"0")}-${String(now.getDate()).padStart(2,"0")}`; }
  function dueText(value) { return value ? dateFormat.format(new Date(`${value}T12:00:00`)) : "No due date"; }
  function timestamp(value) { return timeFormat.format(new Date(value)); }
  function categories() { return [...new Set(state.links.map(link => link.category))].sort(); }
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


  function pageLinks() {
    return state.links.filter(link => (state.editing || link.active) &&
      (state.page === "All apps" || state.page === "Today" || link.workspace === state.page) &&
      (state.category === "All" || link.category === state.category) &&
      (!state.search || `${link.name} ${link.description} ${link.category} ${link.workspace}`.toLowerCase().includes(state.search.toLowerCase())));
  }
  function renderNavigation() {
    $("#category-nav").innerHTML = `<p class="nav-label">YOUR WORKSPACES</p>${pages.map(page => `<button class="category-button ${state.page === page ? "active" : ""}" data-page="${attr(page)}" ${state.page === page ? 'aria-current="page"' : ""}><span aria-hidden="true">${categoryIcons[page]}</span><span>${esc(page)}</span></button>`).join("")}`;
    $$("[data-page]").forEach(button => button.onclick = () => selectPage(button.dataset.page));
  }
  function card(link) {
    const index = state.links.findIndex(item => item.id === link.id);
    const tag = state.editing ? "article" : "a";
    const navigation = state.editing ? "" : `href="${attr(link.url)}" ${link.open_new_tab ? 'target="_blank" rel="noopener noreferrer"' : ""}`;
    const editing = state.editing ? `<div class="card-edit-actions"><button type="button" data-move="up" data-id="${link.id}" aria-label="Move ${attr(link.name)} earlier" ${index === 0 ? "disabled" : ""}>↑</button><button type="button" data-move="down" data-id="${link.id}" aria-label="Move ${attr(link.name)} later" ${index === state.links.length-1 ? "disabled" : ""}>↓</button><button type="button" data-edit-link="${link.id}" aria-label="Edit ${attr(link.name)}">✎</button></div>` : "";
    return `<${tag} class="link-card ${link.active ? "" : "inactive"}" style="--accent:${attr(link.accent)}" ${navigation}>${editing}<span class="service-icon" aria-hidden="true">${esc(link.icon)}</span><div class="card-copy"><small>${esc(link.workspace)}${link.active ? "" : " · hidden"}</small><h3>${esc(link.name)}</h3><p>${esc(link.description || link.url)}</p></div><span class="card-arrow" aria-hidden="true">${link.pinned ? "◆ " : ""}↗</span></${tag}>`;
  }
  function renderTasks() {
    const today = localDate();
    const visible = state.tasks.filter(task => (state.completed || !task.completed) &&
      (state.page === "Today" || state.page === "All apps" || task.workspace === state.page) &&
      (!state.search || `${task.title} ${task.workspace}`.toLowerCase().includes(state.search.toLowerCase())));
    $("#task-list").innerHTML = visible.length ? visible.map(task => `<div class="task-row ${task.completed ? "is-complete" : ""}"><label class="task-check"><input type="checkbox" data-complete="${task.id}" ${task.completed ? "checked" : ""} aria-label="${task.completed ? "Reopen" : "Complete"} ${attr(task.title)}"></label><div class="task-copy"><strong>${esc(task.title)}</strong><div class="task-meta"><span>${esc(task.workspace)}</span><span class="${!task.completed && task.due_date && task.due_date < today ? "overdue" : ""}">${task.due_date && task.due_date < today && !task.completed ? "Overdue · " : ""}${dueText(task.due_date)}</span>${task.priority === "high" ? '<span class="priority">High priority</span>' : ""}</div></div>${task.url ? `<a class="text-link" href="${attr(task.url)}" target="_blank" rel="noopener noreferrer">Open ↗</a>` : ""}<button class="icon-button" data-edit-task="${task.id}" aria-label="Edit ${attr(task.title)}">✎</button></div>`).join("") : `<div class="empty-panel"><span class="empty-mark" aria-hidden="true">✓</span><div><strong>${state.search ? "No matching tasks" : state.tasks.length ? "Nothing to do in this view" : "A clear place to start your day"}</strong><p>${state.search ? "Try another search." : "Add follow-ups, editing deadlines and reminders. Your tasks are saved here."}</p></div></div>`;
    $$("[data-complete]").forEach(box => box.onchange = async () => { box.disabled = true; try { await api(`/api/tasks/${box.dataset.complete}/complete`, {method: "POST", body: JSON.stringify({completed: box.checked})}); await loadDashboard(); } catch (error) { box.checked = !box.checked; toast(error.message, "error"); } finally { box.disabled = false; } });
    $$("[data-edit-task]").forEach(button => button.onclick = () => openTaskModal(state.tasks.find(task => task.id === Number(button.dataset.editTask))));
  }
  function renderConnections() {
    const definitions = [
      {title: "Enquiries & weddings", description: "New enquiries, upcoming weddings and contracts.", names: ["Booking System"], area: "Weddings By Mark"},
      {title: "Payments & accounts", description: "Payments due, balances and money received.", names: ["Accounts"], area: "Accounts"},
      {title: "Couples' planner", description: "Planner invitations and account access.", names: ["Couples' Wedding Planner"], area: "Weddings By Mark"},
      {title: "Diary", description: "Today's appointments and your next weddings.", names: ["Google Calendar"], area: "Weddings By Mark"},
      {title: "Leads & outreach", description: "Leads to follow up and campaign activity.", names: ["Outreach Manager"], area: "Ivory Digital"},
      {title: "Marketing", description: "Content plans and website performance.", names: ["Website Admin"], area: "Marketing"}
    ];
    const relevant = definitions.filter(item => state.page === "Today" ? ["Enquiries & weddings", "Payments & accounts", "Couples' planner"].includes(item.title) : item.area === state.page);
    $("#connections-panel").classList.toggle("hidden", !relevant.length || state.editing || Boolean(state.search));
    $("#connection-grid").innerHTML = relevant.map(item => {
      const link = state.links.find(link => link.active && item.names.includes(link.name));
      return `<div class="connection-card"><div class="connection-title"><h3>${esc(item.title)}</h3><span class="badge">Not connected</span></div><p>${esc(item.description)}</p><div class="connection-bottom"><span class="muted">Live figures unavailable</span>${link ? `<a href="${attr(link.url)}" ${link.open_new_tab ? 'target="_blank" rel="noopener noreferrer"' : ""}>Open app ↗</a>` : ""}</div></div>`;
    }).join("");
  }
  function renderServices() {
    const labels = {reachable: "Reachable", redirected: "Redirect received", restricted: "Access restricted", unavailable: "No response", http_error: "HTTP error"};
    $("#service-list").innerHTML = state.links.filter(link => link.active).map(link => {
      const check = state.services.find(item => item.link_id === link.id && item.url === link.url);
      const stale = check && Date.now() - Date.parse(check.checked_at) > 900000;
      return `<div class="service-row"><div><strong>${esc(link.name)}</strong><small>${check ? `Checked ${timestamp(check.checked_at)}${stale ? " · old result" : ""}` : "No saved check for this address"}</small></div><span class="badge ${check && !stale ? check.status : ""}">${check ? `${labels[check.status] || "Unknown"}${check.http_status ? ` · ${check.http_status}` : ""}` : "Not checked"}</span></div>`;
    }).join("") + '<p class="muted">Custom addresses require an allowed check URL in the server settings.</p>';
  }
  function render() {
    renderNavigation();
    const today = state.page === "Today";
    const searching = Boolean(state.search.trim());
    $("#workspace-label").textContent = today ? "TODAY / YOUR BUSINESS AT A GLANCE" : "YOUR WORKSPACE";
    $("#greeting").textContent = today ? greeting() : state.page;
    $("#dashboard-subtitle").textContent = today ? state.settings.dashboard_subtitle : ({Systems: "Your infrastructure, checks and server tools.", "All apps": "Every shortcut, organised around the way you work."}[state.page] || "Your tasks and tools, together in one place.");
    document.title = state.settings.dashboard_title || "Weddings By Mark Control Centre";
    const open = state.tasks.filter(task => !task.completed);
    $("#task-count").textContent = open.length;
    $("#due-count").textContent = open.filter(task => task.due_date && task.due_date <= localDate()).length;
    $("#favourite-count").textContent = state.links.filter(link => link.active && link.pinned).length;
    $("#today-summary").classList.toggle("hidden", !today || state.editing || searching);
    $("#tasks-panel").classList.toggle("hidden", state.editing || (state.page === "All apps" && !searching));
    $("#systems-panel").classList.toggle("hidden", state.page !== "Systems" || state.editing);
    $("#activity-panel").classList.toggle("hidden", !today || state.editing || searching);
    const links = pageLinks().filter(link => !today || searching || link.pinned);
    $("#section-eyebrow").textContent = searching ? "SEARCH RESULTS" : "QUICK ACCESS";
    $("#section-title").textContent = searching ? "Matching apps" : today ? "Your favourite apps" : state.editing ? "Edit your apps" : "Your apps";
    $("#link-grid").innerHTML = links.map(card).join("");
    $("#empty-state").classList.toggle("hidden", links.length > 0);
    $("#edit-banner").classList.toggle("hidden", !state.editing);
    $("#edit-toggle").classList.toggle("active", state.editing);
    $("#category-filter-label").classList.toggle("hidden", state.page !== "All apps");
    const filter = $("#category-filter");
    filter.innerHTML = ["All", ...categories()].map(category => `<option ${state.category === category ? "selected" : ""}>${esc(category)}</option>`).join("");
    $$("[data-edit-link]").forEach(button => button.onclick = () => openLinkModal(state.links.find(link => link.id === Number(button.dataset.editLink))));
    $$("[data-move]").forEach(button => button.onclick = () => moveLink(Number(button.dataset.id), button.dataset.move));
    renderTasks(); renderConnections(); renderServices();
    $("#activity-list").innerHTML = state.activity.length ? state.activity.slice(0, 4).map(item => `<div class="activity-row"><span>${esc(item.detail)}</span><time datetime="${attr(item.created_at)}">${timestamp(item.created_at)}</time></div>`).join("") : '<p class="muted">Your dashboard changes and tasks will appear here.</p>';
    $("#mobile-home").classList.toggle("active", today);
    $("#mobile-apps").classList.toggle("active", state.page === "All apps");
  }
  function selectPage(page) { state.page = page; state.category = "All"; state.editing = false; state.search = ""; $("#search").value = ""; render(); closeSidebar(); }
  function toggleEditing(on = !state.editing) { state.editing = on; if (on) { state.page = "All apps"; state.category = "All"; state.search = ""; $("#search").value = ""; } render(); }
  function openTaskModal(task = null) {
    showModal(`<div class="modal-head"><div><p class="eyebrow">PERSONAL TASK</p><h2 id="modal-title">${task ? "Edit task" : "What needs doing?"}</h2></div><button type="button" class="modal-close" aria-label="Close">×</button></div><form id="task-form" class="form-grid"><label class="full">Task<input id="task-title" value="${attr(task?.title || "")}" placeholder="Follow up a quote, edit a wedding…" maxlength="180" required></label><label>Workspace<select id="task-workspace">${areas.map(area => `<option ${area === (task?.workspace || (areas.includes(state.page) ? state.page : "Weddings By Mark")) ? "selected" : ""}>${esc(area)}</option>`).join("")}</select></label><label>Due date<input type="date" id="task-date" value="${attr(task?.due_date || "")}"></label><label>Priority<select id="task-priority"><option value="normal">Normal</option><option value="high" ${task?.priority === "high" ? "selected" : ""}>High</option></select></label><label>Related page (optional)<input type="url" id="task-url" maxlength="500" value="${attr(task?.url || "")}" placeholder="https://…"></label><div class="modal-actions full">${task ? '<button type="button" id="delete-task" class="secondary danger-button">Delete task</button>' : "<span></span>"}<div><button type="button" class="secondary modal-close-secondary">Cancel</button><button type="submit" class="primary">Save task</button></div></div></form>`);
    $(".modal-close-secondary").onclick = closeModal;
    $("#task-form").onsubmit = async event => {
      event.preventDefault(); const submit = $('[type="submit"]', event.target); submit.disabled = true;
      try { await api(task ? `/api/tasks/${task.id}` : "/api/tasks", {method: task ? "PUT" : "POST", body: JSON.stringify({title: $("#task-title").value.trim(), workspace: $("#task-workspace").value, due_date: $("#task-date").value || null, priority: $("#task-priority").value, url: $("#task-url").value.trim()})}); closeModal(); await loadDashboard(); toast("Task saved"); } catch (error) { toast(error.message, "error"); } finally { submit.disabled = false; }
    };
    if (task) $("#delete-task").onclick = async () => { if (!confirm("Delete this task?")) return; try { await api(`/api/tasks/${task.id}`, {method: "DELETE"}); closeModal(); await loadDashboard(); toast("Task deleted"); } catch (error) { toast(error.message, "error"); } };
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
    lastFocus = document.activeElement;
    document.body.classList.add("modal-open");
    $(".modal-close")?.addEventListener("click", closeModal);
    requestAnimationFrame(() => $("#modal input, #modal button, #modal select")?.focus());
  }

  function closeModal() {
    $("#modal").classList.add("hidden");
    $("#modal-scrim").classList.add("hidden");
    document.body.classList.remove("modal-open");
    if (lastFocus?.isConnected) lastFocus.focus();
  }

  function linkForm(link = {}) {
    return `<div class="modal-head"><div><p class="eyebrow">${link.id ? "EDIT SHORTCUT" : "NEW SHORTCUT"}</p><h2 id="modal-title">${link.id ? `Change ${esc(link.name)}` : "Add another service"}</h2><p>Every detail can be changed again whenever you need.</p></div><button type="button" class="modal-close" aria-label="Close">×</button></div>
      <form id="link-form" class="form-grid">
        <label>Shortcut name<input id="link-name" value="${attr(link.name || "")}" placeholder="For example: Online Galleries" required maxlength="60"></label>
        <label>Workspace<select id="link-workspace">${areas.map(area => `<option ${area === (link.workspace || "Weddings By Mark") ? "selected" : ""}>${esc(area)}</option>`).join("")}</select></label><label>Category<input id="link-category" list="category-options" value="${attr(link.category || "Business")}" required maxlength="40"><datalist id="category-options">${["Business", "Clients", "Server", "Marketing", ...categories()].map(value => `<option value="${attr(value)}">`).join("")}</datalist></label>
        <label class="full">Complete web address<input id="link-url" type="url" value="${attr(link.url || "https://")}" required maxlength="500"><small class="help-text">Use the full https:// address, or http:// for a private local server page.</small></label>
        <label class="full">Short description<textarea id="link-description" maxlength="180" placeholder="What do you use this service for?">${esc(link.description || "")}</textarea></label>
        <label>Icon or initials<input id="link-icon" value="${attr(link.icon || "↗")}" required maxlength="12" placeholder="📅 or WBM"><small class="help-text">Use an emoji, symbol or short initials.</small></label>
        <label>Tile colour<div class="colour-row"><input id="link-accent" type="color" value="${attr(link.accent || "#167a70")}"><input id="link-accent-text" value="${attr(link.accent || "#167a70")}" pattern="#[0-9A-Fa-f]{6}" maxlength="7"></div></label>
        <label class="checkbox-row"><input id="link-pinned" type="checkbox" ${link.pinned ? "checked" : ""}><span>Show in favourites</span></label>
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
        workspace: $("#link-workspace").value, name: $("#link-name").value.trim(), url: $("#link-url").value.trim(),
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
    const [data, tasks, services, activity] = await Promise.all([api("/api/dashboard"), api("/api/tasks"), api("/api/services"), api("/api/activity?limit=4")]);
    Object.assign(state, {links: data.links, settings: data.settings, tasks, services, activity});
    $("#build-label").textContent = "Version 1.1.0";
    render();
  }
  function setTheme(theme) { document.documentElement.dataset.theme = theme; $("#theme-toggle").setAttribute("aria-label", `Switch to ${theme === "dark" ? "light" : "dark"} theme`); try { localStorage.setItem("wbm-theme", theme); } catch (_) {} }
  function bind() {
    let theme; try { theme = localStorage.getItem("wbm-theme"); } catch (_) {}
    setTheme(theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
    $("#theme-toggle").onclick = () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
    $("#login-form").onsubmit = async event => {
      event.preventDefault(); const button = $("#login-button"); button.disabled = true; $("#login-error").textContent = "";
      try { await api("/api/auth/login", {method: "POST", body: JSON.stringify({email: $("#login-email").value.trim(), password: $("#login-password").value})}); await loadDashboard(); showDashboard(); $("#login-password").value = ""; }
      catch (error) { $("#login-error").textContent = error.message; }
      finally { button.disabled = false; }
    };
    $("#search").oninput = event => { state.search = event.target.value; render(); };
    $("#category-filter").onchange = event => { state.category = event.target.value; render(); };
    $("#show-completed").onchange = event => { state.completed = event.target.checked; renderTasks(); };
    $("#add-link-top").onclick = $("#add-link-banner").onclick = $("#empty-add").onclick = () => openLinkModal();
    $("#add-task-top").onclick = $("#add-task").onclick = $("#mobile-add").onclick = () => openTaskModal();
    $("#edit-toggle").onclick = () => toggleEditing();
    $("#finish-editing").onclick = () => toggleEditing(false);
    $("#open-settings").onclick = openSettings;
    $("#user-menu").onclick = event => { event.stopPropagation(); $("#account-menu").classList.toggle("hidden"); $("#user-menu").setAttribute("aria-expanded", !$("#account-menu").classList.contains("hidden")); };
    $("#change-password").onclick = () => { $("#account-menu").classList.add("hidden"); openPassword(); };
    $("#logout").onclick = async () => { try { await api("/api/auth/logout", {method: "POST"}); showLogin(); } catch (error) { toast(error.message, "error"); } };
    $("#mobile-menu").onclick = $("#mobile-workspaces").onclick = openSidebar;
    $("#mobile-home").onclick = () => selectPage("Today");
    $("#mobile-apps").onclick = () => selectPage("All apps");
    $("#sidebar-scrim").onclick = closeSidebar;
    $("#mobile-search").onclick = () => { selectPage("All apps"); $(".search-shell").classList.add("mobile-open"); $("#search").focus(); };
    $("#modal-scrim").onclick = closeModal;
    $("#check-services").onclick = async () => {
      if (checking) return; checking = true; const button = $("#check-services"); button.disabled = true; button.textContent = "Checking…";
      try { state.services = await api("/api/services/check", {method: "POST"}); renderServices(); toast("Service checks updated"); }
      catch (error) { toast(error.message, "error"); }
      finally { checking = false; button.disabled = false; button.textContent = "Check services"; }
    };
    document.addEventListener("click", event => { if (!event.target.closest("#account-menu") && !event.target.closest("#user-menu")) { $("#account-menu").classList.add("hidden"); $("#user-menu").setAttribute("aria-expanded", "false"); } });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape") { closeModal(); closeSidebar(); $("#account-menu").classList.add("hidden"); }
      if (event.key === "Tab" && !$("#modal").classList.contains("hidden")) {
        const focusable = $$("button:not([disabled]), input:not([disabled]), select, textarea, a[href]", $("#modal"));
        const first = focusable[0], last = focusable[focusable.length-1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k" && !$("#dashboard-app").classList.contains("hidden") && $("#modal").classList.contains("hidden")) { event.preventDefault(); selectPage("All apps"); $(".search-shell").classList.add("mobile-open"); $("#search").focus(); }
    });
    updateDate();
    setInterval(updateDate, 60000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden && !$("#dashboard-app").classList.contains("hidden") && $("#modal").classList.contains("hidden")) loadDashboard().catch(error => toast(error.message,"error")); });
  }
  function updateDate() { const label = new Intl.DateTimeFormat("en-GB", {weekday: "long", day: "numeric", month: "long"}).format(new Date()); $("#today-label").textContent = label; $("#today-label-mobile").textContent = label; if (state.links.length) render(); }
  async function init() {
    bind(); $("#login-email").value = "mark@perfectweddingsbymark.uk";
    try { await api("/api/me"); await loadDashboard(); showDashboard(); } catch (error) { showLogin(error.message === "Please sign in again" ? "" : error.message); }
  }
  init();
})();
