/**
 * CivicPulse v3.5 Tabbed Home UX & Trust Polish
 * (public/assets/civicpulse_v3_5_home_tabs.js)
 *
 * Consolidates dynamically mounted homepage sections into 4 clean customer workflows:
 *   1. Explore Map & Directory   (Map + Address Lookup + Active Cities + Unclaimed Search)
 *   2. Before the Vote           (Upcoming Meetings + 14-Day Draft Previews + P&Z Early Warning)
 *   3. Votes & Topic Radar       (Regional Topic Radar / CSV + Executive Digest + Watchlist)
 *   4. Alignment & Data Health   (Council Alignment & Dissent Explorer + Methodology & Coverage)
 *
 * Also adds clear "Agendas Only — Minutes Pending" badges on active jurisdictions with
 * 0 extracted votes (e.g., Boulder) and smooths QA badge tooltips.
 */

const TAB_STORAGE_KEY = "civicpulse_v35_active_tab";

const WORKFLOW_TABS = [
  {
    id: "explore",
    label: "Explore Map & Directory",
    shortLabel: "Explore Map",
    icon: "🗺️",
    subtitle: "Look up your address, click anywhere in Colorado, or browse active & unclaimed jurisdictions.",
  },
  {
    id: "before_vote",
    label: "Before the Vote",
    shortLabel: "Before the Vote",
    icon: "📋",
    subtitle: "Upcoming meetings, 14-day draft agenda previews, Planning & Zoning early warnings, and public comment.",
  },
  {
    id: "votes_radar",
    label: "Votes & Topic Radar",
    shortLabel: "Votes & Radar",
    icon: "🔍",
    subtitle: "Cross-city regulatory/business filters, CSV exports, Executive Digest, and My Civic Watchlist.",
  },
  {
    id: "alignment",
    label: "Alignment & Analytics",
    shortLabel: "Alignment",
    icon: "⚖️",
    subtitle: "Council split-vote rates, dissent leaderboards, voting blocs, and methodology transparency.",
  },
];

let activeTabId = "explore";
let isSyncingDom = false;

