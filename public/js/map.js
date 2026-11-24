import { escapeHtml } from "./utils.js";

let mapInstance = null;

export function initMap(state, onSelectJurisdiction) {
  if (mapInstance) return mapInstance;

  mapInstance = L.map("map", { scrollWheelZoom: false }).setView([40.05, -105.05], 8);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
    maxZoom: 19,
  }).addTo(mapInstance);

  mapInstance.on("click", e => {
    resolveCoordinates(e.latlng.lat, e.latlng.lng, "Map Location", state, onSelectJurisdiction);
  });

  const form = document.getElementById("addressLookupForm");
  form?.addEventListener("submit", async e => {
    e.preventDefault();
    const addr = document.getElementById("addressInput")?.value.trim();
    if (!addr) return;
    const btn = document.getElementById("addressLookupBtn");
    btn.textContent = "Locating...";
    try {
      const url = `https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?address=${encodeURIComponent(addr)}&benchmark=Public_AR_Current&format=json`;
      const res = await fetch(url);
      const data = await res.json();
      const match = data?.result?.addressMatches?.[0];
      if (match?.coordinates) {
        const { y: lat, x: lng } = match.coordinates;
        mapInstance.setView([lat, lng], 12);
        resolveCoordinates(lat, lng, match.matchedAddress || addr, state, onSelectJurisdiction);
      } else {
        alert("Address not matched in U.S. Census Geocoder. Try including city and state (e.g., Fort Collins, CO).");
      }
    } catch (_) {
      alert("Unable to reach Census Geocoder right now. You can click directly on the map instead.");
    } finally {
      btn.textContent = "Find My Districts";
    }
  });

  document.getElementById("dismissOverlapBtn")?.addEventListener("click", () => {
    document.getElementById("overlapBanner")?.classList.add("hidden");
  });

  return mapInstance;
}

function resolveCoordinates(lat, lng, label, state, onSelectJurisdiction) {
  const matchedIds = new Set();
  const pt = turf.point([lng, lat]);

  if (state.boundaries?.features) {
    for (const feat of state.boundaries.features) {
      try {
        if (turf.booleanPointInPolygon(pt, feat)) {
          const divId = feat.properties?.ocd_division_id || feat.properties?.OCD_ID || feat.id;
          if (divId) matchedIds.add(divId);
        }
      } catch (_) {}
    }
  }

  const allJurs = state.directory.jurisdictions || [];
  if (!matchedIds.size) {
    for (const j of allJurs) {
      if (j.lat && j.lng) {
        const distKm = turf.distance(pt, turf.point([j.lng, j.lat]), { units: "kilometers" });
        if (distKm <= 18) matchedIds.add(j.ocd_division_id);
      }
    }
  }

  const matched = allJurs.filter(j => matchedIds.has(j.ocd_division_id));
  const banner = document.getElementById("overlapBanner");
  const list = document.getElementById("overlapCardsList");
  document.getElementById("overlapLocationTitle").textContent = `${label} (${lat.toFixed(4)}, ${lng.toFixed(4)})`;

  if (!matched.length) {
    list.innerHTML = `<div class="col-span-full text-xs text-[#142834]/80">No tracked polygons matched at this point yet. Choose a jurisdiction below or request coverage.</div>`;
  } else {
    list.innerHTML = matched.map(j => `
      <button data-jur-id="${escapeHtml(j.ocd_division_id)}" class="overlap-jur-btn text-left bg-[#faf5eb] rounded-xl border border-[#1b3b4e]/20 p-3 hover:border-[#c67749] transition shadow-sm">
        <div class="text-[10px] font-bold uppercase text-[#1b3b4e]">${escapeHtml(j.level.replace("_", " "))} • ${escapeHtml(j.status)}</div>
        <div class="text-xs font-bold text-[#1b3b4e] mt-0.5">${escapeHtml(j.name)}</div>
        <div class="text-[11px] text-[#366a8a] font-semibold mt-1">${j.status === "active" ? "Inspect Votes &amp; Guide →" : "Request Tracking →"}</div>
      </button>
    `).join("");
    list.querySelectorAll(".overlap-jur-btn").forEach(btn => {
      btn.addEventListener("click", () => onSelectJurisdiction(btn.dataset.jurId));
    });
  }
  banner.classList.remove("hidden");
}
