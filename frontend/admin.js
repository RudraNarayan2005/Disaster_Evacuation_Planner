const API_BASE = "";
let token = localStorage.getItem("admin_token") || null;

function authHeaders() {
  return { Authorization: `Bearer ${token}` };
}

function showDashboard() {
  document.getElementById("login-view").style.display = "none";
  document.getElementById("dashboard-view").style.display = "block";
  document.getElementById("btn-logout").style.display = "inline-block";
  loadEverything();
}

function showLogin() {
  document.getElementById("login-view").style.display = "block";
  document.getElementById("dashboard-view").style.display = "none";
  document.getElementById("btn-logout").style.display = "none";
}

// ---------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------
document.getElementById("btn-login").onclick = async () => {
  const username = document.getElementById("login-username").value.trim();
  const password = document.getElementById("login-password").value;
  const errorEl = document.getElementById("login-error");
  errorEl.textContent = "";

  if (!username || !password) {
    errorEl.textContent = "Enter a username and password.";
    return;
  }

  try {
    const res = await fetch(
      `${API_BASE}/api/admin/login?username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`,
      { method: "POST" }
    );
    if (!res.ok) {
      errorEl.textContent = "Invalid username or password.";
      return;
    }
    const data = await res.json();
    token = data.token;
    localStorage.setItem("admin_token", token);
    showDashboard();
  } catch (err) {
    errorEl.textContent = "Couldn't reach the server.";
  }
};

document.getElementById("btn-logout").onclick = async () => {
  try {
    await fetch(`${API_BASE}/api/admin/logout`, { method: "POST", headers: authHeaders() });
  } catch (err) {
    /* ignore */
  }
  token = null;
  localStorage.removeItem("admin_token");
  showLogin();
};

async function authedFetch(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...(options.headers || {}), ...authHeaders() },
  });
  if (res.status === 401) {
    token = null;
    localStorage.removeItem("admin_token");
    showLogin();
    throw new Error("session expired");
  }
  return res;
}

// ---------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------
async function loadEverything() {
  await Promise.all([loadOverview(), loadRiskTable(), loadIncidents(), loadShelters()]);
}

async function loadOverview() {
  try {
    const res = await authedFetch("/api/admin/overview");
    const data = await res.json();
    const stats = [
      { num: data.shelters.total, label: "Total shelters" },
      { num: data.shelters.open_count, label: "Open shelters" },
      { num: data.incidents.open_incidents, label: "Open incidents" },
      { num: data.incidents.open_sos, label: "Active SOS" },
      { num: data.roads.high_risk_edges, label: "High-risk road segments" },
    ];
    document.getElementById("stat-row").innerHTML = stats
      .map((s) => `<div class="stat-card"><div class="num">${s.num}</div><div class="label">${s.label}</div></div>`)
      .join("");
  } catch (err) {
    /* handled by authedFetch redirect */
  }
}

async function loadRiskTable() {
  try {
    const [floodRes, cycloneRes] = await Promise.all([
      fetch(`${API_BASE}/api/weather/all`),
      fetch(`${API_BASE}/api/cyclone/all`),
    ]);
    const flood = await floodRes.json();
    const cyclone = await cycloneRes.json();

    const cycloneByDistrict = Object.fromEntries(cyclone.map((c) => [c.district, c]));
    const rank = { Low: 0, Moderate: 1, High: 2, Severe: 3 };

    const rows = flood.map((f) => {
      const c = cycloneByDistrict[f.district] || {};
      const floodLevel = f.impact_level || (f.error ? "n/a" : "Low");
      const cycloneLevel = c.impact_level || (c.error ? "n/a" : "Low");
      const overall = rank[cycloneLevel] > rank[floodLevel] ? cycloneLevel : floodLevel;
      const hazard = rank[cycloneLevel] > rank[floodLevel] ? "cyclone" : "flood";
      return { district: f.district, floodLevel, cycloneLevel, overall, hazard, error: f.error || c.error };
    });

    const body = document.getElementById("risk-table-body");
    if (!rows.length) {
      body.innerHTML = `<tr class="empty-row"><td colspan="5">No district data available.</td></tr>`;
      return;
    }
    body.innerHTML = rows
      .map(
        (r) => `
      <tr>
        <td>${r.district}</td>
        <td class="risk-${r.floodLevel}">${r.floodLevel}</td>
        <td class="risk-${r.cycloneLevel}">${r.cycloneLevel}</td>
        <td class="risk-${r.overall}"><b>${r.overall}</b></td>
        <td class="muted">${r.error ? `error: ${r.error}` : r.hazard}</td>
      </tr>`
      )
      .join("");
  } catch (err) {
    document.getElementById("risk-table-body").innerHTML =
      `<tr class="empty-row"><td colspan="5">Couldn't load risk data.</td></tr>`;
  }
}

