import { loadSearchIndexLazy } from "./api.js";
import { escapeHtml } from "./utils.js";

export function initGlobalSearch(state, { onOpenJurisdiction, onOpenBill }) {
  const input = document.getElementById("globalSearchInput");
  const resultsBox = document.getElementById("globalSearchResults");
  if (!input || !resultsBox) return;

  let fuseInstance = null;

  async function ensureFuse() {
    if (fuseInstance) return fuseInstance;
    const eventsIndex = await loadSearchIndexLazy(state.directory);
    const items = [
      ...(state.directory.jurisdictions || []).map(j => ({
        type: "jurisdiction",
        id: j.ocd_division_id,
        title: j.name,
        subtitle: `${j.level} • ${j.status === "active" ? `${j.event_count} events` : "Unclaimed"}`,
        searchBlob: `${j.name} ${j.level}`,
      })),
      ...eventsIndex.map(ev => ({
        type: "bill",
        id: ev.event_id,
        jurId: ev.jurisdiction_id,
        title: ev.title,
        subtitle: `${ev.jurisdiction_name} • ${ev.meeting_date} • ${ev.outcome}`,
        searchBlob: `${ev.title} ${ev.plain_summary || ""} ${ev.topic || ""} ${ev.voters_text || ""} ${ev.quotes_text || ""}`,
      })),
    ];
    fuseInstance = new Fuse(items, {
      keys: ["title", "subtitle", "searchBlob"],
      threshold: 0.35,
      ignoreLocation: true,
    });
    return fuseInstance;
  }

  input.addEventListener("focus", () => { ensureFuse(); });

  input.addEventListener("input", async () => {
    const q = input.value.trim();
    if (!q) {
      resultsBox.classList.add("hidden");
      return;
    }
    const fuse = await ensureFuse();
    const hits = fuse.search(q).slice(0, 10);
    if (!hits.length) {
      resultsBox.innerHTML = `<div class="p-3 text-xs text-[#142834]/70">No matching measures, representatives, or jurisdictions found.</div>`;
    } else {
      resultsBox.innerHTML = hits.map(({ item }) => `
        <button data-type="${item.type}" data-id="${escapeHtml(item.id)}" data-jur="${escapeHtml(item.jurId || "")}" class="search-hit w-full text-left px-3.5 py-2.5 hover:bg-[#ebe0ca]/60 transition block">
          <div class="text-[10px] font-bold uppercase tracking-wider text-[#366a8a]">${escapeHtml(item.type)}</div>
          <div class="text-xs font-semibold text-[#1b3b4e] line-clamp-2">${escapeHtml(item.title)}</div>
          <div class="text-[11px] text-[#142834]/70 mt-0.5">${escapeHtml(item.subtitle)}</div>
        </button>
      `).join("");
      resultsBox.querySelectorAll(".search-hit").forEach(btn => {
        btn.addEventListener("click", () => {
          resultsBox.classList.add("hidden");
          if (btn.dataset.type === "jurisdiction") onOpenJurisdiction(btn.dataset.id);
          else onOpenBill(btn.dataset.jur, btn.dataset.id);
        });
      });
    }
    resultsBox.classList.remove("hidden");
  });

  document.addEventListener("click", e => {
    if (!input.contains(e.target) && !resultsBox.contains(e.target)) {
      resultsBox.classList.add("hidden");
    }
  });
}
