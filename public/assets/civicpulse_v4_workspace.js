/**
 * CivicPulse v4.1 Map-First Geolocation, "+" Multi-Jurisdiction Filter & Rep Profiles
 * (public/assets/civicpulse_v4_workspace.js)
 *
 * Design rules:
 *  - Map comes FIRST (zero extra banners or jurisdiction pill walls above the map).
 *  - Adds a "📍 Use My Location" button directly into the existing map search bar.
 *  - Enhances every active card inside "RESOLVED LOCATION & OVERLAPPING GOVERNMENTS"
 *    with a "+" toggle button that adds/removes that jurisdiction to the user's filter
 *    (supporting many jurisdictions at once).
 *  - Only after 1+ jurisdictions are added to the filter does the scoped workspace
 *    appear below the map with:
 *      1. Active filter chips + consolidated "How Public Comment Works" button
 *      2. Clickable Representative bubbles (contact info lives at the Rep level)
 *      3. Scoped tabs: Before the Vote (date-first grouped agendas), Votes & Radar, Alignment
 */

const LS_SELECTED_JURS_KEY = "cp_v4_selected_jurisdictions";

let dirData = { jurisdictions: [] };
let upcomingMeetings = [];
let agendaPreviews = [];
let boundariesGeo = null;
let cachedJurPayloads = {};
let selectedJurIds = new Set();
let activeWorkspaceTab = "before";

function esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function jurSlugFromId(ocdId) {
  return String(ocdId || "")
    .replace(/^ocd-division\//, "")
    .replace(/[^a-z0-9]+/gi, "_")
    .toLowerCase();
}

function initialsFor(name) {
  const parts = String(name || "?").trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function formatDateHeading(isoDate) {
  if (!isoDate || isoDate === "undated") return "Date To Be Announced";
  const parts = isoDate.slice(0, 10).split("-");
  if (parts.length !== 3) return isoDate;
  const d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
  if (Number.isNaN(d.getTime())) return isoDate;
  return d.toLocaleDateString("en-US", {
    weekday: "long",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function haversineKm(lat1, lon1, lat2, lon2) {
  const R = 6371;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

async function fetchJsonSafe(url, fallback) {
  try {
    const r = await fetch(url);
    if (!r.ok) return fallback;
    return await r.json();
  } catch {
    return fallback;
  }
}

async function loadJurisdictionPayload(jurId) {
  if (cachedJurPayloads[jurId]) return cachedJurPayloads[jurId];
  const slug = jurSlugFromId(jurId);
  const data = await fetchJsonSafe(`data/${slug}.json`, null);
  if (data) cachedJurPayloads[jurId] = data;
  return data;
}

function persistSelectedJurs() {
  try {
    localStorage.setItem(LS_SELECTED_JURS_KEY, JSON.stringify(Array.from(selectedJurIds)));
  } catch {
    // ignore storage errors
  }
}

function toggleJurisdictionInFilter(jurId) {
  if (!jurId) return;
  if (selectedJurIds.has(jurId)) {
    selectedJurIds.delete(jurId);
  } else {
    selectedJurIds.add(jurId);
  }
  persistSelectedJurs();
  syncPlusButtonsState();
  renderScopedWorkspace();
}

// ---------------------------------------------------------------------------
// 1. "Use My Location" Button Inside the Existing Map Bar (Map-First)
// ---------------------------------------------------------------------------
function resolveOverlappingAtCoords(lat, lng) {
  const allJurs = dirData.jurisdictions || [];
  const matched = new Map();

  if (window.turf && boundariesGeo && Array.isArray(boundariesGeo.features)) {
    const pt = window.turf.point([lng, lat]);
    for (const feat of boundariesGeo.features) {
      try {
        if (window.turf.booleanPointInPolygon(pt, feat)) {
          const divId = feat?.properties?.ocd_division_id;
          if (!divId) continue;
          const j = allJurs.find((x) => x.ocd_division_id === divId);
          if (j && !matched.has(divId)) matched.set(divId, j);
        }
      } catch {
        // skip invalid geometry
      }
    }
  }

  for (const j of allJurs) {
    if (matched.has(j.ocd_division_id)) continue;
    const jLat = Number(j.latitude ?? j.lat ?? 0);
    const jLng = Number(j.longitude ?? j.lng ?? 0);
    if (!jLat || !jLng) continue;
    const radius = j.level === "county" || j.level === "school_district" ? 36 : 14;
    if (haversineKm(lat, lng, jLat, jLng) <= radius) {
      matched.set(j.ocd_division_id, j);
    }
  }

  return Array.from(matched.values()).sort((a, b) => {
    const aAct = a.status === "active" ? 0 : 1;
    const bAct = b.status === "active" ? 0 : 1;
    if (aAct !== bAct) return aAct - bAct;
    return String(a.name || "").localeCompare(String(b.name || ""));
  });
}

function renderFallbackResolvedPanel(lat, lng, labelText) {
  const matches = resolveOverlappingAtCoords(lat, lng);
  const mapEl = document.getElementById("map");
  const mapCard = mapEl?.closest("div.rounded-2xl, section, .map-card") || mapEl?.parentElement;
  if (!mapCard) return;

  let panel = document.getElementById("cpV4GeoResolvedPanel");
  if (!panel) {
    panel = document.createElement("div");
    panel.id = "cpV4GeoResolvedPanel";
    panel.className = "mt-4 rounded-2xl border border-amber-200/80 bg-[#f6efe2] p-4 sm:p-5 space-y-3";
    mapCard.insertAdjacentElement("afterend", panel);
  }

  const cards = matches
    .slice(0, 8)
    .map((j) => {
      const isAct = j.status === "active";
      const isAdded = selectedJurIds.has(j.ocd_division_id);
      const plusBtn = isAct
        ? `<button
            type="button"
            data-v4-plus-jur="${esc(j.ocd_division_id)}"
            title="${isAdded ? "Remove from workspace filter" : "Add to workspace filter"}"
            class="w-7 h-7 rounded-full inline-flex items-center justify-center text-sm font-bold border transition shrink-0 cursor-pointer ${
              isAdded
                ? "bg-emerald-600 text-white border-emerald-600 hover:bg-emerald-700"
                : "bg-white text-slate-800 border-slate-300 hover:bg-blue-600 hover:text-white hover:border-blue-600"
            }"
          >${isAdded ? "✓" : "+"}</button>`
        : "";

      return `
        <div class="rounded-xl border border-slate-200 bg-white/95 p-3.5 flex items-start justify-between gap-2">
          <div class="min-w-0">
            <div class="text-[11px] font-bold uppercase tracking-wide ${isAct ? "text-emerald-700" : "text-slate-500"}">
              ${esc((j.level || "local").replace(/_/g, " "))} • ${isAct ? "ACTIVE" : "UNCLAIMED"}
            </div>
            <div class="text-sm font-bold text-slate-900 mt-0.5 break-words">${esc(j.name)}</div>
            <div class="text-xs text-slate-500 mt-1">
              ${isAct ? "Click + to add to your filter" : "Not yet tracked"}
            </div>
          </div>
          ${plusBtn}
        </div>
      `;
    })
    .join("");

  panel.innerHTML = `
    <div class="flex items-center justify-between gap-2">
      <div>
        <div class="text-[11px] font-bold uppercase tracking-wider text-slate-500">
          RESOLVED LOCATION &amp; OVERLAPPING GOVERNMENTS
        </div>
        <div class="text-base font-bold text-slate-900">${esc(labelText)} (${lat.toFixed(4)}, ${lng.toFixed(4)})</div>
      </div>
      <button type="button" id="cpV4DismissGeoPanel" class="text-xs text-slate-500 hover:text-slate-800 cursor-pointer">
        Dismiss ×
      </button>
    </div>
    <div class="grid grid-cols-1 md:grid-cols-3 gap-3">${cards || '<div class="text-xs text-slate-600">No overlapping jurisdictions found at these coordinates.</div>'}</div>
  `;

  panel.querySelector("#cpV4DismissGeoPanel")?.addEventListener("click", () => panel.remove());
  panel.querySelectorAll("[data-v4-plus-jur]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleJurisdictionInFilter(btn.dataset.v4PlusJur);
    });
  });
}

function handleUseMyLocationClick(btn) {
  if (!navigator.geolocation) {
    alert("Geolocation is not supported by your browser. Please click your location on the map instead.");
    return;
  }

  const origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Locating...";

  navigator.geolocation.getCurrentPosition(
    (pos) => {
      const lat = pos.coords.latitude;
      const lng = pos.coords.longitude;
      btn.disabled = false;
      btn.textContent = origText;

      // Prefer the existing map app's native coordinate handler so the native
      // "RESOLVED LOCATION & OVERLAPPING GOVERNMENTS" panel opens seamlessly
      if (typeof window.handleCoordinateLookup === "function") {
        window.handleCoordinateLookup(lat, lng, "My Current Location");
        setTimeout(injectPlusButtonsIntoResolvedPanel, 120);
      } else if (typeof window.handleMapCoordinateClick === "function") {
        window.handleMapCoordinateClick(lat, lng);
        setTimeout(injectPlusButtonsIntoResolvedPanel, 120);
      } else {
        // Fallback: resolve locally via Turf.js / coordinates and render overlapping panel
        renderFallbackResolvedPanel(lat, lng, "My Current Location");
      }

      // Also fly existing Leaflet map if exposed
      if (window.mapInstance && typeof window.mapInstance.setView === "function") {
        window.mapInstance.setView([lat, lng], 12);
      }
    },
    (err) => {
      btn.disabled = false;
      btn.textContent = origText;
      const msg =
        err.code === 1
          ? "Location access was denied. You can click anywhere on the map or enter an address instead."
          : "Could not determine your current location. Please click on the map instead.";
      alert(msg);
    },
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
  );
}

function mountUseMyLocationButton() {
  if (document.getElementById("cpV4UseMyLocationBtn")) return;

  const btn = document.createElement("button");
  btn.id = "cpV4UseMyLocationBtn";
  btn.type = "button";
  btn.className =
    "px-3.5 py-2 rounded-xl border border-slate-300 bg-white hover:bg-slate-100 text-slate-800 text-xs sm:text-sm font-semibold transition inline-flex items-center gap-1.5 shrink-0 cursor-pointer";
  btn.textContent = "📍 Use My Location";
  btn.title = "Use your device location to resolve overlapping city, county, and school governments";
  btn.addEventListener("click", () => handleUseMyLocationClick(btn));

  // Place cleanly right inside the existing map address search bar (next to Find button)
  const existingAddrBtn =
    document.getElementById("addressLookupBtn") ||
    document.getElementById("addrLookupBtn") ||
    document.getElementById("mapAddressBtn");
  if (existingAddrBtn && existingAddrBtn.parentElement) {
    existingAddrBtn.insertAdjacentElement("afterend", btn);
    return;
  }

  const existingAddrInput =
    document.getElementById("addressLookupInput") ||
    document.getElementById("addrSearchInput") ||
    document.querySelector('input[placeholder*="address" i]');
  if (existingAddrInput && existingAddrInput.parentElement) {
    existingAddrInput.parentElement.insertAdjacentElement("afterend", btn);
    return;
  }

  // Fallback: place cleanly in a slim bar directly above #map
  const mapEl = document.getElementById("map");
  if (mapEl && mapEl.parentElement) {
    const bar = document.createElement("div");
    bar.className = "px-4 py-2 bg-slate-50 border-b border-slate-200 flex items-center justify-end";
    bar.appendChild(btn);
    mapEl.insertAdjacentElement("beforebegin", bar);
  }
}

// ---------------------------------------------------------------------------
// 2. Inject "+" Filter Buttons into "RESOLVED LOCATION & OVERLAPPING GOVERNMENTS"
// ---------------------------------------------------------------------------
function matchActiveJurisdictionFromText(cardText) {
  const low = (cardText || "").toLowerCase();
  const activeJurs = (dirData.jurisdictions || []).filter((j) => j.status === "active");
  // Longest-name match first so "Boulder County Board of Commissioners" beats "Boulder"
  const sorted = [...activeJurs].sort((a, b) => (b.name || "").length - (a.name || "").length);
  return sorted.find((j) => j.name && low.includes(j.name.toLowerCase())) || null;
}

function findResolvedLocationPanels() {
  const panels = [];
  document.querySelectorAll("section, div, aside").forEach((el) => {
    if (el.id === "cpV4WorkspaceRoot" || el.id === "cpV4GeoResolvedPanel") return;
    const txt = (el.textContent || "").toUpperCase();
    if (
      txt.includes("RESOLVED LOCATION") &&
      txt.includes("OVERLAPPING GOVERNMENT") &&
      el.querySelectorAll("div, button, a").length >= 2 &&
      el.textContent.length < 4000
    ) {
      // Only take the tightest container (skip ancestors that contain other matching panels)
      const hasMatchingChild = Array.from(el.children).some((ch) => {
        const ct = (ch.textContent || "").toUpperCase();
        return ct.includes("RESOLVED LOCATION") && ct.includes("OVERLAPPING GOVERNMENT");
      });
      if (!hasMatchingChild) panels.push(el);
    }
  });
  return panels;
}

function injectPlusButtonsIntoResolvedPanel() {
  const panels = findResolvedLocationPanels();
  if (!panels.length) return;

  panels.forEach((panel) => {
    // Find individual government cards inside the resolved panel
    const candidates = panel.querySelectorAll("button, a, div");
    candidates.forEach((card) => {
      if (card.dataset.v4PlusWired) return;
      const txt = (card.textContent || "").trim();
      if (!txt || txt.length > 260) return;
      if (!txt.toUpperCase().includes("ACTIVE")) return;
      if (txt.toUpperCase().includes("UNCLAIMED")) return;
      // Ensure this is a leaf card (doesn't contain multiple cards)
      if ((txt.match(/ACTIVE/gi) || []).length > 1) return;

      const jur = matchActiveJurisdictionFromText(txt);
      if (!jur) return;

      // Avoid double-wiring nested elements inside the same card
      if (card.querySelector("[data-v4-plus-jur]") || card.closest("[data-v4-plus-wired='1']")) {
        return;
      }

      card.dataset.v4PlusWired = "1";
      const prevPos = window.getComputedStyle(card).position;
      if (prevPos === "static") {
        card.style.position = "relative";
      }

      const isAdded = selectedJurIds.has(jur.ocd_division_id);
      const plusBtn = document.createElement("button");
      plusBtn.type = "button";
      plusBtn.dataset.v4PlusJur = jur.ocd_division_id;
      plusBtn.title = isAdded ? "Remove from my filter" : "Add to my filter";
      plusBtn.textContent = isAdded ? "✓" : "+";
      plusBtn.style.position = "absolute";
      plusBtn.style.top = "10px";
      plusBtn.style.right = "10px";
      plusBtn.style.zIndex = "10";
      plusBtn.className = `w-7 h-7 rounded-full inline-flex items-center justify-center text-base font-bold border shadow-xs transition cursor-pointer ${
        isAdded
          ? "bg-emerald-600 text-white border-emerald-600 hover:bg-emerald-700"
          : "bg-white text-slate-800 border-slate-300 hover:bg-blue-600 hover:text-white hover:border-blue-600"
      }`;

      plusBtn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        toggleJurisdictionInFilter(jur.ocd_division_id);
      });

      card.appendChild(plusBtn);
    });
  });

  ensureWorkspaceMountedBelowMap();
}

function syncPlusButtonsState() {
  document.querySelectorAll("[data-v4-plus-jur]").forEach((btn) => {
    const jid = btn.dataset.v4PlusJur;
    const isAdded = selectedJurIds.has(jid);
    btn.textContent = isAdded ? "✓" : "+";
    btn.title = isAdded ? "Remove from my filter" : "Add to my filter";
    btn.className = `w-7 h-7 rounded-full inline-flex items-center justify-center text-base font-bold border shadow-xs transition cursor-pointer ${
      isAdded
        ? "bg-emerald-600 text-white border-emerald-600 hover:bg-emerald-700"
        : "bg-white text-slate-800 border-slate-300 hover:bg-blue-600 hover:text-white hover:border-blue-600"
    }`;
  });
}

// ---------------------------------------------------------------------------
// 3. Clickable Representative Bubbles & Full Representative Detail Modal
// ---------------------------------------------------------------------------
function renderRepBubble(rep, jurId, jurName) {
  const pid = rep.id || rep.ocd_person_id;
  const photo = rep.photo_url
    ? `<img src="${esc(rep.photo_url)}" alt="${esc(rep.name)}" class="w-9 h-9 rounded-full object-cover border border-slate-200 shrink-0" />`
    : `<span class="w-9 h-9 rounded-full bg-slate-800 text-white text-xs font-bold inline-flex items-center justify-center shrink-0">${esc(initialsFor(rep.name))}</span>`;

  return `
    <button
      type="button"
      data-open-rep="${esc(pid)}"
      data-jur-id="${esc(jurId)}"
      class="group text-left inline-flex items-center gap-2.5 px-3 py-2 rounded-xl border border-slate-200 bg-white hover:border-blue-400 hover:shadow-sm transition cursor-pointer"
      title="View ${esc(rep.name)}'s voting record, comments, metrics & contact details"
    >
      ${photo}
      <span class="min-w-0">
        <span class="block text-sm font-semibold text-slate-900 group-hover:text-blue-700 truncate">
          ${esc(rep.name)}
        </span>
        <span class="block text-xs text-slate-500 truncate">
          ${esc(rep.role || "Member")}${rep.district ? " • " + esc(rep.district) : ""} • ${esc(jurName)}
        </span>
      </span>
      <span class="text-xs text-slate-400 group-hover:text-blue-600 pl-1">→</span>
    </button>
  `;
}

async function openRepDetailModal(jurId, personId) {
  const payload = await loadJurisdictionPayload(jurId);
  if (!payload) return;
  const jur = payload.jurisdiction || {};
  const reps = payload.entities || payload.representatives || payload.roster || [];
  const rep = reps.find((r) => (r.id || r.ocd_person_id) === personId);
  if (!rep) return;

  window.location.hash = `#/rep/${encodeURIComponent(personId)}`;

  const items = payload.agenda_items || payload.events || [];
  const repVotes = [];
  items.forEach((item) => {
    const vmap = item.votes || {};
    if (Array.isArray(vmap)) {
      const hit = vmap.find((v) => v.entity_id === personId || v.ocd_person_id === personId);
      if (hit) {
        repVotes.push({
          title: item.title,
          date: item.date || item.meeting_date || "",
          topic: item.topic || item.event_type || "General",
          outcome: item.outcome || "",
          impact_score: Math.round(item.impact_score ?? 0),
          source_url: item.source_url || "",
          vote: hit.vote || hit.value || "Recorded",
          is_pivotal: hit.is_pivotal,
          quote: hit.verbatim_quote || hit.quote || "",
          summary: hit.rationale_summary || "",
        });
      }
    } else if (vmap[personId]) {
      repVotes.push({
        title: item.title,
        date: item.date || item.meeting_date || "",
        topic: item.topic || item.event_type || "General",
        outcome: item.outcome || "",
        impact_score: Math.round(item.impact_score ?? 0),
        source_url: item.source_url || "",
        ...vmap[personId],
      });
    }
  });

  const stats = rep.metrics || rep.stats || {};
  const totalVotes = stats.total_votes ?? repVotes.length;
  const attendance = totalVotes > 0 ? `${stats.attendance_rate ?? 100}%` : "Pending";
  const avgImpact = totalVotes > 0 ? `${Math.round(stats.avg_impact_score ?? 0)}/100` : "—";
  const pivotal = stats.pivotal_votes ?? repVotes.filter((v) => v.is_pivotal).length;

  const contactLinks = [];
  if (rep.email) {
    const subject = encodeURIComponent(`Constituent Feedback — ${jur.name || "Local Government"}`);
    contactLinks.push(
      `<a href="mailto:${esc(rep.email)}?subject=${subject}" class="px-3 py-1.5 rounded-lg bg-blue-600 text-white text-xs font-semibold hover:bg-blue-700">✉️ Email ${esc(rep.email)}</a>`
    );
  }
  if (rep.phone) {
    contactLinks.push(
      `<a href="tel:${esc(rep.phone)}" class="px-3 py-1.5 rounded-lg border border-slate-300 bg-white text-slate-800 text-xs font-semibold hover:bg-slate-50">📞 ${esc(rep.phone)}</a>`
    );
  }
  const webUrl = rep.website_url || rep.website || jur.roster_url || jur.portal_url;
  if (webUrl) {
    contactLinks.push(
      `<a href="${esc(webUrl)}" target="_blank" rel="noopener noreferrer" class="px-3 py-1.5 rounded-lg border border-slate-300 bg-white text-slate-800 text-xs font-semibold hover:bg-slate-50">Official Page ↗</a>`
    );
  }

  const avatar = rep.photo_url
    ? `<img src="${esc(rep.photo_url)}" alt="${esc(rep.name)}" class="w-16 h-16 rounded-2xl object-cover border border-slate-200 shrink-0" />`
    : `<div class="w-16 h-16 rounded-2xl bg-slate-900 text-white text-xl font-bold flex items-center justify-center shrink-0">${esc(initialsFor(rep.name))}</div>`;

  const bioText =
    rep.bio_summary ||
    `${rep.name} serves as ${rep.role || "Member"} for ${jur.name || "this jurisdiction"}.`;

  const commentsList = repVotes.filter((v) => v.quote || v.summary);
  const commentsHtml = commentsList.length
    ? commentsList
        .slice(0, 6)
        .map(
          (c) => `
          <div class="p-3 rounded-xl bg-slate-50 border border-slate-200/80 text-xs space-y-1">
            <div class="font-semibold text-slate-800">${esc(c.date)} • ${esc(c.title)}</div>
            ${c.quote ? `<blockquote class="italic text-slate-700 border-l-2 border-blue-400 pl-2.5">"${esc(c.quote)}"</blockquote>` : ""}
            ${!c.quote && c.summary ? `<p class="text-slate-600">${esc(c.summary)}</p>` : ""}
          </div>
        `
        )
        .join("")
    : `<p class="text-xs text-slate-500">No direct floor remarks extracted from ingested minutes yet.</p>`;

  const votesHtml = repVotes.length
    ? repVotes
        .map((v) => {
          const vLow = (v.vote || "").toLowerCase();
          const badgeCls =
            vLow === "yes" || vLow === "aye"
              ? "bg-emerald-50 text-emerald-800 border-emerald-200"
              : vLow === "no" || vLow === "nay"
              ? "bg-rose-50 text-rose-800 border-rose-200"
              : "bg-slate-100 text-slate-700 border-slate-200";
          return `
            <div class="p-3.5 rounded-xl border border-slate-200 bg-white flex flex-col sm:flex-row sm:items-start justify-between gap-3">
              <div class="space-y-1 min-w-0">
                <div class="text-xs text-slate-500">
                  <span class="font-semibold text-slate-700">${esc(v.date)}</span> • ${esc(v.topic)} • Impact ${v.impact_score}/100
                  ${v.is_pivotal ? '<span class="ml-1.5 px-2 py-0.5 rounded-full bg-amber-100 text-amber-900 font-semibold">Pivotal</span>' : ""}
                </div>
                <div class="text-sm font-semibold text-slate-900 break-words">${esc(v.title)}</div>
                ${v.source_url ? `<a href="${esc(v.source_url)}" target="_blank" rel="noopener noreferrer" class="inline-block text-xs text-blue-600 hover:underline">Official Record ↗</a>` : ""}
              </div>
              <span class="shrink-0 px-3 py-1 rounded-full text-xs font-semibold border ${badgeCls}">
                ${esc(v.vote || "Recorded")}
              </span>
            </div>
          `;
        })
        .join("")
    : `<p class="text-sm text-slate-500">No roll-call votes recorded for this representative yet.</p>`;

  let modal = document.getElementById("cpV4RepModal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "cpV4RepModal";
    modal.className = "fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-3 sm:p-6 overflow-y-auto";
    document.body.appendChild(modal);
  }

  modal.innerHTML = `
    <div class="bg-white rounded-2xl shadow-2xl border border-slate-200 max-w-3xl w-full max-h-[90vh] overflow-y-auto p-5 sm:p-6 space-y-5">
      <div class="flex items-start justify-between gap-4">
        <div class="flex items-start gap-4">
          ${avatar}
          <div>
            <div class="text-xs font-semibold uppercase tracking-wide text-blue-700">
              ${esc(jur.name || "")} • ${esc(rep.role || "Member")}${rep.district ? " (" + esc(rep.district) + ")" : ""}
            </div>
            <h2 class="text-2xl font-bold text-slate-900 mt-0.5">${esc(rep.name)}</h2>
            <div class="text-xs text-slate-500 mt-0.5">
              Elected: ${esc(rep.elected_date || "Active Term")} • Metrics based on docs since ${esc(jur.docs_since || "2026-01-01")}
            </div>
          </div>
        </div>
        <button type="button" id="cpV4CloseRepModal" class="px-3 py-1.5 rounded-lg border border-slate-200 text-sm font-semibold text-slate-600 hover:bg-slate-100 cursor-pointer">
          ✕ Close
        </button>
      </div>

      <div class="flex flex-wrap gap-2 pt-1">${contactLinks.join("")}</div>

      <div class="p-4 rounded-xl bg-blue-50/60 border border-blue-200/80 space-y-1.5">
        <div class="flex items-center justify-between gap-2">
          <span class="text-xs font-bold uppercase tracking-wide text-blue-900">Legislative Profile &amp; Voting Summary</span>
          <span class="text-[11px] text-blue-700">Grounded in official votes &amp; minutes</span>
        </div>
        <p class="text-sm text-slate-800 leading-relaxed">${esc(bioText)}</p>
      </div>

      <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div class="p-3 rounded-xl bg-slate-50 border border-slate-200/80">
          <div class="text-xs text-slate-500">Recorded Votes</div>
          <div class="text-xl font-bold text-slate-900 mt-0.5">${totalVotes}</div>
        </div>
        <div class="p-3 rounded-xl bg-slate-50 border border-slate-200/80">
          <div class="text-xs text-slate-500">Attendance</div>
          <div class="text-xl font-bold text-slate-900 mt-0.5">${attendance}</div>
        </div>
        <div class="p-3 rounded-xl bg-slate-50 border border-slate-200/80">
          <div class="text-xs text-slate-500">Avg Impact</div>
          <div class="text-xl font-bold text-blue-700 mt-0.5">${avgImpact}</div>
        </div>
        <div class="p-3 rounded-xl bg-slate-50 border border-slate-200/80">
          <div class="text-xs text-slate-500">Pivotal Votes</div>
          <div class="text-xl font-bold text-amber-700 mt-0.5">${pivotal}</div>
        </div>
      </div>

      <div class="space-y-2">
        <h3 class="text-sm font-bold text-slate-900">Comments &amp; Remarks on Measures</h3>
        ${commentsHtml}
      </div>

      <div class="space-y-2">
        <h3 class="text-sm font-bold text-slate-900">Recorded Roll-Call Votes (${repVotes.length})</h3>
        <div class="space-y-2.5">${votesHtml}</div>
      </div>
    </div>
  `;

  modal.classList.remove("hidden");
  document.getElementById("cpV4CloseRepModal")?.addEventListener("click", () => {
    modal.classList.add("hidden");
  });
}

// ---------------------------------------------------------------------------
// 4. Consolidated "How to Engage" Reference Drawer
// ---------------------------------------------------------------------------
function openConsolidatedEngageModal() {
  let modal = document.getElementById("cpV4EngageModal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "cpV4EngageModal";
    modal.className = "fixed inset-0 z-50 bg-slate-900/60 flex items-center justify-center p-4";
    modal.innerHTML = `
      <div class="bg-white rounded-2xl shadow-xl border border-slate-200 max-w-xl w-full p-6 space-y-4">
        <div class="flex items-center justify-between">
          <h2 class="text-lg font-bold text-slate-900">How Local Public Comment Works</h2>
          <button type="button" id="cpV4CloseEngage" class="px-2.5 py-1 rounded-lg border border-slate-200 text-xs font-semibold text-slate-600 hover:bg-slate-100 cursor-pointer">✕ Close</button>
        </div>
        <ol class="list-decimal pl-5 space-y-2 text-sm text-slate-800">
          <li><strong>Check the Agenda 48–72 Hours Early:</strong> Ordinances require two readings; weighing in before the second reading has the highest impact.</li>
          <li><strong>Email Your Representative Directly:</strong> Click any representative bubble to email them with the item title and your neighborhood/ward before noon on meeting day.</li>
          <li><strong>Sign Up for Public Comment (2–3 Minutes):</strong> Use the official agenda link to register for in-person or virtual comment.</li>
          <li><strong>State Your Name, City/District &amp; Specific Ask:</strong> Lead with whether you support, oppose, or request an amendment on the specific item.</li>
        </ol>
      </div>
    `;
    document.body.appendChild(modal);
    document.getElementById("cpV4CloseEngage")?.addEventListener("click", () => modal.classList.add("hidden"));
  }
  modal.classList.remove("hidden");
}

// ---------------------------------------------------------------------------
// 5. Date-First Grouped Upcoming & Recent Agendas (Unclipped)
// ---------------------------------------------------------------------------
function renderDateGroupedAgendas(jurIdsSet) {
  const byDate = new Map();

  function addEntry(dateStr, entry) {
    const key = (dateStr || "undated").slice(0, 10);
    if (!byDate.has(key)) byDate.set(key, []);
    byDate.get(key).push(entry);
  }

  upcomingMeetings.forEach((m) => {
    const jid = m.jurisdiction_id || m.ocd_division_id;
    if (jurIdsSet.size > 0 && !jurIdsSet.has(jid)) return;
    addEntry(m.meeting_date || m.date, {
      kind: "Upcoming Meeting",
      jurId: jid,
      jurName: m.jurisdiction_name || jid,
      title: m.title || "Regular Meeting",
      url: m.source_url || m.portal_url || "",
      items: [],
    });
  });

  agendaPreviews.forEach((p) => {
    const jid = p.jurisdiction_id || p.ocd_division_id;
    if (jurIdsSet.size > 0 && !jurIdsSet.has(jid)) return;
    addEntry(p.meeting_date, {
      kind: "Agenda Preview",
      jurId: jid,
      jurName: p.jurisdiction_name || jid,
      title: p.meeting_title || "Scheduled Agenda",
      url: p.source_url || "",
      items: p.items || [],
    });
  });

  if (byDate.size === 0) {
    return `
      <div class="p-5 rounded-2xl bg-white border border-slate-200 text-sm text-slate-600">
        No upcoming meetings scheduled in the next 14 days for your filtered jurisdiction(s).
        Check <strong>Votes &amp; Radar</strong> for recently completed minutes.
      </div>
    `;
  }

  return Array.from(byDate.keys())
    .sort()
    .map((dt) => {
      const meetings = byDate.get(dt);
      const cards = meetings
        .map((m) => {
          const previewBullets = (m.items || [])
            .slice(0, 4)
            .map(
              (it) => `
              <li class="text-xs text-slate-700 leading-relaxed">
                <span class="font-semibold text-slate-900">${esc(it.title || it)}</span>
                ${it.plain_summary ? ` — <span class="text-slate-600">${esc(it.plain_summary)}</span>` : ""}
              </li>
            `
            )
            .join("");

          return `
            <div class="p-4 rounded-xl bg-slate-50/80 border border-slate-200/90 space-y-2">
              <div class="flex flex-wrap items-start justify-between gap-2">
                <div class="space-y-1 min-w-0 flex-1">
                  <div class="flex flex-wrap items-center gap-2">
                    <span class="px-2 py-0.5 rounded-md text-[11px] font-semibold bg-blue-100 text-blue-900">${esc(m.jurName)}</span>
                    <span class="px-2 py-0.5 rounded-md text-[11px] font-medium bg-slate-200/80 text-slate-700">${esc(m.kind)}</span>
                  </div>
                  <h4 class="text-base font-bold text-slate-900 leading-snug break-words">${esc(m.title)}</h4>
                </div>
                ${
                  m.url
                    ? `<a href="${esc(m.url)}" target="_blank" rel="noopener noreferrer" class="shrink-0 px-3 py-1.5 rounded-lg bg-white border border-slate-300 text-xs font-semibold text-slate-800 hover:bg-slate-100">Official Agenda ↗</a>`
                    : ""
                }
              </div>
              ${previewBullets ? `<ul class="list-disc pl-5 space-y-1 pt-1">${previewBullets}</ul>` : ""}
            </div>
          `;
        })
        .join("");

      return `
        <article class="bg-white rounded-2xl border border-slate-200 shadow-xs p-5 space-y-3">
          <div class="flex flex-wrap items-center justify-between gap-2 pb-2 border-b border-slate-100">
            <h3 class="text-base font-bold text-slate-900">📅 ${esc(formatDateHeading(dt))}</h3>
            <span class="text-xs font-medium text-slate-500">${meetings.length} meeting${meetings.length !== 1 ? "s" : ""} on this date</span>
          </div>
          <div class="space-y-3">${cards}</div>
        </article>
      `;
    })
    .join("");
}

// ---------------------------------------------------------------------------
// 6. Scoped Workspace Mounted BELOW the Map (Hidden Until 1+ Jurs Added via "+")
// ---------------------------------------------------------------------------
function ensureWorkspaceMountedBelowMap() {
  let wsRoot = document.getElementById("cpV4WorkspaceRoot");
  const resolvedPanels = findResolvedLocationPanels();
  const geoPanel = document.getElementById("cpV4GeoResolvedPanel");
  const mapEl = document.getElementById("map");
  const mapCard = mapEl?.closest("div.rounded-2xl, section") || mapEl?.parentElement;
  const anchor = resolvedPanels[0] || geoPanel || mapCard;

  if (!wsRoot) {
    wsRoot = document.createElement("div");
    wsRoot.id = "cpV4WorkspaceRoot";
    wsRoot.className = "mt-6 mb-8";
  }

  if (anchor && anchor.nextElementSibling !== wsRoot) {
    anchor.insertAdjacentElement("afterend", wsRoot);
  } else if (!wsRoot.parentElement) {
    (document.querySelector("main") || document.body).appendChild(wsRoot);
  }
  return wsRoot;
}

async function renderScopedWorkspace() {
  const root = ensureWorkspaceMountedBelowMap();
  if (!root) return;

  const activeJurs = (dirData.jurisdictions || []).filter((j) => j.status === "active");
  const selectedList = activeJurs.filter((j) => selectedJurIds.has(j.ocd_division_id));

  // Stay completely hidden when 0 jurisdictions are in the filter (Map-First!)
  if (selectedList.length === 0) {
    root.innerHTML = "";
    root.classList.add("hidden");
    return;
  }

  root.classList.remove("hidden");

  const filterChips = selectedList
    .map(
      (j) => `
      <span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-slate-900 text-white text-xs font-semibold">
        ${esc(j.name)}
        <button type="button" data-remove-jur="${esc(j.ocd_division_id)}" class="text-slate-300 hover:text-white font-bold cursor-pointer" title="Remove from filter">×</button>
      </span>
    `
    )
    .join("");

  const payloads = await Promise.all(selectedList.map((j) => loadJurisdictionPayload(j.ocd_division_id)));

  const repBubbles = [];
  const allEvents = [];
  payloads.forEach((p, idx) => {
    if (!p) return;
    const jMeta = selectedList[idx];
    (p.entities || p.representatives || p.roster || []).forEach((r) => {
      repBubbles.push(renderRepBubble(r, jMeta.ocd_division_id, jMeta.name));
    });
    (p.agenda_items || p.events || []).forEach((e) => {
      allEvents.push({ ...e, _jurName: jMeta.name, _jurId: jMeta.ocd_division_id });
    });
  });

  allEvents.sort((a, b) => String(b.date || b.meeting_date || "").localeCompare(String(a.date || a.meeting_date || "")));

  let tabBodyHtml = "";
  if (activeWorkspaceTab === "before") {
    tabBodyHtml = `<div class="space-y-4">${renderDateGroupedAgendas(selectedJurIds)}</div>`;
  } else if (activeWorkspaceTab === "votes") {
    const cards = allEvents.slice(0, 40).map((ev) => {
      const dStr = (ev.date || ev.meeting_date || "").slice(0, 10);
      return `
        <article class="bg-white rounded-2xl border border-slate-200 p-4 space-y-2">
          <div class="flex flex-wrap items-center justify-between gap-2 text-xs">
            <div class="flex flex-wrap items-center gap-2">
              <span class="font-bold text-slate-800">${esc(formatDateHeading(dStr))}</span>
              <span class="px-2 py-0.5 rounded bg-slate-100 text-slate-700 font-semibold">${esc(ev._jurName)}</span>
              <span class="px-2 py-0.5 rounded bg-blue-50 text-blue-700 font-medium">${esc(ev.topic || "General")}</span>
            </div>
            <span class="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-800 border border-emerald-200">
              ${esc(ev.outcome || "Recorded")} • Impact ${Math.round(ev.impact_score ?? 0)}/100
            </span>
          </div>
          <h4 class="text-base font-bold text-slate-900 break-words">${esc(ev.title)}</h4>
          ${ev.plain_summary ? `<p class="text-sm text-slate-700">${esc(ev.plain_summary)}</p>` : ""}
          ${ev.source_url ? `<a href="${esc(ev.source_url)}" target="_blank" rel="noopener noreferrer" class="inline-block text-xs font-semibold text-blue-600 hover:underline">Official Minutes / Record ↗</a>` : ""}
        </article>
      `;
    });
    tabBodyHtml = cards.length
      ? `<div class="space-y-3">${cards.join("")}</div>`
      : `<div class="p-5 rounded-2xl bg-white border border-slate-200 text-sm text-slate-600">No extracted roll-call votes yet for your filtered jurisdiction(s).</div>`;
  } else {
    const rows = [];
    payloads.forEach((p, idx) => {
      if (!p) return;
      const jMeta = selectedList[idx];
      (p.entities || p.representatives || p.roster || []).forEach((r) => {
        const pid = r.id || r.ocd_person_id;
        const st = r.metrics || r.stats || {};
        const tv = st.total_votes ?? 0;
        rows.push(`
          <tr class="hover:bg-slate-50">
            <td class="py-3 px-4">
              <button type="button" data-open-rep="${esc(pid)}" data-jur-id="${esc(jMeta.ocd_division_id)}" class="font-semibold text-blue-700 hover:underline text-left cursor-pointer">
                ${esc(r.name)}
              </button>
              <div class="text-xs text-slate-500">${esc(jMeta.name)}</div>
            </td>
            <td class="py-3 px-4 text-xs text-slate-700">${esc(r.district || "At-Large")}</td>
            <td class="py-3 px-4 text-xs font-semibold">${tv > 0 ? `${st.attendance_rate ?? 100}%` : "Pending"}</td>
            <td class="py-3 px-4 text-xs font-semibold">${tv > 0 ? `${Math.round(st.avg_impact_score ?? 0)}/100` : "—"}</td>
            <td class="py-3 px-4 text-xs font-semibold">${st.pivotal_votes ?? 0}</td>
          </tr>
        `);
      });
    });
    tabBodyHtml = `
      <div class="bg-white rounded-2xl border border-slate-200 overflow-x-auto">
        <table class="w-full text-left border-collapse text-sm">
          <thead>
            <tr class="bg-slate-50 border-b border-slate-200 text-xs uppercase text-slate-500">
              <th class="py-3 px-4">Representative (Click for Profile)</th>
              <th class="py-3 px-4">District</th>
              <th class="py-3 px-4">Attendance</th>
              <th class="py-3 px-4">Avg Impact</th>
              <th class="py-3 px-4">Pivotal Votes</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">${rows.join("")}</tbody>
        </table>
      </div>
    `;
  }

  root.innerHTML = `
    <section class="space-y-5">
      <!-- Active Jurisdiction Filter Chips -->
      <div class="bg-white rounded-2xl border border-slate-200 p-4 space-y-3">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div class="text-xs font-bold uppercase tracking-wide text-slate-500">
            Active Filter (${selectedList.length} Jurisdiction${selectedList.length !== 1 ? "s" : ""})
          </div>
          <div class="flex items-center gap-2">
            <button type="button" id="cpV4OpenEngageTop" class="px-3 py-1 rounded-lg border border-slate-300 text-xs font-semibold text-slate-700 hover:bg-slate-50 cursor-pointer">
              📣 How Public Comment Works
            </button>
            <button type="button" id="cpV4ClearJurs" class="px-3 py-1 rounded-lg border border-slate-200 text-xs text-slate-600 hover:bg-slate-100 cursor-pointer">
              Clear All
            </button>
          </div>
        </div>
        <div class="flex flex-wrap gap-2">${filterChips}</div>
      </div>

      <!-- Clickable Representative Bubbles (Contact Info Lives at Rep Level) -->
      <div class="bg-white rounded-2xl border border-slate-200 p-4 sm:p-5 space-y-3">
        <h2 class="text-sm font-bold text-slate-900">
          Representatives (${repBubbles.length}) — Click any representative for vote record, comments &amp; contact info
        </h2>
        <div class="flex flex-wrap gap-2.5">${repBubbles.join("")}</div>
      </div>

      <!-- Scoped Workflow Tabs (Shown Only After Selecting Jurisdictions) -->
      <div class="border-b border-slate-200 flex flex-wrap gap-4 sm:gap-6 text-sm font-semibold">
        <button type="button" data-ws-tab="before" class="pb-3 border-b-2 cursor-pointer ${activeWorkspaceTab === "before" ? "border-blue-600 text-blue-600" : "border-transparent text-slate-500 hover:text-slate-800"}">
          📅 Before the Vote (Date-Grouped Agendas)
        </button>
        <button type="button" data-ws-tab="votes" class="pb-3 border-b-2 cursor-pointer ${activeWorkspaceTab === "votes" ? "border-blue-600 text-blue-600" : "border-transparent text-slate-500 hover:text-slate-800"}">
          🗳️ Votes &amp; Radar (${allEvents.length})
        </button>
        <button type="button" data-ws-tab="alignment" class="pb-3 border-b-2 cursor-pointer ${activeWorkspaceTab === "alignment" ? "border-blue-600 text-blue-600" : "border-transparent text-slate-500 hover:text-slate-800"}">
          📊 Alignment &amp; Metrics
        </button>
      </div>

      ${tabBodyHtml}
    </section>
  `;

  root.querySelectorAll("[data-remove-jur]").forEach((btn) => {
    btn.addEventListener("click", () => toggleJurisdictionInFilter(btn.dataset.removeJur));
  });
  root.querySelectorAll("[data-ws-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      activeWorkspaceTab = btn.dataset.wsTab;
      renderScopedWorkspace();
    });
  });
  root.querySelectorAll("[data-open-rep]").forEach((btn) => {
    btn.addEventListener("click", () => openRepDetailModal(btn.dataset.jurId, btn.dataset.openRep));
  });
  document.getElementById("cpV4OpenEngageTop")?.addEventListener("click", openConsolidatedEngageModal);
  document.getElementById("cpV4ClearJurs")?.addEventListener("click", () => {
    selectedJurIds.clear();
    persistSelectedJurs();
    syncPlusButtonsState();
    renderScopedWorkspace();
  });
}

