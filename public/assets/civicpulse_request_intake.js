/**
 * CivicPulse Self-Service Jurisdiction Request Intake
 * (public/assets/civicpulse_request_intake.js)
 *
 * Routes unclaimed jurisdiction & special district requests to a pre-filled
 * GitHub Issue (`labels=jurisdiction-request`) so the daily autonomous onboarding
 * agent (`autonomous_onboarder.py`) picks them up hands-free.
 */

const GITHUB_ISSUES_URL = "https://github.com/BryanTeisl/civics/issues/new";

function buildGithubRequestUrl({ name, ocdId = "", level = "city", portalUrl = "" }) {
  const title = `[Request] ${name}`;
  const bodyLines = [
    "### Jurisdiction Tracking Request",
    `- **Jurisdiction:** ${name}`,
    ocdId ? `- **OCD Division ID:** ${ocdId}` : "",
    `- **Level:** ${level}`,
    portalUrl ? `- **Portal URL:** ${portalUrl}` : "- **Portal URL:** (auto-discover)",
    "",
    "_Submitted via CivicPulse — will be automatically scouted and provisioned during the next daily pipeline run._",
  ].filter(Boolean);

  const params = new URLSearchParams({
    labels: "jurisdiction-request",
    title,
    body: bodyLines.join("\n"),
  });
  return `${GITHUB_ISSUES_URL}?${params.toString()}`;
}

function wireIntakeLinks() {
  const footer = document.getElementById("unclaimedUxFooter");
  if (footer) {
    const mailLink = footer.querySelector('a[href^="mailto:"]');
    if (mailLink && !mailLink.dataset.v4IntakeWired) {
      mailLink.href = buildGithubRequestUrl({
        name: "Colorado Special District (Enter Name)",
        level: "special_district",
      });
      mailLink.target = "_blank";
      mailLink.rel = "noopener noreferrer";
      mailLink.title = "Opens a pre-filled GitHub request picked up automatically by the daily onboarding agent";
      mailLink.dataset.v4IntakeWired = "1";
    }
  }

  document.querySelectorAll('a[href^="mailto:"]').forEach((a) => {
    if (a.dataset.v4IntakeWired) return;
    const href = decodeURIComponent(a.href || "");
    const txt = (a.textContent || "").toLowerCase();
    if (txt.includes("request") && !txt.includes("sponsor")) {
      const mOcd = href.match(/ocd-division\/[^\s&]+/i);
      const mName = href.match(/(?:for|jurisdiction[:\s]+)\s*([A-Z][A-Za-z0-9\s.-]{2,50})/);
      const jName = mName ? mName[1].trim() : "Colorado Jurisdiction";
      a.href = buildGithubRequestUrl({
        name: jName,
        ocdId: mOcd ? mOcd[0] : "",
      });
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.dataset.v4IntakeWired = "1";
    }
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    wireIntakeLinks();
    new MutationObserver(wireIntakeLinks).observe(document.body, { childList: true, subtree: true });
  });
} else {
  wireIntakeLinks();
  new MutationObserver(wireIntakeLinks).observe(document.body, { childList: true, subtree: true });
}