function getSavedTab() {
  try {
    const hash = window.location.hash || "";
    const m = hash.match(/^#\/tab\/([a-z_]+)$/);
    if (m && WORKFLOW_TABS.some((t) => t.id === m[1])) return m[1];
    const stored = sessionStorage.getItem(TAB_STORAGE_KEY);
    if (stored && WORKFLOW_TABS.some((t) => t.id === stored)) return stored;
  } catch (_) {}
  return "explore";
}

function saveTab(tabId) {
  try {
    sessionStorage.setItem(TAB_STORAGE_KEY, tabId);
  } catch (_) {}
}

function classifyHomeChild(el) {
  if (!el || el.nodeType !== 1) return null;
  const id = el.id || "";
  if (id === "v35TabBarWrap" || id === "v35TabPanels") return null;

  // Before the Vote workflow
  if (
    id === "upcomingMeetingsSection" ||
    id === "v32AgendaPreviewsSection" ||
    id === "v31PlanningWarningSection"
  ) {
    return "before_vote";
  }

  // Votes & Topic Radar workflow
  if (id === "topicRadarSection" || id === "v3DigestPanelCard") {
    return "votes_radar";
  }

  // Alignment & Analytics workflow
  if (id === "v3AlignmentPanelCard" || id === "v35DataHealthCard") {
    return "alignment";
  }

  // Everything else (Map card, Overlap banner, Level filters, Active grid, Unclaimed directory)
  return "explore";
}

function splitV3SuiteCardsIfPresent(homeView) {
  const root = document.getElementById("v3SuiteRoot");
  if (!root) return;

  const children = Array.from(root.children);
  children.forEach((child) => {
    const txt = (child.textContent || "").toLowerCase();
    if (txt.includes("alignment") && txt.includes("dissent")) {
      child.id = "v3AlignmentPanelCard";
      const panel = document.getElementById("v35Panel_alignment");
      if (panel && child.parentNode !== panel) {
        panel.insertBefore(child, panel.firstChild);
      }
    } else if (txt.includes("executive digest") || txt.includes("watchlist")) {
      child.id = "v3DigestPanelCard";
      const panel = document.getElementById("v35Panel_votes_radar");
      if (panel && child.parentNode !== panel) {
        panel.appendChild(child);
      }
    }
  });

  if (root.children.length === 0) {
    root.classList.add("hidden");
  }
}

function polishZeroVoteActiveCards() {
  const grid = document.getElementById("jurisdictionCardsGrid");
  if (!grid) return;

  Array.from(grid.children).forEach((card) => {
    if (card.dataset.v35Polished === "1") return;
    const text = card.textContent || "";
    const isZeroVotes = /\b0\s*(Vote\s+Events|Votes|Events)\b/i.test(text) || /Pending ingestion/i.test(text);
    if (isZeroVotes) {
      const spans = card.querySelectorAll("span");
      spans.forEach((sp) => {
        if (/Pending ingestion/i.test(sp.textContent || "") || /^0\s*(Vote\s+Events|Votes|Events)$/i.test((sp.textContent || "").trim())) {
          sp.textContent = "Agendas Only • Minutes Pending";
          sp.title = "Upcoming agendas are tracked; post-meeting roll-call minutes archive is pending ingestion.";
          sp.className = "px-2 py-0.5 rounded-full bg-amber-100 text-amber-900 border border-amber-300/70 font-semibold text-[11px]";
        }
      });
      card.dataset.v35Polished = "1";
    }
  });
}

function buildDataHealthCard() {
  const existing = document.getElementById("v35DataHealthCard");
  if (existing) return existing;

  const card = document.createElement("div");
  card.id = "v35DataHealthCard";
  card.className = "bg-[#faf5eb] rounded-2xl border border-[#1b3b4e]/20 p-5 sm:p-6 space-y-3 shadow-sm text-xs";
  card.innerHTML = `
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
      <div>
        <span class="text-[11px] font-bold uppercase tracking-wider text-[#366a8a]">Transparency &amp; Coverage</span>
        <h3 class="text-base font-bold text-[#1b3b4e]">🛡️ Data Provenance, QA Standards &amp; Scoring</h3>
      </div>
      <div class="flex flex-wrap gap-2">
        <a href="docs/civicpulse_impact_formula.md" target="_blank" rel="noopener noreferrer" class="px-3 py-1.5 rounded-xl border border-[#1b3b4e]/25 bg-white font-semibold text-[#1b3b4e] hover:bg-[#ebe0ca]">
          Impact Formula v2.0.0 ↗
        </a>
        <a href="feeds/all.xml" target="_blank" rel="noopener noreferrer" class="px-3 py-1.5 rounded-xl bg-[#1b3b4e] text-[#faf5eb] font-semibold hover:bg-[#366a8a]">
          RSS Feed (All Cities) ↗
        </a>
      </div>
    </div>
    <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
      <div class="rounded-xl bg-white border border-[#1b3b4e]/15 p-3 space-y-1">
        <div class="font-bold text-[#1b3b4e]">Source Capture Labels</div>
        <p class="text-[#142834]/80"><strong>Structured Portal Data</strong> comes directly from municipal APIs. <strong>AI-Extracted from Minutes</strong> is parsed from official PDF minutes and audited against recorded tallies.</p>
      </div>
      <div class="rounded-xl bg-white border border-[#1b3b4e]/15 p-3 space-y-1">
        <div class="font-bold text-[#1b3b4e]">Agendas-Only Cities</div>
        <p class="text-[#142834]/80">Active portals whose signed minutes live in a separate archive (e.g., Boulder) are clearly badged <em>Agendas Only • Minutes Pending</em> rather than displaying misleading 0% attendance.</p>
      </div>
      <div class="rounded-xl bg-white border border-[#1b3b4e]/15 p-3 space-y-1">
        <div class="font-bold text-[#1b3b4e]">$0/Month Civic Infrastructure</div>
        <p class="text-[#142834]/80">100% static JSON on Cloudflare Pages with zero paywalls for residents. Voluntary business patrons fund priority onboarding for unclaimed Colorado communities.</p>
      </div>
    </div>
  `;
  return card;
}

function updateTabBadges() {
  const beforePanel = document.getElementById("v35Panel_before_vote");
  const radarPanel = document.getElementById("v35Panel_votes_radar");
  const alignPanel = document.getElementById("v35Panel_alignment");

  const setBadge = (id, count) => {
    const el = document.getElementById(`v35Badge_${id}`);
    if (!el) return;
    if (count > 0) {
      el.textContent = String(count);
      el.classList.remove("hidden");
    } else {
      el.classList.add("hidden");
    }
  };

  const upcomingCards = beforePanel ? beforePanel.querySelectorAll("article, a[href*='civicclerk'], a[href*='legistar'], a[href*='primegov']").length : 0;
  const activeCount = Number(document.getElementById("countAll")?.textContent || 0);
  setBadge("explore", activeCount);
  setBadge("before_vote", Math.min(99, upcomingCards));

  // Show clean placeholder if a workflow panel has no loaded sections yet
  [
    ["before_vote", beforePanel, "No upcoming meetings or agenda previews are currently loaded for the next 14 days."],
    ["votes_radar", radarPanel, "Loading cross-city Topic Radar and Executive Digest..."],
    ["alignment", alignPanel, "Loading Council Alignment & Dissent analytics..."],
  ].forEach(([tabId, panel, msg]) => {
    if (!panel) return;
    const realSections = Array.from(panel.children).filter(
      (c) => !c.classList.contains("v35-empty-placeholder") && !c.classList.contains("hidden")
    );
    let placeholder = panel.querySelector(".v35-empty-placeholder");
    if (realSections.length === 0) {
      if (!placeholder) {
        placeholder = document.createElement("div");
        placeholder.className = "v35-empty-placeholder rounded-2xl border border-[#1b3b4e]/15 bg-[#faf5eb] p-6 text-center text-xs text-[#142834]/75";
        placeholder.textContent = msg;
        panel.appendChild(placeholder);
      }
    } else if (placeholder) {
      placeholder.remove();
    }
  });
}

function switchHomeTab(tabId, updateUrl = false) {
  if (!WORKFLOW_TABS.some((t) => t.id === tabId)) tabId = "explore";
  activeTabId = tabId;
  saveTab(tabId);

  if (updateUrl && (!window.location.hash || window.location.hash.startsWith("#/tab/"))) {
    history.replaceState(null, "", tabId === "explore" ? "#" : `#/tab/${tabId}`);
  }

  WORKFLOW_TABS.forEach((t) => {
    const btn = document.getElementById(`v35TabBtn_${t.id}`);
    const panel = document.getElementById(`v35Panel_${t.id}`);
    const isSel = t.id === tabId;

    if (btn) {
      btn.setAttribute("aria-selected", isSel ? "true" : "false");
      btn.className = isSel
        ? "v35-tab-btn flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs sm:text-sm font-bold bg-[#1b3b4e] text-[#faf5eb] shadow-sm transition whitespace-nowrap"
        : "v35-tab-btn flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs sm:text-sm font-semibold bg-white/80 text-[#1b3b4e] border border-[#1b3b4e]/15 hover:bg-[#ebe0ca] transition whitespace-nowrap";
    }
    if (panel) {
      panel.classList.toggle("hidden", !isSel);
    }
  });

  const subEl = document.getElementById("v35TabSubtitle");
  const curTab = WORKFLOW_TABS.find((t) => t.id === tabId);
  if (subEl && curTab) subEl.textContent = curTab.subtitle;

  // Trigger Leaflet resize if returning to Explore Map tab
  if (tabId === "explore") {
    setTimeout(() => window.dispatchEvent(new Event("resize")), 60);
  }
}

function redistributeHomeChildren(homeView) {
  if (isSyncingDom) return;
  isSyncingDom = true;
  try {
    splitV3SuiteCardsIfPresent(homeView);

    const directChildren = Array.from(homeView.children);
    directChildren.forEach((child) => {
      if (child.id === "v35TabBarWrap" || child.id === "v35TabPanels" || child.id === "v3SuiteRoot") {
        return;
      }
      const targetTab = classifyHomeChild(child);
      if (!targetTab) return;
      const targetPanel = document.getElementById(`v35Panel_${targetTab}`);
      if (targetPanel && child.parentNode !== targetPanel) {
        targetPanel.appendChild(child);
      }
    });

    // Enforce deterministic order inside Before the Vote: Upcoming -> Agenda Previews -> P&Z Early Warning
    const bvPanel = document.getElementById("v35Panel_before_vote");
    if (bvPanel) {
      ["upcomingMeetingsSection", "v32AgendaPreviewsSection", "v31PlanningWarningSection"].forEach((id) => {
        const el = document.getElementById(id);
        if (el && el.parentNode === bvPanel) {
          bvPanel.appendChild(el);
        }
      });
    }

    // Ensure Data Health card sits at the bottom of Alignment & Analytics
    const alignPanel = document.getElementById("v35Panel_alignment");
    if (alignPanel) {
      const healthCard = buildDataHealthCard();
      if (healthCard.parentNode !== alignPanel) {
        alignPanel.appendChild(healthCard);
      }
    }

    polishZeroVoteActiveCards();
    updateTabBadges();
  } finally {
    isSyncingDom = false;
  }
}

function mountTabbedHomeUx() {
  const homeView = document.getElementById("homeView");
  if (!homeView || document.getElementById("v35TabBarWrap")) return;

  activeTabId = getSavedTab();

  // 1. Create clean workflow tab bar
  const tabBarWrap = document.createElement("div");
  tabBarWrap.id = "v35TabBarWrap";
  tabBarWrap.className = "bg-[#faf5eb] rounded-2xl border border-[#1b3b4e]/20 p-3 sm:p-4 shadow-sm space-y-2";
  tabBarWrap.innerHTML = `
    <div role="tablist" aria-label="CivicPulse Workflows" class="flex items-center gap-2 overflow-x-auto pb-0.5">
      ${WORKFLOW_TABS.map(
        (t) => `
        <button
          id="v35TabBtn_${t.id}"
          type="button"
          role="tab"
          aria-selected="false"
          aria-controls="v35Panel_${t.id}"
          data-tab="${t.id}"
          class="v35-tab-btn flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs sm:text-sm font-semibold bg-white/80 text-[#1b3b4e] border border-[#1b3b4e]/15 hover:bg-[#ebe0ca] transition whitespace-nowrap"
        >
          <span>${t.icon}</span>
          <span class="hidden sm:inline">${t.label}</span>
          <span class="sm:hidden">${t.shortLabel}</span>
          <span id="v35Badge_${t.id}" class="hidden ml-1 px-1.5 py-0.5 rounded-full bg-[#c67749] text-white text-[10px] font-bold"></span>
        </button>`
      ).join("")}
    </div>
    <p id="v35TabSubtitle" class="text-xs text-[#142834]/75 px-1"></p>
  `;

  // 2. Create 4 tab panels container
  const panelsWrap = document.createElement("div");
  panelsWrap.id = "v35TabPanels";
  panelsWrap.className = "space-y-6";
  panelsWrap.innerHTML = WORKFLOW_TABS.map(
    (t) => `<div id="v35Panel_${t.id}" role="tabpanel" class="space-y-6 ${t.id === activeTabId ? "" : "hidden"}"></div>`
  ).join("");

  homeView.insertBefore(panelsWrap, homeView.firstChild);
  homeView.insertBefore(tabBarWrap, homeView.firstChild);

  tabBarWrap.querySelectorAll(".v35-tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchHomeTab(btn.dataset.tab, true));
  });

  // 3. Move existing sections into their workflow panels & observe late-mounting v3/v3.1/v3.2 modules
  redistributeHomeChildren(homeView);
  switchHomeTab(activeTabId, false);

  const observer = new MutationObserver(() => {
    redistributeHomeChildren(homeView);
  });
  observer.observe(homeView, { childList: true });

  // Also observe #jurisdictionCardsGrid so "Agendas Only" badges apply after app.js renders
  const jurGrid = document.getElementById("jurisdictionCardsGrid");
  if (jurGrid) {
    new MutationObserver(() => polishZeroVoteActiveCards()).observe(jurGrid, { childList: true });
  }

  // Re-check once after async fetches settle (~800ms & ~2000ms)
  setTimeout(() => redistributeHomeChildren(homeView), 800);
  setTimeout(() => redistributeHomeChildren(homeView), 2000);

  window.CivicPulseTabs = { switchHomeTab };
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", mountTabbedHomeUx);
} else {
  mountTabbedHomeUx();
}
