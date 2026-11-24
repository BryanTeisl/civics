import { escapeHtml, isPassedOutcome, normalizePortalUrl } from "../utils.js";

export function renderJurisdictionHub(state, { onOpenRep, onOpenBill }) {
  const jurData = state.currentJurData;
  const j = jurData.jurisdiction;
  const divId = j.ocd_division_id;
  const portalHref = normalizePortalUrl(j.portal_url);

  document.getElementById("jurLevelBadge").textContent = (j.level || "municipality").replace("_", " ");
  document.getElementById("jurDocsSinceBadge").textContent = `Docs since ${j.docs_since || "2026"}`;
  document.getElementById("jurTitle").textContent = j.name;
  document.getElementById("jurSubtitle").textContent = divId;
  document.getElementById("jurPortalLink").href = portalHref;

  renderEngagementGuide(divId, jurData, state.engagementGuides);
  renderLifecycles(divId, state.billLifecycles, onOpenBill);
  renderEntities(divId, jurData.entities || [], onOpenRep);
  renderEvents(divId, jurData.events || [], onOpenBill);
}

function renderEngagementGuide(divId, jurData, engagementGuides) {
  const guide = (engagementGuides.guides || {})[divId];
  const portalHref = normalizePortalUrl(guide?.portal_url || jurData.jurisdiction.portal_url);
  document.getElementById("engageOfficialPortalBtn").href = portalHref;

  const checklist = guide?.checklist || [
    "Review the posted meeting agenda before the session to identify ordinances, budgets, or zoning items affecting your neighborhood.",
    "Check the official portal for public comment sign-up rules, speaker time limits, or written correspondence deadlines.",
    "Share concise, factual points with your district and at-large representatives.",
    "Follow up after the vote to check the final roll call and implementation timeline.",
  ];
  document.getElementById("engageChecklist").innerHTML = checklist.map(s => `<li>${escapeHtml(s)}</li>`).join("");

  const meetingsBox = document.getElementById("engageMeetingsList");
  const upcoming = guide?.upcoming_meetings || [];
  const recent = guide?.recent_agendas_and_docs || [];

  if (upcoming.length) {
    meetingsBox.innerHTML = upcoming.map(m => `
      <div class="p-2.5 rounded-lg bg-[#ebe0ca] border border-[#5c7258]/30 min-w-0 overflow-hidden">
        <div class="font-bold text-[#1b3b4e]">Upcoming: ${escapeHtml(m.date)}</div>
        <a href="${escapeHtml(normalizePortalUrl(m.portal_url || portalHref))}" target="_blank" rel="noopener noreferrer" class="text-[#142834] hover:text-[#366a8a] font-medium truncate block mt-0.5">${escapeHtml(m.title)} ↗</a>
      </div>
    `).join("");
  } else if (recent.length) {
    meetingsBox.innerHTML = recent.slice(0, 4).map(d => {
      const rawTitle = (d.title || "").trim();
      const friendly = (/^https?:\/\//i.test(rawTitle) || rawTitle.includes("GetMeetingFileStream"))
        ? `${escapeHtml(d.meeting_date || "Meeting")} Council Agenda & Packet`
        : escapeHtml(rawTitle);
      const safeUrl = normalizePortalUrl(d.source_url || portalHref);
      return `
        <div class="p-2.5 rounded-lg bg-[#ebe0ca] border border-[#1b3b4e]/15 min-w-0 overflow-hidden">
          <div class="text-[11px] font-semibold text-[#142834]/70">${escapeHtml(d.meeting_date || "")} • ${escapeHtml((d.doc_type || "agenda").toUpperCase())}</div>
          <a href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener noreferrer" class="text-[#1b3b4e] hover:text-[#366a8a] font-medium truncate block mt-0.5" title="${friendly}">${friendly} ↗</a>
        </div>
      `;
    }).join("");
  } else {
    meetingsBox.innerHTML = `<div class="text-[#142834]/70">Check the <a href="${escapeHtml(portalHref)}" target="_blank" rel="noopener noreferrer" class="text-[#366a8a] underline">official portal</a> for upcoming meeting dates and public comment rules.</div>`;
  }

  const contactsBox = document.getElementById("engageContactsList");
  const reps = guide?.representatives || jurData.entities || [];
  contactsBox.innerHTML = reps.length
    ? reps.map(r => `
        <div class="p-2 rounded-lg bg-[#ebe0ca]/80 border border-[#1b3b4e]/15 flex items-center justify-between gap-2">
          <div>
            <div class="font-bold text-[#1b3b4e]">${escapeHtml(r.name)}</div>
            <div class="text-[11px] text-[#142834]/70">${escapeHtml(r.district || r.role || "")}</div>
          </div>
          <div class="flex items-center gap-2 text-[11px] font-semibold">
            ${r.email ? `<a href="mailto:${escapeHtml(r.email)}" class="text-[#366a8a] hover:underline">Email</a>` : ""}
            ${r.phone ? `<a href="tel:${escapeHtml(r.phone)}" class="text-[#142834] hover:underline">Call</a>` : ""}
          </div>
        </div>
      `).join("")
    : `<div class="text-[#142834]/70">Representative directory pending ingestion.</div>`;
}

function renderLifecycles(divId, billLifecycles, onOpenBill) {
  const chains = (billLifecycles.by_jurisdiction || {})[divId] || [];
  const card = document.getElementById("jurLifecyclesCard");
  if (!chains.length) {
    card.classList.add("hidden");
    return;
  }
  card.classList.remove("hidden");
  document.getElementById("jurLifecyclesCount").textContent = `${chains.length} multi-stage item(s)`;
  const list = document.getElementById("jurLifecyclesList");
  list.innerHTML = chains.map(ch => `
    <div class="rounded-xl border border-[#366a8a]/25 bg-[#ebe0ca]/70 p-4 space-y-2.5">
      <div class="flex items-center justify-between gap-2">
        <span class="text-[11px] font-bold uppercase text-[#366a8a]">${escapeHtml(ch.match_basis)}</span>
        <span class="text-[11px] text-[#142834]/70">${escapeHtml(ch.first_date)} → ${escapeHtml(ch.latest_date)}</span>
      </div>
      <div class="space-y-1.5 border-l-2 border-[#366a8a]/50 pl-3">
        ${(ch.stages || []).map(st => `
          <button data-event-id="${escapeHtml(st.event_id)}" class="lifecycle-stage-btn w-full text-left block hover:bg-white rounded p-1.5 transition">
            <div class="text-[11px] font-semibold text-[#142834]/70">${escapeHtml(st.meeting_date)} • ${escapeHtml(st.outcome)} (${escapeHtml(st.tally)})</div>
            <div class="text-xs font-bold text-[#1b3b4e] line-clamp-2">${escapeHtml(st.title)}</div>
          </button>
        `).join("")}
      </div>
    </div>
  `).join("");
  list.querySelectorAll(".lifecycle-stage-btn").forEach(btn => {
    btn.addEventListener("click", () => onOpenBill(divId, btn.dataset.eventId));
  });
}

function renderEntities(divId, entities, onOpenRep) {
  const grid = document.getElementById("jurEntitiesGrid");
  if (!entities.length) {
    grid.innerHTML = `<div class="col-span-full text-xs text-[#142834]/70">Roster pending ingestion.</div>`;
    return;
  }
  grid.innerHTML = entities.map(ent => {
    const m = ent.metrics || {};
    const hasVotes = (m.total_votes || 0) > 0;
    return `
      <button data-person-id="${escapeHtml(ent.ocd_person_id)}" class="rep-card-btn text-left rounded-xl border border-[#1b3b4e]/20 bg-[#f3e6cf]/65 p-4 hover:border-[#c67749] transition flex flex-col justify-between gap-3">
        <div>
          <div class="flex items-center justify-between gap-2">
            <span class="text-[11px] font-bold uppercase text-[#1b3b4e]">${escapeHtml(ent.district || "At-Large")}</span>
            <span class="text-[11px] text-[#142834]/65">Elected ${escapeHtml(ent.elected_date || "Active")}</span>
          </div>
          <div class="font-bold text-[#1b3b4e] text-sm mt-1">${escapeHtml(ent.name)}</div>
          <div class="text-xs text-[#142834]/70">${escapeHtml(ent.role || "Representative")}</div>
        </div>
        <div class="pt-2 border-t border-[#1b3b4e]/10 flex items-center justify-between text-xs">
          ${hasVotes
            ? `<span>Attendance: <strong>${m.attendance_rate}%</strong> (${m.present_votes}/${m.total_votes})</span><span>Impact: <strong>${m.avg_impact_score}</strong></span>`
            : `<span class="px-2 py-0.5 rounded bg-[#ebe0ca] text-[#1b3b4e] border border-[#c67749]/40 font-medium">Pending ingestion</span>`}
        </div>
      </button>
    `;
  }).join("");
  grid.querySelectorAll(".rep-card-btn").forEach(btn => {
    btn.addEventListener("click", () => onOpenRep(divId, btn.dataset.personId));
  });
}

export function renderEvents(divId, eventsRaw, onOpenBill) {
  const events = [...eventsRaw];
  const sortMode = document.getElementById("eventSortSelect")?.value || "date_desc";
  if (sortMode === "impact_desc") events.sort((a, b) => (b.impact_score || 0) - (a.impact_score || 0));
  else if (sortMode === "closest_margin") events.sort((a, b) => Math.abs((a.yes_count || 0) - (a.no_count || 0)) - Math.abs((b.yes_count || 0) - (b.no_count || 0)));
  else events.sort((a, b) => String(b.meeting_date || "").localeCompare(String(a.meeting_date || "")));

  const list = document.getElementById("jurEventsList");
  if (!events.length) {
    list.innerHTML = `<div class="rounded-xl bg-[#ebe0ca] border border-[#c67749]/35 p-4 text-xs text-[#1b3b4e]">Pending ingestion — documents are queued for extraction. Check the Engagement Guide above for official agendas and meeting links.</div>`;
    return;
  }

  list.innerHTML = events.map(ev => `
    <button data-event-id="${escapeHtml(ev.event_id)}" class="event-card-btn w-full text-left rounded-xl border border-[#1b3b4e]/20 bg-[#f3e6cf]/65 p-4 hover:border-[#c67749] transition block space-y-2">
      <div class="flex flex-wrap items-center justify-between gap-2 text-xs">
        <div class="flex items-center gap-2">
          <span class="font-semibold text-[#142834]/80">${escapeHtml(ev.meeting_date)}</span>
          <span class="px-2 py-0.5 rounded bg-[#ebe0ca] text-[#142834] font-medium">${escapeHtml(ev.topic || "General")}</span>
          <span class="px-2 py-0.5 rounded font-semibold ${isPassedOutcome(ev.outcome) ? "bg-[#5c7258] text-white" : "bg-[#ebe0ca] text-[#1b3b4e]"}">${escapeHtml(ev.outcome)} (${ev.yes_count}-${ev.no_count})</span>
        </div>
        <span class="px-2.5 py-0.5 rounded-full bg-[#366a8a] text-[#faf5eb] font-bold">Impact ${ev.impact_score ?? 0}/100</span>
      </div>
      <div class="font-bold text-[#1b3b4e] text-sm">${escapeHtml(ev.title)}</div>
      ${ev.plain_summary ? `<p class="text-xs text-[#142834]/80 leading-relaxed">${escapeHtml(ev.plain_summary)}</p>` : ""}
    </button>
  `).join("");
  list.querySelectorAll(".event-card-btn").forEach(btn => {
    btn.addEventListener("click", () => onOpenBill(divId, btn.dataset.eventId));
  });
}
