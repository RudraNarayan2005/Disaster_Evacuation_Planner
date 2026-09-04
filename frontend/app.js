const API_BASE = "";

const map = L.map("map").setView([20.2961, 85.8245], 8);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);

const shelterIcon = L.divIcon({ html: "🏠", className: "", iconSize: [22, 22], iconAnchor: [11, 11] });
const closedShelterIcon = L.divIcon({ html: "🚫", className: "", iconSize: [20, 20], iconAnchor: [10, 10] });
const sosIcon = L.divIcon({ html: "🆘", className: "", iconSize: [26, 26], iconAnchor: [13, 13] });
const incidentIcon = L.divIcon({ html: "⚠️", className: "", iconSize: [22, 22], iconAnchor: [11, 11] });
const userIcon = L.divIcon({ html: "🧍", className: "", iconSize: [24, 24], iconAnchor: [12, 12] });

const sheltersLayer = L.layerGroup().addTo(map);
const incidentsLayer = L.layerGroup().addTo(map);
const roadsLayer = L.layerGroup().addTo(map);
const routeLayer = L.layerGroup().addTo(map);
let userMarker = null;
let userLocation = null; // {lat, lng}
let lastNotifiedImpactLevel = null;

function updateNotificationStatus() {
  const el = document.getElementById("notification-status");
  if (!el) return;
  if (!("Notification" in window)) {
    el.textContent = "Browser notifications are not supported here.";
    return;
  }
  const labels = {
    granted: "🔔 Evacuation alerts enabled",
    denied: "🔕 Notifications blocked — enable them in browser site settings.",
    default: "Notifications not enabled — click Enable evacuation alerts.",
  };
  el.textContent = labels[Notification.permission] || "";
}

async function requestNotificationPermission() {
  if (!("Notification" in window)) {
    logMessage("Browser notifications are not supported in this browser.");
    return;
  }
  if (Notification.permission === "default") await Notification.requestPermission();
  updateNotificationStatus();
}

function sendBrowserNotification(title, body) {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  const notification = new Notification(title, { body, tag: "evacuation-risk-alert" });
  notification.onclick = () => { window.focus(); notification.close(); };
}

function maybeNotifyRisk(data) {
  const level = data.impact_level || "Low";
  if (level === lastNotifiedImpactLevel) return;
  lastNotifiedImpactLevel = level;
  if (data.should_evacuate) {
    sendBrowserNotification(`⚠️ Evacuate: ${data.district || "your area"}`, data.message || `Current risk level: ${level}`);
  }
}

// ---------------------------------------------------------------------
// User location
// ---------------------------------------------------------------------
function setUserLocation(lat, lng) {
  userLocation = { lat, lng };
  if (userMarker) map.removeLayer(userMarker);
  userMarker = L.marker([lat, lng], { icon: userIcon, draggable: true }).addTo(map);
  userMarker.on("dragend", () => {
    const pos = userMarker.getLatLng();
    setUserLocation(pos.lat, pos.lng);
  });
  document.getElementById("location-readout").innerHTML =
    `Location set: <b>${lat.toFixed(4)}, ${lng.toFixed(4)}</b> — drag the marker or click the map to adjust.`;
}

map.on("click", (e) => setUserLocation(e.latlng.lat, e.latlng.lng));

document.getElementById("btn-use-browser-location").onclick = () => {
  if (!navigator.geolocation) {
    logMessage("Browser geolocation isn't available here.");
    return;
  }
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      setUserLocation(pos.coords.latitude, pos.coords.longitude);
      map.setView([pos.coords.latitude, pos.coords.longitude], 12);
    },
    () => logMessage("Couldn't get your browser location — click the map instead.")
  );
};

function requireLocation() {
  if (!userLocation) {
    logMessage("Set your location first (click the map or use browser location).");
    return false;
  }
  return true;
}

