# Wiring CivicPulse v2 Frontend Enhancements

`public/assets/civicpulse_enhancements.js` is designed to drop cleanly into your modular v2 `public/index.html` without overwriting your existing styling or layout.

## 1. Replace Pre-Load / No-JS Placeholders in `public/index.html`
Replace placeholder strings like `Jurisdiction Name`, `Docs since —`, and `href="#"` with clean loading states and a `<noscript>` fallback right inside `<main>`:

```html
<noscript>
  <div class="max-w-3xl mx-auto my-6 p-4 rounded-xl bg-amber-50 border border-amber-200 text-sm text-amber-900">
    <strong>JavaScript is required for the interactive map and filters.</strong>
    You can still download our plain-English
    <a href="docs/civicpulse_impact_formula.md" class="underline font-semibold">Impact Scoring Formula</a>
    or subscribe to our
    <a href="feeds/all.xml" class="underline font-semibold">Colorado Local Measures RSS Feed</a>.
  </div>
</noscript>
```

For dynamic elements before JS hydrates, avoid dead `href="#"` links:
- Use `aria-busy="true"` with skeleton text (`Loading jurisdiction...` / `Loading schedule...`).
- Hide external portal links (`class="hidden"`) until a real `https://` URL is bound.

## 2. Import the Enhancement Module
Add this near your existing `<script type="module">` entry point in `public/index.html`:

```html
<script type="module">
  import { CivicPulseEnhancements } from "./assets/civicpulse_enhancements.js";

  // 1. Immediately fix $15 / $50 Support mailto links
  CivicPulseEnhancements.fixSupportLinks();

  // 2. Render the live, versioned Impact Formula + Download (.md / .json) panel
  const formulaBox = document.getElementById("scoringMethodologyPanel");
  if (formulaBox) {
    CivicPulseEnhancements.loadScoringMethodology(formulaBox);
  }

  // Expose helpers globally if your existing inline scripts call them
  window.CivicPulseEnhancements = CivicPulseEnhancements;
</script>
```

## 3. Drop-In UI Hooks
- **Measure Cards & Detail Views:** Append `CivicPulseEnhancements.renderMeasureTrustBadges(ev)` to show *Structured Portal Data vs. AI-Extracted from Minutes*, *QA Status*, *Formula Version*, and the pre-filled **Report an Error** button.
- **Jurisdiction Header:** Render `CivicPulseEnhancements.renderFreshnessBadge(jur)` for *"Data as of YYYY-MM-DD"* and automatic stale-data warnings (`>14 days`).
- **Business Regional Radar / CSV Export:** Wire an `<button onclick="CivicPulseEnhancements.exportEventsToCsv(filteredEvents)">Export CSV</button>` next to your topic filter bar.
- **Upcoming Meetings + Calendar Export:** Fetch `data/upcoming_meetings.json` and wire each meeting's **Add to Calendar (.ics)** button to `CivicPulseEnhancements.downloadMeetingIcs(meeting)`.
- **Progressive Search Loading:** Replace monolithic `fetch("data/search_index.json")` with `await CivicPulseEnhancements.loadSearchChunked({ quartersToLoad: 2 })` and add a *"Load older quarters"* button when `hasMore === true`.
