export function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function normalizePortalUrl(url) {
  const raw = String(url || "").trim();
  if (raw.toLowerCase().includes(".api.civicclerk.com")) {
    const slug = raw.split("//")[1]?.split(".api.civicclerk.com")[0];
    if (slug) return `https://${slug}.portal.civicclerk.com/`;
  }
  return raw || "#";
}

export function isPassedOutcome(outcome) {
  return /^(passed|adopted)/i.test(String(outcome || ""));
}

export function openModal(id) {
  document.getElementById(id)?.classList.remove("hidden");
}

export function closeModal(id) {
  document.getElementById(id)?.classList.add("hidden");
}

export function showOnlySection(sectionId) {
  ["homeView", "jurisdictionView", "repView", "billView"].forEach(id => {
    document.getElementById(id)?.classList.toggle("hidden", id !== sectionId);
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}
