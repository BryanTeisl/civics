/**
 * CivicPulse v4.0 Unified Workspace & Constituency UX
 * (public/assets/civicpulse_v4_workspace.js)
 */

const LS_SAVED_LOC_KEY = "cp_v4_saved_location";
const LS_SELECTED_JURS_KEY = "cp_v4_selected_jurisdictions";

let dirData = { jurisdictions: [] };
let upcomingMeetings = [];
let agendaPreviews = [];
let earlyWarnings = [];
let cachedJurPayloads = {};
let selectedJurIds = new Set();
let savedLocation = null; // { label, lat, lng, matchedJurIds: [], matchedDistricts: {} }
let activeWorkspaceTab = "before";
let activeRepProfile = null; // { jurId, personId }

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

function initialsFor(name) {
  const parts = String(name || "?").trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

// ---------------------------------------------------------------------------
// Data Loading
// ---------------------------------------------------------------------------
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

// ---------------------------------------------------------------------------
// 1. Optional Location -> Exact Constituencies & "My Reps"
// ---------------------------------------------------------------------------
function distanceKm(lat1, lon1, lat2, lon2) {
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

async function resolveLocationFromQuery(queryText) {
  const q = (queryText || "").trim();
  if (!q) return null;

  // Match city/county name directly against active jurisdictions first
  const activeJurs = (dirData.jurisdictions || []).filter((j) => j.status === "active");
  const nameMatches = activeJurs.filter((j) =>
    (j.name || "").toLowerCase().includes(q.toLowerCase())
  );

  // Also query free U.S. Census Geocoder for street addresses / ZIPs
  let lat = null;
  let lng = null;
  let resolvedLabel = q;

  try {
    const censusUrl =
      "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?address=" +
      encodeURIComponent(q.includes("CO") ? q : `${q}, CO`) +
      "&benchmark=Public_AR_Current&format=json";
    const resp = await fetch(censusUrl);
    if (resp.ok) {
      const json = await resp.json();
      const match = json?.result?.addressMatches?.[0];
      if (match?.coordinates) {
        lat = Number(match.coordinates.y);
        lng = Number(match.coordinates.x);
        resolvedLabel = match.matchedAddress || q;
      }
    }
  } catch {
    // Fallback to name/coordinate matching
  }

  if (lat === null && nameMatches.length > 0) {
    lat = Number(nameMatches[0].latitude || nameMatches[0].lat || 0);
    lng = Number(nameMatches[0].longitude || nameMatches[0].lng || 0);
    resolvedLabel = nameMatches[0].name;
  }

  const matchedJurIds = new Set(nameMatches.map((j) => j.ocd_division_id));
  if (lat && lng) {
    activeJurs.forEach((j) => {
      const jLat = Number(j.latitude || j.lat || 0);
      const jLng = Number(j.longitude || j.lng || 0);
      if (!jLat || !jLng) return;
      const radius = j.level === "county" || j.level === "school_district" ? 38 : 16;
      if (distanceKm(lat, lng, jLat, jLng) <= radius) {
        matchedJurIds.add(j.ocd_division_id);
      }
    });
  }

  return {
    label: resolvedLabel,
    lat,
    lng,
    matchedJurIds: Array.from(matchedJurIds),
    matchedDistricts: {},
  };
}

// ---------------------------------------------------------------------------
// 2 & 3. Clickable Representative Bubbles & Full Representative Detail View
// ---------------------------------------------------------------------------
function renderRepBubble(rep, jurId, jurName, isMyRep = false) {
  const pid = rep.id || rep.ocd_person_id;
  const photo = rep.photo_url
    ? `<img src="${esc(rep.photo_url)}" alt="${esc(rep.name)}" class="w-9 h-9 rounded-full object-cover border border-slate-200 shrink-0" />`
    : `<span class="w-9 h-9 rounded-full bg-slate-800 text-white text-xs font-bold inline-flex items-center justify-center shrink-0">${esc(initialsFor(rep.name))}</span>`;

  const myBadge = isMyRep
    ? `<span class="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-indigo-100 text-indigo-800">Your Rep</span>`
    : "";

  return `
    <button
      type="button"
      data-open-rep="${esc(pid)}"
      data-jur-id="${esc(jurId)}"
      class="group text-left inline-flex items-center gap-2.5 px-3 py-2 rounded-xl border ${
        isMyRep ? "border-indigo-300 bg-indigo-50/50" : "border-slate-200 bg-white"
      } hover:border-blue-400 hover:shadow-sm transition cursor-pointer"
      title="View ${esc(rep.name)}'s voting record, comments, metrics & contact details"
    >
      ${photo}
      <span class="min-w-0">
        <span class="block text-sm font-semibold text-slate-900 group-hover:text-blue-700 truncate">
          ${esc(rep.name)} ${myBadge}
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

  activeRepProfile = { jurId, personId };
  window.location.hash = `#/rep/${encodeURIComponent(personId)}`;

  const items = payload.agenda_items || payload.events || [];
  const repVotes = [];
  items.forEach((item) => {
    const vmap = item.votes || {};
    if (vmap[personId]) {
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

  // Contact info lives at the Representative level (never as misleading jurisdiction-wide bubbles)
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
  const socials = rep.social_links || {};
  Object.entries(socials).forEach(([plat, u]) => {
    if (u && plat !== "website") {
      contactLinks.push(
        `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer" class="px-3 py-1.5 rounded-lg border border-slate-200 bg-slate-50 text-slate-700 text-xs font-medium hover:bg-slate-100">${esc(plat)} ↗</a>`
      );
    }
  });

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
        <button type="button" id="cpV4CloseRepModal" class="px-3 py-1.5 rounded-lg border border-slate-200 text-sm font-semibold text-slate-600 hover:bg-slate-100">
          ✕ Close
        </button>
      </div>

      <!-- Representative-Level Contact Channels -->
      <div class="flex flex-wrap gap-2 pt-1">
        ${contactLinks.join("")}
      </div>

      <!-- AI-Generated Profile Summary from Voting Record & Comments -->
      <div class="p-4 rounded-xl bg-blue-50/60 border border-blue-200/80 space-y-1.5">
        <div class="flex items-center justify-between gap-2">
          <span class="text-xs font-bold uppercase tracking-wide text-blue-900">Legislative Profile & Voting Summary</span>
          <span class="text-[11px] text-blue-700">Grounded in official votes & minutes</span>
        </div>
        <p class="text-sm text-slate-800 leading-relaxed">${esc(bioText)}</p>
      </div>

      <!-- Metrics Strip -->
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

      <!-- Comments & Remarks on Measures -->
      <div class="space-y-2">
        <h3 class="text-sm font-bold text-slate-900">Comments & Remarks on Measures</h3>
        ${commentsHtml}
      </div>

      <!-- Complete Roll-Call Record -->
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
// 5. Consolidated "How to Engage" Reference Drawer (Replaces Repeated Boxes)
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
          <button type="button" id="cpV4CloseEngage" class="px-2.5 py-1 rounded-lg border border-slate-200 text-xs font-semibold text-slate-600 hover:bg-slate-100">✕ Close</button>
        </div>
        <p class="text-xs text-slate-600">
          Colorado city councils, county boards, and school boards follow the same core public participation rhythm:
        </p>
        <ol class="list-decimal pl-5 space-y-2 text-sm text-slate-800">
          <li><strong>Check the Agenda 48–72 Hours Early:</strong> Ordinances require two readings; weighing in before the second reading has the highest impact.</li>
          <li><strong>Email Your Representative Directly:</strong> Click your representative's profile bubble to email them with the item title and your neighborhood/ward before noon on meeting day so it enters the public record.</li>
          <li><strong>Sign Up for Public Comment (2–3 Minutes):</strong> Use the jurisdiction's <em>Official Portal ↗</em> link to register for in-person or Zoom/virtual comment.</li>
          <li><strong>State Your Name, City/District & Specific Ask:</strong> Lead with whether you support, oppose, or request an amendment on the specific agenda item.</li>
        </ol>
      </div>
    `;
    document.body.appendChild(modal);
    document.getElementById("cpV4CloseEngage")?.addEventListener("click", () => modal.classList.add("hidden"));
  }
  modal.classList.remove("hidden");
}

// ---------------------------------------------------------------------------
// 6. Date-First Grouped Upcoming & Recent Agendas (No Cut-Off Cards)
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
      <div class="p-6 rounded-2xl bg-white border border-slate-200 text-sm text-slate-600">
        No upcoming meetings scheduled in the next 14 days for the selected jurisdiction(s).
        Check the <strong>Votes &amp; Radar</strong> tab for recently completed minutes.
      </div>
    `;
  }

  const sortedDates = Array.from(byDate.keys()).sort();
  return sortedDates
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
// 7. Scoped Workspace (Rendered ONLY after 1+ Jurisdictions are Selected)
// ---------------------------------------------------------------------------
async function renderScopedWorkspace() {
  const root = document.getElementById("cpV4WorkspaceRoot");
  if (!root) return;

  const activeJurs = (dirData.jurisdictions || []).filter((j) => j.status === "active");
  const selectedList = activeJurs.filter((j) => selectedJurIds.has(j.ocd_division_id));

  // Location / My Constituencies Card
  const locHtml = savedLocation
    ? `
      <div class="p-4 rounded-2xl bg-indigo-50/70 border border-indigo-200 space-y-3">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div>
            <span class="text-xs font-bold uppercase tracking-wide text-indigo-800">📍 Your Constituencies</span>
            <h3 class="text-sm font-bold text-slate-900">${esc(savedLocation.label)}</h3>
          </div>
          <div class="flex items-center gap-2">
            <button type="button" id="cpV4SelectAllMyJurs" class="px-3 py-1.5 rounded-lg bg-indigo-600 text-white text-xs font-semibold hover:bg-indigo-700">
              Select All My Constituencies (${savedLocation.matchedJurIds.length})
            </button>
            <button type="button" id="cpV4ClearLocation" class="px-2.5 py-1.5 rounded-lg border border-indigo-200 bg-white text-xs text-slate-600 hover:bg-slate-50">
              Clear
            </button>
          </div>
        </div>
        <div id="cpV4MyRepsRow" class="flex flex-wrap gap-2"></div>
      </div>
    `
    : "";

  // Multi-select jurisdiction pills
  const jurPills = activeJurs
    .map((j) => {
      const isSel = selectedJurIds.has(j.ocd_division_id);
      return `
        <button
          type="button"
          data-toggle-jur="${esc(j.ocd_division_id)}"
          class="px-3 py-1.5 rounded-xl text-xs font-semibold border transition cursor-pointer ${
            isSel
              ? "bg-slate-900 text-white border-slate-900 shadow-xs"
              : "bg-white text-slate-700 border-slate-300 hover:border-slate-500"
          }"
        >
          ${isSel ? "✓ " : "+ "}${esc(j.name)}
        </button>
      `;
    })
    .join("");

  // Prompt state when 0 jurisdictions are selected
  if (selectedList.length === 0) {
    root.innerHTML = `
      <section class="space-y-4">
        ${locHtml}
        <div class="bg-white rounded-2xl border border-slate-200 p-5 space-y-4">
          <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <div>
              <h2 class="text-lg font-bold text-slate-900">1. Select One or More Jurisdictions to Explore</h2>
              <p class="text-xs text-slate-600">
                Pick a city, county, or school board below (or enter your address above) to open its Representatives, Agendas, Votes, and Alignment tabs.
              </p>
            </div>
            <button type="button" id="cpV4OpenEngageTop" class="self-start px-3 py-1.5 rounded-lg border border-slate-300 text-xs font-semibold text-slate-700 hover:bg-slate-50">
              📣 How Public Comment Works
            </button>
          </div>
          <div class="flex flex-wrap gap-2">${jurPills}</div>
        </div>
      </section>
    `;
    wireWorkspaceEvents();
    await populateMyRepsRow();
    return;
  }

  // Load payloads for all selected jurisdictions
  const payloads = await Promise.all(selectedList.map((j) => loadJurisdictionPayload(j.ocd_division_id)));

  // Collect clickable representative bubbles across selected jurisdictions
  const repBubbles = [];
  const allEvents = [];
  payloads.forEach((p, idx) => {
    if (!p) return;
    const jMeta = selectedList[idx];
    const reps = p.entities || p.representatives || p.roster || [];
    reps.forEach((r) => {
      const isMy = savedLocation?.matchedJurIds?.includes(jMeta.ocd_division_id);
      repBubbles.push(renderRepBubble(r, jMeta.ocd_division_id, jMeta.name, Boolean(isMy)));
    });
    const evs = p.agenda_items || p.events || [];
    evs.forEach((e) => {
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
      : `<div class="p-6 rounded-2xl bg-white border border-slate-200 text-sm text-slate-600">No extracted roll-call votes yet for the selected jurisdiction(s).</div>`;
  } else {
    // Alignment & Roster Metrics tab
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
              <button type="button" data-open-rep="${esc(pid)}" data-jur-id="${esc(jMeta.ocd_division_id)}" class="font-semibold text-blue-700 hover:underline text-left">
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
      ${locHtml}

      <!-- Selected Jurisdictions Filter Bar -->
      <div class="bg-white rounded-2xl border border-slate-200 p-4 sm:p-5 space-y-3">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div class="text-xs font-bold uppercase tracking-wide text-slate-500">
            Selected Jurisdictions (${selectedList.length}) — Click to Toggle
          </div>
          <div class="flex items-center gap-2">
            <button type="button" id="cpV4OpenEngageTop" class="px-3 py-1 rounded-lg border border-slate-300 text-xs font-semibold text-slate-700 hover:bg-slate-50">
              📣 How Public Comment Works
            </button>
            <button type="button" id="cpV4ClearJurs" class="px-3 py-1 rounded-lg border border-slate-200 text-xs text-slate-600 hover:bg-slate-100">
              Clear Selection
            </button>
          </div>
        </div>
        <div class="flex flex-wrap gap-2">${jurPills}</div>
      </div>

      <!-- Clickable Representative Bubbles (Contact Info Lives Inside Each Rep Profile) -->
      <div class="bg-white rounded-2xl border border-slate-200 p-4 sm:p-5 space-y-3">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h2 class="text-sm font-bold text-slate-900">
            Representatives (${repBubbles.length}) — Click any representative for vote record, comments &amp; contact info
          </h2>
        </div>
        <div class="flex flex-wrap gap-2.5">${repBubbles.join("")}</div>
      </div>

      <!-- Scoped Workflow Tabs (Placed AFTER Jurisdiction Selection) -->
      <div class="border-b border-slate-200 flex flex-wrap gap-4 sm:gap-6 text-sm font-semibold">
        <button type="button" data-ws-tab="before" class="pb-3 border-b-2 ${activeWorkspaceTab === "before" ? "border-blue-600 text-blue-600" : "border-transparent text-slate-500 hover:text-slate-800"}">
          📅 Before the Vote (Date-Grouped Agendas)
        </button>
        <button type="button" data-ws-tab="votes" class="pb-3 border-b-2 ${activeWorkspaceTab === "votes" ? "border-blue-600 text-blue-600" : "border-transparent text-slate-500 hover:text-slate-800"}">
          🗳️ Votes &amp; Radar (${allEvents.length})
        </button>
        <button type="button" data-ws-tab="alignment" class="pb-3 border-b-2 ${activeWorkspaceTab === "alignment" ? "border-blue-600 text-blue-600" : "border-transparent text-slate-500 hover:text-slate-800"}">
          📊 Alignment &amp; Metrics
        </button>
      </div>

      ${tabBodyHtml}
    </section>
  `;

  wireWorkspaceEvents();
  await populateMyRepsRow();
}

async function populateMyRepsRow() {
  const row = document.getElementById("cpV4MyRepsRow");
  if (!row || !savedLocation) return;
  const activeJurs = (dirData.jurisdictions || []).filter((j) =>
    savedLocation.matchedJurIds.includes(j.ocd_division_id)
  );
  const payloads = await Promise.all(activeJurs.map((j) => loadJurisdictionPayload(j.ocd_division_id)));
  const bubbles = [];
  payloads.forEach((p, i) => {
    if (!p) return;
    const j = activeJurs[i];
    (p.entities || p.representatives || p.roster || []).slice(0, 4).forEach((r) => {
      bubbles.push(renderRepBubble(r, j.ocd_division_id, j.name, true));
    });
  });
  row.innerHTML = bubbles.length
    ? bubbles.join("")
    : `<span class="text-xs text-slate-600">Click "Select All My Constituencies" to inspect local boards at this location.</span>`;
  row.querySelectorAll("[data-open-rep]").forEach((btn) => {
    btn.addEventListener("click", () => openRepDetailModal(btn.dataset.jurId, btn.dataset.openRep));
  });
}

function wireWorkspaceEvents() {
  document.querySelectorAll("[data-toggle-jur]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const jid = btn.dataset.toggleJur;
      if (selectedJurIds.has(jid)) selectedJurIds.delete(jid);
      else selectedJurIds.add(jid);
      localStorage.setItem(LS_SELECTED_JURS_KEY, JSON.stringify(Array.from(selectedJurIds)));
      renderScopedWorkspace();
    });
  });

  document.querySelectorAll("[data-ws-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      activeWorkspaceTab = btn.dataset.wsTab;
      renderScopedWorkspace();
    });
  });

  document.querySelectorAll("[data-open-rep]").forEach((btn) => {
    btn.addEventListener("click", () => openRepDetailModal(btn.dataset.jurId, btn.dataset.openRep));
  });

  document.getElementById("cpV4OpenEngageTop")?.addEventListener("click", openConsolidatedEngageModal);
  document.getElementById("cpV4ClearJurs")?.addEventListener("click", () => {
    selectedJurIds.clear();
    localStorage.setItem(LS_SELECTED_JURS_KEY, "[]");
    renderScopedWorkspace();
  });
  document.getElementById("cpV4SelectAllMyJurs")?.addEventListener("click", () => {
    if (!savedLocation) return;
    savedLocation.matchedJurIds.forEach((id) => selectedJurIds.add(id));
    localStorage.setItem(LS_SELECTED_JURS_KEY, JSON.stringify(Array.from(selectedJurIds)));
    renderScopedWorkspace();
  });
  document.getElementById("cpV4ClearLocation")?.addEventListener("click", () => {
    savedLocation = null;
    localStorage.removeItem(LS_SAVED_LOC_KEY);
    renderScopedWorkspace();
  });
}

// ---------------------------------------------------------------------------
// Bootstrap Location Bar + Scoped Workspace
// ---------------------------------------------------------------------------
async function initCivicPulseV4() {
  [dirData, upcomingMeetings, agendaPreviews, earlyWarnings] = await Promise.all([
    fetchJsonSafe("data/directory.json", { jurisdictions: [] }),
    fetchJsonSafe("data/upcoming_meetings.json", []),
    fetchJsonSafe("data/agenda_previews.json", []),
    fetchJsonSafe("data/planning_early_warning.json", []),
  ]);

  try {
    const rawLoc = localStorage.getItem(LS_SAVED_LOC_KEY);
    if (rawLoc) savedLocation = JSON.parse(rawLoc);
    const rawJurs = localStorage.getItem(LS_SELECTED_JURS_KEY);
    if (rawJurs) selectedJurIds = new Set(JSON.parse(rawJurs));
  } catch {
    // ignore storage errors
  }

  // Inject optional Location Bar + Scoped Workspace container into <main>
  const mainEl = document.querySelector("main") || document.body;
  let locBar = document.getElementById("cpV4LocationBar");
  if (!locBar) {
    locBar = document.createElement("section");
    locBar.id = "cpV4LocationBar";
    locBar.className = "bg-white rounded-2xl border border-slate-200 shadow-xs p-4 sm:p-5 mb-6 space-y-3";
    locBar.innerHTML = `
      <div class="flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div>
          <h2 class="text-base font-bold text-slate-900">Find Your Constituencies &amp; Representatives (Optional)</h2>
          <p class="text-xs text-slate-600">
            Enter a street address or city in Colorado to see overlapping city, county, and school districts plus who represents you—or pick jurisdictions directly below.
          </p>
        </div>
        <form id="cpV4LocationForm" class="flex flex-1 max-w-lg gap-2">
          <input
            id="cpV4LocationInput"
            type="text"
            placeholder="e.g., 300 Laporte Ave, Fort Collins or Aurora, CO"
            class="flex-1 rounded-xl border border-slate-300 px-3.5 py-2 text-sm focus:outline-none focus:border-blue-500"
          />
          <button type="submit" class="px-4 py-2 rounded-xl bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 shrink-0">
            Find My Reps
          </button>
        </form>
      </div>
    `;
    mainEl.prepend(locBar);
  }

  let wsRoot = document.getElementById("cpV4WorkspaceRoot");
  if (!wsRoot) {
    wsRoot = document.createElement("div");
    wsRoot.id = "cpV4WorkspaceRoot";
    wsRoot.className = "mb-8";
    locBar.insertAdjacentElement("afterend", wsRoot);
  }

  // Remove legacy floating/jurisdiction-level contact bubbles if present
  document.querySelectorAll("[data-jur-contact-bubbles], #allRepContactChannels").forEach((el) => el.remove());

  document.getElementById("cpV4LocationForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const inp = document.getElementById("cpV4LocationInput");
    const loc = await resolveLocationFromQuery(inp?.value || "");
    if (loc) {
      savedLocation = loc;
      localStorage.setItem(LS_SAVED_LOC_KEY, JSON.stringify(loc));
      loc.matchedJurIds.forEach((id) => selectedJurIds.add(id));
      localStorage.setItem(LS_SELECTED_JURS_KEY, JSON.stringify(Array.from(selectedJurIds)));
      renderScopedWorkspace();
    }
  });

  await renderScopedWorkspace();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initCivicPulseV4);
} else {
  initCivicPulseV4();
}
