const jurCache = new Map();
let searchIndexCache = null;

async function fetchJsonSafe(url, fallback) {
  try {
    const res = await fetch(url);
    if (res.ok) return await res.json();
  } catch (_) {}
  return fallback;
}

export async function loadInitialData() {
  // Prefer lightweight directory.json; fall back to legacy index.json
  let directory = await fetchJsonSafe("data/directory.json", null);
  if (!directory) {
    directory = await fetchJsonSafe("data/index.json", { jurisdictions: [] });
  }
  const [boundaries, engagementGuides, billLifecycles] = await Promise.all([
    fetchJsonSafe("geo/boundaries.geojson", null),
    fetchJsonSafe("data/engagement_guides.json", { guides: {} }),
    fetchJsonSafe("data/bill_lifecycles.json", { by_jurisdiction: {} }),
  ]);
  return { directory, boundaries, engagementGuides, billLifecycles };
}

export async function loadSearchIndexLazy(directory) {
  if (searchIndexCache) return searchIndexCache;
  const searchPayload = await fetchJsonSafe("data/search_index.json", null);
  if (searchPayload && Array.isArray(searchPayload.search_index)) {
    searchIndexCache = searchPayload.search_index;
    return searchIndexCache;
  }
  searchIndexCache = directory.search_index || [];
  return searchIndexCache;
}

export async function loadJurisdictionData(file) {
  if (jurCache.has(file)) return jurCache.get(file);
  const res = await fetch(`data/${file}`);
  const data = await res.json();
  jurCache.set(file, data);
  return data;
}
