/**
 * CivicPulse Consolidated Frontend Application (public/js/civicpulse_app.js)
 *
 * Single source of truth for state, map spatial resolution, multi-jurisdiction
 * filtering, representative profiles with voting-record summaries, date-first
 * agendas, votes & topic radar, and council alignment analytics.
 */

const GITHUB_REPO = "BryanTeisl/civics";
const LS_SELECTED_JURS = "cp_v5_selected_jurisdictions";
const LS_ACTIVE_TAB = "cp_v5_active_tab";
const UNCLAIMED_PAGE_SIZE = 12;

const AppState = {
  jurisdictions: [],
  lastUpdated: "",
  boundariesGeo: null,
  upcomingMeetings: [],
  agendaPreviews: [],
  earlyWarnings: [],
  alignmentMatrix: null,
  billLifecycles: {},
  scoringMethodology: null,
  feedsIndex: null,
  patrons: null,
  officialContacts: {},
  siteConfig: null,
  searchRecords: null,

  // Cached per-jurisdiction JSON payloads keyed by ocd_division_id
  jurPayloads: new Map(),

  // Single unified filter controlling the entire workspace
  selectedJurIds: new Set(),
  activeTab: "reps", // 'reps' | 'before' | 'votes' | 'alignment'

  // Resolved user location & matched council/federal districts
  resolvedLocation: null, // { label, lat, lng, matches: [...], districtHints: Map<jurId, string>, federalDistricts: [...] }

  // Workspace sub-filters
  votesSearch: "",
  votesTopic: "all",
  votesCommercialOnly: false,
  votesSort: "date_desc",

  // Directory filters
  activeLevelFilter: "all",
  unclaimedSearch: "",
  unclaimedTier: "all",
  unclaimedCap: UNCLAIMED_PAGE_SIZE,

  map: null,
  locationMarker: null,
};

const COMMERCIAL_TOPICS = new Set([
  "Zoning & Land Use",
  "Housing & Development",
  "Taxes, Fees & Utilities",
  "Budget & Finance",
  "Contracts & Procurement",
  "Permits & Licensing",
  "Infrastructure & Transit",
]);

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------
function esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function normalizeLevel(raw) {
  const s = String(raw || "city").toLowerCase().trim();
  if (s === "municipality" || s === "municipal" || s === "town" || s === "place") return "city";
  if (s === "school" || s === "school_board" || s === "school_district") return "school_district";
  if (s === "county") return "county";
  return s || "city";
}

function formatLevelLabel(raw) {
  const lv = normalizeLevel(raw);
  if (lv === "school_district") return "School Board";
  if (lv === "county") return "County";
  return "City / Town";
}

function jurIdOf(j) {
  return j?.ocd_division_id || j?.id || "";
}

