import { escapeHtml, isPassedOutcome, normalizePortalUrl } from "../utils.js";

export function renderRepProfile(divId, ent, jurName, { onBack, onOpenBill }) {
  document.getElementById("repBackBtn").onclick = onBack;
  const m = ent.metrics || {};
  const hasVotes = (m.total_votes || 0) > 0;
  const container = document.getElementById("repProfileContent");

  container.innerHTML = `
    <div class="flex flex-col sm:flex-row sm:items-start justify-between gap-4 border-b border-[#1b3b4e]/15 pb-4">
      <div>
        <div class="text-xs font-bold uppercase text-[#1b3b4e]">${escapeHtml(ent.district || "At-Large")} • Elected ${escapeHtml(ent.elected_date || "Active")}</div>
        <h1 class="text-2xl font-bold text-[#1b3b4e] mt-1">${escapeHtml(ent.name)}</h1>
        <p class="text-xs text-[#142834]/70 mt-0.5">${escapeHtml(ent.role)} • ${escapeHtml(jurName)}</p>
      </div>
      <div class="flex flex-wrap gap-2 text-xs">
        ${ent.email ? `<a href="mailto:${escapeHtml(ent.email)}" class="px-3 py-1.5 rounded-xl bg-[#366a8a] text-[#faf5eb] font-semibold">Email Representative</a>` : ""}
        ${ent.website_url ? `<a href="${escapeHtml(ent.website_url)}" target="_blank" rel="noopener noreferrer" class="px-3 py-1.5 rounded-xl border border-[#1b3b4e]/25 bg-white font-semibold">Official Bio ↗</a>` : ""}
      </div>
    </div>
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
      <div class="p-3 rounded-xl bg-[#ebe0ca] border border-[#1b3b4e]/15"><div class="text-[#142834]/70">Attendance</div><div class="text-base font-bold text-[#1b3b4e] mt-0.5">${hasVotes ? `${m.attendance_rate}%` : "Pending ingestion"}</div></div>
      <div class="p-3 rounded-xl bg-[#ebe0ca] border border-[#1b3b4e]/15"><div class="text-[#142834]/70">Recorded Votes</div><div class="text-base font-bold text-[#1b3b4e] mt-0.5">${m.total_votes || 0}</div></div>
      <div class="p-3 rounded-xl bg-[#ebe0ca] border border-[#1b3b4e]/15"><div class="text-[#142834]/70">Avg Impact Score</div><div class="text-base font-bold text-[#1b3b4e] mt-0.5">${hasVotes ? m.avg_impact_score : "—"}</div></div>
      <div class="p-3 rounded-xl bg-[#ebe0ca] border border-[#1b3b4e]/15"><div class="text-[#142834]/70">Pivotal Votes</div><div class="text-base font-bold text-[#1b3b4e] mt-0.5">${m.pivotal_votes || 0}</div></div>
    </div>
    <div class="space-y-2.5">
      <h2 class="text-base font-bold text-[#1b3b4e]">Roll-Call Voting History</h2>
      ${(ent.votes || []).length
        ? ent.votes.map(v => `
            <button data-event-id="${escapeHtml(v.event_id)}" class="rep-vote-btn w-full text-left p-3.5 rounded-xl border border-[#1b3b4e]/20 bg-white hover:border-[#c67749] transition block">
              <div class="flex items-center justify-between text-xs">
                <span class="text-[#142834]/70">${escapeHtml(v.meeting_date)}</span>
                <span class="font-bold px-2 py-0.5 rounded ${v.vote === "Yes" ? "bg-[#5c7258] text-white" : v.vote === "No" ? "bg-[#c67749] text-white" : "bg-[#ebe0ca] text-[#1b3b4e]"}">${escapeHtml(v.vote)}</span>
              </div>
              <div class="text-xs font-bold text-[#1b3b4e] mt-1">${escapeHtml(v.title)}</div>
            </button>
          `).join("")
        : `<div class="text-xs text-[#142834]/70">No individual roll-call votes ingested for this representative yet.</div>`}
    </div>
  `;
  container.querySelectorAll(".rep-vote-btn").forEach(btn => {
    btn.addEventListener("click", () => onOpenBill(divId, btn.dataset.eventId));
  });
}

export function renderBillDetail(divId, ev, matchingChain, { onBack, onOpenRep, onOpenEngage }) {
  document.getElementById("billBackBtn").onclick = onBack;
  const container = document.getElementById("billDetailContent");

  container.innerHTML = `
    <div class="space-y-3 border-b border-[#1b3b4e]/15 pb-4">
      <div class="flex flex-wrap items-center justify-between gap-2 text-xs">
        <div class="flex flex-wrap items-center gap-2">
          <span class="font-semibold text-[#142834]/80">${escapeHtml(ev.meeting_date)}</span>
          <span class="px-2 py-0.5 rounded bg-[#ebe0ca] text-[#142834] font-medium">${escapeHtml(ev.topic || "General")}</span>
          <span class="px-2 py-0.5 rounded font-semibold ${isPassedOutcome(ev.outcome) ? "bg-[#5c7258] text-white" : "bg-[#ebe0ca] text-[#1b3b4e]"}">${escapeHtml(ev.outcome)} (${ev.yes_count}-${ev.no_count})</span>
          <span class="px-2 py-0.5 rounded bg-[#366a8a] text-[#faf5eb] font-bold">Impact ${ev.impact_score ?? 0}/100</span>
        </div>
        <a href="${escapeHtml(normalizePortalUrl(ev.source_url))}" target="_blank" rel="noopener noreferrer" class="text-[#366a8a] font-semibold hover:underline">Official Record ↗</a>
      </div>
      <h1 class="text-xl font-bold text-[#1b3b4e]">${escapeHtml(ev.title)}</h1>
      ${ev.plain_summary ? `<div class="p-3.5 rounded-xl bg-[#ebe0ca] border border-[#366a8a]/30 text-xs text-[#142834] space-y-1"><div class="font-bold text-[#1b3b4e]">Plain-English Summary</div><p class="leading-relaxed">${escapeHtml(ev.plain_summary)}</p></div>` : ""}
      ${ev.diff_summary ? `<div class="p-3.5 rounded-xl bg-[#f3e6cf] border border-[#c67749]/35 text-xs text-[#142834] space-y-1"><div class="font-bold text-[#1b3b4e]">What Changed?</div><p class="leading-relaxed">${escapeHtml(ev.diff_summary)}</p></div>` : ""}
    </div>
    ${matchingChain ? `
      <div class="p-4 rounded-xl bg-[#ebe0ca]/70 border border-[#366a8a]/25 space-y-2">
        <div class="text-xs font-bold text-[#1b3b4e]">Cross-Meeting Bill Lifecycle (${escapeHtml(matchingChain.match_basis)})</div>
        <div class="space-y-1.5 border-l-2 border-[#366a8a]/50 pl-3">
          ${matchingChain.stages.map(st => `<div class="text-xs ${st.event_id === ev.event_id ? "font-bold text-[#1b3b4e]" : "text-[#142834]/85"}">${escapeHtml(st.meeting_date)} — ${escapeHtml(st.outcome)} (${escapeHtml(st.tally)}): ${escapeHtml(st.title)}</div>`).join("")}
        </div>
      </div>` : ""}
    <div class="p-3.5 rounded-xl bg-[#ebe0ca] border border-[#5c7258]/35 flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs">
      <div><strong class="text-[#1b3b4e]">Want to weigh in on related council or board items?</strong> <span class="text-[#142834]/80">View upcoming meetings, public comment rules, and representative contacts.</span></div>
      <button id="billOpenEngageBtn" class="px-3 py-1.5 rounded-lg bg-[#366a8a] text-[#faf5eb] font-semibold hover:bg-[#1b3b4e] transition self-start">Open Engagement Guide →</button>
    </div>
    <div class="space-y-2.5">
      <h2 class="text-base font-bold text-[#1b3b4e]">Roll-Call Breakdown</h2>
      ${(ev.votes || []).length
        ? `<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5">` +
          ev.votes.map(v => `
            <button data-entity-id="${escapeHtml(v.entity_id)}" class="bill-rep-btn text-left p-3 rounded-xl border border-[#1b3b4e]/20 bg-white hover:border-[#c67749] transition flex items-center justify-between gap-2 text-xs">
              <div><div class="font-bold text-[#1b3b4e]">${escapeHtml(v.name)}</div><div class="text-[11px] text-[#142834]/70">${escapeHtml(v.district || "")}</div></div>
              <span class="font-bold px-2 py-0.5 rounded ${v.vote === "Yes" ? "bg-[#5c7258] text-white" : v.vote === "No" ? "bg-[#c67749] text-white" : "bg-[#ebe0ca] text-[#1b3b4e]"}">${escapeHtml(v.vote)}</span>
            </button>
          `).join("") + `</div>`
        : `<div class="text-xs text-[#142834]/70">Individual roll-call breakdown not recorded for this summary item.</div>`}
    </div>
  `;
  container.querySelector("#billOpenEngageBtn")?.addEventListener("click", onOpenEngage);
  container.querySelectorAll(".bill-rep-btn").forEach(btn => {
    btn.addEventListener("click", () => onOpenRep(divId, btn.dataset.entityId));
  });
}
