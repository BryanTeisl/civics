/**
 * CivicPulse v2 UI Bridge (public/assets/civicpulse_ui_bridge.js)
 *
 * Self-contained companion module wired into public/index.html that powers:
 *  1. Safe portal link visibility (hides placeholder links until real https:// URLs are bound)
 *  2. Freshness / "Data As Of" & stale-data warnings in Jurisdiction Hub
 *  3. Upcoming Meetings & Public Comment Deadlines section + .ics Calendar Export
 *  4. Regional Topic Radar (with quarterly chunked loading, commercial toggle, and CSV export)
 *  5. Provenance ("Structured Portal Data" vs "AI-Extracted from Minutes"), QA Status,
 *     and pre-filled "Report an Error" links on all measures
 *  6. Published Versioned Impact Formula modal + downloadable .md / .json specs
 *  7. RSS & Topic Alerts modal with 1-click copyable feed URLs
 */

const REPO_ISSUES_URL = "https://github.com/BryanTeisl/civics/issues/new";

function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function buildReportErrorUrl(ev) {
  const title = encodeURIComponent(
    `[Data Error] ${ev.jurisdiction_name || ""}: ${(ev.title || "").slice(0, 70)}`
  );
  const body = encodeURIComponent(
    [
      "### Reported Issue",
      `- **Jurisdiction:** ${ev.jurisdiction_name || ev.jurisdiction_id || "Unknown"}`,
      `- **Measure ID:** \`${ev.event_id || "N/A"}\``,
      `- **Meeting Date:** ${ev.meeting_date || "Unknown"}`,
      `- **Title:** ${ev.title || "N/A"}`,
      `- **Capture Method:** ${ev.capture_method || "Unknown"}`,
      `- **QA Status:** ${ev.qa_status || "Unknown"}`,
      `- **Official Source:** ${ev.source_url || "N/A"}`,
      "",
      "### What looks wrong?",
      "(Please describe the vote tally, representative name, or summary correction here.)",
    ].join("\n")
  );
  return `${REPO_ISSUES_URL}?title=${title}&body=${body}&labels=data-quality`;
}