function jurSlugFromId(ocdId) {
  return String(ocdId || "")
    .replace(/^ocd-division\//, "")
    .replace(/[^a-z0-9]+/gi, "_")
    .toLowerCase();
}

function jurDataFile(jurMeta) {
  const raw = jurMeta?.file || jurMeta?.data_file || jurMeta?.filename || "";
  if (raw) {
    const clean = raw.replace(/^\.?\//, "").replace(/^public\//, "");
    return clean.startsWith("data/") ? clean : `data/${clean}`;
  }
  return `data/${jurSlugFromId(jurIdOf(jurMeta))}.json`;
}

function normalizeHumanPortalUrl(url) {
  const u = String(url || "").trim();
  if (!u || u === "#") return "";
  const cc = u.match(/^https?:\/\/([a-z0-9-]+)\.api\.civicclerk\.com/i);
  if (cc) return `https://${cc[1]}.portal.civicclerk.com/`;
  return u;
}

function cleanMeetingTitle(rawTitle, docType = "") {
  const t = String(rawTitle || "").trim();
  if (!t || /^upcoming:\s*https?:\/\//i.test(t) || /^https?:\/\//i.test(t)) {
    const low = t.toLowerCase();
    if (low.includes("minute")) return "Official Meeting Minutes";
    if (low.includes("packet")) return "Meeting Agenda Packet";
    return String(docType).toLowerCase() === "minutes"
      ? "Council / Board Minutes"
      : "Scheduled Council / Board Meeting";
  }
  return t.replace(/^upcoming:\s*/i, "").trim();
}

function initialsFor(name) {
  const parts = String(name || "?").trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function formatDateHeading(isoDate) {
  if (!isoDate || isoDate === "undated") return "Date To Be Announced";
  const parts = String(isoDate).slice(0, 10).split("-");
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

function buildGithubRequestUrl({ name, ocdId = "", level = "city", portalUrl = "" }) {
  const title = `[Request] ${name}`;
  const body = [
    "### Jurisdiction Tracking Request",
    `- **Jurisdiction:** ${name}`,
    ocdId ? `- **OCD Division ID:** ${ocdId}` : "",
    `- **Level:** ${level}`,
    portalUrl ? `- **Portal URL:** ${portalUrl}` : "- **Portal URL:** (auto-discover)",
    "",
    "_Submitted via CivicPulse — automatically scouted on the next daily pipeline run._",
  ]
    .filter(Boolean)
    .join("\n");
  const params = new URLSearchParams({ labels: "jurisdiction-request", title, body });
  return `https://github.com/${GITHUB_REPO}/issues/new?${params.toString()}`;
}

function buildGithubErrorReportUrl({ eventId, jurName, title, sourceUrl }) {
  const params = new URLSearchParams({
    title: `[Data Correction] ${jurName}: ${String(title || "").slice(0, 60)}`,
    body: [
      "### CivicPulse Record Correction",
      `- **Jurisdiction:** ${jurName}`,
      `- **Event ID:** ${eventId}`,
      `- **Title:** ${title}`,
      sourceUrl ? `- **Official Source:** ${sourceUrl}` : "",
      "",
      "**What needs correction?**",
      "(Please describe the vote, summary, or date issue.)",
    ]
      .filter(Boolean)
      .join("\n"),
  });
  return `https://github.com/${GITHUB_REPO}/issues/new?${params.toString()}`;
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

function persistState() {
  try {
    localStorage.setItem(LS_SELECTED_JURS, JSON.stringify(Array.from(AppState.selectedJurIds)));
    localStorage.setItem(LS_ACTIVE_TAB, AppState.activeTab);
  } catch {
    // ignore storage errors
  }
}

function getJurisdictionById(jid) {
  return AppState.jurisdictions.find((j) => jurIdOf(j) === jid) || null;
}

async function loadJurPayload(jid) {
  if (AppState.jurPayloads.has(jid)) return AppState.jurPayloads.get(jid);
  const meta = getJurisdictionById(jid);
  if (!meta) return null;
  const data = await fetchJsonSafe(jurDataFile(meta), null);
  if (data) AppState.jurPayloads.set(jid, data);
  return data;
}

function getEntitiesFromPayload(payload) {
  if (!payload) return [];
  return (
    payload.entities ||
    payload.representatives ||
    payload.roster ||
    payload.officials ||
    payload.legislators ||
    []
  );
}

function getEventsFromPayload(payload) {
  if (!payload) return [];
  return payload.events || payload.agenda_items || [];
}

function normalizeEventVotes(ev) {
  const raw = ev?.votes;
  if (!raw) return [];
  if (Array.isArray(raw)) {
    return raw.map((v) => ({
      entity_id: v.entity_id || v.ocd_person_id || v.id || "",
      name: v.name || "",
      district: v.district || "",
      vote: v.vote || v.value || "Recorded",
      is_pivotal: Boolean(v.is_pivotal),
      quote: v.verbatim_quote || v.quote || "",
      summary: v.rationale_summary || v.summary || "",
    }));
  }
  if (typeof raw === "object") {
    return Object.entries(raw).map(([pid, v]) => ({
      entity_id: pid,
      name: v?.name || "",
      district: v?.district || "",
      vote: v?.vote || v?.value || (typeof v === "string" ? v : "Recorded"),
      is_pivotal: Boolean(v?.is_pivotal),
      quote: v?.verbatim_quote || v?.quote || "",
      summary: v?.rationale_summary || v?.summary || "",
    }));
  }
  return [];
}

function synthesizeClientFallbackBio(rep, jurName, repVotes) {
  if (rep.bio_summary && rep.bio_summary.trim().length >= 25) {
    return rep.bio_summary.trim();
  }
  const seat = `${rep.role || "Representative"}${rep.district ? ` (${rep.district})` : ""}`;
  if (!repVotes.length) {
    return `${rep.name} serves as ${seat} for ${jurName}. Roll-call vote breakdowns and floor comments for this term are currently pending ingestion.`;
  }
  const yesCnt = repVotes.filter((v) => /^(yes|aye|yea)$/i.test(v.vote)).length;
  const noCnt = repVotes.filter((v) => /^(no|nay)$/i.test(v.vote)).length;
  const pivCnt = repVotes.filter((v) => v.is_pivotal).length;
  const topicCounts = new Map();
  repVotes.forEach((v) => {
    const t = String(v.topic || "").trim();
    if (t && !/^(general|procedural|consent)$/i.test(t)) {
      topicCounts.set(t, (topicCounts.get(t) || 0) + 1);
    }
  });
  const topTopics = Array.from(topicCounts.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([t]) => t);

  let bio = `${rep.name} serves as ${seat} for ${jurName}, with ${repVotes.length} recorded roll-call vote${
    repVotes.length === 1 ? "" : "s"
  } (${yesCnt} Yes, ${noCnt} No${pivCnt ? `, including ${pivCnt} pivotal deciding vote${pivCnt === 1 ? "" : "s"}` : ""}).`;
  if (topTopics.length) {
    bio += ` Recorded legislative activity has centered most frequently on ${topTopics.join(", ")}.`;
  }
  const q = repVotes.find((v) => v.quote && v.quote.trim().length >= 20)?.quote;
  if (q) {
    bio += ` In official minutes, they noted: "${q.trim().slice(0, 140)}."`;
  }
  return bio;
}

// ---------------------------------------------------------------------------
// Modal Helpers
// ---------------------------------------------------------------------------
function openModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove("hidden");
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add("hidden");
}

// ---------------------------------------------------------------------------
// Stage 1: Map & Strict Polygon Spatial Resolution (No Loose Spillover!)
// ---------------------------------------------------------------------------
function initMap() {
  if (AppState.map || !window.L) return;
  const map = window.L.map("map", { scrollWheelZoom: false }).setView([39.85, -105.1], 8);
  window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);

  map.on("click", (e) => {
    resolvePoint(e.latlng.lat, e.latlng.lng, "Map Location");
  });

  AppState.map = map;
}

function resolvePoint(lat, lng, label) {
  if (AppState.map && window.L) {
    if (AppState.locationMarker) {
      AppState.locationMarker.setLatLng([lat, lng]);
    } else {
      AppState.locationMarker = window.L.circleMarker([lat, lng], {
        radius: 8,
        color: "#1b3b4e",
        weight: 2.5,
        fillColor: "#c67749",
        fillOpacity: 0.9,
      }).addTo(AppState.map);
    }
  }

  const matchedIds = new Set();
  const districtHints = new Map();
  const federalDistricts = [];

  if (window.turf && AppState.boundariesGeo && Array.isArray(AppState.boundariesGeo.features)) {
    const pt = window.turf.point([lng, lat]);
    for (const feat of AppState.boundariesGeo.features) {
      try {
        if (!window.turf.booleanPointInPolygon(pt, feat)) continue;
        const p = feat.properties || {};
        const divId = p.ocd_division_id || p.OCD_ID || feat.id || "";
        const fType = String(p.layer || p.level || p.type || "").toLowerCase();

        // Capture council district / ward hints so we can highlight "Your Rep"
        const divStr = String(divId || "");
        const isSubDistrict =
          fType === "district" ||
          fType.includes("council_district") ||
          fType.includes("ward") ||
          /\/(council_district|ward):/i.test(divStr) ||
          Boolean(p.district_number || p.council_district);

        if (isSubDistrict) {
          const derivedParent = divStr.replace(/\/(council_district|ward):[^/]+$/i, "");
          const parentId = p.parent_division_id || p.parent_id || p.jurisdiction_id || derivedParent;
          let distLabel = p.district || p.district_name || p.name || "";
          const numMatch = distLabel.match(/(?:district|ward)\s*([0-9a-z-]+)/i) || divStr.match(/(?:council_district|ward):([^/]+)/i);
          if (numMatch) {
            const prefix = /ward/i.test(distLabel + divStr) ? "Ward" : "District";
            distLabel = `${prefix} ${numMatch[1].toUpperCase()}`;
          }
          if (parentId && distLabel) districtHints.set(parentId, distLabel);
          if (parentId) matchedIds.add(parentId);
          continue;
        }

        // Capture federal congressional district info
        if (fType.includes("congress") || String(divId).includes("/cd:")) {
          federalDistricts.push({
            name: p.name || divId,
            cd: p.cd || p.district_number || "",
          });
          continue;
        }

        if (divId) matchedIds.add(divId);
      } catch {
        // skip invalid polygon
      }
    }
  }

  // Also include parent_division_id links (e.g., city -> county) if polygon had city cut-out
  const snapshot = Array.from(matchedIds);
  snapshot.forEach((id) => {
    const j = getJurisdictionById(id);
    if (j && j.parent_division_id) matchedIds.add(j.parent_division_id);
  });

  // Strict fallback ONLY if zero polygons matched at all (avoids Windsor showing up inside Fort Collins!)
  if (matchedIds.size === 0 && window.turf) {
    const pt = window.turf.point([lng, lat]);
    let nearest = null;
    let bestKm = 12;
    for (const j of AppState.jurisdictions) {
      const jLat = Number(j.lat ?? j.latitude ?? 0);
      const jLng = Number(j.lng ?? j.longitude ?? 0);
      if (!jLat || !jLng) continue;
      const d = window.turf.distance(pt, window.turf.point([jLng, jLat]), { units: "kilometers" });
      if (d < bestKm) {
        bestKm = d;
        nearest = j;
      }
    }
    if (nearest) matchedIds.add(jurIdOf(nearest));
  }

  const matches = AppState.jurisdictions
    .filter((j) => matchedIds.has(jurIdOf(j)))
    .sort((a, b) => {
      const aAct = a.status === "active" ? 0 : 1;
      const bAct = b.status === "active" ? 0 : 1;
      if (aAct !== bAct) return aAct - bAct;
      const order = { city: 0, school_district: 1, county: 2 };
      const oa = order[normalizeLevel(a.level)] ?? 3;
      const ob = order[normalizeLevel(b.level)] ?? 3;
      if (oa !== ob) return oa - ob;
      return String(a.name || "").localeCompare(String(b.name || ""));
    });

  AppState.resolvedLocation = {
    label,
    lat,
    lng,
    matches,
    districtHints,
    federalDistricts,
  };

  renderResolvedPanel();
  if (AppState.selectedJurIds.size > 0 && AppState.activeTab === "reps") {
    renderWorkspace();
  }
}

function renderResolvedPanel() {
  const panel = document.getElementById("resolvedPanel");
  const loc = AppState.resolvedLocation;
  if (!panel || !loc) {
    if (panel) panel.classList.add("hidden");
    return;
  }

  const activeMatches = loc.matches.filter((j) => j.status === "active");
  const anyUnselectedActive = activeMatches.some((j) => !AppState.selectedJurIds.has(jurIdOf(j)));

  const cardsHtml = loc.matches.length
    ? loc.matches
        .map((j) => {
          const jid = jurIdOf(j);
          const isAct = j.status === "active";
          const isSel = AppState.selectedJurIds.has(jid);
          const distHint = loc.districtHints.get(jid);

          if (isAct) {
            return `
              <div class="rounded-xl border ${
                isSel ? "border-emerald-500 bg-emerald-50/40" : "border-[#1b3b4e]/15 bg-white"
              } p-3.5 flex items-start justify-between gap-2.5 shadow-xs transition">
                <button type="button" data-select-and-open="${esc(jid)}" class="text-left min-w-0 flex-1 cursor-pointer group">
                  <div class="text-[10px] font-bold uppercase tracking-wider text-emerald-800">
                    ${esc(formatLevelLabel(j.level))} • ACTIVE${distHint ? ` • ${esc(distHint)}` : ""}
                  </div>
                  <div class="text-sm font-bold text-[#142834] group-hover:text-[#366a8a] mt-0.5 break-words">
                    ${esc(j.name)}
                  </div>
                  <div class="text-[11px] font-semibold text-[#366a8a] mt-1">
                    ${isSel ? "In your filter — View below ↓" : "Click + to add or click to explore →"}
                  </div>
                </button>
                <button
                  type="button"
                  data-toggle-jur="${esc(jid)}"
                  title="${isSel ? "Remove from filter" : "Add to filter"}"
                  class="w-8 h-8 rounded-full inline-flex items-center justify-center text-base font-bold border transition shrink-0 cursor-pointer ${
                    isSel
                      ? "bg-emerald-600 text-white border-emerald-600 hover:bg-emerald-700"
                      : "bg-white text-[#1b3b4e] border-[#1b3b4e]/30 hover:bg-[#1b3b4e] hover:text-white"
                  }"
                >${isSel ? "✓" : "+"}</button>
              </div>
            `;
          }

          const reqUrl = buildGithubRequestUrl({
            name: j.name,
            ocdId: jid,
            level: normalizeLevel(j.level),
            portalUrl: j.portal_url || "",
          });
          return `
            <div class="rounded-xl border border-[#1b3b4e]/12 bg-white/75 p-3.5 flex flex-col justify-between gap-2">
              <div>
                <div class="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                  ${esc(formatLevelLabel(j.level))} • UNCLAIMED
                </div>
                <div class="text-sm font-bold text-[#142834] mt-0.5 break-words">${esc(j.name)}</div>
              </div>
              <a href="${esc(reqUrl)}" target="_blank" rel="noopener noreferrer" class="text-[11px] font-semibold text-[#c67749] hover:underline">
                Request Automated Tracking ↗
              </a>
            </div>
          `;
        })
        .join("")
    : `<div class="col-span-full text-xs text-slate-600">No tracked Colorado boundaries matched this exact point. Select an active jurisdiction below or request coverage.</div>`;

  const myRepBadges = [];
  loc.districtHints.forEach((distLabel, parentJid) => {
    const cachedP = AppState.jurPayloads.get(parentJid);
    const parentName = getJurisdictionById(parentJid)?.name || "";
    if (cachedP) {
      getEntitiesFromPayload(cachedP).forEach((rep) => {
        const rDist = String(rep.district || "").toLowerCase();
        if (rDist === distLabel.toLowerCase() || rDist.includes("at-large")) {
          myRepBadges.push(
            `<button type="button" data-resolved-rep="${esc(rep.ocd_person_id || rep.id)}" data-jur-id="${esc(parentJid)}" class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-white border border-[#c67749]/40 hover:border-[#c67749] text-xs font-semibold text-[#142834] cursor-pointer">
              <span class="text-[#c67749]">&#9733;</span><span>${esc(rep.name)}</span><span class="text-slate-500 font-normal">(${esc(rep.district || rep.role)})</span>
            </button>`
          );
        }
      });
    } else if (parentName) {
      loadJurPayload(parentJid).then(() => renderResolvedPanel());
    }
  });
  // Highlight At-Large / countywide reps for matched active jurisdictions without sub-district polygons (cpV51AtLargeReps)
  activeMatches.forEach((j) => {
    const jid = jurIdOf(j);
    if (loc.districtHints.has(jid)) return;
    if (!j?.parity?.is_at_large && normalizeLevel(j.level) === "city") return;
    const cachedP = AppState.jurPayloads.get(jid);
    if (cachedP) {
      getEntitiesFromPayload(cachedP).slice(0, 4).forEach((rep) => {
        myRepBadges.push(
          `<button type="button" data-resolved-rep="${esc(rep.ocd_person_id || rep.id)}" data-jur-id="${esc(jid)}" class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-white border border-[#c67749]/40 hover:border-[#c67749] text-xs font-semibold text-[#142834] cursor-pointer">
            <span class="text-[#c67749]">&#9733;</span><span>${esc(rep.name)}</span><span class="text-slate-500 font-normal">(${esc(j.name.split(" ")[0])} At-Large)</span>
          </button>`
        );
      });
    } else {
      loadJurPayload(jid).then(() => renderResolvedPanel());
    }
  });
  const myRepsStrip = myRepBadges.length
    ? `<div class="pt-2 border-t border-[#1b3b4e]/10 flex flex-wrap items-center gap-2">
         <span class="text-[11px] font-bold uppercase tracking-wider text-[#9c5128]">Your Local Reps:</span>
         ${myRepBadges.join("")}
       </div>`
    : "";

  const fedHtml = loc.federalDistricts.length
    ? `<div class="text-xs text-[#142834]/75 pt-1">
         Federal overlay: <strong>${esc(loc.federalDistricts.map((f) => f.name).join(", "))}</strong>
         — <a href="https://www.congress.gov/members?q=%7B%22member-state%22%3A%22Colorado%22%7D" target="_blank" rel="noopener noreferrer" class="text-[#366a8a] font-semibold hover:underline">View on Congress.gov ↗</a>
       </div>`
    : "";

  panel.innerHTML = `
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <div class="text-[11px] font-bold uppercase tracking-wider text-[#366a8a]">
          Resolved Location &amp; Overlapping Governments
        </div>
        <h2 class="text-base font-bold text-[#142834] mt-0.5">
          ${esc(loc.label)} <span class="font-normal text-xs text-slate-500">(${loc.lat.toFixed(4)}, ${loc.lng.toFixed(4)})</span>
        </h2>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        ${
          activeMatches.length > 0 && anyUnselectedActive
            ? `<button type="button" id="addAllResolvedBtn" class="px-3 py-1.5 rounded-lg bg-[#1b3b4e] text-[#faf5eb] text-xs font-semibold hover:bg-[#366a8a] cursor-pointer">+ Add All Active (${activeMatches.length})</button>`
            : ""
        }
        ${
          AppState.selectedJurIds.size > 0
            ? `<button type="button" id="jumpToWorkspaceBtn" class="px-3 py-1.5 rounded-lg bg-[#c67749] text-[#faf5eb] text-xs font-semibold hover:bg-[#b56638] cursor-pointer">Explore Selected (${AppState.selectedJurIds.size}) ↓</button>`
            : ""
        }
        <button type="button" id="dismissResolvedBtn" class="text-xs text-slate-500 hover:text-slate-800 px-1.5 py-1 cursor-pointer">Dismiss ✕</button>
      </div>
    </div>
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">${cardsHtml}</div>
    ${myRepsStrip}
    ${fedHtml}
  `;

  panel.classList.remove("hidden");

  panel.querySelector("#dismissResolvedBtn")?.addEventListener("click", () => {
    AppState.resolvedLocation = null;
    panel.classList.add("hidden");
  });

  panel.querySelector("#addAllResolvedBtn")?.addEventListener("click", () => {
    activeMatches.forEach((j) => AppState.selectedJurIds.add(jurIdOf(j)));
    persistState();
    onSelectionChanged(true);
  });

  panel.querySelector("#jumpToWorkspaceBtn")?.addEventListener("click", () => {
    document.getElementById("workspaceSection")?.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  panel.querySelectorAll("[data-resolved-rep]").forEach((btn) => {
    btn.addEventListener("click", () => openRepModal(btn.dataset.jurId, btn.dataset.resolvedRep));
  });
  panel.querySelectorAll("[data-toggle-jur]").forEach((btn) => {
    btn.addEventListener("click", () => toggleJurisdiction(btn.dataset.toggleJur, false));
  });

  panel.querySelectorAll("[data-select-and-open]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const jid = btn.dataset.selectAndOpen;
      if (!AppState.selectedJurIds.has(jid)) {
        AppState.selectedJurIds.add(jid);
        persistState();
      }
      onSelectionChanged(true);
    });
  });
}

async function handleAddressSubmit(e) {
  e.preventDefault();
  const q = (document.getElementById("addressInput")?.value || "").trim();
  if (!q) return;
  const btn = document.getElementById("addressLookupBtn");
  const orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Locating...";

  try {
    const queryAddr = /\bco\b|colorado/i.test(q) ? q : `${q}, CO`;
    const url = `https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?address=${encodeURIComponent(
      queryAddr
    )}&benchmark=Public_AR_Current&format=json`;
    const res = await fetch(url);
    const json = await res.json();
    const match = json?.result?.addressMatches?.[0];
    if (match?.coordinates) {
      const lat = Number(match.coordinates.y);
      const lng = Number(match.coordinates.x);
      AppState.map?.setView([lat, lng], 12);
      resolvePoint(lat, lng, match.matchedAddress || q);
      return;
    }

    // Fallback: match city/county name directly from directory
    const hit = AppState.jurisdictions.find((j) =>
      String(j.name || "").toLowerCase().includes(q.toLowerCase())
    );
    if (hit && (hit.lat || hit.latitude)) {
      const lat = Number(hit.lat ?? hit.latitude);
      const lng = Number(hit.lng ?? hit.longitude);
      AppState.map?.setView([lat, lng], 11);
      resolvePoint(lat, lng, hit.name);
      return;
    }

    alert("Address not found. Try a full Colorado street address or click directly on the map.");
  } catch {
    alert("Could not reach the U.S. Census Geocoder right now. Please click anywhere on the map instead.");
  } finally {
    btn.disabled = false;
    btn.textContent = orig;
  }
}

function handleUseMyLocation() {
  if (!navigator.geolocation) {
    alert("Geolocation is not supported by your browser. Click anywhere on the map instead.");
    return;
  }
  const btn = document.getElementById("useMyLocationBtn");
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.textContent = "Locating...";

  navigator.geolocation.getCurrentPosition(
    (pos) => {
      btn.disabled = false;
      btn.innerHTML = orig;
      const lat = pos.coords.latitude;
      const lng = pos.coords.longitude;
      AppState.map?.setView([lat, lng], 12);
      resolvePoint(lat, lng, "My Current Location");
    },
    (err) => {
      btn.disabled = false;
      btn.innerHTML = orig;
      alert(
        err.code === 1
          ? "Location permission was denied. You can click anywhere on the map or enter an address instead."
          : "Unable to detect your location. Please click directly on the map instead."
      );
    },
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
  );
}

// ---------------------------------------------------------------------------
// Selection State Controller
// ---------------------------------------------------------------------------
function toggleJurisdiction(jid, scrollToWorkspace = false) {
  if (!jid) return;
  if (AppState.selectedJurIds.has(jid)) {
    AppState.selectedJurIds.delete(jid);
  } else {
    AppState.selectedJurIds.add(jid);
  }
  persistState();
  onSelectionChanged(scrollToWorkspace);
}

async function onSelectionChanged(scrollToWorkspace = false) {
  renderResolvedPanel();
  renderActiveDirectory();
  await renderWorkspace();
  if (scrollToWorkspace && AppState.selectedJurIds.size > 0) {
    document.getElementById("workspaceSection")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

// ---------------------------------------------------------------------------
// Stage 2: Unified Scoped Workspace (Controlled by ONE Filter Set)
// ---------------------------------------------------------------------------
function getScopedUpcomingItems() {
  const jSet = AppState.selectedJurIds;
  const byDate = new Map();

  function add(dateStr, entry) {
    const key = (dateStr || "undated").slice(0, 10);
    if (!byDate.has(key)) byDate.set(key, []);
    const arr = byDate.get(key);
    const dup = arr.some(
      (x) =>
        x.jurId === entry.jurId &&
        x.title.toLowerCase() === entry.title.toLowerCase() &&
        x.kind === entry.kind
    );
    if (!dup) arr.push(entry);
  }

  AppState.upcomingMeetings.forEach((m) => {
    const jid = m.jurisdiction_id || m.ocd_division_id;
    if (!jSet.has(jid)) return;
    add(m.meeting_date || m.date, {
      date: (m.meeting_date || m.date || "").slice(0, 10),
      jurId: jid,
      jurName: m.jurisdiction_name || getJurisdictionById(jid)?.name || jid,
      title: cleanMeetingTitle(m.title, m.doc_type),
      kind: "Scheduled Meeting",
      url: normalizeHumanPortalUrl(m.source_url || m.portal_url || getJurisdictionById(jid)?.portal_url || ""),
      items: [],
    });
  });

  AppState.agendaPreviews.forEach((p) => {
    const jid = p.jurisdiction_id || p.ocd_division_id;
    if (!jSet.has(jid)) return;
    add(p.meeting_date, {
      date: (p.meeting_date || "").slice(0, 10),
      jurId: jid,
      jurName: p.jurisdiction_name || getJurisdictionById(jid)?.name || jid,
      title: cleanMeetingTitle(p.meeting_title || p.title, "agenda"),
      kind: "Agenda Preview",
      url: normalizeHumanPortalUrl(p.source_url || getJurisdictionById(jid)?.portal_url || ""),
      items: p.items || [],
    });
  });

  AppState.earlyWarnings.forEach((w) => {
    const jid = w.jurisdiction_id || w.ocd_division_id;
    if (!jSet.has(jid)) return;
    add(w.meeting_date || w.date, {
      date: (w.meeting_date || w.date || "").slice(0, 10),
      jurId: jid,
      jurName: w.jurisdiction_name || getJurisdictionById(jid)?.name || jid,
      title: cleanMeetingTitle(w.title, "agenda"),
      kind: "Planning & Zoning Signal",
      url: normalizeHumanPortalUrl(w.source_url || getJurisdictionById(jid)?.portal_url || ""),
      items: [],
    });
  });

  return byDate;
}

async function renderWorkspace() {
  const ws = document.getElementById("workspaceSection");
  if (!ws) return;

  const selectedJurs = Array.from(AppState.selectedJurIds)
    .map((id) => getJurisdictionById(id))
    .filter((j) => j && j.status === "active");

  if (!selectedJurs.length) {
    ws.classList.add("hidden");
    return;
  }

  ws.classList.remove("hidden");

  // Active Filter Chips
  const chipsEl = document.getElementById("activeFilterChips");
  chipsEl.innerHTML = selectedJurs
    .map((j) => {
      const jid = jurIdOf(j);
      const portal = normalizeHumanPortalUrl(j.portal_url);
      return `
        <span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-[#1b3b4e] text-[#faf5eb] text-xs font-semibold shadow-xs">
          <span>${esc(j.name)}</span>
          ${
            portal
              ? `<a href="${esc(portal)}" target="_blank" rel="noopener noreferrer" class="text-[#faf5eb]/75 hover:text-white text-[11px]" title="Official Portal">↗</a>`
              : ""
          }
          <button type="button" data-remove-chip="${esc(jid)}" class="ml-0.5 text-[#faf5eb]/75 hover:text-white font-bold cursor-pointer" title="Remove from filter">×</button>
        </span>
      `;
    })
    .join("");

  chipsEl.querySelectorAll("[data-remove-chip]").forEach((btn) => {
    btn.addEventListener("click", () => toggleJurisdiction(btn.dataset.removeChip, false));
  });

  // Load JSON payloads for all selected jurisdictions in parallel
  const payloads = await Promise.all(selectedJurs.map((j) => loadJurPayload(jurIdOf(j))));

  // Collect all scoped reps and events
  const scopedReps = [];
  const scopedEvents = [];
  payloads.forEach((payload, i) => {
    if (!payload) return;
    const jMeta = selectedJurs[i];
    const jid = jurIdOf(jMeta);
    const distHint = AppState.resolvedLocation?.districtHints?.get(jid) || "";

    getEntitiesFromPayload(payload).forEach((rep) => {
      const repDist = String(rep.district || "").toLowerCase();
      const isMyRep =
        Boolean(distHint) &&
        (repDist.includes(distHint.toLowerCase()) ||
          distHint.toLowerCase().includes(repDist) ||
          repDist.includes("at-large") ||
          String(rep.role || "").toLowerCase().includes("mayor"));
      scopedReps.push({ rep, jurId: jid, jurName: jMeta.name, isMyRep });
    });

    getEventsFromPayload(payload).forEach((ev) => {
      scopedEvents.push({
        ...ev,
        _jurId: jid,
        _jurName: jMeta.name,
        _date: String(ev.meeting_date || ev.date || "").slice(0, 10),
        _topic: ev.topic || ev.event_type || "General",
        _impact: Math.round(Number(ev.impact_score ?? 0)),
        _votes: normalizeEventVotes(ev),
      });
    });
  });

  // Sort "Your Rep" first, then by jurisdiction + name
  scopedReps.sort((a, b) => {
    if (a.isMyRep !== b.isMyRep) return a.isMyRep ? -1 : 1;
    if (a.jurName !== b.jurName) return a.jurName.localeCompare(b.jurName);
    return String(a.rep.name || "").localeCompare(String(b.rep.name || ""));
  });

  const upcomingByDate = getScopedUpcomingItems();
  let upcomingTotal = 0;
  upcomingByDate.forEach((arr) => {
    upcomingTotal += arr.length;
  });

  // Update tab badges & active styles
  document.getElementById("tabCountReps").textContent = String(scopedReps.length);
  document.getElementById("tabCountBefore").textContent = String(upcomingTotal);
  document.getElementById("tabCountVotes").textContent = String(scopedEvents.length);

  document.querySelectorAll(".ws-tab").forEach((btn) => {
    const isAct = btn.dataset.wsTab === AppState.activeTab;
    btn.className = isAct
      ? "ws-tab pb-3 px-1 border-b-2 border-[#c67749] text-[#1b3b4e] transition cursor-pointer"
      : "ws-tab pb-3 px-1 border-b-2 border-transparent text-[#142834]/60 hover:text-[#1b3b4e] transition cursor-pointer";
  });

  const body = document.getElementById("workspaceTabContent");
  if (AppState.activeTab === "reps") {
    renderTabReps(body, scopedReps);
  } else if (AppState.activeTab === "before") {
    renderTabBeforeTheVote(body, upcomingByDate);
  } else if (AppState.activeTab === "votes") {
    renderTabVotesRadar(body, scopedEvents);
  } else {
    renderTabAlignment(body, selectedJurs, scopedReps);
  }
}

// ---------------------------------------------------------------------------
// Tab 1: Clickable Representative Bubbles (Contact Info Lives at Rep Level)
// ---------------------------------------------------------------------------
function renderTabReps(container, scopedReps) {
  if (!scopedReps.length) {
    container.innerHTML = `
      <div class="cp-card p-6 text-sm text-slate-600">
        Representative rosters are currently pending ingestion for the selected jurisdiction(s).
      </div>
    `;
    return;
  }

  const cards = scopedReps
    .map(({ rep, jurId, jurName, isMyRep }) => {
      const pid = rep.ocd_person_id || rep.id;
      const stats = rep.metrics || rep.stats || {};
      const tv = Number(stats.total_votes ?? 0);
      const avatar = rep.photo_url
        ? `<img src="${esc(rep.photo_url)}" alt="${esc(rep.name)}" class="w-11 h-11 rounded-full object-cover border border-slate-200 shrink-0" />`
        : `<span class="w-11 h-11 rounded-full bg-[#1b3b4e] text-[#faf5eb] text-xs font-bold inline-flex items-center justify-center shrink-0">${esc(initialsFor(rep.name))}</span>`;

      return `
        <button
          type="button"
          data-open-rep="${esc(pid)}"
          data-jur-id="${esc(jurId)}"
          class="text-left cp-card p-4 hover:border-[#c67749] hover:shadow-md transition flex flex-col justify-between gap-3 cursor-pointer ${
            isMyRep ? "ring-2 ring-[#c67749]/40 bg-[#fffdf9]" : ""
          }"
        >
          <div class="flex items-start gap-3">
            ${avatar}
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-1.5">
                <span class="text-sm font-bold text-[#142834] break-words">${esc(rep.name)}</span>
                ${
                  isMyRep
                    ? `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-[#c67749]/15 text-[#9c5128]">★ Your Rep</span>`
                    : ""
                }
              </div>
              <div class="text-xs text-[#366a8a] font-medium mt-0.5">
                ${esc(rep.role || "Member")}${rep.district ? ` • ${esc(rep.district)}` : ""}
              </div>
              <div class="text-[11px] text-slate-500 mt-0.5">${esc(jurName)}</div>
            </div>
          </div>

          ${
            rep.bio_summary
              ? `<p class="text-xs text-slate-600 leading-relaxed">${esc(rep.bio_summary.slice(0, 150))}${rep.bio_summary.length > 150 ? "…" : ""}</p>`
              : ""
          }

          <div class="pt-2.5 border-t border-slate-100 flex items-center justify-between text-xs text-slate-600">
            ${
              tv > 0
                ? `<span>Attendance: <strong>${stats.attendance_rate ?? 100}%</strong> • Impact: <strong>${Math.round(stats.avg_impact_score ?? 0)}</strong></span>`
                : `<span class="px-2 py-0.5 rounded bg-amber-50 text-amber-800 font-medium">Pending roll-call votes</span>`
            }
            <span class="text-[#366a8a] font-semibold shrink-0 ml-2">Profile &amp; Contact →</span>
          </div>
        </button>
      `;
    })
    .join("");

  const parityNotes = [];
  Array.from(AppState.selectedJurIds).forEach((jid) => {
    const jm = getJurisdictionById(jid);
    (jm?.parity?.notes || []).forEach((n) => parityNotes.push(`<strong>${esc(jm.name)}:</strong> ${esc(n)}`));
  });
  const parityBanner = parityNotes.length
    ? `<div id="cpV51ParityBanner" class="p-3 rounded-xl bg-[#f4ecdc]/80 border border-[#1b3b4e]/15 text-xs text-[#142834]/85 space-y-1">${parityNotes.map((n) => `<div>&#8505;&#65039; ${n}</div>`).join("")}</div>`
    : "";
  const digestUrl = AppState.siteConfig?.weekly_digest_url || "";
  const digestBtn = digestUrl
    ? `<a href="${esc(digestUrl)}" target="_blank" rel="noopener noreferrer" class="shrink-0 px-3 py-1.5 rounded-lg bg-[#c67749] text-[#faf5eb] hover:bg-[#b56638] text-xs font-semibold">Get Weekly Email Alerts &#8599;</a>`
    : `<button type="button" data-open-modal="alertsModal" class="shrink-0 px-3 py-1.5 rounded-lg bg-[#1b3b4e] text-[#faf5eb] hover:bg-[#366a8a] text-xs font-semibold cursor-pointer">Subscribe to RSS Alerts</button>`;

  container.innerHTML = `
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div class="text-xs text-[#142834]/75">
        Click any representative to open their full profile: direct email/phone, voting-record summary, floor comments, metrics, and roll-call log.
      </div>
      ${digestBtn}
    </div>
    ${parityBanner}
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">${cards}</div>
  `;

  container.querySelectorAll("[data-open-modal]").forEach((btn) => { btn.addEventListener("click", () => openModal(btn.dataset.openModal)); });
  container.querySelectorAll("[data-open-rep]").forEach((btn) => {
    btn.addEventListener("click", () => openRepModal(btn.dataset.jurId, btn.dataset.openRep));
  });
}

// ---------------------------------------------------------------------------
// Tab 2: Before the Vote (Date-First Grouped, Zero Cut-Off Cards, .ics Export)
// ---------------------------------------------------------------------------
function downloadIcsEvent(entry) {
  const dt = String(entry.date || "").replace(/-/g, "");
  if (dt.length !== 8) return;
  const ics = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//CivicPulse//Local Meetings//EN",
    "BEGIN:VEVENT",
    `DTSTART;VALUE=DATE:${dt}`,
    `SUMMARY:${entry.jurName} — ${entry.title}`,
    `DESCRIPTION:${entry.kind}${entry.url ? `\\nOfficial Agenda: ${entry.url}` : ""}`,
    "END:VEVENT",
    "END:VCALENDAR",
  ].join("\r\n");
  const blob = new Blob([ics], { type: "text/calendar;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `civicpulse_${dt}.ics`;
  a.click();
  URL.revokeObjectURL(a.href);
}

function renderTabBeforeTheVote(container, upcomingByDate) {
  const dates = Array.from(upcomingByDate.keys()).sort();
  if (!dates.length) {
    container.innerHTML = `
      <div class="cp-card p-6 text-sm text-slate-600 space-y-2">
        <div class="font-bold text-[#142834]">No upcoming agendas or P&amp;Z hearings currently posted for your selected jurisdiction(s).</div>
        <p class="text-xs">Switch to <strong>Votes &amp; Topic Radar</strong> to review recently completed roll-call votes, or click any jurisdiction chip's <strong>↗</strong> icon to open its official calendar.</p>
      </div>
    `;
    return;
  }

  const allEntries = [];
  const groupsHtml = dates
    .map((dt) => {
      const list = upcomingByDate.get(dt);
      const rows = list
        .map((m) => {
          const idx = allEntries.length;
          allEntries.push(m);
          const kindCls =
            m.kind === "Planning & Zoning Signal"
              ? "bg-amber-100 text-amber-900"
              : m.kind === "Agenda Preview"
              ? "bg-indigo-100 text-indigo-900"
              : "bg-[#1b3b4e]/10 text-[#1b3b4e]";

          const bullets = (m.items || [])
            .slice(0, 4)
            .map(
              (it) => `
              <li class="text-xs text-slate-700 leading-relaxed">
                <strong class="text-slate-900">${esc(it.title || it)}</strong>
                ${it.plain_summary ? ` — ${esc(it.plain_summary)}` : ""}
              </li>
            `
            )
            .join("");

          return `
            <div class="p-4 rounded-xl bg-[#faf5eb]/80 border border-[#1b3b4e]/12 space-y-2.5">
              <div class="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
                <div class="min-w-0 flex-1 space-y-1.5">
                  <div class="flex flex-wrap items-center gap-2">
                    <span class="px-2 py-0.5 rounded-md text-[11px] font-bold bg-white border border-[#1b3b4e]/15 text-[#1b3b4e]">${esc(m.jurName)}</span>
                    <span class="px-2 py-0.5 rounded-md text-[11px] font-semibold ${kindCls}">${esc(m.kind)}</span>
                  </div>
                  <h4 class="text-sm sm:text-base font-bold text-[#142834] leading-snug break-words">${esc(m.title)}</h4>
                </div>
                <div class="flex flex-wrap items-center gap-2 shrink-0">
                  <button type="button" data-email-meeting-idx="${idx}" class="px-2.5 py-1.5 rounded-lg border border-[#c67749]/40 bg-white hover:bg-[#faf5eb] text-xs font-semibold text-[#9c5128] cursor-pointer">
                    &#9993;&#65039; Email Council
                  </button>
                  <button type="button" data-ics-idx="${idx}" class="px-2.5 py-1.5 rounded-lg border border-[#1b3b4e]/20 bg-white hover:bg-[#f4ecdc] text-xs font-semibold text-[#1b3b4e] cursor-pointer">
                    + Calendar (.ics)
                  </button>
                  ${
                    m.url
                      ? `<a href="${esc(m.url)}" target="_blank" rel="noopener noreferrer" class="px-3 py-1.5 rounded-lg bg-[#1b3b4e] text-[#faf5eb] hover:bg-[#366a8a] text-xs font-semibold">Open Agenda ↗</a>`
                      : ""
                  }
                </div>
              </div>
              ${bullets ? `<ul class="list-disc pl-5 space-y-1 pt-1 border-t border-[#1b3b4e]/10">${bullets}</ul>` : ""}
            </div>
          `;
        })
        .join("");

      return `
        <article class="cp-card p-5 space-y-3 shadow-xs">
          <div class="flex flex-wrap items-center justify-between gap-2 pb-2.5 border-b border-[#1b3b4e]/10">
            <h3 class="text-base font-bold text-[#142834]">📅 ${esc(formatDateHeading(dt))}</h3>
            <span class="text-xs font-semibold text-[#366a8a]">${list.length} meeting${list.length === 1 ? "" : "s"} on this date</span>
          </div>
          <div class="space-y-3">${rows}</div>
        </article>
      `;
    })
    .join("");

  container.innerHTML = groupsHtml;
  container.querySelectorAll("[data-email-meeting-idx]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const m = allEntries[Number(btn.dataset.emailMeetingIdx)];
      const p = await loadJurPayload(m.jurId);
      const reps = getEntitiesFromPayload(p);
      const repEmails = reps.map((r) => r.email).filter(Boolean);
      const fallback = AppState.officialContacts?.[m.jurId]?.council_email || getJurisdictionById(m.jurId)?.council_email || "";
      const toEmail = repEmails.length ? repEmails.join(",") : fallback;
      openCommentComposer({
        toEmail: toEmail || "council@city.gov",
        recipientName: `${m.jurName} Members`,
        jurName: m.jurName,
        measureTitle: `${m.title} (${m.date})`,
      });
    });
  });
  container.querySelectorAll("[data-ics-idx]").forEach((btn) => {
    btn.addEventListener("click", () => downloadIcsEvent(allEntries[Number(btn.dataset.icsIdx)]));
  });
}

// ---------------------------------------------------------------------------
// Tab 3: Votes & Topic Radar (Scoped to Selected Jurs + CSV Export)
// ---------------------------------------------------------------------------
function exportEventsCsv(events) {
  const header = ["Date", "Jurisdiction", "Topic", "Title", "Outcome", "Impact_Score", "QA_Status", "Source_URL"];
  const lines = [header.join(",")];
  events.forEach((ev) => {
    const row = [
      ev._date,
      ev._jurName,
      ev._topic,
      ev.title || "",
      ev.outcome || "",
      ev._impact,
      ev.qa_status || "verified",
      ev.source_url || "",
    ].map((cell) => `"${String(cell).replace(/"/g, '""')}"`);
    lines.push(row.join(","));
  });
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `civicpulse_filtered_votes_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

function renderTabVotesRadar(container, scopedEvents) {
  const topics = Array.from(new Set(scopedEvents.map((e) => e._topic))).sort();

  let filtered = scopedEvents.filter((ev) => {
    if (AppState.votesTopic !== "all" && ev._topic !== AppState.votesTopic) return false;
    if (AppState.votesCommercialOnly && !COMMERCIAL_TOPICS.has(ev._topic)) return false;
    if (AppState.votesSearch.trim()) {
      const q = AppState.votesSearch.trim().toLowerCase();
      const hay = `${ev.title || ""} ${ev.plain_summary || ""} ${ev._topic} ${ev._jurName}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  if (AppState.votesSort === "impact_desc") {
    filtered.sort((a, b) => b._impact - a._impact || b._date.localeCompare(a._date));
  } else if (AppState.votesSort === "closest") {
    filtered.sort((a, b) => {
      const ma = Math.abs(Number(a.yes_count ?? 0) - Number(a.no_count ?? 0));
      const mb = Math.abs(Number(b.yes_count ?? 0) - Number(b.no_count ?? 0));
      return ma - mb || b._impact - a._impact;
    });
  } else {
    filtered.sort((a, b) => b._date.localeCompare(a._date) || b._impact - a._impact);
  }

  const cardsHtml = filtered.length
    ? filtered
        .slice(0, 60)
        .map((ev) => {
          const isPassed = /pass|adopt|approv/i.test(String(ev.outcome || ""));
          const outcomeCls = isPassed
            ? "bg-emerald-50 text-emerald-800 border-emerald-200"
            : "bg-slate-100 text-slate-700 border-slate-200";
          const tally =
            ev.yes_count !== undefined && ev.no_count !== undefined && (ev.yes_count > 0 || ev.no_count > 0)
              ? ` (${ev.yes_count}-${ev.no_count})`
              : "";
          return `
            <article class="cp-card p-4 sm:p-5 hover:border-[#c67749] transition space-y-2.5">
              <div class="flex flex-wrap items-center justify-between gap-2 text-xs">
                <div class="flex flex-wrap items-center gap-2">
                  <span class="font-bold text-[#142834]">${esc(formatDateHeading(ev._date))}</span>
                  <span class="px-2 py-0.5 rounded bg-[#f4ecdc] text-[#1b3b4e] font-semibold">${esc(ev._jurName)}</span>
                  <span class="px-2 py-0.5 rounded bg-blue-50 text-blue-800 font-medium">${esc(ev._topic)}</span>
                </div>
                <div class="flex flex-wrap items-center gap-1.5">
                  <span class="px-2.5 py-0.5 rounded-full font-semibold border ${outcomeCls}">${esc(ev.outcome || "Recorded")}${tally}</span>
                  <span class="px-2.5 py-0.5 rounded-full bg-[#1b3b4e] text-[#faf5eb] font-bold">Impact ${ev._impact}/100</span>
                </div>
              </div>
              <button type="button" data-open-bill="${esc(ev.event_id)}" data-jur-id="${esc(ev._jurId)}" class="text-left block w-full group cursor-pointer">
                <h4 class="text-base font-bold text-[#142834] group-hover:text-[#366a8a] break-words">${esc(ev.title)}</h4>
              </button>
              ${ev.plain_summary ? `<p class="text-xs sm:text-sm text-slate-700 leading-relaxed">${esc(ev.plain_summary)}</p>` : ""}
              <div class="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-slate-100 text-xs">
                <div class="flex flex-wrap items-center gap-3 text-slate-500">
                  <span>QA: <strong class="text-emerald-700">${esc(ev.qa_status || "verified")}</strong></span>${ev._votes.length === 0 ? '<span class="px-2 py-0.5 rounded bg-slate-100 text-slate-600 font-medium">Voice / Consent Vote</span>' : ""}
                  ${ev.source_url ? `<a href="${esc(ev.source_url)}" target="_blank" rel="noopener noreferrer" class="text-[#366a8a] font-semibold hover:underline">Official Record ↗</a>` : ""}
                </div>
                <button type="button" data-open-bill="${esc(ev.event_id)}" data-jur-id="${esc(ev._jurId)}" class="text-[#c67749] font-semibold hover:underline cursor-pointer">
                  Inspect Roll Call &amp; Quotes →
                </button>
              </div>
            </article>
          `;
        })
        .join("")
    : `<div class="cp-card p-6 text-sm text-slate-600">No recorded measures match your current filter. Try clearing the topic filter or selecting another jurisdiction.</div>`;

  container.innerHTML = `
    <div class="cp-card p-4 flex flex-col lg:flex-row lg:items-center justify-between gap-3">
      <div class="flex flex-wrap items-center gap-2 flex-1">
        <input
          id="wsVotesSearchInput"
          type="search"
          value="${esc(AppState.votesSearch)}"
          placeholder="Filter measures by keyword (e.g. zoning, water, budget)..."
          class="flex-1 min-w-[200px] rounded-xl border border-[#1b3b4e]/25 bg-[#faf5eb]/60 px-3 py-1.5 text-xs sm:text-sm focus:bg-white focus:border-[#c67749] focus:outline-none"
        />
        <select id="wsVotesTopicSelect" class="rounded-xl border border-[#1b3b4e]/25 bg-white px-3 py-1.5 text-xs font-semibold text-[#1b3b4e]">
          <option value="all">All Topics (${scopedEvents.length})</option>
          ${topics.map((t) => `<option value="${esc(t)}" ${AppState.votesTopic === t ? "selected" : ""}>${esc(t)}</option>`).join("")}
        </select>
        <label class="inline-flex items-center gap-1.5 text-xs font-semibold text-[#1b3b4e] cursor-pointer px-2">
          <input id="wsCommercialOnlyToggle" type="checkbox" ${AppState.votesCommercialOnly ? "checked" : ""} class="rounded" />
          <span>Commercial / Regulatory Only</span>
        </label>
      </div>
      <div class="flex items-center gap-2 shrink-0">
        <select id="wsVotesSortSelect" class="rounded-xl border border-[#1b3b4e]/25 bg-white px-3 py-1.5 text-xs font-semibold text-[#1b3b4e]">
          <option value="date_desc" ${AppState.votesSort === "date_desc" ? "selected" : ""}>Newest First</option>
          <option value="impact_desc" ${AppState.votesSort === "impact_desc" ? "selected" : ""}>Highest Impact</option>
          <option value="closest" ${AppState.votesSort === "closest" ? "selected" : ""}>Closest Margin</option>
        </select>
        <button type="button" id="wsExportCsvBtn" class="px-3 py-1.5 rounded-xl bg-[#1b3b4e] text-[#faf5eb] hover:bg-[#366a8a] text-xs font-semibold cursor-pointer">
          ⬇ Export CSV (${filtered.length})
        </button>
      </div>
    </div>
    <div class="space-y-3">${cardsHtml}</div>
  `;

  container.querySelector("#wsVotesSearchInput")?.addEventListener("input", (e) => {
    AppState.votesSearch = e.target.value;
    renderTabVotesRadar(container, scopedEvents);
  });
  container.querySelector("#wsVotesTopicSelect")?.addEventListener("change", (e) => {
    AppState.votesTopic = e.target.value;
    renderTabVotesRadar(container, scopedEvents);
  });
  container.querySelector("#wsCommercialOnlyToggle")?.addEventListener("change", (e) => {
    AppState.votesCommercialOnly = e.target.checked;
    renderTabVotesRadar(container, scopedEvents);
  });
  container.querySelector("#wsVotesSortSelect")?.addEventListener("change", (e) => {
    AppState.votesSort = e.target.value;
    renderTabVotesRadar(container, scopedEvents);
  });
  container.querySelector("#wsExportCsvBtn")?.addEventListener("click", () => exportEventsCsv(filtered));
  container.querySelectorAll("[data-open-bill]").forEach((btn) => {
    btn.addEventListener("click", () => openBillModal(btn.dataset.jurId, btn.dataset.openBill));
  });
}

// ---------------------------------------------------------------------------
// Tab 4: Alignment & Representative Accountability Metrics
// ---------------------------------------------------------------------------
function renderTabAlignment(container, selectedJurs, scopedReps) {
  const alignMap = AppState.alignmentMatrix?.jurisdictions || AppState.alignmentMatrix?.by_jurisdiction || {};
  const alignBlocks = selectedJurs
    .map((j) => {
      const jid = jurIdOf(j);
      const a = alignMap[jid];
      if (!a) return "";
      const pairs = (a.most_divergent_pairs || a.divergent_pairs || []).slice(0, 4);
      const splitCount = a.split_vote_count ?? a.split_votes ?? 0;
      const unanRate = a.unanimity_rate !== undefined ? `${Math.round(a.unanimity_rate)}%` : "—";
      return `
        <div class="cp-card p-4 sm:p-5 space-y-3">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <h3 class="text-base font-bold text-[#142834]">${esc(j.name)} — Council Split Votes</h3>
            <span class="text-xs font-semibold px-2.5 py-1 rounded-full bg-[#f4ecdc] text-[#1b3b4e]">
              ${splitCount} Split Votes • Unanimity ${unanRate}
            </span>
          </div>
          ${
            pairs.length
              ? `<div class="grid grid-cols-1 sm:grid-cols-2 gap-2.5 text-xs">
                  ${pairs
                    .map(
                      (p) => `
                      <div class="p-3 rounded-xl bg-[#faf5eb] border border-[#1b3b4e]/12 flex items-center justify-between gap-2">
                        <span class="font-semibold text-[#142834]">${esc(p.member_a || p.a)} &amp; ${esc(p.member_b || p.b)}</span>
                        <span class="font-bold text-[#c67749]">${Math.round(p.agreement_rate ?? p.agreement_pct ?? 0)}% agree</span>
                      </div>
                    `
                    )
                    .join("")}
                </div>`
              : `<p class="text-xs text-slate-500">Not enough contested split votes yet to compute pairwise divergence.</p>`
          }
        </div>
      `;
    })
    .filter(Boolean)
    .join("");

  const rowsHtml = scopedReps
    .map(({ rep, jurId, jurName }) => {
      const pid = rep.ocd_person_id || rep.id;
      const st = rep.metrics || rep.stats || {};
      const tv = Number(st.total_votes ?? 0);
      return `
        <tr class="hover:bg-[#faf5eb]/70">
          <td class="py-3 px-4">
            <button type="button" data-open-rep="${esc(pid)}" data-jur-id="${esc(jurId)}" class="font-bold text-[#366a8a] hover:underline text-left cursor-pointer">
              ${esc(rep.name)}
            </button>
            <div class="text-[11px] text-slate-500">${esc(jurName)}</div>
          </td>
          <td class="py-3 px-4 text-xs text-slate-700">${esc(rep.district || "At-Large")}</td>
          <td class="py-3 px-4 text-xs font-semibold">${tv > 0 ? tv : "Pending"}</td>
          <td class="py-3 px-4 text-xs font-semibold">${tv > 0 ? `${st.attendance_rate ?? 100}%` : "—"}</td>
          <td class="py-3 px-4 text-xs font-semibold text-[#1b3b4e]">${tv > 0 ? `${Math.round(st.avg_impact_score ?? 0)}/100` : "—"}</td>
          <td class="py-3 px-4 text-xs font-semibold text-[#c67749]">${st.pivotal_votes ?? 0}</td>
        </tr>
      `;
    })
    .join("");

  container.innerHTML = `
    ${alignBlocks}
    <div class="cp-card overflow-x-auto shadow-xs">
      <table class="w-full text-left border-collapse text-sm">
        <thead>
          <tr class="bg-[#f4ecdc] border-b border-[#1b3b4e]/15 text-[11px] uppercase tracking-wider text-[#1b3b4e]">
            <th class="py-3 px-4">Representative (Click for Profile)</th>
            <th class="py-3 px-4">District</th>
            <th class="py-3 px-4">Votes</th>
            <th class="py-3 px-4">Attendance</th>
            <th class="py-3 px-4">Avg Impact</th>
            <th class="py-3 px-4">Pivotal</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-slate-100">${rowsHtml}</tbody>
      </table>
    </div>
  `;

  container.querySelectorAll("[data-open-rep]").forEach((btn) => {
    btn.addEventListener("click", () => openRepModal(btn.dataset.jurId, btn.dataset.openRep));
  });
}

// ---------------------------------------------------------------------------
// Representative Profile Modal (Contact, Photo, AI Bio, Comments & Votes)
// ---------------------------------------------------------------------------
async function openRepModal(jurId, personId) {
  const payload = await loadJurPayload(jurId);
  if (!payload) return;
  const jur = payload.jurisdiction || getJurisdictionById(jurId) || {};
  const rep = getEntitiesFromPayload(payload).find((r) => (r.ocd_person_id || r.id) === personId);
  if (!rep) return;

  history.replaceState(null, "", `#/rep/${encodeURIComponent(jurId)}/${encodeURIComponent(personId)}`);

  const repVotes = [];
  getEventsFromPayload(payload).forEach((ev) => {
    const vList = normalizeEventVotes(ev);
    const hit = vList.find((v) => v.entity_id === personId);
    if (hit) {
      repVotes.push({
        event_id: ev.event_id,
        title: ev.title,
        date: String(ev.meeting_date || ev.date || "").slice(0, 10),
        topic: ev.topic || ev.event_type || "General",
        outcome: ev.outcome || "",
        impact_score: Math.round(Number(ev.impact_score ?? 0)),
        source_url: ev.source_url || "",
        ...hit,
      });
    }
  });
  repVotes.sort((a, b) => b.date.localeCompare(a.date));

  const stats = rep.metrics || rep.stats || {};
  const totalVotes = Number(stats.total_votes ?? repVotes.length);
  const attendance = totalVotes > 0 ? `${stats.attendance_rate ?? 100}%` : "Pending";
  const avgImpact = totalVotes > 0 ? `${Math.round(stats.avg_impact_score ?? 0)}/100` : "—";
  const pivotal = stats.pivotal_votes ?? repVotes.filter((v) => v.is_pivotal).length;

  const fallbackEmail = AppState.officialContacts?.[jurId]?.council_email || jur.council_email || "";
  const directEmail = rep.email || fallbackEmail;
  const officialUrl = normalizeHumanPortalUrl(rep.website_url || rep.website || jur.roster_url || jur.portal_url);

  const contactBtns = [];
  if (directEmail) {
    contactBtns.push(
      `<button type="button" id="repDraftCommentBtn" class="px-3.5 py-1.5 rounded-lg bg-[#1b3b4e] text-[#faf5eb] hover:bg-[#366a8a] text-xs font-semibold cursor-pointer">✉️ Draft Email to ${esc(rep.email ? rep.name : "Council Office")}</button>`
    );
  }
  if (rep.phone) {
    contactBtns.push(
      `<a href="tel:${esc(rep.phone)}" class="px-3 py-1.5 rounded-lg border border-[#1b3b4e]/25 bg-white hover:bg-[#f4ecdc] text-[#1b3b4e] text-xs font-semibold">📞 ${esc(rep.phone)}</a>`
    );
  }
  if (officialUrl) {
    contactBtns.push(
      `<a href="${esc(officialUrl)}" target="_blank" rel="noopener noreferrer" class="px-3 py-1.5 rounded-lg border border-[#1b3b4e]/25 bg-white hover:bg-[#f4ecdc] text-[#1b3b4e] text-xs font-semibold">Official Page ↗</a>`
    );
  }

  const avatar = rep.photo_url
    ? `<img src="${esc(rep.photo_url)}" alt="${esc(rep.name)}" class="w-16 h-16 rounded-2xl object-cover border border-slate-200 shrink-0" />`
    : `<div class="w-16 h-16 rounded-2xl bg-[#1b3b4e] text-[#faf5eb] text-xl font-bold flex items-center justify-center shrink-0">${esc(initialsFor(rep.name))}</div>`;

  const bioText = synthesizeClientFallbackBio(rep, jur.name || jurId, repVotes);
  const comments = repVotes.filter((v) => v.quote || v.summary);

  const body = document.getElementById("repModalBody");
  body.innerHTML = `
    <div class="flex items-start justify-between gap-4">
      <div class="flex items-start gap-4">
        ${avatar}
        <div>
          <div class="text-xs font-bold uppercase tracking-wide text-[#366a8a]">
            ${esc(jur.name || "")} • ${esc(rep.role || "Member")}${rep.district ? ` (${esc(rep.district)})` : ""}
          </div>
          <h2 class="text-2xl font-bold text-[#142834] mt-0.5">${esc(rep.name)}</h2>
          <div class="text-xs text-slate-500 mt-0.5">
            Term: ${esc(rep.elected_date || "Active")} • Records since ${esc(jur.docs_since || "2026-01-01")}
          </div>
        </div>
      </div>
      <button type="button" data-close-modal="repModal" class="px-3 py-1.5 rounded-lg border border-slate-200 text-xs font-semibold text-slate-600 hover:bg-slate-100 cursor-pointer">✕ Close</button>
    </div>

    <div class="flex flex-wrap gap-2">${contactBtns.join("")}</div>

    <div class="p-4 rounded-xl bg-[#f4ecdc]/75 border border-[#1b3b4e]/15 space-y-1.5">
      <div class="flex items-center justify-between gap-2">
        <span class="text-xs font-bold uppercase tracking-wide text-[#1b3b4e]">Legislative Profile &amp; Voting Summary</span>
        <span class="text-[11px] text-[#366a8a]">Grounded in official votes &amp; minutes</span>
      </div>
      <p class="text-sm text-[#142834] leading-relaxed">${esc(bioText)}</p>
    </div>

    <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
      <div class="p-3 rounded-xl bg-slate-50 border border-slate-200/80"><div class="text-xs text-slate-500">Recorded Votes</div><div class="text-xl font-bold text-[#142834] mt-0.5">${totalVotes}</div></div>
      <div class="p-3 rounded-xl bg-slate-50 border border-slate-200/80"><div class="text-xs text-slate-500">Attendance</div><div class="text-xl font-bold text-[#142834] mt-0.5">${attendance}</div></div>
      <div class="p-3 rounded-xl bg-slate-50 border border-slate-200/80"><div class="text-xs text-slate-500">Avg Impact</div><div class="text-xl font-bold text-[#366a8a] mt-0.5">${avgImpact}</div></div>
      <div class="p-3 rounded-xl bg-slate-50 border border-slate-200/80"><div class="text-xs text-slate-500">Pivotal Votes</div><div class="text-xl font-bold text-[#c67749] mt-0.5">${pivotal}</div></div>
    </div>

    <div class="space-y-2">
      <h3 class="text-sm font-bold text-[#142834]">Comments &amp; Remarks on Measures</h3>
      ${
        comments.length
          ? comments
              .slice(0, 6)
              .map(
                (c) => `
                <div class="p-3 rounded-xl bg-[#faf5eb] border border-[#1b3b4e]/12 text-xs space-y-1">
                  <div class="font-semibold text-[#142834]">${esc(c.date)} • ${esc(c.title)}</div>
                  ${c.quote ? `<blockquote class="italic text-slate-700 border-l-2 border-[#c67749] pl-2.5">"${esc(c.quote)}"</blockquote>` : ""}
                  ${!c.quote && c.summary ? `<p class="text-slate-600">${esc(c.summary)}</p>` : ""}
                </div>
              `
              )
              .join("")
          : `<p class="text-xs text-slate-500">No direct floor remarks extracted from ingested minutes yet.</p>`
      }
    </div>

    <div class="space-y-2">
      <h3 class="text-sm font-bold text-[#142834]">Recorded Roll-Call Votes (${repVotes.length})</h3>
      ${
        repVotes.length
          ? `<div class="space-y-2.5">${repVotes
              .map((v) => {
                const isYes = /^(yes|aye|yea)$/i.test(v.vote);
                const isNo = /^(no|nay)$/i.test(v.vote);
                const cls = isYes
                  ? "bg-emerald-50 text-emerald-800 border-emerald-200"
                  : isNo
                  ? "bg-rose-50 text-rose-800 border-rose-200"
                  : "bg-slate-100 text-slate-700 border-slate-200";
                return `
                  <div class="p-3.5 rounded-xl border border-slate-200 bg-white flex flex-col sm:flex-row sm:items-start justify-between gap-2.5">
                    <div class="min-w-0 space-y-1">
                      <div class="text-xs text-slate-500">
                        <strong class="text-slate-700">${esc(v.date)}</strong> • ${esc(v.topic)} • Impact ${v.impact_score}/100
                        ${v.is_pivotal ? '<span class="ml-1 px-2 py-0.5 rounded-full bg-amber-100 text-amber-900 font-semibold">Pivotal</span>' : ""}
                      </div>
                      <button type="button" data-open-bill="${esc(v.event_id)}" data-jur-id="${esc(jurId)}" class="text-left text-sm font-bold text-[#142834] hover:text-[#366a8a] break-words cursor-pointer">
                        ${esc(v.title)}
                      </button>
                    </div>
                    <span class="shrink-0 px-3 py-1 rounded-full text-xs font-semibold border ${cls}">${esc(v.vote)}</span>
                  </div>
                `;
              })
              .join("")}</div>`
          : `<p class="text-xs text-slate-500">No individual roll-call votes ingested for this representative yet.</p>`
      }
    </div>
  `;

  body.querySelector("[data-close-modal]")?.addEventListener("click", () => closeModal("repModal"));
  body.querySelector("#repDraftCommentBtn")?.addEventListener("click", () => {
    openCommentComposer({
      toEmail: directEmail,
      recipientName: rep.name,
      jurName: jur.name || "",
      measureTitle: "",
    });
  });
  body.querySelectorAll("[data-open-bill]").forEach((btn) => {
    btn.addEventListener("click", () => {
      closeModal("repModal");
      openBillModal(btn.dataset.jurId, btn.dataset.openBill);
    });
  });

  openModal("repModal");
}

// ---------------------------------------------------------------------------
// Bill / Measure Detail Modal (Roll-Call Matrix, Lifecycles, Error Report)
// ---------------------------------------------------------------------------
async function openBillModal(jurId, eventId) {
  const payload = await loadJurPayload(jurId);
  if (!payload) return;
  const jur = payload.jurisdiction || getJurisdictionById(jurId) || {};
  const ev = getEventsFromPayload(payload).find((e) => String(e.event_id) === String(eventId));
  if (!ev) return;

  history.replaceState(null, "", `#/bill/${encodeURIComponent(jurId)}/${encodeURIComponent(eventId)}`);

  const votes = normalizeEventVotes(ev);
  const entitiesById = new Map(getEntitiesFromPayload(payload).map((r) => [r.ocd_person_id || r.id, r]));
  const chains = AppState.billLifecycles?.[jurId] || [];
  const chain = chains.find((c) => (c.stages || []).some((s) => String(s.event_id) === String(eventId)));
  const errUrl = buildGithubErrorReportUrl({
    eventId: ev.event_id,
    jurName: jur.name || jurId,
    title: ev.title,
    sourceUrl: ev.source_url,
  });

  const body = document.getElementById("billModalBody");
  body.innerHTML = `
    <div class="flex items-start justify-between gap-4">
      <div class="space-y-1.5">
        <div class="flex flex-wrap items-center gap-2 text-xs">
          <span class="font-bold text-[#1b3b4e]">${esc(jur.name || "")}</span>
          <span class="text-slate-500">${esc(formatDateHeading(ev.meeting_date || ev.date))}</span>
          <span class="px-2 py-0.5 rounded bg-blue-50 text-blue-800 font-semibold">${esc(ev.topic || "General")}</span>
          <span class="px-2 py-0.5 rounded bg-[#1b3b4e] text-[#faf5eb] font-bold">Impact ${Math.round(ev.impact_score ?? 0)}/100</span>
        </div>
        <h2 class="text-xl font-bold text-[#142834] break-words">${esc(ev.title)}</h2>
      </div>
      <button type="button" data-close-modal="billModal" class="px-3 py-1.5 rounded-lg border border-slate-200 text-xs font-semibold text-slate-600 hover:bg-slate-100 cursor-pointer">✕ Close</button>
    </div>

    ${
      ev.plain_summary
        ? `<div class="p-4 rounded-xl bg-[#f4ecdc]/75 border border-[#1b3b4e]/15 space-y-1">
             <div class="text-xs font-bold uppercase tracking-wide text-[#1b3b4e]">Plain-English Summary</div>
             <p class="text-sm text-[#142834] leading-relaxed">${esc(ev.plain_summary)}</p>
           </div>`
        : ""
    }
    ${
      ev.diff_summary
        ? `<div class="p-3.5 rounded-xl bg-amber-50 border border-amber-200 text-xs text-amber-950"><strong>What Changed:</strong> ${esc(ev.diff_summary)}</div>`
        : ""
    }

    ${
      chain
        ? `<div class="p-4 rounded-xl bg-indigo-50/60 border border-indigo-200 space-y-2">
             <div class="text-xs font-bold text-indigo-900">Multi-Meeting Lifecycle (${esc(chain.match_basis || "Tracked Measure")})</div>
             <div class="space-y-1.5 border-l-2 border-indigo-300 pl-3 text-xs">
               ${(chain.stages || [])
                 .map(
                   (st) => `
                   <div class="${String(st.event_id) === String(eventId) ? "font-bold text-indigo-950" : "text-slate-700"}">
                     ${esc(st.meeting_date)} — ${esc(st.outcome)} (${esc(st.tally || "")}): ${esc(st.title)}
                   </div>
                 `
                 )
                 .join("")}
             </div>
           </div>`
        : ""
    }

    <div class="space-y-2.5">
      <h3 class="text-sm font-bold text-[#142834]">Roll-Call Breakdown (${votes.length})</h3>
      ${
        votes.length
          ? `<div class="grid grid-cols-1 sm:grid-cols-2 gap-2.5">${votes
              .map((v) => {
                const repObj = entitiesById.get(v.entity_id);
                const rName = v.name || repObj?.name || v.entity_id;
                const isYes = /^(yes|aye|yea)$/i.test(v.vote);
                const isNo = /^(no|nay)$/i.test(v.vote);
                const cls = isYes
                  ? "bg-emerald-50 text-emerald-800 border-emerald-200"
                  : isNo
                  ? "bg-rose-50 text-rose-800 border-rose-200"
                  : "bg-slate-100 text-slate-700 border-slate-200";
                return `
                  <button type="button" data-open-rep="${esc(v.entity_id)}" data-jur-id="${esc(jurId)}" class="text-left p-3 rounded-xl border border-slate-200 hover:border-[#c67749] transition space-y-1 cursor-pointer">
                    <div class="flex items-center justify-between gap-2">
                      <span class="text-xs font-bold text-[#142834]">${esc(rName)}</span>
                      <span class="px-2 py-0.5 rounded-full text-[11px] font-semibold border ${cls}">${esc(v.vote)}</span>
                    </div>
                    ${v.quote ? `<div class="text-[11px] italic text-slate-600">"${esc(v.quote.slice(0, 110))}"</div>` : ""}
                  </button>
                `;
              })
              .join("")}</div>`
          : `<p class="text-xs text-slate-500">Adopted by consent / voice vote or individual roll call was not listed in source minutes.</p>`
      }
    </div>

    <div class="flex flex-wrap items-center justify-between gap-2 pt-3 border-t border-slate-100 text-xs">
      <div class="flex flex-wrap items-center gap-3">
        ${ev.source_url ? `<a href="${esc(ev.source_url)}" target="_blank" rel="noopener noreferrer" class="font-semibold text-[#366a8a] hover:underline">Official Minutes / PDF ↗</a>` : ""}
        <a href="${esc(errUrl)}" target="_blank" rel="noopener noreferrer" class="text-slate-500 hover:text-rose-700 hover:underline">Report a Data Error ↗</a>
      </div>
      <span class="text-slate-500">QA: <strong class="text-emerald-700">${esc(ev.qa_status || "verified")}</strong></span>
    </div>
  `;

  body.querySelector("[data-close-modal]")?.addEventListener("click", () => closeModal("billModal"));
  body.querySelectorAll("[data-open-rep]").forEach((btn) => {
    btn.addEventListener("click", () => {
      closeModal("billModal");
      openRepModal(btn.dataset.jurId, btn.dataset.openRep);
    });
  });

  openModal("billModal");
}

function openCommentComposer({ toEmail, recipientName, jurName, measureTitle }) {
  const body = document.getElementById("commentComposerBody");
  const subj = measureTitle ? `Constituent Comment: ${measureTitle}` : `Constituent Feedback — ${jurName}`;
  const draft = `Dear ${recipientName},\n\nAs a resident of ${jurName}, I am writing to share my input${
    measureTitle ? ` regarding "${measureTitle}"` : ""
  }.\n\n[Share your brief perspective or specific ask here.]\n\nThank you for your service,\n[Your Name & Neighborhood/Ward]`;

  body.innerHTML = `
    <div class="flex items-center justify-between">
      <h3 class="text-lg font-bold text-[#142834]">Draft Constituent Email</h3>
      <button type="button" data-close-modal="commentComposerModal" class="px-2.5 py-1 rounded-lg border border-slate-200 text-xs font-semibold text-slate-600 cursor-pointer">✕ Close</button>
    </div>
    <div class="text-xs text-slate-600">To: <strong>${esc(toEmail)}</strong></div>
    <div class="space-y-2">
      <label class="block text-xs font-semibold text-slate-700">Subject</label>
      <input id="ccSubject" type="text" value="${esc(subj)}" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-xs" />
      <label class="block text-xs font-semibold text-slate-700">Message</label>
      <textarea id="ccBody" rows="6" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-xs leading-relaxed">${esc(draft)}</textarea>
    </div>
    <div class="flex flex-wrap justify-end gap-2">
      <button type="button" id="ccCopyBtn" class="px-3.5 py-2 rounded-xl border border-slate-300 text-xs font-semibold text-slate-700 hover:bg-slate-50 cursor-pointer">Copy Text</button>
      <a id="ccMailtoBtn" href="#" class="px-4 py-2 rounded-xl bg-[#1b3b4e] text-[#faf5eb] text-xs font-semibold hover:bg-[#366a8a]">Open in Email Client ↗</a>
    </div>
  `;

  function syncMailto() {
    const s = document.getElementById("ccSubject").value;
    const b = document.getElementById("ccBody").value;
    document.getElementById("ccMailtoBtn").href = `mailto:${encodeURIComponent(toEmail)}?subject=${encodeURIComponent(s)}&body=${encodeURIComponent(b)}`;
  }
  syncMailto();
  body.querySelector("#ccSubject")?.addEventListener("input", syncMailto);
  body.querySelector("#ccBody")?.addEventListener("input", syncMailto);
  body.querySelector("#ccCopyBtn")?.addEventListener("click", () => {
    navigator.clipboard?.writeText(document.getElementById("ccBody").value);
    body.querySelector("#ccCopyBtn").textContent = "Copied ✓";
  });
  body.querySelector("[data-close-modal]")?.addEventListener("click", () => closeModal("commentComposerModal"));
  openModal("commentComposerModal");
}

// ---------------------------------------------------------------------------
// Directory Views (Active + Searchable/Paginated Unclaimed)
// ---------------------------------------------------------------------------
function renderActiveDirectory() {}

function renderUnclaimedDirectory() {
  const unclaimed = AppState.jurisdictions.filter((j) => j.status !== "active");
  document.getElementById("unclaimedTotalBadge").textContent = `${unclaimed.length} available to request`;

  const q = AppState.unclaimedSearch.trim().toLowerCase();
  const matching = unclaimed.filter((j) => {
    const lvl = normalizeLevel(j.level);
    if (AppState.unclaimedTier !== "all" && lvl !== AppState.unclaimedTier) return false;
    if (q && !String(j.name || "").toLowerCase().includes(q)) return false;
    return true;
  });

  const shown = matching.slice(0, AppState.unclaimedCap);
  const grid = document.getElementById("unclaimedCardsGrid");

  grid.innerHTML = shown.length
    ? shown
        .map((j) => {
          const jid = jurIdOf(j);
          const reqUrl = buildGithubRequestUrl({
            name: j.name,
            ocdId: jid,
            level: normalizeLevel(j.level),
            portalUrl: j.portal_url || "",
          });
          return `
            <a href="${esc(reqUrl)}" target="_blank" rel="noopener noreferrer" class="rounded-xl border border-[#1b3b4e]/15 bg-[#faf5eb]/70 hover:bg-white hover:border-[#c67749] p-3 transition block">
              <div class="text-[10px] font-bold uppercase text-slate-500">${esc(formatLevelLabel(j.level))}</div>
              <div class="text-xs font-bold text-[#142834] mt-0.5 break-words">${esc(j.name)}</div>
              <div class="text-[11px] text-[#c67749] font-semibold mt-1.5">+ Request Tracking ↗</div>
            </a>
          `;
        })
        .join("")
    : `<div class="col-span-full text-xs text-slate-500 p-3">No unclaimed jurisdictions match that search.</div>`;

  const pagBar = document.getElementById("unclaimedPaginationBar");
  const showMoreBtn = document.getElementById("unclaimedShowMoreBtn");
  const collapseBtn = document.getElementById("unclaimedCollapseBtn");
  const rem = matching.length - shown.length;

  pagBar.classList.toggle("hidden", rem <= 0 && AppState.unclaimedCap <= UNCLAIMED_PAGE_SIZE);
  showMoreBtn.classList.toggle("hidden", rem <= 0);
  if (rem > 0) showMoreBtn.textContent = `Show ${Math.min(UNCLAIMED_PAGE_SIZE, rem)} More (${rem} remaining)`;
  collapseBtn.classList.toggle("hidden", AppState.unclaimedCap <= UNCLAIMED_PAGE_SIZE);
}

// ---------------------------------------------------------------------------
// Global Lazy Search
// ---------------------------------------------------------------------------
async function ensureSearchRecordsLoaded() {
  if (AppState.searchRecords !== null) return AppState.searchRecords;
  const raw = await fetchJsonSafe("data/search_index.json", []);
  AppState.searchRecords = Array.isArray(raw) ? raw : raw?.events || raw?.items || [];
  return AppState.searchRecords;
}

function wireGlobalSearch() {
  const inp = document.getElementById("globalSearchInput");
  const box = document.getElementById("globalSearchResults");
  if (!inp || !box) return;

  inp.addEventListener("focus", () => {
    ensureSearchRecordsLoaded();
  });

  inp.addEventListener("input", async () => {
    const q = inp.value.trim().toLowerCase();
    if (!q) {
      box.classList.add("hidden");
      return;
    }

    const evs = await ensureSearchRecordsLoaded();

    // 1. Active Jurisdictions
    const matchedActiveJurs = AppState.jurisdictions.filter(
      (j) =>
        j.status === "active" &&
        `${j.name || ""} ${formatLevelLabel(j.level)}`.toLowerCase().includes(q)
    );
    const jurHits = matchedActiveJurs.slice(0, 3).map((j) => ({
      group: "Jurisdictions",
      title: j.name,
      sub: `${formatLevelLabel(j.level)} ? ${j.entity_count ?? 0} Reps ? Click to add to workspace`,
      badge: "+ Filter",
      jurId: jurIdOf(j),
    }));

    // 2. Representatives (from matched active jurisdictions + cached payloads)
    const jursToInspect = new Set(matchedActiveJurs.slice(0, 3).map(jurIdOf));
    AppState.selectedJurIds.forEach((id) => jursToInspect.add(id));
    await Promise.all(Array.from(jursToInspect).map((id) => loadJurPayload(id)));

    const repHits = [];
    const seenRepIds = new Set();
    AppState.jurPayloads.forEach((payload, jid) => {
      const jName = payload?.jurisdiction?.name || getJurisdictionById(jid)?.name || "";
      getEntitiesFromPayload(payload).forEach((rep) => {
        const pid = rep.ocd_person_id || rep.id;
        if (!pid || seenRepIds.has(pid)) return;
        const hay = `${rep.name || ""} ${rep.role || ""} ${rep.district || ""} ${jName}`.toLowerCase();
        if (hay.includes(q)) {
          seenRepIds.add(pid);
          repHits.push({
            group: "Representatives",
            title: rep.name,
            sub: `${rep.role || "Member"}${rep.district ? ` (${rep.district})` : ""} ? ${jName}`,
            badge: "Profile ?",
            jurId: jid,
            personId: pid,
          });
        }
      });
    });

    // 3. Upcoming Meetings & Agenda Previews
    const upHits = [];
    const seenUp = new Set();
    [...AppState.upcomingMeetings, ...AppState.agendaPreviews].forEach((m) => {
      const jid = m.jurisdiction_id || m.ocd_division_id || "";
      const jName = m.jurisdiction_name || getJurisdictionById(jid)?.name || "";
      const title = cleanMeetingTitle(m.title || m.meeting_title, m.doc_type);
      const dt = String(m.meeting_date || m.date || "").slice(0, 10);
      const hay = `${title} ${jName} ${dt}`.toLowerCase();
      const key = `${jid}_${dt}_${title.toLowerCase()}`;
      if (hay.includes(q) && !seenUp.has(key)) {
        seenUp.add(key);
        upHits.push({
          group: "Upcoming Meetings",
          title,
          sub: `${jName} ? ${formatDateHeading(dt)}`,
          badge: "Agenda",
          jurId: jid,
          openBeforeTab: true,
        });
      }
    });

    // 4. Measures & Votes (deduplicated & ranked by impact so repetitive items don't crowd results)
    const rawMeasures = evs.filter((e) =>
      `${e.title || ""} ${e.plain_summary || ""} ${e.topic || ""} ${e.jurisdiction_name || ""}`
        .toLowerCase()
        .includes(q)
    );
    rawMeasures.sort(
      (a, b) =>
        Number(b.impact_score ?? 0) - Number(a.impact_score ?? 0) ||
        String(b.meeting_date || "").localeCompare(String(a.meeting_date || ""))
    );

    const billHits = [];
    const seenTitles = new Set();
    for (const e of rawMeasures) {
      const normTitle = String(e.title || "")
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, " ")
        .trim()
        .slice(0, 48);
      const dedupKey = `${e.jurisdiction_id}_${e.meeting_date}_${normTitle}`;
      if (seenTitles.has(dedupKey)) continue;
      seenTitles.add(dedupKey);
      billHits.push({
        group: "Measures & Votes",
        title: e.title,
        sub: `${e.jurisdiction_name || ""} ? ${e.meeting_date || ""} ? ${e.topic || "General"}`,
        badge: `Impact ${Math.round(Number(e.impact_score ?? 0))}`,
        jurId: e.jurisdiction_id,
        eventId: e.event_id,
      });
      if (billHits.length >= 4) break;
    }

    // 5. Unclaimed Colorado Jurisdictions (Demand Capture)
    const unclaimedHits = AppState.jurisdictions
      .filter((j) => j.status !== "active" && String(j.name || "").toLowerCase().includes(q))
      .slice(0, 2)
      .map((j) => ({
        group: "Request Coverage",
        title: j.name,
        sub: `${formatLevelLabel(j.level)} ? Not yet tracked ? Click to request`,
        badge: "+ Request ?",
        requestUrl: buildGithubRequestUrl({
          name: j.name,
          ocdId: jurIdOf(j),
          level: normalizeLevel(j.level),
          portalUrl: j.portal_url || "",
        }),
      }));

    const sections = [
      { label: "Jurisdictions", items: jurHits },
      { label: "Representatives", items: repHits.slice(0, 4) },
      { label: "Upcoming Meetings", items: upHits.slice(0, 3) },
      { label: "Measures & Votes", items: billHits },
      { label: "Request Coverage", items: unclaimedHits },
    ].filter((sec) => sec.items.length > 0);

    if (!sections.length) {
      box.innerHTML = `<div class="p-4 text-xs text-slate-500">No matching jurisdictions, representatives, meetings, or measures found for ?${esc(inp.value.trim())}?.</div>`;
      box.classList.remove("hidden");
      return;
    }

    const flatHits = [];
    box.innerHTML = sections
      .map((sec) => {
        const rows = sec.items
          .map((h) => {
            const idx = flatHits.length;
            flatHits.push(h);
            return `
              <button type="button" data-search-idx="${idx}" class="w-full text-left px-3.5 py-2.5 hover:bg-[#faf5eb] transition flex items-start justify-between gap-2.5 border-t border-slate-100 cursor-pointer">
                <div class="min-w-0 flex-1">
                  <div class="text-xs font-bold text-[#142834] leading-snug break-words">${esc(h.title)}</div>
                  <div class="text-[11px] text-slate-500 mt-0.5 truncate">${esc(h.sub)}</div>
                </div>
                <span class="shrink-0 px-2 py-0.5 rounded-md bg-[#f4ecdc] text-[#1b3b4e] text-[10px] font-bold">${esc(h.badge)}</span>
              </button>
            `;
          })
          .join("");

        return `
          <div>
            <div class="sticky top-0 z-10 bg-slate-100/95 backdrop-blur-xs px-3.5 py-1.5 flex items-center justify-between text-[10px] font-bold uppercase tracking-wider text-[#1b3b4e]">
              <span>${esc(sec.label)}</span>
              <span class="text-slate-500">${sec.items.length}</span>
            </div>
            ${rows}
          </div>
        `;
      })
      .join("");

    box.querySelectorAll("[data-search-idx]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const hit = flatHits[Number(btn.dataset.searchIdx)];
        box.classList.add("hidden");
        inp.value = "";
        if (hit.requestUrl) {
          window.open(hit.requestUrl, "_blank", "noopener,noreferrer");
          return;
        }
        if (hit.jurId) {
          AppState.selectedJurIds.add(hit.jurId);
          if (hit.openBeforeTab) AppState.activeTab = "before";
          else if (hit.personId) AppState.activeTab = "reps";
          persistState();
          onSelectionChanged(!hit.eventId && !hit.personId);
        }
        if (hit.personId) openRepModal(hit.jurId, hit.personId);
        else if (hit.eventId) openBillModal(hit.jurId, hit.eventId);
      });
    });

    box.classList.remove("hidden");
  });

  document.addEventListener("click", (e) => {
    if (!inp.contains(e.target) && !box.contains(e.target)) {
      box.classList.add("hidden");
    }
  });
}

