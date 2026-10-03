(() => {
  const appRoot = document.querySelector("#app");
  const dialog = document.querySelector("#logs-dialog");
  const state = { apps: [], page: "apps", activeName: null, filter: "ALL", loading: true };
  const statusLabels = { BUILDING: "Building", DEPLOYING: "Deploying", RUNNING: "Running", CRASHING: "Crashing", FAILED: "Failed" };
  const statusDescriptions = {
    BUILDING: "Preparing your application",
    DEPLOYING: "Your application is being made available",
    RUNNING: "Your application is live",
    CRASHING: "Your application needs attention",
    FAILED: "This deployment didn't complete",
  };

  const escapeHtml = (value = "") => String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
  const statusClass = (status) => status.toLowerCase();
  const appByName = (name) => state.apps.find((app) => app.name === name);

  function setPage(page, name = null) {
    state.page = page;
    state.activeName = name;
    render();
    document.querySelector("#app").focus({ preventScroll: true });
  }

  function renderStatus(status) {
    return `<span class="status status-${statusClass(status)}"><i></i>${statusLabels[status]}</span>`;
  }

  function renderAppRow(app) {
    const live = app.url
      ? `<a class="table-url" href="${escapeHtml(app.url)}" target="_blank" rel="noreferrer">${escapeHtml(app.url.replace("https://", ""))}<span aria-hidden="true">↗</span></a>`
      : `<span class="url-pending">Not live yet</span>`;
    return `<tr>
      <td><button class="app-name-button" type="button" data-action="details" data-name="${escapeHtml(app.name)}"><span class="app-glyph ${app.type === "FastAPI" ? "api-glyph" : "site-glyph"}" aria-hidden="true">${app.type === "FastAPI" ? "ƒ" : "◫"}</span><span><strong>${escapeHtml(app.name)}</strong><small>${escapeHtml(app.summary)}</small></span></button></td>
      <td><span class="type-label">${escapeHtml(app.type)}</span></td>
      <td>${renderStatus(app.status)}</td>
      <td>${live}</td>
      <td class="updated-cell">${escapeHtml(app.updated)}</td>
      <td><button class="row-more" type="button" aria-label="Open ${escapeHtml(app.name)} details" data-action="details" data-name="${escapeHtml(app.name)}">···</button></td>
    </tr>`;
  }

  function renderDashboard() {
    const visibleApps = state.filter === "ALL" ? state.apps : state.apps.filter((app) => app.status === state.filter);
    const running = state.apps.filter((app) => app.status === "RUNNING").length;
    const attention = state.apps.filter((app) => ["CRASHING", "FAILED"].includes(app.status)).length;
    return `<section class="page-content dashboard-page">
      <div class="page-heading"><div><p class="eyebrow">YOUR WORKSPACE</p><h1>Applications</h1><p class="page-subtitle">A clear view of everything your team has put into motion.</p></div><button class="button button-primary" type="button" data-action="new-app"><span aria-hidden="true">＋</span> Deploy application</button></div>
      <div class="overview-strip" aria-label="Workspace overview">
        <div class="overview-item"><span class="overview-symbol symbol-apps" aria-hidden="true">◫</span><span><small>Applications</small><strong>${state.apps.length}</strong></span></div>
        <div class="overview-item"><span class="overview-symbol symbol-live" aria-hidden="true"><i></i></span><span><small>Live</small><strong>${running}</strong></span></div>
        <div class="overview-item"><span class="overview-symbol symbol-attention" aria-hidden="true">!</span><span><small>Needs attention</small><strong>${attention}</strong></span></div>
        <div class="overview-note"><span class="note-sun" aria-hidden="true">✳</span><span><strong>One path from repo to running.</strong><small>Choose a Golden Path and we’ll take it from there.</small></span></div>
      </div>
      <section class="app-section" aria-labelledby="app-list-title">
        <div class="section-heading"><div><h2 id="app-list-title">Your applications <span class="count">${state.apps.length}</span></h2><p>Monitor status and jump straight to a live app.</p></div><button class="button button-secondary compact-button" type="button" data-action="refresh"><span aria-hidden="true">↻</span> Refresh</button></div>
        <div class="filter-bar" role="group" aria-label="Filter applications by status">${["ALL", "RUNNING", "BUILDING", "DEPLOYING", "CRASHING", "FAILED"].map((filter) => `<button type="button" class="filter-chip ${state.filter === filter ? "is-selected" : ""}" data-action="filter" data-filter="${filter}" aria-pressed="${state.filter === filter}">${filter === "ALL" ? "All apps" : statusLabels[filter]}</button>`).join("")}</div>
        ${visibleApps.length ? `<div class="table-wrap"><table class="app-table"><thead><tr><th scope="col">APPLICATION</th><th scope="col">GOLDEN PATH</th><th scope="col">STATUS</th><th scope="col">LIVE URL</th><th scope="col">UPDATED</th><th scope="col"><span class="visually-hidden">Actions</span></th></tr></thead><tbody>${visibleApps.map(renderAppRow).join("")}</tbody></table></div>` : `<div class="empty-state"><span class="empty-mark" aria-hidden="true">◫</span><h3>${state.apps.length ? "No applications in this view" : "A good place to start"}</h3><p>${state.apps.length ? "Try another status filter." : "Connect a public repository and choose a Golden Path to make your first application."}</p>${state.apps.length ? "" : `<button class="button button-primary" type="button" data-action="new-app">＋ Deploy your first application</button>`}</div>`}
      </section>
      <footer class="page-footer"><span><i class="footer-dot"></i> Platform status: operational</span><span>Updated just now <span aria-hidden="true">·</span> Demo workspace</span></footer>
    </section>`;
  }

  function renderDeploy() {
    return `<section class="page-content deploy-page">
      <div class="page-heading"><div><p class="eyebrow">NEW APPLICATION</p><h1>Deploy an application</h1><p class="page-subtitle">Start with a repository. We’ll guide it through a supported Golden Path.</p></div><button class="button button-quiet back-button" type="button" data-action="back">← <span>Applications</span></button></div>
      <form class="deploy-form" id="deploy-form" novalidate>
        <div class="form-main">
          <section class="form-section"><div class="form-step"><span>01</span><div><h2>Connect your repository</h2><p>Use a public GitHub repository to get started.</p></div></div>
            <label class="field-label" for="repository">GitHub repository URL</label>
            <div class="input-wrap"><span class="input-prefix" aria-hidden="true">⌘</span><input id="repository" name="repository" type="url" placeholder="https://github.com/you/your-project" autocomplete="url" required><span class="input-suffix">PUBLIC</span></div>
            <p class="field-hint">The repository should contain the source for the application you want to deploy.</p>
            <label class="field-label name-label" for="app-name">Application name</label>
            <input class="text-input" id="app-name" name="name" type="text" placeholder="my-awesome-app" minlength="2" maxlength="40" required>
            <p class="field-hint">Use lowercase letters, numbers, and hyphens.</p>
            <p class="form-error" id="form-error" role="alert" hidden></p>
          </section>
          <section class="form-section path-section"><div class="form-step"><span>02</span><div><h2>Choose a Golden Path</h2><p>A supported starting point, tailored to your app.</p></div></div>
            <div class="path-options">
              <label class="path-option is-chosen"><input type="radio" name="goldenPath" value="Static Website" checked><span class="path-select" aria-hidden="true"></span><span class="path-illustration static-illustration" aria-hidden="true"><i></i><i></i><i></i></span><span class="path-copy"><strong>Static Website</strong><small>For frontend apps, sites, and docs.</small><span class="path-tags"><em>HTML</em><em>React</em><em>Vue</em></span></span></label>
              <label class="path-option"><input type="radio" name="goldenPath" value="FastAPI"><span class="path-select" aria-hidden="true"></span><span class="path-illustration api-illustration" aria-hidden="true"><i></i><i></i><i></i></span><span class="path-copy"><strong>FastAPI Web Service</strong><small>For Python APIs and web services.</small><span class="path-tags"><em>Python</em><em>FastAPI</em><em>REST</em></span></span></label>
            </div>
          </section>
          <div class="form-actions"><button class="button button-primary deploy-submit" type="submit"><span>Deploy application</span><span aria-hidden="true">→</span></button><span class="form-footnote">You can check progress from your applications list.</span></div>
        </div>
        <aside class="path-aside"><div class="aside-orbit" aria-hidden="true"><span>REPO</span><i>→</i><span class="orbit-center">✳</span><i>→</i><span>LIVE</span></div><p class="eyebrow">THE GOLDEN PATH</p><h3>From repository<br>to running app.</h3><ol class="path-steps"><li><span>1</span><div><strong>Repository</strong><small>Your source stays yours.</small></div></li><li><span>2</span><div><strong>Golden Path</strong><small>A platform-supported route.</small></div></li><li><span>3</span><div><strong>Deploy</strong><small>Follow progress as it happens.</small></div></li><li><span>4</span><div><strong>Status + live URL</strong><small>Know when it’s ready.</small></div></li></ol><div class="aside-note"><span aria-hidden="true">i</span><p>No infrastructure setup required. Pick the path that fits your app.</p></div></aside>
      </form>
    </section>`;
  }

  function renderProgress(app) {
    const stages = ["BUILDING", "DEPLOYING", "RUNNING"];
    const activeIndex = stages.indexOf(app.status);
    const done = app.status === "RUNNING";
    const failed = ["CRASHING", "FAILED"].includes(app.status);
    const errorStep = app.status === "CRASHING" ? 2 : 1;
    return `<div class="deployment-progress ${failed ? "has-failed" : ""}"><div class="progress-heading"><span class="progress-symbol" aria-hidden="true">${done ? "✓" : failed ? "!" : "◷"}</span><span><strong>${failed ? "Deployment needs attention" : done ? "Deployment complete" : "Deployment in progress"}</strong><small>${statusDescriptions[app.status]}</small></span>${renderStatus(app.status)}</div><ol class="progress-steps">${stages.map((stage, index) => {
      const completed = done || (failed && index < errorStep) || (!failed && activeIndex > index);
      const current = !failed && activeIndex === index;
      const stepClass = completed ? "is-done" : current ? "is-current" : failed && index === errorStep ? "is-error" : "";
      const labels = { BUILDING: "Building", DEPLOYING: "Deploying", RUNNING: "Running" };
      const notes = { BUILDING: "Preparing your app", DEPLOYING: "Making it available", RUNNING: "Ready for traffic" };
      return `<li class="${stepClass}"><span class="step-marker">${completed ? "✓" : index + 1}</span><span><strong>${labels[stage]}</strong><small>${notes[stage]}</small></span></li>`;
    }).join("")}</ol></div>`;
  }

  function renderDetails(app) {
    const isError = ["CRASHING", "FAILED"].includes(app.status);
    const livePanel = app.url && app.status !== "FAILED"
      ? `<div class="live-panel"><span class="live-panel-icon" aria-hidden="true">↗</span><span class="live-panel-copy"><small>YOUR LIVE URL</small><a href="${escapeHtml(app.url)}" target="_blank" rel="noreferrer">${escapeHtml(app.url)} <span aria-hidden="true">↗</span></a></span><span class="live-now ${app.status === "CRASHING" ? "is-degraded" : ""}"><i></i>${app.status === "CRASHING" ? "DEGRADED" : "LIVE"}</span></div>`
      : `<div class="live-panel live-pending"><span class="live-panel-icon" aria-hidden="true">◷</span><span class="live-panel-copy"><small>YOUR LIVE URL</small><strong>${app.status === "FAILED" ? "Available after a successful deployment" : "Available when deployment is complete"}</strong></span></div>`;
    return `<section class="page-content detail-page">
      <div class="detail-back-row"><button class="text-back" type="button" data-action="back">← Applications</button><span class="detail-deployment-id">${escapeHtml(app.deployment)}</span></div>
      <div class="detail-heading"><div class="detail-title-wrap"><span class="detail-app-glyph ${app.type === "FastAPI" ? "api-glyph" : "site-glyph"}" aria-hidden="true">${app.type === "FastAPI" ? "ƒ" : "◫"}</span><div><p class="eyebrow">APPLICATION</p><h1>${escapeHtml(app.name)}</h1><p class="detail-subtitle">${escapeHtml(app.type)} <span>·</span> Created from a repository</p></div></div><div class="detail-actions"><button class="button button-secondary" type="button" data-action="logs" data-name="${escapeHtml(app.name)}">↗ <span>View logs</span></button><button class="button button-primary" type="button" data-action="redeploy" data-name="${escapeHtml(app.name)}">↻ <span>Redeploy</span></button><button class="icon-button delete-button" type="button" data-action="delete" data-name="${escapeHtml(app.name)}" aria-label="Delete application">⌫</button></div></div>
      ${isError ? `<div class="error-banner"><span class="error-icon" aria-hidden="true">!</span><span><strong>${app.status === "CRASHING" ? "Your application is not responding" : "This deployment failed"}</strong><small>${escapeHtml(app.issue || statusDescriptions[app.status])}</small></span><button class="button button-secondary error-log-button" type="button" data-action="logs" data-name="${escapeHtml(app.name)}">View logs</button></div>` : ""}
      ${renderProgress(app)}
      <div class="detail-grid"><section class="detail-section"><div class="section-heading detail-section-heading"><div><h2>Application details</h2><p>Source and Golden Path for this application.</p></div></div><dl class="details-list"><div><dt>Repository</dt><dd><a href="${escapeHtml(app.repository)}" target="_blank" rel="noreferrer">${escapeHtml(app.repository.replace("https://github.com/", ""))}<span aria-hidden="true">↗</span></a></dd></div><div><dt>Golden Path</dt><dd><span class="type-dot ${app.type === "FastAPI" ? "dot-api" : "dot-site"}"></span>${escapeHtml(app.type)}</dd></div><div><dt>Deployment</dt><dd class="mono-value">${escapeHtml(app.deployment)}</dd></div><div><dt>Last updated</dt><dd>${escapeHtml(app.updated)}</dd></div></dl></section><section class="detail-section url-section"><div class="section-heading detail-section-heading"><div><h2>Live application</h2><p>Your app’s address and availability.</p></div></div>${livePanel}</section></div>
      <footer class="page-footer"><span><i class="footer-dot"></i> Platform status: operational</span><span>Application details <span aria-hidden="true">·</span> Demo workspace</span></footer>
    </section>`;
  }

  function render() {
    const active = appByName(state.activeName);
    document.querySelector("#breadcrumb-current").textContent = state.page === "detail" && active ? active.name : state.page === "deploy" ? "Deploy application" : "Applications";
    document.querySelectorAll("[data-nav]").forEach((link) => link.classList.toggle("is-active", link.dataset.nav === state.page || (state.page === "detail" && link.dataset.nav === "apps")));
    if (state.loading) {
      appRoot.innerHTML = `<section class="loading-view"><span class="loading-spinner" aria-hidden="true"></span><p>Loading your workspace</p></section>`;
    } else if (state.page === "deploy") appRoot.innerHTML = renderDeploy();
    else if (state.page === "detail") appRoot.innerHTML = active ? renderDetails(active) : renderEmptyDetails();
    else appRoot.innerHTML = renderDashboard();
  }

  function renderEmptyDetails() {
    return `<section class="page-content empty-state detail-empty"><span class="empty-mark" aria-hidden="true">◫</span><h3>Application not found</h3><p>It may have been removed from this workspace.</p><button class="button button-primary" type="button" data-action="back">Back to applications</button></section>`;
  }

  async function refreshApps() {
    state.loading = true;
    render();
    try {
      state.apps = await window.MockService.getApps();
    } catch (error) {
      state.apps = [];
      appRoot.innerHTML = `<section class="load-error"><strong>Workspace unavailable</strong><p>We couldn't load your applications. Try refreshing.</p><button class="button button-secondary" type="button" data-action="refresh">Try again</button></section>`;
      return;
    }
    state.loading = false;
    render();
  }

  function watchDeployment(name) {
    let attempts = 0;
    const check = async () => {
      if (state.page !== "detail" || state.activeName !== name || attempts++ >= 12) return;
      const current = await window.MockService.getApp(name);
      if (!current) return;
      const index = state.apps.findIndex((app) => app.name === name);
      if (index >= 0) state.apps[index] = current;
      render();
      if (["BUILDING", "DEPLOYING"].includes(current.status)) setTimeout(check, 900);
    };
    setTimeout(check, 850);
  }

  async function openLogs(name) {
    const app = appByName(name);
    if (!app) return;
    document.querySelector("#logs-title").textContent = `${app.name} logs`;
    document.querySelector("#logs-app-name").textContent = app.deployment;
    document.querySelector("#log-output").textContent = "Loading recent output…";
    dialog.showModal();
    const lines = await window.MockService.getLogs(name);
    document.querySelector("#log-output").textContent = lines.join("\n");
  }

  appRoot.addEventListener("click", async (event) => {
    const control = event.target.closest("[data-action]");
    if (!control) return;
    const { action, name } = control.dataset;
    if (action === "new-app") setPage("deploy");
    if (action === "back") setPage("apps");
    if (action === "details") setPage("detail", name);
    if (action === "filter") {
      state.filter = control.dataset.filter;
      render();
    }
    if (action === "refresh") await refreshApps();
    if (action === "logs") await openLogs(name);
    if (action === "redeploy") {
      const app = appByName(name);
      if (!app) return;
      const updated = await window.MockService.deployApp({ name: app.name, repository: app.repository, goldenPath: app.type });
      const index = state.apps.findIndex((item) => item.name === name);
      if (index >= 0) state.apps[index] = updated;
      setPage("detail", name);
      watchDeployment(name);
    }
    if (action === "delete") {
      if (!window.confirm(`Delete ${name} from this workspace?`)) return;
      await window.MockService.deleteApp(name);
      state.apps = state.apps.filter((app) => app.name !== name);
      setPage("apps");
    }
  });

  document.querySelectorAll("[data-nav]").forEach((link) => link.addEventListener("click", (event) => {
    event.preventDefault();
    setPage(link.dataset.nav);
  }));

  appRoot.addEventListener("change", (event) => {
    if (event.target.name !== "goldenPath") return;
    appRoot.querySelectorAll(".path-option").forEach((option) => option.classList.toggle("is-chosen", option.contains(event.target)));
  });

  appRoot.addEventListener("submit", async (event) => {
    if (event.target.id !== "deploy-form") return;
    event.preventDefault();
    const form = event.target;
    const values = new FormData(form);
    const name = String(values.get("name") || "").trim();
    const repository = String(values.get("repository") || "").trim();
    const goldenPath = String(values.get("goldenPath") || "Static Website");
    const error = document.querySelector("#form-error");
    const nameValid = /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(name) && name.length <= 40;
    let repositoryUrl;
    try { repositoryUrl = new URL(repository); } catch { repositoryUrl = null; }
    if (!nameValid || !repositoryUrl || repositoryUrl.hostname !== "github.com" || repositoryUrl.pathname.split("/").filter(Boolean).length < 2) {
      error.hidden = false;
      error.textContent = !nameValid ? "Choose a name using lowercase letters, numbers, and hyphens (up to 40 characters)." : "Enter a valid public GitHub repository URL, such as https://github.com/you/project.";
      return;
    }
    if (state.apps.some((app) => app.name === name)) {
      error.hidden = false;
      error.textContent = "An application with this name already exists in the workspace.";
      return;
    }
    const submit = form.querySelector("[type=submit]");
    submit.disabled = true;
    submit.innerHTML = `<span class="loading-spinner small-spinner" aria-hidden="true"></span><span>Starting deployment…</span>`;
    try {
      const created = await window.MockService.deployApp({ name, repository, goldenPath });
      state.apps.push(created);
      setPage("detail", name);
      watchDeployment(name);
    } catch {
      submit.disabled = false;
      error.hidden = false;
      error.textContent = "We couldn't start this deployment. Please try again.";
    }
  });

  dialog.addEventListener("click", (event) => {
    if (event.target === dialog || event.target.closest("[data-action=close-dialog]")) dialog.close();
  });

  refreshApps();
})();