/**
 * CivicPulse v2 UX, Trust & Business Intelligence Enhancements
 * Drop-in companion module for public/index.html.
 *
 * Adds:
 *  1. Automatic fix for $15 / $50 Support mailto links (prevents $5 copy bug)
 *  2. Transparent, Versioned Formula Modal + Download (.md / .json) + Change Detector
 *  3. Capture Provenance ("Structured API" vs "AI Minutes"), QA Status, Stale Warnings & Report Error
 *  4. Upcoming Meetings & Public Comment Deadlines Drawer + .ics Calendar Export
 *  5. Business "Regional Radar" Topic Filter + 1-Click Client-Side CSV Export + RSS Feed Links
 *  6. Quarterly Chunked Search Loader (loads search_chunks/manifest.json progressively)
 */

export const CivicPulseEnhancements = (() => {
  const REPO_ISSUES_URL = "https://github.com/BryanTeisl/civics/issues/new";
  const SUPPORT_EMAIL = "bryanateisl@gmail.com";

  /** 1. Fix any $15 / $50 mailto links that accidentally carried $5 text */
  function fixSupportLinks() {
    document.querySelectorAll('a[href^="mailto:"]').forEach((a) => {
      const label = (a.textContent || "").trim();
      const match = label.match(/\$(\d+)/);
      if (match && a.href.includes("CivicPulse")) {
        const amt = match[1];
        const subject = encodeURIComponent(`CivicPulse Individual Support ($${amt})`);
        const body = encodeURIComponent(
          `Hi Bryan,\n\nI'd like to make a voluntary $${amt} contribution to support CivicPulse. Please send me the payment link!`
        );
        a.href = `mailto:${SUPPORT_EMAIL}?subject=${subject}&body=${body}`;
      }
    });
  }

  /** 2. Build a pre-filled "Report an Error" URL (GitHub Issue with mailto fallback) */
  function buildReportErrorUrl(ev) {
    const title = encodeURIComponent(`[Data Error] ${ev.jurisdiction_name || ""}: ${(ev.title || "").slice(0, 70)}`);
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
        "(Please describe the vote tally, name, or summary correction here.)",
      ].join("\n")
    );
    return `${REPO_ISSUES_URL}?title=${title}&body=${body}&labels=data-quality`;
  }

  /** 3. Render Trust & Provenance Badges for any measure object */
  function renderMeasureTrustBadges(ev) {
    const captureLabel =
      ev.capture_method === "structured_api"
        ? "Structured Portal Data"
        : ev.capture_method === "agenda_preview"
        ? "Upcoming Agenda Preview"
        : "AI-Extracted from Minutes";

    const captureClass =
      ev.capture_method === "structured_api"
        ? "bg-emerald-50 text-emerald-800 border-emerald-200"
        : "bg-amber-50 text-amber-800 border-amber-200";

    const qaStatus = (ev.qa_status || "verified").toLowerCase();
    const qaLabel =
      qaStatus === "verified"
        ? "QA: Verified"
        : qaStatus === "flagged"
        ? "QA: Flagged for Review"
        : "QA: Needs Verification";
    const qaClass =
      qaStatus === "verified"
        ? "bg-slate-100 text-slate-700 border-slate-200"
        : "bg-rose-50 text-rose-800 border-rose-200";

    const reportUrl = buildReportErrorUrl(ev);

    return `
      <div class="flex flex-wrap items-center gap-2 text-xs mt-2">
        <span class="px-2 py-0.5 rounded-full border font-medium ${captureClass}">${captureLabel}</span>
        <span class="px-2 py-0.5 rounded-full border font-medium ${qaClass}">${qaLabel}</span>
        ${ev.formula_version ? `<span class="px-2 py-0.5 rounded-full border bg-blue-50 text-blue-800 border-blue-200">Formula v${ev.formula_version}</span>` : ""}
        <a href="${reportUrl}" target="_blank" rel="noopener noreferrer"
           class="text-slate-500 hover:text-rose-700 underline ml-auto">
          Report an Error ↗
        </a>
      </div>
    `;
  }

  /** 4. Render Freshness / Stale Data Warning for a Jurisdiction */
  function renderFreshnessBadge(jur) {
    if (!jur || !jur.as_of_date) {
      return `<span class="px-2.5 py-0.5 rounded-full text-xs bg-slate-100 text-slate-600 border border-slate-200">Pending ingestion</span>`;
    }
    if (jur.is_stale) {
      return `<span class="px-2.5 py-0.5 rounded-full text-xs bg-amber-50 text-amber-800 border border-amber-300" title="No new official minutes indexed in ${jur.stale_days} days">⚠ Data as of ${jur.as_of_date} (${jur.stale_days}d old)</span>`;
    }
    return `<span class="px-2.5 py-0.5 rounded-full text-xs bg-emerald-50 text-emerald-800 border border-emerald-200">Data as of ${jur.as_of_date}</span>`;
  }

  /** 5. Client-Side CSV Export for Businesses, Attorneys & Journalists */
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

  /** 6. Client-Side .ics Calendar File Export for Upcoming Public Hearings */
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
    link.download = `${dt}_${(meeting.jurisdiction_name || "meeting").toLowerCase().replace(/[^a-z0-9]+/g, "_")}.ics`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }

  /** 7. Load & Render Published Versioned Scoring Formula + Download Buttons */
  async function loadScoringMethodology(containerEl) {
    if (!containerEl) return null;
    const res = await fetch("data/scoring_methodology.json");
    if (!res.ok) return null;
    const spec = await res.json();

    // Detect if formula changed since the user's last visit
    const storageKey = "civicpulse_seen_formula_hash";
    const lastSeenHash = localStorage.getItem(storageKey);
    const changed = Boolean(lastSeenHash && lastSeenHash !== spec.formula_hash);
    localStorage.setItem(storageKey, spec.formula_hash);

    const changelogRows = (spec.changelog || [])
      .map(
        (c) => `
        <tr class="border-t border-slate-200">
          <td class="py-1.5 pr-3 font-mono text-xs">v${c.version}</td>
          <td class="py-1.5 pr-3 text-xs text-slate-500 whitespace-nowrap">${c.date}</td>
          <td class="py-1.5 text-xs text-slate-700">${c.summary}</td>
        </tr>`
      )
      .join("");

    containerEl.innerHTML = `
      <div class="rounded-2xl border border-slate-200 bg-white p-5 space-y-4">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 class="text-lg font-bold text-slate-900">How Vote Impactfulness (0–100) Works</h3>
            <p class="text-xs text-slate-500">
              Formula <strong>v${spec.formula_version}</strong> • Effective ${spec.effective_date} •
              Checksum <code class="font-mono">${spec.formula_hash}</code>
            </p>
          </div>
          <div class="flex flex-wrap gap-2">
            ${changed ? `<span class="px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-100 text-amber-900">Updated since last visit</span>` : ""}
            <a href="${spec.downloads.markdown}" download
               class="px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-900 text-white hover:bg-slate-700">
              Download Formula (.md)
            </a>
            <a href="${spec.downloads.json}" download
               class="px-3 py-1.5 rounded-lg text-xs font-semibold border border-slate-300 text-slate-800 hover:bg-slate-50">
              Download Spec (.json)
            </a>
          </div>
        </div>
        <p class="text-sm text-slate-700 leading-relaxed">${spec.plain_english_summary}</p>
        <div class="rounded-xl bg-slate-50 border border-slate-200 p-3 font-mono text-xs text-slate-800 overflow-x-auto">
          ${spec.equation}
        </div>
        <div>
          <h4 class="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2">Formula Revision History</h4>
          <table class="w-full text-left border-collapse">
            <tbody>${changelogRows}</tbody>
          </table>
        </div>
      </div>
    `;
    return spec;
  }

  /** 8. Progressive Quarterly Search Loader (prevents loading 600KB+ JSON upfront) */
  async function loadSearchChunked({ quartersToLoad = 2 } = {}) {
    const manifestRes = await fetch("data/search_chunks/manifest.json");
    if (!manifestRes.ok) {
      // Fallback to monolithic search_index.json
      const fallback = await fetch("data/search_index.json");
      return { events: fallback.ok ? await fallback.json() : [], hasMore: false, remainingChunks: [] };
    }
    const manifest = await manifestRes.json();
    const initial = manifest.chunks.slice(0, quartersToLoad);
    const remaining = manifest.chunks.slice(quartersToLoad);
    const loadedArrays = await Promise.all(
      initial.map((c) => fetch(c.path).then((r) => (r.ok ? r.json() : [])))
    );
    return {
      events: loadedArrays.flat(),
      hasMore: remaining.length > 0,
      remainingChunks: remaining,
      totalEvents: manifest.total_events,
    };
  }

  return {
    fixSupportLinks,
    buildReportErrorUrl,
    renderMeasureTrustBadges,
    renderFreshnessBadge,
    exportEventsToCsv,
    downloadMeetingIcs,
    loadScoringMethodology,
    loadSearchChunked,
  };
})();