// ---------------------------------------------------------------------------
// Utility Modals (Formula, RSS Alerts, Embed Widget, Voluntary Support)
// ---------------------------------------------------------------------------
function populateUtilityModals() {
  // 1. Formula Modal
  const fm = AppState.scoringMethodology;
  const fBody = document.getElementById("formulaModalBody");
  if (fBody) {
    fBody.innerHTML = `
      <div class="flex items-center justify-between">
        <div>
          <h3 class="text-lg font-bold text-[#142834]">Impact Score Methodology</h3>
          <div class="text-xs text-slate-500">Version ${esc(fm?.formula_version || "2.0.0")} • Hash ${esc(fm?.formula_hash || "verified")}</div>
        </div>
        <button type="button" data-close-modal="formulaModal" class="px-2.5 py-1 rounded-lg border border-slate-200 text-xs font-semibold text-slate-600 cursor-pointer">✕ Close</button>
      </div>
      <p class="text-xs text-slate-700 leading-relaxed">${esc(fm?.plain_english_summary || "CivicPulse computes an open, nonpartisan 0–100 Vote Impactfulness score based on fiscal scope, citywide reach, contested margin, and policy permanence.")}</p>
      <div class="flex flex-wrap gap-2 pt-2">
        <a href="docs/civicpulse_impact_formula.md" target="_blank" class="px-3 py-1.5 rounded-lg bg-[#1b3b4e] text-[#faf5eb] text-xs font-semibold">Download Formula (.md) ↗</a>
        <a href="docs/civicpulse_impact_formula.json" target="_blank" class="px-3 py-1.5 rounded-lg border border-slate-300 text-xs font-semibold text-slate-700">Download JSON ↗</a>
      </div>
    `;
    fBody.querySelector("[data-close-modal]")?.addEventListener("click", () => closeModal("formulaModal"));
  }

  // 2. RSS Alerts Modal
  const aBody = document.getElementById("alertsModalBody");
  if (aBody) {
    const base = window.location.origin + window.location.pathname.replace(/\/[^/]*$/, "/");
    const feeds = [
      { label: "All Colorado Jurisdictions", url: `${base}feeds/all.xml` },
      ...(AppState.feedsIndex?.jurisdictions || []).slice(0, 14).map((f) => ({
        label: f.name || f.title,
        url: `${base}${String(f.path || f.url || "").replace(/^\/+/, "")}`,
      })),
    ];
    aBody.innerHTML = `
      <div class="flex items-center justify-between">
        <h3 class="text-lg font-bold text-[#142834]">RSS &amp; Slack / Teams Feeds</h3>
        <button type="button" data-close-modal="alertsModal" class="px-2.5 py-1 rounded-lg border border-slate-200 text-xs font-semibold text-slate-600 cursor-pointer">✕ Close</button>
      </div>
      <p class="text-xs text-slate-600">Subscribe in any RSS reader, Slack, or Teams channel for automated updates whenever new votes publish.</p>
      <div class="space-y-2">${feeds
        .map(
          (f) => `
          <div class="p-2.5 rounded-xl bg-[#faf5eb] border border-[#1b3b4e]/12 flex items-center justify-between gap-2 text-xs">
            <span class="font-semibold text-[#142834] truncate">${esc(f.label)}</span>
            <a href="${esc(f.url)}" target="_blank" rel="noopener noreferrer" class="shrink-0 text-[#366a8a] font-semibold hover:underline">Open XML ↗</a>
          </div>
        `
        )
        .join("")}</div>
    `;
    aBody.querySelector("[data-close-modal]")?.addEventListener("click", () => closeModal("alertsModal"));
  }

  // 3. Embed Modal
  const eBody = document.getElementById("embedModalBody");
  if (eBody) {
    const embedUrl = `${window.location.origin}${window.location.pathname.replace(/\/[^/]*$/, "/")}embed.html?type=digest`;
    const snippet = `<iframe src="${embedUrl}" width="100%" height="460" style="border:1px solid #d6c7ac;border-radius:12px;" loading="lazy"></iframe>`;
    eBody.innerHTML = `
      <div class="flex items-center justify-between">
        <h3 class="text-lg font-bold text-[#142834]">Embed CivicPulse Widget</h3>
        <button type="button" data-close-modal="embedModal" class="px-2.5 py-1 rounded-lg border border-slate-200 text-xs font-semibold text-slate-600 cursor-pointer">✕ Close</button>
      </div>
      <p class="text-xs text-slate-600">Free for Colorado newsrooms, Substacks, and neighborhood blogs:</p>
      <textarea readonly rows="3" class="w-full rounded-xl border border-slate-300 bg-slate-50 p-3 font-mono text-xs">${esc(snippet)}</textarea>
    `;
    eBody.querySelector("[data-close-modal]")?.addEventListener("click", () => closeModal("embedModal"));
  }

  // 4. Patron / Voluntary Support Modal
  const pBody = document.getElementById("patronModalBody");
  if (pBody) {
    pBody.innerHTML = `
      <div class="flex items-center justify-between">
        <h3 class="text-lg font-bold text-[#142834]">Support CivicPulse</h3>
        <button type="button" data-close-modal="patronModal" class="px-2.5 py-1 rounded-lg border border-slate-200 text-xs font-semibold text-slate-600 cursor-pointer">✕ Close</button>
      </div>
      <p class="text-xs text-slate-700 leading-relaxed">
        CivicPulse is <strong>100% free with zero paywalls</strong>. Voluntary support helps expand automated coverage to more Colorado municipalities, counties, and school districts.
      </p>
      <div class="grid grid-cols-1 sm:grid-cols-3 gap-2.5 text-xs">
        <a href="${esc(AppState.siteConfig?.support_links?.coffee_5 || "mailto:bryanateisl@gmail.com?subject=CivicPulse%20Support%20(%245%20Coffee)")}" class="p-3 rounded-xl border border-slate-200 hover:border-[#c67749] text-center block"><div class="font-bold text-[#1b3b4e]">$5 Coffee</div><div class="text-slate-500 mt-0.5">One-time pitch-in</div></a>
        <a href="${esc(AppState.siteConfig?.support_links?.supporter_15 || "mailto:bryanateisl@gmail.com?subject=CivicPulse%20Support%20(%2415%20Supporter)")}" class="p-3 rounded-xl border border-slate-200 hover:border-[#c67749] text-center block"><div class="font-bold text-[#1b3b4e]">$15 Supporter</div><div class="text-slate-500 mt-0.5">Community backer</div></a>
        <a href="${esc(AppState.siteConfig?.support_links?.patron || "mailto:bryanateisl@gmail.com?subject=CivicPulse%20Business%20Patron")}" class="p-3 rounded-xl border border-slate-200 hover:border-[#c67749] text-center block"><div class="font-bold text-[#c67749]">Business Patron</div><div class="text-slate-500 mt-0.5">Sponsor city coverage</div></a>
      </div>
      <p class="text-[11px] text-slate-500 bg-slate-50 p-3 rounded-xl border border-slate-200/80">
        Transparency Notice: CivicPulse is an independent civic technology project, not a registered 501(c)(3) nonprofit. Voluntary contributions are not tax-deductible as charitable donations.
      </p>
    `;
    pBody.querySelector("[data-close-modal]")?.addEventListener("click", () => closeModal("patronModal"));
  }
}

