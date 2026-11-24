import { loadInitialData, loadJurisdictionData } from "./api.js";
import { initMap } from "./map.js";
import { initGlobalSearch } from "./search.js";
import { closeModal, openModal, showOnlySection } from "./utils.js";
import { openUnclaimedModal, renderHomeDirectory } from "./views/home.js";
import { renderEvents, renderJurisdictionHub } from "./views/jurisdiction.js";
import { renderBillDetail, renderRepProfile } from "./views/detail.js";

const state = {
  directory: { jurisdictions: [] },
  boundaries: null,
  engagementGuides: { guides: {} },
  billLifecycles: { by_jurisdiction: {} },
  currentJurData: null,
  levelFilter: "all",
};

function navigateHome() {
  history.replaceState(null, "", "#");
  showOnlySection("homeView");
}

async function openJurisdiction(divId, skipHash = false) {
  const meta = (state.directory.jurisdictions || []).find(j => j.ocd_division_id === divId);
  if (!meta) return;
  if (meta.status === "unclaimed") {
    openUnclaimedModal(divId, state);
    return;
  }
  if (!skipHash) history.replaceState(null, "", `#/jur/${encodeURIComponent(divId)}`);
  state.currentJurData = await loadJurisdictionData(meta.file);
  renderJurisdictionHub(state, { onOpenRep: openRep, onOpenBill: openBill });
  showOnlySection("jurisdictionView");
}

async function openRep(divId, personId, skipHash = false) {
  if (!state.currentJurData || state.currentJurData.jurisdiction.ocd_division_id !== divId) {
    await openJurisdiction(divId, true);
  }
  if (!skipHash) history.replaceState(null, "", `#/rep/${encodeURIComponent(divId)}/${encodeURIComponent(personId)}`);
  const ent = (state.currentJurData.entities || []).find(e => e.ocd_person_id === personId);
  if (!ent) return;
  renderRepProfile(divId, ent, state.currentJurData.jurisdiction.name, {
    onBack: () => openJurisdiction(divId),
    onOpenBill: openBill,
  });
  showOnlySection("repView");
}

async function openBill(divId, eventId, skipHash = false) {
  if (!state.currentJurData || state.currentJurData.jurisdiction.ocd_division_id !== divId) {
    await openJurisdiction(divId, true);
  }
  if (!skipHash) history.replaceState(null, "", `#/bill/${encodeURIComponent(divId)}/${encodeURIComponent(eventId)}`);
  const ev = (state.currentJurData.events || []).find(e => e.event_id === eventId);
  if (!ev) return;
  const chains = (state.billLifecycles.by_jurisdiction || {})[divId] || [];
  const matchingChain = chains.find(c => (c.stages || []).some(s => s.event_id === eventId));
  renderBillDetail(divId, ev, matchingChain, {
    onBack: () => openJurisdiction(divId),
    onOpenRep: openRep,
    onOpenEngage: async () => {
      await openJurisdiction(divId);
      document.getElementById("engagementGuideCard")?.scrollIntoView({ behavior: "smooth", block: "start" });
    },
  });
  showOnlySection("billView");
}

function handleHashRoute() {
  const h = window.location.hash || "";
  if (h.startsWith("#/jur/")) openJurisdiction(decodeURIComponent(h.slice(6)), true);
  else if (h.startsWith("#/rep/")) {
    const [d, p] = h.slice(6).split("/");
    if (d && p) openRep(decodeURIComponent(d), decodeURIComponent(p), true);
  } else if (h.startsWith("#/bill/")) {
    const [d, e] = h.slice(7).split("/");
    if (d && e) openBill(decodeURIComponent(d), decodeURIComponent(e), true);
  }
}

async function bootstrap() {
  const data = await loadInitialData();
  state.directory = data.directory;
  state.boundaries = data.boundaries;
  state.engagementGuides = data.engagementGuides;
  state.billLifecycles = data.billLifecycles;

  const badge = document.getElementById("lastUpdatedBadge");
  if (badge) badge.textContent = state.directory.last_updated ? `Updated ${state.directory.last_updated}` : "Static index loaded";

  // Wire static UI controls
  document.getElementById("brandHomeBtn")?.addEventListener("click", navigateHome);
  document.getElementById("jurBackHomeBtn")?.addEventListener("click", navigateHome);
  document.getElementById("scrollEngageBtn")?.addEventListener("click", () => {
    document.getElementById("engagementGuideCard")?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  document.getElementById("quickJumpSelect")?.addEventListener("change", e => {
    if (e.target.value) openJurisdiction(e.target.value);
  });
  document.getElementById("eventSortSelect")?.addEventListener("change", () => {
    if (state.currentJurData) {
      renderEvents(state.currentJurData.jurisdiction.ocd_division_id, state.currentJurData.events || [], openBill);
    }
  });

  document.querySelectorAll(".level-pill").forEach(btn => {
    btn.addEventListener("click", () => {
      state.levelFilter = btn.dataset.level;
      document.querySelectorAll(".level-pill").forEach(b => {
        const active = b.dataset.level === state.levelFilter;
        b.className = active
          ? "level-pill px-3.5 py-1.5 rounded-full text-xs font-semibold bg-[#1b3b4e] text-[#faf5eb] shadow-sm"
          : "level-pill px-3.5 py-1.5 rounded-full text-xs font-semibold bg-[#faf5eb] border border-[#1b3b4e]/25 text-[#1b3b4e] hover:bg-[#ebe0ca]";
      });
      renderHomeDirectory(state, openJurisdiction);
    });
  });

  document.querySelectorAll("[data-open-modal]").forEach(btn => {
    btn.addEventListener("click", () => openModal(btn.dataset.openModal));
  });
  document.querySelectorAll("[data-close-modal]").forEach(btn => {
    btn.addEventListener("click", () => closeModal(btn.dataset.closeModal));
  });

  renderHomeDirectory(state, openJurisdiction);
  initMap(state, openJurisdiction);
  initGlobalSearch(state, { onOpenJurisdiction: openJurisdiction, onOpenBill: openBill });
  window.addEventListener("hashchange", handleHashRoute);
  handleHashRoute();
}

bootstrap();
