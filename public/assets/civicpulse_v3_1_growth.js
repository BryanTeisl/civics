/**
 * CivicPulse v3.1 Early Warning & Growth UI (public/assets/civicpulse_v3_1_growth.js)
 *
 * Mounts the metadata-only "Planning & Zoning Early Warning" section on Home so
 * homeowners, developers, and contractors see rezonings, site plans, and land-use
 * hearings weeks before they reach City Council.
 */

function escHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function mountPlanningEarlyWarning() {
  const anchor = document.getElementById("upcomingMeetingsSection");
  if (!anchor || document.getElementById("v31PlanningEarlyWarning")) return;

  let payload = null;
  try {
    const res = await fetch("data/planning_early_warning.json");
    if (!res.ok) return;
    payload = await res.json();
  } catch (_) {
    return;
  }

  const hearings = payload.hearings || [];
  const sec = document.createElement("section");
  sec.id = "v31PlanningEarlyWarning";
  sec.className = "bg-[#faf5eb] rounded-2xl border border-[#1b3b4e]/20 p-5 sm:p-6 space-y-4 shadow-sm";

  const seenJurs = new Map();
  hearings.forEach((h) => {
    if (h.jurisdiction_id && !seenJurs.has(h.jurisdiction_id)) {
      seenJurs.set(h.jurisdiction_id, h.jurisdiction_name);
    }
  });
  const jurOpts = [`<option value="all">All Jurisdictions (${hearings.length})</option>`]
    .concat(
      Array.from(seenJurs.entries())
        .sort((a, b) => a[1].localeCompare(b[1]))
        .map(([id, name]) => `<option value="${escHtml(id)}">${escHtml(name)}</option>`)
    )
    .join("");

  sec.innerHTML = `
    <div class="flex flex-col md:flex-row md:items-center justify-between gap-3">
      <div>
        <span class="text-[11px] font-bold uppercase tracking-wider text-[#c67749]">Early-Stage Land Use &amp; Development Signals</span>
        <h2 class="text-lg font-bold text-[#1b3b4e]">🏗️ Planning &amp; Zoning Commission Early Warning</h2>
        <p class="text-xs text-[#142834]/75 mt-0.5">Track rezonings, subdivisions, and Board of Adjustment hearings weeks before they reach City Council.</p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <select id="v31PlanningJurFilter" aria-label="Filter planning hearings by city" class="rounded-xl border border-[#1b3b4e]/25 bg-white px-3 py-1.5 text-xs font-medium text-[#1b3b4e]">
          ${jurOpts}
        </select>
        <span class="text-xs font-semibold px-2.5 py-1 rounded-full bg-[#ebe0ca] text-[#1b3b4e]">
          ${payload.upcoming_count || 0} upcoming • ${payload.total_count || 0} recent
        </span>
      </div>
    </div>
    <div id="v31PlanningGrid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3"></div>
  `;

  (document.getElementById("v32AgendaPreviewsSection") || anchor).insertAdjacentElement("afterend", sec);

  const sel = sec.querySelector("#v31PlanningJurFilter");
  const grid = sec.querySelector("#v31PlanningGrid");

  const render = () => {
    const jid = sel.value;
    const rows = (jid === "all" ? hearings : hearings.filter((h) => h.jurisdiction_id === jid)).slice(0, 12);
    if (!rows.length) {
      grid.innerHTML = `<div class="col-span-full text-xs text-[#142834]/70 py-4 text-center">No Planning &amp; Zoning Commission hearings indexed in the last ${payload.lookback_days || 30} days for this filter.</div>`;
      return;
    }
    grid.innerHTML = rows
      .map(
        (h) => `
        <article class="rounded-xl border border-[#1b3b4e]/15 bg-white p-3.5 flex flex-col justify-between gap-2">
          <div class="space-y-1">
            <div class="flex items-center justify-between gap-2 text-[11px]">
              <span class="font-bold text-[#366a8a] truncate">${escHtml(h.jurisdiction_name)}</span>
              <span class="px-2 py-0.5 rounded-full font-semibold shrink-0 ${
                h.is_upcoming ? "bg-amber-100 text-amber-900" : "bg-slate-100 text-slate-700"
              }">${escHtml(h.meeting_date)} ${h.is_upcoming ? "• Upcoming" : ""}</span>
            </div>
            <h3 class="text-xs sm:text-sm font-bold text-[#1b3b4e] line-clamp-2">${escHtml(h.title)}</h3>
          </div>
          <div class="flex items-center justify-between pt-2 border-t border-[#1b3b4e]/10 text-[11px]">
            <span class="uppercase text-[#142834]/60 font-mono">${escHtml(h.platform || "portal")}</span>
            ${
              h.agenda_url
                ? `<a href="${escHtml(h.agenda_url)}" target="_blank" rel="noopener noreferrer" class="font-semibold text-[#c67749] hover:underline">View Hearing Packet ↗</a>`
                : `<span class="text-[#142834]/50">Link pending</span>`
            }
          </div>
        </article>`
      )
      .join("");
  };

  sel.addEventListener("change", render);
  render();
}

mountPlanningEarlyWarning();