// ---------------------------------------------------------------------------
// Deep Link Hash Router (#/jur/..., #/rep/..., #/bill/...)
// ---------------------------------------------------------------------------
async function handleHashRoute() {
  const h = window.location.hash || "";
  if (h.startsWith("#/jur/")) {
    const jid = decodeURIComponent(h.slice(6));
    if (getJurisdictionById(jid)) {
      AppState.selectedJurIds.add(jid);
      persistState();
      await onSelectionChanged(true);
    }
  } else if (h.startsWith("#/rep/")) {
    const parts = h.slice(6).split("/");
    if (parts.length >= 2) {
      const jid = decodeURIComponent(parts[0]);
      const pid = decodeURIComponent(parts[1]);
      if (getJurisdictionById(jid)) {
        AppState.selectedJurIds.add(jid);
        persistState();
        await onSelectionChanged(false);
      }
      await openRepModal(jid, pid);
    }
  } else if (h.startsWith("#/bill/")) {
    const parts = h.slice(7).split("/");
    if (parts.length >= 2) {
      const jid = decodeURIComponent(parts[0]);
      const eid = decodeURIComponent(parts[1]);
      if (getJurisdictionById(jid)) {
        AppState.selectedJurIds.add(jid);
        persistState();
        await onSelectionChanged(false);
      }
      await openBillModal(jid, eid);
    }
  }
}

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------
async function boot() {
  // Load persisted selections
  try {
    const savedJurs = JSON.parse(localStorage.getItem(LS_SELECTED_JURS) || "[]");
    if (Array.isArray(savedJurs)) savedJurs.forEach((id) => AppState.selectedJurIds.add(id));
    const savedTab = localStorage.getItem(LS_ACTIVE_TAB);
    if (savedTab && ["reps", "before", "votes", "alignment"].includes(savedTab)) {
      AppState.activeTab = savedTab;
    }
  } catch {
    // ignore
  }

  // Parallel static JSON fetch ($0/mo Cloudflare Pages)
  const [dirRaw, geo, upRaw, prevRaw, warnRaw, alignRaw, lifeRaw, scoreRaw, feedRaw, contactsRaw, siteCfg] =
    await Promise.all([
      fetchJsonSafe("data/directory.json", null),
      fetchJsonSafe("geo/boundaries.geojson", null),
      fetchJsonSafe("data/upcoming_meetings.json", []),
      fetchJsonSafe("data/agenda_previews.json", []),
      fetchJsonSafe("data/planning_early_warning.json", []),
      fetchJsonSafe("data/alignment_matrix.json", null),
      fetchJsonSafe("data/bill_lifecycles.json", {}),
      fetchJsonSafe("data/scoring_methodology.json", null),
      fetchJsonSafe("data/feeds_index.json", null),
      fetchJsonSafe("data/official_contacts.json", {}),
      fetchJsonSafe("data/site_config.json", null),
    ]);

  const dir = dirRaw || (await fetchJsonSafe("data/index.json", { jurisdictions: [] }));
  AppState.jurisdictions = dir?.jurisdictions || [];
  AppState.lastUpdated = dir?.last_updated || dir?.generated_at || "";
  AppState.boundariesGeo = geo;
  AppState.upcomingMeetings = Array.isArray(upRaw) ? upRaw : upRaw?.meetings || upRaw?.upcoming || [];
  AppState.agendaPreviews = Array.isArray(prevRaw) ? prevRaw : prevRaw?.previews || prevRaw?.items || [];
  AppState.earlyWarnings = Array.isArray(warnRaw) ? warnRaw : warnRaw?.hearings || warnRaw?.items || [];
  AppState.alignmentMatrix = alignRaw;
  AppState.billLifecycles = lifeRaw?.by_jurisdiction || lifeRaw || {};
  AppState.scoringMethodology = scoreRaw;
  AppState.feedsIndex = feedRaw;
  AppState.officialContacts = contactsRaw?.jurisdictions || contactsRaw || {};
  AppState.siteConfig = siteCfg || {};
  if (AppState.siteConfig?.cloudflare_analytics_token && !document.getElementById("cpCfBeacon")) {
    const s = document.createElement("script");
    s.id = "cpCfBeacon";
    s.defer = true;
    s.src = "https://static.cloudflareinsights.com/beacon.min.js";
    s.setAttribute("data-cf-beacon", JSON.stringify({ token: AppState.siteConfig.cloudflare_analytics_token }));
    document.head.appendChild(s);
  }

  // Drop any stale saved IDs that aren't active jurisdictions anymore
  const activeIdSet = new Set(AppState.jurisdictions.filter((j) => j.status === "active").map(jurIdOf));
  Array.from(AppState.selectedJurIds).forEach((id) => {
    if (!activeIdSet.has(id)) AppState.selectedJurIds.delete(id);
  });

  document.getElementById("lastUpdatedBadge").textContent = AppState.lastUpdated
    ? `Updated ${AppState.lastUpdated}`
    : `${activeIdSet.size} active Colorado jurisdictions`;

  // Wire Special District GitHub intake link
  const sdLink = document.getElementById("requestSpecialDistrictLink");
  if (sdLink) {
    sdLink.href = buildGithubRequestUrl({
      name: "Colorado Special District (Enter Name)",
      level: "special_district",
    });
  }

  // Wire static UI controls
  document.getElementById("addressLookupForm")?.addEventListener("submit", handleAddressSubmit);
  document.getElementById("useMyLocationBtn")?.addEventListener("click", handleUseMyLocation);

  document.getElementById("clearAllFiltersBtn")?.addEventListener("click", () => {
    AppState.selectedJurIds.clear();
    persistState();
    onSelectionChanged(false);
  });

  document.getElementById("printBriefingBtn")?.addEventListener("click", () => window.print());

  document.querySelectorAll(".ws-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      AppState.activeTab = btn.dataset.wsTab;
      persistState();
      renderWorkspace();
    });
  });

  document.querySelectorAll(".active-level-pill").forEach((pill) => {
    pill.addEventListener("click", () => {
      AppState.activeLevelFilter = pill.dataset.level;
      document.querySelectorAll(".active-level-pill").forEach((p) => {
        const isSel = p === pill;
        p.className = isSel
          ? "active-level-pill px-3 py-1.5 rounded-full text-xs font-semibold bg-[#1b3b4e] text-[#faf5eb] cursor-pointer"
          : "active-level-pill px-3 py-1.5 rounded-full text-xs font-semibold bg-white border border-[#1b3b4e]/20 text-[#1b3b4e] hover:bg-[#f4ecdc] cursor-pointer";
      });
      renderActiveDirectory();
    });
  });

  document.getElementById("unclaimedSearchInput")?.addEventListener("input", (e) => {
    AppState.unclaimedSearch = e.target.value;
    AppState.unclaimedCap = UNCLAIMED_PAGE_SIZE;
    renderUnclaimedDirectory();
  });

  document.querySelectorAll(".unc-tier-pill").forEach((pill) => {
    pill.addEventListener("click", () => {
      AppState.unclaimedTier = pill.dataset.tier;
      AppState.unclaimedCap = UNCLAIMED_PAGE_SIZE;
      document.querySelectorAll(".unc-tier-pill").forEach((p) => {
        const isSel = p === pill;
        p.className = isSel
          ? "unc-tier-pill px-3 py-1.5 rounded-full text-xs font-semibold bg-[#1b3b4e] text-[#faf5eb] cursor-pointer"
          : "unc-tier-pill px-3 py-1.5 rounded-full text-xs font-semibold bg-white border border-[#1b3b4e]/20 text-[#1b3b4e] cursor-pointer";
      });
      renderUnclaimedDirectory();
    });
  });

  document.getElementById("unclaimedShowMoreBtn")?.addEventListener("click", () => {
    AppState.unclaimedCap += UNCLAIMED_PAGE_SIZE;
    renderUnclaimedDirectory();
  });
  document.getElementById("unclaimedCollapseBtn")?.addEventListener("click", () => {
    AppState.unclaimedCap = UNCLAIMED_PAGE_SIZE;
    renderUnclaimedDirectory();
  });

  document.querySelectorAll("[data-open-modal]").forEach((btn) => {
    btn.addEventListener("click", () => openModal(btn.dataset.openModal));
  });
  document.querySelectorAll("[data-close-modal]").forEach((btn) => {
    btn.addEventListener("click", () => closeModal(btn.dataset.closeModal));
  });

  // Close modals on Escape key
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      ["repModal", "billModal", "commentComposerModal", "engageModal", "measures101Modal", "formulaModal", "alertsModal", "embedModal", "patronModal"].forEach(closeModal);
    }
  });

  initMap();
  wireGlobalSearch();
  populateUtilityModals();
  renderActiveDirectory();
  renderUnclaimedDirectory();
  await renderWorkspace();
  await handleHashRoute();
  window.addEventListener("hashchange", handleHashRoute);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