function exportEventsToCsv(events, filename = "civicpulse_measures.csv") {
  const headers = [
    "meeting_date",
    "jurisdiction_name",
    "level",
    "topic",
    "event_type",
    "title",
    "outcome_status",
    "passage_method",
    "tally",
    "impact_score",
    "formula_version",
    "capture_method",
    "qa_status",
    "plain_summary",
    "source_url",
  ];
  const esc = (val) => `"${String(val ?? "").replace(/"/g, '""')}"`;
  const rows = [headers.join(",")].concat(
    (events || []).map((ev) => headers.map((h) => esc(ev[h])).join(","))
  );
  const blob = new Blob([rows.join("\n")], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

function downloadMeetingIcs(meeting) {
  const dt = (meeting.meeting_date || "").replace(/-/g, "");
  if (!dt) return;
  const summary = `${meeting.jurisdiction_name}: ${meeting.title}`.replace(/[,;]/g, " ");
  const desc = `${meeting.public_comment_note || ""}\\nOfficial Agenda: ${meeting.agenda_url || meeting.portal_url || ""}`;
  const ics = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//CivicPulse//Local Government Calendar//EN",
    "BEGIN:VEVENT",
    `DTSTART;VALUE=DATE:${dt}`,
    `SUMMARY:${summary}`,
    `DESCRIPTION:${desc}`,
    `URL:${meeting.agenda_url || meeting.portal_url || ""}`,
    "END:VEVENT",
    "END:VCALENDAR",
  ].join("\r\n");

  const blob = new Blob([ics], { type: "text/calendar;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${dt}_${(meeting.jurisdiction_name || "meeting")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")}.ics`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// 1. Watch Portal Links & Jurisdiction Header to Prevent Dead "#" Links & Show Freshness
// ---------------------------------------------------------------------------
function initPortalAndFreshnessObservers(directoryMap) {
  const portalIds = ["jurPortalLink", "engageOfficialPortalBtn", "unclaimedPortalLink"];
  portalIds.forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    const syncVisibility = () => {
      const href = el.getAttribute("href") || "";
      const isRealExternal =
        href.startsWith("http") && !href.startsWith("https://civics-d03.pages.dev");
      if (isRealExternal) {
        el.classList.remove("hidden");
      } else {
        el.classList.add("hidden");
      }
    };
    syncVisibility();
    new MutationObserver(syncVisibility).observe(el, {
      attributes: true,
      attributeFilter: ["href"],
    });
  });

  // Update freshness badge & jurisdiction RSS link whenever jurSubtitle updates
  const jurSub = document.getElementById("jurSubtitle");
  const freshnessSlot = document.getElementById("jurFreshnessSlot");
  const jurRssLink = document.getElementById("jurRssLink");
  if (jurSub && freshnessSlot) {
    const syncFreshness = () => {
      const divId = (jurSub.textContent || "").trim();
      const jur = directoryMap.get(divId);
      if (!jur) {
        freshnessSlot.innerHTML = "";
        return;
      }
      if (jurRssLink) {
        const slug = divId
          .replace("ocd-division/", "")
          .replace(/\//g, "__")
          .replace(/:/g, "_")
          .replace(/-/g, "_");
        jurRssLink.href = `feeds/jur_${slug}.xml`;
      }
      if (!jur.as_of_date) {
        freshnessSlot.innerHTML = `<span class="px-2.5 py-0.5 rounded-full text-xs font-medium bg-white border border-[#1b3b4e]/20 text-[#142834]/75">Pending ingestion</span>`;
      } else if (jur.is_stale) {
        freshnessSlot.innerHTML = `<span class="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-900 border border-amber-300" title="No new official minutes indexed in ${jur.stale_days} days">⚠ Data as of ${escapeHtml(jur.as_of_date)} (${jur.stale_days}d old)</span>`;
      } else {
        freshnessSlot.innerHTML = `<span class="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-900 border border-emerald-300">Data as of ${escapeHtml(jur.as_of_date)}</span>`;
      }
    };
    syncFreshness();
    new MutationObserver(syncFreshness).observe(jurSub, {
      childList: true,
      characterData: true,
      subtree: true,
    });
  }
}

// ---------------------------------------------------------------------------
// 2. Upcoming Meetings & Public Comment Deadlines Controller
// ---------------------------------------------------------------------------
async function initUpcomingMeetings() {
  const listEl = document.getElementById("upcomingMeetingsList");
  const badgeEl = document.getElementById("upcomingCountBadge");
  const filterEl = document.getElementById("upcomingJurFilter");
  const loadMoreWrap = document.getElementById("upcomingLoadMoreWrap");
  const loadMoreBtn = document.getElementById("upcomingLoadMoreBtn");
  if (!listEl) return;

  let allMeetings = [];
  let visibleLimit = 9;

  try {
    const res = await fetch("data/upcoming_meetings.json");
    if (!res.ok) throw new Error("Failed to load upcoming_meetings.json");
    const data = await res.json();
    allMeetings = data.meetings || [];
  } catch (err) {
    if (badgeEl) badgeEl.textContent = "Schedule unavailable";
    listEl.innerHTML = `<div class="col-span-full text-xs text-[#142834]/70 py-3">Upcoming schedule data is currently refreshing. Check individual jurisdiction hubs above.</div>`;
    return;
  }

  // Populate jurisdiction filter dropdown
  if (filterEl) {
    const seen = new Map();
    allMeetings.forEach((m) => {
      if (m.jurisdiction_id && !seen.has(m.jurisdiction_id)) {
        seen.set(m.jurisdiction_id, m.jurisdiction_name);
      }
    });
    Array.from(seen.entries())
      .sort((a, b) => a[1].localeCompare(b[1]))
      .forEach(([id, name]) => {
        const opt = document.createElement("option");
        opt.value = id;
        opt.textContent = name;
        filterEl.appendChild(opt);
      });
  }

  const todayMs = new Date().setHours(0, 0, 0, 0);

  function render() {
    const selectedJur = filterEl ? filterEl.value : "all";
    const filtered =
      selectedJur === "all"
        ? allMeetings
        : allMeetings.filter((m) => m.jurisdiction_id === selectedJur);

    if (badgeEl) {
      badgeEl.textContent = `${filtered.length} upcoming session${filtered.length === 1 ? "" : "s"}`;
    }

    if (filtered.length === 0) {
      listEl.innerHTML = `<div class="col-span-full text-xs text-[#142834]/75 py-4 text-center">No upcoming meetings posted in the current polling window for this filter.</div>`;
      if (loadMoreWrap) loadMoreWrap.classList.add("hidden");
      return;
    }

    const slice = filtered.slice(0, visibleLimit);
    listEl.innerHTML = slice
      .map((m, idx) => {
        const mDate = new Date(`${m.meeting_date}T00:00:00`);
        const diffDays = Math.round((mDate.getTime() - todayMs) / 86400000);
        const countdown =
          diffDays <= 0
            ? "Today"
            : diffDays === 1
            ? "Tomorrow"
            : `In ${diffDays} days`;
        const href = m.agenda_url || m.portal_url || "";
        return `
          <article class="rounded-xl border border-[#1b3b4e]/15 bg-white p-4 flex flex-col justify-between gap-3">
            <div class="space-y-1.5">
              <div class="flex items-center justify-between gap-2 text-[11px]">
                <span class="font-bold text-[#366a8a] truncate">${escapeHtml(m.jurisdiction_name)}</span>
                <span class="px-2 py-0.5 rounded-full bg-[#ebe0ca] text-[#1b3b4e] font-semibold shrink-0">${escapeHtml(m.meeting_date)} • ${countdown}</span>
              </div>
              <h3 class="text-sm font-bold text-[#1b3b4e] line-clamp-2">${escapeHtml(m.title)}</h3>
              <p class="text-[11px] text-[#142834]/75 leading-relaxed">${escapeHtml(m.public_comment_note)}</p>
            </div>
            <div class="flex items-center justify-between gap-2 pt-2 border-t border-[#1b3b4e]/10 text-xs">
              ${
                href
                  ? `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer" class="font-semibold text-[#366a8a] hover:underline">Open Agenda ↗</a>`
                  : `<span class="text-[#142834]/50">Agenda pending</span>`
              }
              <button type="button" data-ics-idx="${idx}" class="upcoming-ics-btn px-2.5 py-1 rounded-lg border border-[#1b3b4e]/20 bg-[#faf5eb] hover:bg-[#ebe0ca] font-semibold text-[#1b3b4e] transition">
                + Calendar (.ics)
              </button>
            </div>
          </article>
        `;
      })
      .join("");

    listEl.querySelectorAll(".upcoming-ics-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const item = slice[Number(btn.dataset.icsIdx)];
        if (item) downloadMeetingIcs(item);
      });
    });

    if (loadMoreWrap) {
      if (filtered.length > visibleLimit) {
        loadMoreWrap.classList.remove("hidden");
      } else {
        loadMoreWrap.classList.add("hidden");
      }
    }
  }

  if (filterEl) {
    filterEl.addEventListener("change", () => {
      visibleLimit = 9;
      render();
    });
  }
  if (loadMoreBtn) {
    loadMoreBtn.addEventListener("click", () => {
      visibleLimit += 9;
      render();
    });
  }

  render();
}

// ---------------------------------------------------------------------------
// 3. Regional Topic Radar (Chunked Search Loader + Business Filter + CSV Export)
// ---------------------------------------------------------------------------
async function initRegionalRadar() {
  const listEl = document.getElementById("regionalRadarList");
  const statusEl = document.getElementById("radarStatusLabel");
  const jurFilterEl = document.getElementById("radarJurFilter");
  const outcomeFilterEl = document.getElementById("radarOutcomeFilter");
  const bizOnlyEl = document.getElementById("radarBusinessOnlyToggle");
  const exportBtn = document.getElementById("radarExportCsvBtn");
  const pagWrap = document.getElementById("radarPaginationWrap");
  const loadOlderBtn = document.getElementById("radarLoadOlderQuarterBtn");
  if (!listEl) return;

  let loadedEvents = [];
  let remainingChunks = [];
  let totalAvailable = 0;
  let activeTopic = "all";
  let lastFiltered = [];

  async function loadInitial() {
    try {
      const mRes = await fetch("data/search_chunks/manifest.json");
      if (!mRes.ok) throw new Error("No chunk manifest");
      const manifest = await mRes.json();
      totalAvailable = manifest.total_events || 0;
      const firstTwo = (manifest.chunks || []).slice(0, 2);
      remainingChunks = (manifest.chunks || []).slice(2);
      const arrays = await Promise.all(
        firstTwo.map((c) => fetch(c.path).then((r) => (r.ok ? r.json() : [])))
      );
      loadedEvents = arrays.flat();
    } catch (_) {
      const fb = await fetch("data/search_index.json");
      loadedEvents = fb.ok ? await fb.json() : [];
      totalAvailable = loadedEvents.length;
      remainingChunks = [];
    }
    syncJurisdictionDropdown();
    render();
  }

  function syncJurisdictionDropdown() {
    if (!jurFilterEl) return;
    const prev = jurFilterEl.value;
    const seen = new Map();
    loadedEvents.forEach((ev) => {
      if (ev.jurisdiction_id && !seen.has(ev.jurisdiction_id)) {
        seen.set(ev.jurisdiction_id, ev.jurisdiction_name || ev.jurisdiction_id);
      }
    });
    jurFilterEl.innerHTML = `<option value="all">All Jurisdictions</option>`;
    Array.from(seen.entries())
      .sort((a, b) => a[1].localeCompare(b[1]))
      .forEach(([id, name]) => {
        const opt = document.createElement("option");
        opt.value = id;
        opt.textContent = name;
        jurFilterEl.appendChild(opt);
      });
    if (prev && seen.has(prev)) jurFilterEl.value = prev;
  }

  function render() {
    const jurVal = jurFilterEl ? jurFilterEl.value : "all";
    const outVal = outcomeFilterEl ? outcomeFilterEl.value : "all";
    const bizOnly = Boolean(bizOnlyEl && bizOnlyEl.checked);

    lastFiltered = loadedEvents.filter((ev) => {
      if (activeTopic !== "all" && (ev.topic || "General") !== activeTopic) return false;
      if (jurVal !== "all" && ev.jurisdiction_id !== jurVal) return false;
      if (outVal !== "all" && (ev.outcome_status || ev.outcome || "") !== outVal) return false;
      if (bizOnly && !ev.business_relevant) return false;
      return true;
    });

    if (statusEl) {
      statusEl.textContent = `Showing ${Math.min(lastFiltered.length, 25)} of ${lastFiltered.length} matching measures (${loadedEvents.length} of ${totalAvailable} loaded)`;
    }

    if (pagWrap && loadOlderBtn) {
      if (remainingChunks.length > 0) {
        pagWrap.classList.remove("hidden");
        const nextQ = remainingChunks[0];
        loadOlderBtn.textContent = `Load Older Quarter (${nextQ.quarter} • ${nextQ.count} measures)`;
      } else {
        pagWrap.classList.add("hidden");
      }
    }

    if (lastFiltered.length === 0) {
      listEl.innerHTML = `<div class="rounded-xl border border-[#1b3b4e]/15 bg-white p-5 text-center text-xs text-[#142834]/75">No measures match the selected topic and filters in the loaded quarters.</div>`;
      return;
    }

    listEl.innerHTML = lastFiltered
      .slice(0, 25)
      .map((ev) => {
        const outcome = ev.outcome_status || ev.outcome || "Recorded";
        const tally = ev.tally ? ` (${ev.tally})` : "";
        const outcomeBadge =
          outcome === "Passed"
            ? "bg-emerald-50 text-emerald-800 border-emerald-200"
            : outcome === "Failed"
            ? "bg-rose-50 text-rose-800 border-rose-200"
            : "bg-slate-100 text-slate-800 border-slate-200";

        const captureLabel =
          ev.capture_method === "structured_api"
            ? "Structured Portal Data"
            : "AI-Extracted from Minutes";
        const captureBadge =
          ev.capture_method === "structured_api"
            ? "bg-emerald-50 text-emerald-800 border-emerald-200"
            : "bg-amber-50 text-amber-900 border-amber-200";

        const qa = (ev.qa_status || "verified").toLowerCase();
        const qaLabel =
          qa === "verified"
            ? "QA: Verified"
            : qa === "flagged"
            ? "QA: Flagged"
            : "QA: Needs Review";
        const qaBadge =
          qa === "verified"
            ? "bg-slate-100 text-slate-700 border-slate-200"
            : "bg-rose-50 text-rose-800 border-rose-200";

        const reportUrl = buildReportErrorUrl(ev);

        return `
          <article class="rounded-xl border border-[#1b3b4e]/15 bg-white p-4 space-y-2">
            <div class="flex flex-wrap items-center justify-between gap-2 text-xs">
              <div class="flex flex-wrap items-center gap-1.5">
                <span class="font-bold text-[#1b3b4e]">${escapeHtml(ev.jurisdiction_name)}</span>
                <span class="text-[#142834]/50">•</span>
                <span class="text-[#142834]/75">${escapeHtml(ev.meeting_date)}</span>
                <span class="px-2 py-0.5 rounded-full bg-[#ebe0ca] text-[#1b3b4e] font-semibold">${escapeHtml(ev.topic || "General")}</span>
              </div>
              <div class="flex items-center gap-2">
                <span class="px-2.5 py-0.5 rounded-full border font-semibold ${outcomeBadge}">${escapeHtml(outcome + tally)}</span>
                <span class="px-2.5 py-0.5 rounded-full bg-[#1b3b4e] text-[#faf5eb] font-bold">Impact ${escapeHtml(ev.impact_score ?? 0)}/100</span>
              </div>
            </div>
            <h3 class="text-sm font-bold text-[#142834]">${escapeHtml(ev.title)}</h3>
            ${ev.plain_summary ? `<p class="text-xs text-[#142834]/80 leading-relaxed">${escapeHtml(ev.plain_summary)}</p>` : ""}
            <div class="flex flex-wrap items-center gap-2 pt-1.5 border-t border-[#1b3b4e]/10 text-[11px]">
              <span class="px-2 py-0.5 rounded-full border font-medium ${captureBadge}">${captureLabel}</span>
              <span class="px-2 py-0.5 rounded-full border font-medium ${qaBadge}">${qaLabel}</span>
              ${ev.passage_method ? `<span class="px-2 py-0.5 rounded-full border border-slate-200 bg-slate-50 text-slate-700">${escapeHtml(ev.passage_method)}</span>` : ""}
              ${
                ev.source_url
                  ? `<a href="${escapeHtml(ev.source_url)}" target="_blank" rel="noopener noreferrer" class="text-[#366a8a] font-semibold hover:underline">Official Record ↗</a>`
                  : ""
              }
              <a href="${reportUrl}" target="_blank" rel="noopener noreferrer" class="ml-auto text-[#142834]/65 hover:text-rose-700 underline">
                Report an Error ↗
              </a>
            </div>
          </article>
        `;
      })
      .join("");
  }

  document.querySelectorAll(".radar-topic-pill").forEach((pill) => {
    pill.addEventListener("click", () => {
      activeTopic = pill.dataset.topic || "all";
      document.querySelectorAll(".radar-topic-pill").forEach((p) => {
        const isSel = p === pill;
        p.className = isSel
          ? "radar-topic-pill px-3 py-1 rounded-full text-xs font-semibold bg-[#1b3b4e] text-[#faf5eb]"
          : "radar-topic-pill px-3 py-1 rounded-full text-xs font-semibold bg-white border border-[#1b3b4e]/20 text-[#1b3b4e] hover:bg-[#ebe0ca]";
      });
      render();
    });
  });

  if (jurFilterEl) jurFilterEl.addEventListener("change", render);
  if (outcomeFilterEl) outcomeFilterEl.addEventListener("change", render);
  if (bizOnlyEl) bizOnlyEl.addEventListener("change", render);

  if (exportBtn) {
    exportBtn.addEventListener("click", () => {
      const slug = activeTopic === "all" ? "all_topics" : activeTopic.toLowerCase().replace(/[^a-z0-9]+/g, "_");
      exportEventsToCsv(lastFiltered, `civicpulse_${slug}.csv`);
    });
  }

  if (loadOlderBtn) {
    loadOlderBtn.addEventListener("click", async () => {
      if (remainingChunks.length === 0) return;
      const next = remainingChunks.shift();
      loadOlderBtn.disabled = true;
      loadOlderBtn.textContent = `Loading ${next.quarter}...`;
      try {
        const r = await fetch(next.path);
        if (r.ok) {
          const more = await r.json();
          loadedEvents = loadedEvents.concat(more);
          syncJurisdictionDropdown();
        }
      } finally {
        loadOlderBtn.disabled = false;
        render();
      }
    });
  }

  // Also wire Jurisdiction Hub's "Export CSV" button to export that jurisdiction's loaded measures
  const jurCsvBtn = document.getElementById("jurExportCsvBtn");
  if (jurCsvBtn) {
    jurCsvBtn.addEventListener("click", () => {
      const divId = (document.getElementById("jurSubtitle")?.textContent || "").trim();
      const rows = loadedEvents.filter((e) => e.jurisdiction_id === divId);
      const slug = (divId.split(":").pop() || "jurisdiction").replace(/[^a-z0-9]+/gi, "_");
      exportEventsToCsv(rows.length ? rows : loadedEvents, `civicpulse_${slug}.csv`);
    });
  }

  await loadInitial();
}

// ---------------------------------------------------------------------------
// 4. Published Versioned Scoring Formula Modal
// ---------------------------------------------------------------------------
async function initScoringFormulaModal() {
  const panel = document.getElementById("scoringMethodologyPanel");
  if (!panel) return;
  try {
    const res = await fetch("data/scoring_methodology.json");
    if (!res.ok) throw new Error("Missing scoring_methodology.json");
    const spec = await res.json();

    const storageKey = "civicpulse_seen_formula_hash";
    const prevHash = localStorage.getItem(storageKey);
    const hasChanged = Boolean(prevHash && prevHash !== spec.formula_hash);
    localStorage.setItem(storageKey, spec.formula_hash);

    const rows = (spec.changelog || [])
      .map(
        (c) => `
        <tr class="border-t border-[#1b3b4e]/15">
          <td class="py-2 pr-3 font-mono font-semibold text-[#1b3b4e]">v${escapeHtml(c.version)}</td>
          <td class="py-2 pr-3 text-[#142834]/70 whitespace-nowrap">${escapeHtml(c.date)}</td>
          <td class="py-2 text-[#142834]/90">${escapeHtml(c.summary)}</td>
        </tr>`
      )
      .join("");

    const examples = (spec.examples || [])
      .map(
        (ex) => `
        <div class="rounded-xl border border-[#1b3b4e]/15 bg-white p-3 flex items-center justify-between gap-3">
          <div>
            <div class="font-semibold text-[#1b3b4e]">${escapeHtml(ex.label)}</div>
            <div class="text-[11px] text-[#142834]/75 mt-0.5">${escapeHtml(ex.result.plain_english)}</div>
          </div>
          <span class="px-2.5 py-1 rounded-full bg-[#1b3b4e] text-[#faf5eb] font-bold shrink-0">${ex.result.score}/100</span>
        </div>`
      )
      .join("");

    panel.innerHTML = `
      <div class="space-y-4">
        <div class="flex flex-wrap items-center justify-between gap-2 bg-white p-3.5 rounded-xl border border-[#1b3b4e]/15">
          <div>
            <div class="font-bold text-[#1b3b4e]">Active Version: v${escapeHtml(spec.formula_version)}</div>
            <div class="text-[11px] text-[#142834]/70">Effective ${escapeHtml(spec.effective_date)} • SHA-256 Checksum: <code class="font-mono">${escapeHtml(spec.formula_hash)}</code></div>
          </div>
          <div class="flex flex-wrap gap-2">
            ${hasChanged ? `<span class="px-2.5 py-1 rounded-full font-semibold bg-amber-100 text-amber-900">Formula updated since last visit</span>` : ""}
            <a href="${escapeHtml(spec.downloads.markdown)}" download class="px-3 py-1.5 rounded-xl bg-[#1b3b4e] text-[#faf5eb] font-semibold hover:bg-[#366a8a] transition">
              ⬇ Download Formula (.md)
            </a>
            <a href="${escapeHtml(spec.downloads.json)}" download class="px-3 py-1.5 rounded-xl border border-[#1b3b4e]/25 bg-[#faf5eb] text-[#1b3b4e] font-semibold hover:bg-[#ebe0ca] transition">
              ⬇ Spec (.json)
            </a>
          </div>
        </div>

        <p class="leading-relaxed text-[#142834]/90">${escapeHtml(spec.plain_english_summary)}</p>

        <div class="rounded-xl bg-white border border-[#1b3b4e]/20 p-3 font-mono text-[11px] text-[#1b3b4e] overflow-x-auto">
          ${escapeHtml(spec.equation)}
        </div>

        <div class="space-y-2">
          <div class="font-bold text-[#1b3b4e]">Worked Examples</div>
          ${examples}
        </div>

        <div class="space-y-2">
          <div class="font-bold text-[#1b3b4e]">Formula Revision History (Change Detection Log)</div>
          <div class="rounded-xl border border-[#1b3b4e]/15 bg-white px-3 overflow-x-auto">
            <table class="w-full text-left border-collapse">
              <tbody>${rows}</tbody>
            </table>
          </div>
        </div>
      </div>
    `;
  } catch (_) {
    panel.innerHTML = `<p class="text-xs text-[#142834]/75">Download the formula directly: <a href="docs/civicpulse_impact_formula.md" class="underline font-semibold text-[#366a8a]">civicpulse_impact_formula.md</a></p>`;
  }
}

// ---------------------------------------------------------------------------
// 5. RSS & Topic Alerts Modal
// ---------------------------------------------------------------------------
async function initRssAlertsModal() {
  const panel = document.getElementById("rssFeedsDirectoryPanel");
  if (!panel) return;
  const baseUrl = window.location.origin;

  try {
    const res = await fetch("data/feeds_index.json");
    if (!res.ok) throw new Error("Missing feeds_index.json");
    const feeds = await res.json();

    const topicCards = Object.entries(feeds.topics || {})
      .map(([topic, meta]) => {
        const fullUrl = `${baseUrl}/${meta.url}`;
        return `
          <div class="rounded-xl border border-[#1b3b4e]/15 bg-white p-3 flex items-center justify-between gap-2">
            <div>
              <div class="font-bold text-[#1b3b4e]">${escapeHtml(topic)}</div>
              <div class="text-[11px] text-[#142834]/70">${meta.item_count} measures tracked</div>
            </div>
            <div class="flex items-center gap-1.5">
              <button type="button" data-copy-url="${escapeHtml(fullUrl)}" class="copy-rss-btn px-2.5 py-1 rounded-lg border border-[#1b3b4e]/20 bg-[#faf5eb] hover:bg-[#ebe0ca] font-semibold text-[#1b3b4e]">Copy URL</button>
              <a href="${escapeHtml(meta.url)}" target="_blank" rel="noopener noreferrer" class="px-2.5 py-1 rounded-lg bg-[#366a8a] text-[#faf5eb] font-semibold">XML ↗</a>
            </div>
          </div>`;
      })
      .join("");

    const jurCards = Object.values(feeds.jurisdictions || {})
      .map((meta) => {
        const fullUrl = `${baseUrl}/${meta.url}`;
        return `
          <div class="rounded-xl border border-[#1b3b4e]/15 bg-white p-3 flex items-center justify-between gap-2">
            <div>
              <div class="font-bold text-[#1b3b4e]">${escapeHtml(meta.name)}</div>
              <div class="text-[11px] text-[#142834]/70">${meta.item_count} measures tracked</div>
            </div>
            <div class="flex items-center gap-1.5">
              <button type="button" data-copy-url="${escapeHtml(fullUrl)}" class="copy-rss-btn px-2.5 py-1 rounded-lg border border-[#1b3b4e]/20 bg-[#faf5eb] hover:bg-[#ebe0ca] font-semibold text-[#1b3b4e]">Copy URL</button>
              <a href="${escapeHtml(meta.url)}" target="_blank" rel="noopener noreferrer" class="px-2.5 py-1 rounded-lg bg-[#366a8a] text-[#faf5eb] font-semibold">XML ↗</a>
            </div>
          </div>`;
      })
      .join("");

    panel.innerHTML = `
      <div class="rounded-xl border border-[#c67749]/40 bg-white p-3.5 flex flex-wrap items-center justify-between gap-2">
        <div>
          <div class="font-bold text-[#1b3b4e]">Master Feed — All Colorado Jurisdictions</div>
          <div class="text-[11px] text-[#142834]/70 font-mono">${escapeHtml(baseUrl)}/feeds/all.xml</div>
        </div>
        <div class="flex gap-2">
          <button type="button" data-copy-url="${escapeHtml(baseUrl)}/feeds/all.xml" class="copy-rss-btn px-3 py-1.5 rounded-xl border border-[#1b3b4e]/20 bg-[#faf5eb] font-semibold text-[#1b3b4e]">Copy Feed URL</button>
          <a href="feeds/all.xml" target="_blank" rel="noopener noreferrer" class="px-3 py-1.5 rounded-xl bg-[#c67749] text-white font-semibold">Open XML ↗</a>
        </div>
      </div>

      <div class="space-y-2">
        <div class="font-bold text-[#1b3b4e]">Subscribe by Topic (Resident &amp; Business Alerts)</div>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">${topicCards}</div>
      </div>

      <div class="space-y-2">
        <div class="font-bold text-[#1b3b4e]">Subscribe by City / Jurisdiction</div>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">${jurCards}</div>
      </div>
    `;

    panel.querySelectorAll(".copy-rss-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const url = btn.dataset.copyUrl || "";
        try {
          await navigator.clipboard.writeText(url);
          const orig = btn.textContent;
          btn.textContent = "Copied!";
          setTimeout(() => {
            btn.textContent = orig;
          }, 1500);
        } catch (_) {
          window.prompt("Copy this RSS feed URL:", url);
        }
      });
    });
  } catch (_) {
    panel.innerHTML = `<p class="text-xs">Master RSS feed: <a href="feeds/all.xml" class="underline font-semibold text-[#366a8a]">feeds/all.xml</a></p>`;
  }
}

// ---------------------------------------------------------------------------
// 6. Smooth Section Navigation & Modal Wiring
// ---------------------------------------------------------------------------
function wireSectionNavAndModals() {
  const scrollToHomeSection = (sectionId) => {
    const homeView = document.getElementById("homeView");
    if (homeView && homeView.classList.contains("hidden")) {
      document.getElementById("brandHomeBtn")?.click();
    }
    setTimeout(() => {
      document.getElementById(sectionId)?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 60);
  };

  document.getElementById("navUpcomingBtn")?.addEventListener("click", () => scrollToHomeSection("upcomingMeetingsSection"));
  document.getElementById("jumpUpcomingCardBtn")?.addEventListener("click", () => scrollToHomeSection("upcomingMeetingsSection"));
  document.getElementById("navRadarBtn")?.addEventListener("click", () => scrollToHomeSection("regionalRadarSection"));
  document.getElementById("jumpRadarCardBtn")?.addEventListener("click", () => scrollToHomeSection("regionalRadarSection"));

  // Ensure any newly added [data-open-modal] / [data-close-modal] buttons work reliably
  document.querySelectorAll("[data-open-modal]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = document.getElementById(btn.dataset.openModal);
      if (target) target.classList.remove("hidden");
    });
  });
  document.querySelectorAll("[data-close-modal]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = document.getElementById(btn.dataset.closeModal);
      if (target) target.classList.add("hidden");
    });
  });
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
(async function bootCivicPulseBridge() {
  wireSectionNavAndModals();

  const directoryMap = new Map();
  try {
    const res = await fetch("data/directory.json");
    if (res.ok) {
      const payload = await res.json();
      const jurs = Array.isArray(payload) ? payload : payload.jurisdictions || [];
      jurs.forEach((j) => {
        const id = j.ocd_division_id || j.jurisdiction_id;
        if (id) directoryMap.set(id, j);
      });
    }
  } catch (_) {}

  initPortalAndFreshnessObservers(directoryMap);
  await Promise.all([
    initUpcomingMeetings(),
    initRegionalRadar(),
    initScoringFormulaModal(),
    initRssAlertsModal(),
  ]);
})();