// ---------------------------------------------------------------------------
// Bootstrap (Map-First, Zero Extra Banners Above the Map)
// ---------------------------------------------------------------------------
async function initCivicPulseV4() {
  // Remove any legacy v4.0 top banners if present from earlier version
  document.getElementById("cpV4LocationBar")?.remove();
  document.querySelectorAll("[data-jur-contact-bubbles], #allRepContactChannels").forEach((el) => el.remove());

  [dirData, upcomingMeetings, agendaPreviews, boundariesGeo] = await Promise.all([
    fetchJsonSafe("data/directory.json", { jurisdictions: [] }),
    fetchJsonSafe("data/upcoming_meetings.json", []),
    fetchJsonSafe("data/agenda_previews.json", []),
    fetchJsonSafe("geo/boundaries.geojson", null),
  ]);

  try {
    const rawJurs = localStorage.getItem(LS_SELECTED_JURS_KEY);
    if (rawJurs) selectedJurIds = new Set(JSON.parse(rawJurs));
  } catch {
    // ignore storage errors
  }

  mountUseMyLocationButton();
  injectPlusButtonsIntoResolvedPanel();
  await renderScopedWorkspace();

  // Watch for dynamic updates to "RESOLVED LOCATION & OVERLAPPING GOVERNMENTS" when user clicks the map
  const observer = new MutationObserver(() => {
    mountUseMyLocationButton();
    injectPlusButtonsIntoResolvedPanel();
  });
  observer.observe(document.body, { childList: true, subtree: true });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initCivicPulseV4);
} else {
  initCivicPulseV4();
}