// ---------------------------------------------------------------------
// District list (drives the risk-check dropdown)
// ---------------------------------------------------------------------
async function loadDistricts() {
  const select = document.getElementById("district-select");
  try {
    const res = await fetch(`${API_BASE}/api/districts`);
    const districts = await res.json();
    select.innerHTML = districts.map((d) => `<option value="${d.district}">${d.district}</option>`).join("");
  } catch (err) {
    select.innerHTML = `<option value="Puri">Puri</option>`;
    logMessage("Couldn't load district list — defaulting to Puri.");
  }
}
loadDistricts();

const notificationButton = document.getElementById("btn-enable-notifications");
if (notificationButton) notificationButton.onclick = requestNotificationPermission;
updateNotificationStatus();

// ---------------------------------------------------------------------
// Risk check + nearest shelters
// ---------------------------------------------------------------------
document.getElementById("btn-check-risk").onclick = async () => {
  if (!requireLocation()) return;
  const district = document.getElementById("district-select").value;
  const resultEl = document.getElementById("risk-result");
  resultEl.style.display = "block";
  resultEl.innerHTML = `<div class="msg">Checking live weather → risk model → nearest shelters…</div>`;

  try {
    const res = await fetch(
      `${API_BASE}/api/check-my-risk/combined?lat=${userLocation.lat}&lng=${userLocation.lng}&district=${encodeURIComponent(district)}`
    );
    const data = await res.json();
    if (data.error) {
      resultEl.innerHTML = `<div class="msg">${data.error}</div>`;
      return;
    }
    renderRiskResult(data);
    maybeNotifyRisk(data);
  } catch (err) {
    resultEl.innerHTML = `<div class="msg">Couldn't reach the server — is the backend running?</div>`;
  }
};

function renderRiskResult(data) {
  const resultEl = document.getElementById("risk-result");
  const level = data.impact_level || "Low";
  let html = `<div class="level level-${level}">${level} risk${data.driving_hazard ? " · " + data.driving_hazard : ""}</div>`;
  html += `<div class="msg">${data.message || ""}</div>`;

  if (data.nearest_shelters && data.nearest_shelters.length) {
    html += data.nearest_shelters
      .map(
        (s, i) => `
      <div class="shelter-row">
        <div class="info"><b>${s.name}</b><span>${s.block ? s.block + ", " : ""}${s.district} · ${s.distance_km} km</span></div>
        <button class="route-btn" data-lat="${s.lat}" data-lng="${s.lng}" data-name="${s.name.replace(/"/g, "&quot;")}">Route</button>
      </div>`
      )
      .join("");
  }

  resultEl.innerHTML = html;

  resultEl.querySelectorAll(".route-btn").forEach((btn) => {
    btn.onclick = () => routeToShelter(parseFloat(btn.dataset.lat), parseFloat(btn.dataset.lng), btn.dataset.name);
  });
}

// ---------------------------------------------------------------------
// Routing
// ---------------------------------------------------------------------
async function routeToShelter(shelterLat, shelterLng, shelterName) {
  if (!requireLocation()) return;
  logMessage(`Computing safest route to ${shelterName}…`);

  try {
    const res = await fetch(
      `${API_BASE}/api/route?user_lat=${userLocation.lat}&user_lng=${userLocation.lng}&shelter_lat=${shelterLat}&shelter_lng=${shelterLng}`
    );
    const data = await res.json();
    routeLayer.clearLayers();

    const routeCard = document.getElementById("route-card");
    const summaryEl = document.getElementById("route-summary");

    if (data.error || !data.path_coords) {
      routeCard.style.display = "block";
      summaryEl.innerHTML = `${data.error || "No route found."}`;
      logMessage(`Route to ${shelterName}: ${data.error || "no route found"}.`);
      return;
    }

    const latlngs = data.path_coords.map(([lat, lng]) => [lat, lng]);
    L.polyline(latlngs, { color: "#ff6a45", weight: 5, opacity: 0.9 }).addTo(routeLayer);
    L.marker(latlngs[latlngs.length - 1], { icon: shelterIcon }).addTo(routeLayer).bindPopup(`<b>${shelterName}</b>`);
    map.fitBounds(latlngs, { padding: [40, 40] });

    routeCard.style.display = "block";
    const km = (data.total_cost / 1000).toFixed(1);
    summaryEl.innerHTML = `To <b>${shelterName}</b><br>Risk-weighted route cost: <b>${km} km-equivalent</b><br>${latlngs.length} waypoints`;
    logMessage(`Route to ${shelterName} drawn on map.`);
  } catch (err) {
    logMessage(`Failed to compute route to ${shelterName}.`);
  }
}

