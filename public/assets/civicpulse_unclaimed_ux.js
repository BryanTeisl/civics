/**
 * CivicPulse Unclaimed Jurisdictions Search, Tier Filter & Pagination UX
 * (public/assets/civicpulse_unclaimed_ux.js)
 *
 * Non-destructively enhances #unclaimedSection so all ~514 Colorado cities,
 * counties, and school districts are searchable and requestable without
 * creating a 500-card scroll wall. Preserves all js/app.js click handlers.
 */

const PAGE_SIZE = 12;

function detectCardLevel(cardEl) {
  const raw = (cardEl.dataset.level || "").toLowerCase();
  if (raw) {
    if (raw === "municipal" || raw === "municipality" || raw === "town") return "city";
    if (raw === "school_board" || raw === "school") return "school_district";
    return raw;
  }
  const text = (cardEl.textContent || "").toUpperCase();
  if (text.includes("SCHOOL DISTRICT") || text.includes("SCHOOL BOARD") || text.includes("BOARD OF EDUCATION")) {
    return "school_district";
  }
  if (text.includes("COUNTY")) {
    return "county";
  }
  return "city";
}

function mountUnclaimedDirectoryUx() {
  const section = document.getElementById("unclaimedSection");
  const grid = document.getElementById("unclaimedCardsGrid");
  if (!section || !grid || document.getElementById("unclaimedUxControls")) return;

  let searchQuery = "";
  let activeTier = "all";
  let visibleCap = PAGE_SIZE;
  let isApplying = false;

  // 1. Insert Search + Tier Filter Bar directly above #unclaimedCardsGrid
  const controls = document.createElement("div");
  controls.id = "unclaimedUxControls";
  controls.className = "space-y-2.5 pt-1";
  controls.innerHTML = `
    <div class="flex flex-col sm:flex-row sm:items-center gap-2.5">
      <div class="relative flex-1">
        <input
          id="unclaimedSearchInput"
          type="search"
          aria-label="Search unclaimed Colorado cities, counties, and school districts"
          placeholder="Search all Colorado cities, counties & school districts (e.g. Grand Junction, Denver Public)..."
          class="w-full rounded-xl border border-[#1b3b4e]/25 bg-white px-3.5 py-2 text-xs sm:text-sm text-[#142834] placeholder:text-[#1b3b4e]/55 focus:border-[#c67749] focus:outline-none"
        />
      </div>
      <div id="unclaimedTierPills" class="flex flex-wrap items-center gap-1.5 shrink-0">
        <button type="button" data-tier="all" class="unclaimed-tier-pill px-3 py-1.5 rounded-full text-xs font-semibold bg-[#1b3b4e] text-[#faf5eb]">
          All (<span id="uncCountAll">0</span>)
        </button>
        <button type="button" data-tier="city" class="unclaimed-tier-pill px-3 py-1.5 rounded-full text-xs font-semibold bg-white border border-[#1b3b4e]/20 text-[#1b3b4e] hover:bg-[#ebe0ca]">
          Cities (<span id="uncCountCity">0</span>)
        </button>
        <button type="button" data-tier="county" class="unclaimed-tier-pill px-3 py-1.5 rounded-full text-xs font-semibold bg-white border border-[#1b3b4e]/20 text-[#1b3b4e] hover:bg-[#ebe0ca]">
          Counties (<span id="uncCountCounty">0</span>)
        </button>
        <button type="button" data-tier="school_district" class="unclaimed-tier-pill px-3 py-1.5 rounded-full text-xs font-semibold bg-white border border-[#1b3b4e]/20 text-[#1b3b4e] hover:bg-[#ebe0ca]">
          Schools (<span id="uncCountSchool">0</span>)
        </button>
      </div>
    </div>
    <div class="flex flex-wrap items-center justify-between gap-2 text-[11px] text-[#142834]/75">
      <span id="unclaimedFilterStatus">Showing available jurisdictions...</span>
      <button id="unclaimedClearFilterBtn" type="button" class="hidden font-semibold text-[#366a8a] hover:underline">
        Clear search &amp; filters
      </button>
    </div>
  `;
  grid.parentNode.insertBefore(controls, grid);

  // 2. Insert Empty State + Pagination + Special District Catch-All Footer below #unclaimedCardsGrid
  const footer = document.createElement("div");
  footer.id = "unclaimedUxFooter";
  footer.className = "space-y-3 pt-2";
  footer.innerHTML = `
    <div id="unclaimedNoMatches" class="hidden rounded-xl border border-[#1b3b4e]/15 bg-white p-4 text-center text-xs text-[#142834]/75">
      No unclaimed jurisdictions match your search. If it is already actively tracked, check the Active section above—or request it below.
    </div>
    <div id="unclaimedPaginationBar" class="hidden flex flex-wrap items-center justify-center gap-2">
      <button id="unclaimedShowMoreBtn" type="button" class="px-4 py-2 rounded-xl border border-[#1b3b4e]/25 bg-white text-xs font-semibold text-[#1b3b4e] hover:bg-[#ebe0ca] transition">
        Show 12 More
      </button>
      <button id="unclaimedCollapseBtn" type="button" class="hidden px-3.5 py-2 rounded-xl border border-[#1b3b4e]/20 bg-[#ebe0ca]/60 text-xs font-semibold text-[#1b3b4e] hover:bg-[#ebe0ca] transition">
        Collapse List
      </button>
    </div>
    <div class="rounded-xl bg-[#ebe0ca]/70 border border-[#1b3b4e]/15 px-4 py-3 flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs">
      <div class="text-[#142834]/85">
        <strong class="text-[#1b3b4e]">Looking for a Fire, Water, Library, or Metro Special District?</strong>
        <span class="block sm:inline sm:ml-1">Send us the district name and portal link to add it to our coverage queue.</span>
      </div>
      <a
        href="mailto:bryanateisl@gmail.com?subject=CivicPulse%20Special%20District%20Tracking%20Request&amp;body=Hi%20Bryan%2C%0A%0APlease%20consider%20adding%20this%20Colorado%20special%20district%20or%20local%20board%20to%20CivicPulse%3A%0A%0ADistrict%20Name%3A%20%0ACounty%20%2F%20City%3A%20%0AOfficial%20Meeting%20URL%20(if%20known)%3A%20"
        class="shrink-0 inline-flex items-center justify-center px-3.5 py-1.5 rounded-xl bg-[#1b3b4e] text-[#faf5eb] font-semibold hover:bg-[#366a8a] transition"
      >
        + Request Special District ↗
      </a>
    </div>
  `;
  grid.insertAdjacentElement("afterend", footer);

  const searchInput = document.getElementById("unclaimedSearchInput");
  const statusEl = document.getElementById("unclaimedFilterStatus");
  const clearBtn = document.getElementById("unclaimedClearFilterBtn");
  const noMatchesEl = document.getElementById("unclaimedNoMatches");
  const pagBar = document.getElementById("unclaimedPaginationBar");
  const showMoreBtn = document.getElementById("unclaimedShowMoreBtn");
  const collapseBtn = document.getElementById("unclaimedCollapseBtn");

  function applyFiltersAndPagination() {
    if (isApplying) return;
    isApplying = true;
    try {
      const cards = Array.from(grid.children);
      const q = searchQuery.trim().toLowerCase();

      const counts = { all: cards.length, city: 0, county: 0, school_district: 0 };
      const matchingCards = [];

      cards.forEach((card) => {
        const lvl = detectCardLevel(card);
        if (lvl in counts) counts[lvl] += 1;

        const matchesTier = activeTier === "all" || lvl === activeTier;
        const matchesQuery = !q || (card.textContent || "").toLowerCase().includes(q);
        if (matchesTier && matchesQuery) {
          matchingCards.push(card);
        }
      });

      // Update tier counts
      const setTxt = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.textContent = String(val);
      };
      setTxt("uncCountAll", counts.all);
      setTxt("uncCountCity", counts.city);
      setTxt("uncCountCounty", counts.county);
      setTxt("uncCountSchool", counts.school_district);

      // Show only up to visibleCap matching cards; hide the rest
      const shownSet = new Set(matchingCards.slice(0, visibleCap));
      cards.forEach((card) => {
        card.classList.toggle("hidden", !shownSet.has(card));
      });

      const shownCount = shownSet.size;
      const totalMatch = matchingCards.length;

      if (statusEl) {
        if (totalMatch === 0 && counts.all === 0) {
          statusEl.textContent = "Loading available jurisdictions...";
        } else if (totalMatch === 0) {
          statusEl.textContent = "0 matching jurisdictions";
        } else {
          statusEl.textContent = `Showing ${shownCount} of ${totalMatch} matching jurisdiction${totalMatch === 1 ? "" : "s"}`;
        }
      }

      if (clearBtn) {
        clearBtn.classList.toggle("hidden", !q && activeTier === "all");
      }
      if (noMatchesEl) {
        noMatchesEl.classList.toggle("hidden", !(counts.all > 0 && totalMatch === 0));
      }

      if (pagBar && showMoreBtn && collapseBtn) {
        const remaining = totalMatch - shownCount;
        const showBar = remaining > 0 || visibleCap > PAGE_SIZE;
        pagBar.classList.toggle("hidden", !showBar);

        if (remaining > 0) {
          showMoreBtn.classList.remove("hidden");
          const step = Math.min(PAGE_SIZE, remaining);
          showMoreBtn.textContent = `Show ${step} More (${remaining} remaining)`;
        } else {
          showMoreBtn.classList.add("hidden");
        }
        collapseBtn.classList.toggle("hidden", visibleCap <= PAGE_SIZE || totalMatch <= PAGE_SIZE);
      }
    } finally {
      isApplying = false;
    }
  }

  // Wire controls
  searchInput.addEventListener("input", () => {
    searchQuery = searchInput.value;
    visibleCap = PAGE_SIZE;
    applyFiltersAndPagination();
  });

  controls.querySelectorAll(".unclaimed-tier-pill").forEach((pill) => {
    pill.addEventListener("click", () => {
      activeTier = pill.dataset.tier || "all";
      visibleCap = PAGE_SIZE;
      controls.querySelectorAll(".unclaimed-tier-pill").forEach((p) => {
        const isSel = p === pill;
        p.className = isSel
          ? "unclaimed-tier-pill px-3 py-1.5 rounded-full text-xs font-semibold bg-[#1b3b4e] text-[#faf5eb]"
          : "unclaimed-tier-pill px-3 py-1.5 rounded-full text-xs font-semibold bg-white border border-[#1b3b4e]/20 text-[#1b3b4e] hover:bg-[#ebe0ca]";
      });
      applyFiltersAndPagination();
    });
  });

  clearBtn.addEventListener("click", () => {
    searchQuery = "";
    searchInput.value = "";
    activeTier = "all";
    visibleCap = PAGE_SIZE;
    controls.querySelector('.unclaimed-tier-pill[data-tier="all"]')?.click();
  });

  showMoreBtn.addEventListener("click", () => {
    visibleCap += PAGE_SIZE;
    applyFiltersAndPagination();
  });

  collapseBtn.addEventListener("click", () => {
    visibleCap = PAGE_SIZE;
    applyFiltersAndPagination();
    section.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  // Watch #unclaimedCardsGrid so whenever js/app.js renders or re-renders cards, pagination re-applies automatically
  const observer = new MutationObserver(() => {
    if (!isApplying) {
      visibleCap = PAGE_SIZE;
      applyFiltersAndPagination();
    }
  });
  observer.observe(grid, { childList: true });

  applyFiltersAndPagination();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", mountUnclaimedDirectoryUx);
} else {
  mountUnclaimedDirectoryUx();
}
