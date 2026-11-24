import { escapeHtml, openModal } from "../utils.js";

export function openUnclaimedModal(divId, state) {
  const jur = (state.directory.jurisdictions || []).find(j => j.ocd_division_id === divId);
  if (!jur) return;
  document.getElementById("unclaimedModalTitle").textContent = jur.name;
  document.getElementById("unclaimedDivId").textContent = jur.ocd_division_id;
  document.getElementById("unclaimedRequestMailto").href = `mailto:bryanateisl@gmail.com?subject=${encodeURIComponent(`CivicPulse Request: Track ${jur.name}`)}`;
  document.getElementById("unclaimedSponsorMailto").href = `mailto:bryanateisl@gmail.com?subject=${encodeURIComponent(`CivicPulse Priority Onboarding: ${jur.name}`)}`;
  const pLink = document.getElementById("unclaimedPortalLink");
  if (jur.portal_url) {
    pLink.href = jur.portal_url;
    pLink.classList.remove("hidden");
  } else {
    pLink.classList.add("hidden");
  }
  openModal("unclaimedModal");
}

export function renderHomeDirectory(state, onOpenJurisdiction) {
  const allJurs = state.directory.jurisdictions || [];
  const activeAll = allJurs.filter(j => (j.status || "active") === "active");
  const unclaimedAll = allJurs.filter(j => j.status === "unclaimed");

  const isCity = lvl => lvl === "municipality" || lvl === "city";
  document.getElementById("countAll").textContent = activeAll.length;
  document.getElementById("countCity").textContent = activeAll.filter(j => isCity(j.level)).length;
  document.getElementById("countCounty").textContent = activeAll.filter(j => j.level === "county").length;
  document.getElementById("countSchool").textContent = activeAll.filter(j => j.level === "school_district" || j.level === "school").length;

  const filtered = state.levelFilter === "all"
    ? activeAll
    : state.levelFilter === "municipality"
      ? activeAll.filter(j => isCity(j.level))
      : state.levelFilter === "school_district"
        ? activeAll.filter(j => j.level === "school_district" || j.level === "school")
        : activeAll.filter(j => j.level === state.levelFilter);

  const select = document.getElementById("quickJumpSelect");
  select.innerHTML =
    `<option value="">Jump directly to jurisdiction...</option>` +
    `<optgroup label="Active Tracked Jurisdictions">` +
    activeAll.map(j => `<option value="${escapeHtml(j.ocd_division_id)}">${escapeHtml(j.name)} (${escapeHtml(j.level)})</option>`).join("") +
    `</optgroup>` +
    (unclaimedAll.length
      ? `<optgroup label="Unclaimed (Request Coverage)">` +
        unclaimedAll.map(j => `<option value="${escapeHtml(j.ocd_division_id)}">${escapeHtml(j.name)} — Request Tracking</option>`).join("") +
        `</optgroup>`
      : "");

  const grid = document.getElementById("jurisdictionCardsGrid");
  if (!filtered.length) {
    grid.innerHTML = `<div class="col-span-full bg-[#faf5eb] rounded-xl border border-[#1b3b4e]/20 p-6 text-center text-xs text-[#142834]/70">No active jurisdictions in this filter tier yet.</div>`;
  } else {
    grid.innerHTML = filtered.map(j => {
      const hasVotes = (j.event_count || 0) > 0;
      const badgeCls = j.level === "county"
        ? "bg-[#c67749] text-white"
        : j.level === "school_district"
          ? "bg-[#1b3b4e] text-[#faf5eb]"
          : "bg-[#366a8a] text-[#faf5eb]";
      return `
        <button data-jur-id="${escapeHtml(j.ocd_division_id)}" class="jur-card-btn text-left bg-[#faf5eb] rounded-2xl border border-[#1b3b4e]/20 p-4 hover:border-[#c67749] hover:bg-[#fdf9f2] hover:shadow-sm transition flex flex-col justify-between gap-3">
          <div>
            <div class="flex items-center justify-between gap-2 mb-1.5">
              <span class="px-2 py-0.5 rounded text-[11px] font-semibold uppercase ${badgeCls}">${escapeHtml(j.level.replace("_", " "))}</span>
              <span class="text-[11px] text-[#142834]/70">Docs since ${escapeHtml(j.docs_since || "2026")}</span>
            </div>
            <h3 class="font-bold text-[#1b3b4e] text-base">${escapeHtml(j.name)}</h3>
          </div>
          <div class="flex items-center justify-between text-xs text-[#142834]/80 pt-2.5 border-t border-[#1b3b4e]/10">
            <span><strong>${j.entity_count || 0}</strong> Reps</span>
            <span>${hasVotes ? `<strong>${j.event_count}</strong> Vote Events` : `<span class="px-2 py-0.5 rounded bg-[#ebe0ca] text-[#1b3b4e] border border-[#c67749]/40 font-medium">Pending ingestion</span>`}</span>
            <span class="text-[#366a8a] font-semibold">Open →</span>
          </div>
        </button>
      `;
    }).join("");
    grid.querySelectorAll(".jur-card-btn").forEach(btn => {
      btn.addEventListener("click", () => onOpenJurisdiction(btn.dataset.jurId));
    });
  }

  const unclaimedGrid = document.getElementById("unclaimedCardsGrid");
  document.getElementById("unclaimedCountBadge").textContent = `${unclaimedAll.length} available to request`;
  unclaimedGrid.innerHTML = unclaimedAll.map(j => `
    <button data-jur-id="${escapeHtml(j.ocd_division_id)}" class="unclaimed-card-btn text-left rounded-xl border border-[#1b3b4e]/15 bg-[#ebe0ca]/60 p-3 hover:border-[#c67749] hover:bg-white transition">
      <div class="text-[10px] font-bold uppercase text-[#142834]/70">${escapeHtml(j.level.replace("_", " "))}</div>
      <div class="text-xs font-bold text-[#1b3b4e] mt-0.5">${escapeHtml(j.name)}</div>
      <div class="text-[11px] text-[#366a8a] font-semibold mt-1.5">+ Request Tracking</div>
    </button>
  `).join("");
  unclaimedGrid.querySelectorAll(".unclaimed-card-btn").forEach(btn => {
    btn.addEventListener("click", () => openUnclaimedModal(btn.dataset.jurId, state));
  });
}