document.getElementById("btn-refresh-risk").onclick = async () => {
  const logEl = document.getElementById("admin-log");
  logEl.textContent = "Refreshing live risk for every tracked district…";
  try {
    const res = await authedFetch("/api/admin/refresh-risk", { method: "POST" });
    const data = await res.json();
    logEl.textContent = `Refreshed — ${data.roads_updated.edges_touched} road segments re-scored.`;
    await Promise.all([loadRiskTable(), loadOverview()]);
  } catch (err) {
    logEl.textContent = "Refresh failed.";
  }
};

async function loadIncidents() {
  try {
    const res = await authedFetch("/api/admin/incidents");
    const incidents = await res.json();
    document.getElementById("incidents-count").textContent = `${incidents.length} open`;

    const body = document.getElementById("incidents-table-body");
    if (!incidents.length) {
      body.innerHTML = `<tr class="empty-row"><td colspan="4">No open incidents.</td></tr>`;
      return;
    }
    body.innerHTML = incidents
      .map(
        (inc) => `
      <tr data-id="${inc.id}">
        <td>${inc.report_type.replace("_", " ")}</td>
        <td>${inc.description || "—"}</td>
        <td class="muted">${inc.created_at}</td>
        <td><button class="btn btn-ghost btn-small resolve-btn" data-id="${inc.id}">Resolve</button></td>
      </tr>`
      )
      .join("");

    document.querySelectorAll(".resolve-btn").forEach((btn) => {
      btn.onclick = async () => {
        btn.disabled = true;
        btn.textContent = "Resolving…";
        await authedFetch(`/api/admin/incidents/${btn.dataset.id}/resolve`, { method: "PUT" });
        loadIncidents();
        loadOverview();
      };
    });
  } catch (err) {
    /* handled by authedFetch redirect */
  }
}

async function loadShelters() {
  try {
    const res = await authedFetch("/api/admin/shelters");
    const shelters = await res.json();
    document.getElementById("shelters-count").textContent = `${shelters.length} total`;

    const body = document.getElementById("shelters-table-body");
    if (!shelters.length) {
      body.innerHTML = `<tr class="empty-row"><td colspan="6">No shelters found.</td></tr>`;
      return;
    }
    body.innerHTML = shelters
      .map(
        (s) => `
      <tr data-id="${s.id}">
        <td>${s.name}</td>
        <td class="muted">${s.district || "—"} / ${s.block || "—"}</td>
        <td>${s.shelter_type || "—"}</td>
        <td><input type="number" class="cap-input" value="${s.capacity ?? ""}" data-id="${s.id}" placeholder="—" /></td>
        <td><span class="badge ${s.is_open ? "badge-open" : "badge-closed"}">${s.is_open ? "Open" : "Closed"}</span></td>
        <td><button class="btn btn-ghost btn-small toggle-btn" data-id="${s.id}" data-open="${s.is_open}">${s.is_open ? "Close" : "Reopen"}</button></td>
      </tr>`
      )
      .join("");

    document.querySelectorAll(".toggle-btn").forEach((btn) => {
      btn.onclick = async () => {
        const newState = btn.dataset.open === "true" ? "false" : "true";
        btn.disabled = true;
        await authedFetch(`/api/admin/shelters/${btn.dataset.id}?is_open=${newState}`, { method: "PUT" });
        loadShelters();
        loadOverview();
      };
    });

    document.querySelectorAll(".cap-input").forEach((input) => {
      input.onchange = async () => {
        const value = input.value === "" ? null : parseInt(input.value, 10);
        if (value === null) return;
        await authedFetch(`/api/admin/shelters/${input.dataset.id}?capacity=${value}`, { method: "PUT" });
      };
    });
  } catch (err) {
    /* handled by authedFetch redirect */
  }
}

// ---------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------
if (token) {
  showDashboard();
} else {
  showLogin();
}