document.getElementById("btn-clear-route").onclick = () => {
  routeLayer.clearLayers();
  document.getElementById("route-card").style.display = "none";
};

// ---------------------------------------------------------------------
// Shelters (default view, before a risk check has been run)
// ---------------------------------------------------------------------
async function loadShelters() {
  try {
    const center = map.getCenter();
    const res = await fetch(`${API_BASE}/api/nearest-shelters?lat=${center.lat}&lng=${center.lng}&limit=30`);
    const shelters = await res.json();
    sheltersLayer.clearLayers();
    shelters.forEach((s) => {
      L.marker([s.lat, s.lng], { icon: shelterIcon })
        .addTo(sheltersLayer)
        .bindPopup(`<b>${s.name}</b><br>${s.district}, ${s.block}<br>Type: ${s.shelter_type}<br>${s.distance_km} km away`);
    });
  } catch (err) {
    logMessage("Failed to load shelters — is the backend running?");
  }
}
loadShelters();

// ---------------------------------------------------------------------
// Incidents / SOS
// ---------------------------------------------------------------------
async function loadIncidents() {
  try {
    const res = await fetch(`${API_BASE}/api/incidents`);
    const incidents = await res.json();
    incidentsLayer.clearLayers();
    incidents.forEach((inc) => plotIncident(inc));
  } catch (err) {
    logMessage("Failed to load incidents");
  }
}
loadIncidents();

function plotIncident(inc) {
  const icon = inc.report_type === "sos" ? sosIcon : incidentIcon;
  L.marker([inc.lat, inc.lng], { icon })
    .addTo(incidentsLayer)
    .bindPopup(`<b>${inc.report_type.toUpperCase()}</b><br>${inc.description || ""}<br><span style="color:#8b96a5">${inc.created_at}</span>`);
}

document.getElementById("btn-report-incident").onclick = async () => {
  if (!requireLocation()) return;
  const report_type = document.getElementById("incident-type").value;
  const description = document.getElementById("incident-desc").value;
  const btn = document.getElementById("btn-report-incident");
  btn.disabled = true;
  try {
    const res = await fetch(
      `${API_BASE}/api/incidents?report_type=${report_type}&lat=${userLocation.lat}&lng=${userLocation.lng}&description=${encodeURIComponent(description)}`,
      { method: "POST" }
    );
    const result = await res.json();
    if (result.error) {
      logMessage(`Report failed: ${result.error}`);
    } else {
      logMessage(`Reported ${report_type.replace("_", " ")} at your location.`);
      document.getElementById("incident-desc").value = "";
    }
  } catch (err) {
    logMessage("Report failed — is the backend running?");
  } finally {
    btn.disabled = false;
  }
};

document.getElementById("btn-sos").onclick = async () => {
  if (!requireLocation()) return;
  const description = document.getElementById("incident-desc").value || "SOS from map UI";
  const btn = document.getElementById("btn-sos");
  btn.disabled = true;
  try {
    const res = await fetch(
      `${API_BASE}/api/sos?lat=${userLocation.lat}&lng=${userLocation.lng}&description=${encodeURIComponent(description)}`,
      { method: "POST" }
    );
    const result = await res.json();
    logMessage(`SOS sent: ${result.emergency_id || "(no id returned)"}`);
  } catch (err) {
    logMessage("SOS failed — is the backend running?");
  } finally {
    btn.disabled = false;
  }
};

// ---------------------------------------------------------------------
// Road network (colored by live risk_weight)
// ---------------------------------------------------------------------
function colorForRiskWeight(w) {
  if (w >= 8) return "#e0473f";   // severe
  if (w >= 4.5) return "#e07a3b"; // high
  if (w >= 2) return "#d9a441";   // moderate
  return "#33b17a";                // low/safe
}

async function loadRoadNetwork() {
  try {
    const res = await fetch(`${API_BASE}/api/road-network`);
    const data = await res.json();
    roadsLayer.clearLayers();

    const nodeById = Object.fromEntries(data.nodes.map((n) => [n.id, n]));
    data.edges.forEach((e) => {
      const a = nodeById[e.from_node];
      const b = nodeById[e.to_node];
      if (!a || !b) return;
      L.polyline(
        [[a.lat, a.lng], [b.lat, b.lng]],
        {
          color: e.is_closed ? "#555" : colorForRiskWeight(e.risk_weight),
          weight: 3,
          opacity: e.is_closed ? 0.4 : 0.75,
          dashArray: e.is_closed ? "4,6" : null,
        }
      )
        .addTo(roadsLayer)
        .bindPopup(
          `Risk weight: <b>${e.risk_weight.toFixed(1)}</b><br>${(e.distance_m / 1000).toFixed(1)} km${e.is_closed ? "<br><b>Closed</b>" : ""}`
        );
    });
  } catch (err) {
    logMessage("Failed to load road network.");
  }
}
loadRoadNetwork();

document.getElementById("btn-refresh-roads").onclick = loadRoadNetwork;

document.getElementById("toggle-roads").onchange = (e) => {
  if (e.target.checked) map.addLayer(roadsLayer);
  else map.removeLayer(roadsLayer);
};
document.getElementById("toggle-shelters").onchange = (e) => {
  if (e.target.checked) map.addLayer(sheltersLayer);
  else map.removeLayer(sheltersLayer);
};

// ---------------------------------------------------------------------
// WebSocket live updates
// ---------------------------------------------------------------------
const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
const ws = new WebSocket(`${wsProtocol}//${window.location.host}/ws`);
const wsStatus = document.getElementById("ws-status");

ws.onopen = () => {
  wsStatus.textContent = "● Live";
  wsStatus.className = "status-connected";
};
ws.onclose = () => {
  wsStatus.textContent = "● Disconnected";
  wsStatus.className = "status-disconnected";
};

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);

  if (msg.type === "risk_alert") {
    const data = msg.data || {};
    logMessage(`📡 Risk alert: ${data.district || "District"} is now ${data.impact_level || "unknown"}`);
    if (data.should_evacuate) {
      sendBrowserNotification(`⚠️ Evacuate: ${data.district || "your area"}`, `Risk level is now ${data.impact_level}. ${data.driving_hazard || "Please move to a safe shelter."}`);
    }
    return;
  }

  if (msg.type === "risk_updated") {
    loadRoadNetwork();
    const worst = (msg.data.districts || [])
      .filter((d) => d.overall_impact_level)
      .sort((a, b) => ({ Low: 0, Moderate: 1, High: 2, Severe: 3 }[b.overall_impact_level] - { Low: 0, Moderate: 1, High: 2, Severe: 3 }[a.overall_impact_level]))[0];
    logMessage(
      `Risk refreshed · ${msg.data.roads_updated.edges_touched} road segments re-scored` +
        (worst ? ` · worst: ${worst.district} (${worst.overall_impact_level})` : "")
    );
    return;
  }

  const data = msg.data;
  if (!data) return;
  plotIncident(data);
  logMessage(`${msg.type === "sos_alert" ? "🆘 SOS" : "⚠️ Incident"}: ${data.description || data.report_type}`);
  if (map.getZoom() < 10) map.setView([data.lat, data.lng], 11);
};

function logMessage(text) {
  const log = document.getElementById("log");
  const entry = document.createElement("div");
  entry.className = "log-entry";
  entry.innerHTML = `${text}<span class="t">${new Date().toLocaleTimeString()}</span>`;
  log.prepend(entry);
  while (log.children.length > 25) log.removeChild(log.lastChild);
}
