/**
 * CivicPulse v3 Customer Suite (public/assets/civicpulse_v3_suite.js)
 *
 * Adds:
 *   1. Executive Digest & Printable PDF Briefing
 *   2. My Civic Watchlist (localStorage topic & city alerts)
 *   3. Council Alignment & Dissent Explorer
 *   4. Neutral Public Comment Composer Modal (exposed at window.CivicPulseV3.openCommentComposer)
 *   5. Embeddable Newsroom Widget Builder (widget.html)
 */

const WATCHLIST_KEY = "civicpulse_v3_watchlist";

function escHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function loadWatchlist() {
  try {
    const raw = localStorage.getItem(WATCHLIST_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    return {
      topics: Array.isArray(parsed?.topics) ? parsed.topics : ["Zoning & Land Use", "Budget & Finance"],
      jurisdictions: Array.isArray(parsed?.jurisdictions) ? parsed.jurisdictions : [],
    };
  } catch (_) {
    return { topics: ["Zoning & Land Use", "Budget & Finance"], jurisdictions: [] };
  }
}

function saveWatchlist(wl) {
  try {
    localStorage.setItem(WATCHLIST_KEY, JSON.stringify(wl));
  } catch (_) {}
}

let cachedContacts = {};

function findContactForJurisdiction(jurNameOrId) {
  const needle = String(jurNameOrId || "").toLowerCase();
  for (const [jid, obj] of Object.entries(cachedContacts)) {
    if (jid.toLowerCase() === needle || (obj.jurisdiction_name || "").toLowerCase() === needle) {
      return obj;
    }
  }
  return null;
}

function ensureCommentModal() {
  let modal = document.getElementById("v3CommentModal");
  if (modal) return modal;

  modal = document.createElement("div");
  modal.id = "v3CommentModal";
  modal.className = "hidden fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4";
  modal.innerHTML = `
    <div class="bg-[#faf5eb] rounded-2xl border border-[#1b3b4e]/25 max-w-xl w-full p-5 sm:p-6 space-y-4 shadow-xl max-h-[90vh] overflow-y-auto">
      <div class="flex items-start justify-between gap-3">
        <div>
          <span class="text-[11px] font-bold uppercase tracking-wider text-[#c67749]">Civic Action Tool</span>
          <h3 class="text-lg font-bold text-[#1b3b4e]">✉️ Draft Public Comment</h3>
          <p id="v3CommentMeta" class="text-xs text-[#142834]/75 mt-0.5"></p>
        </div>
        <button id="v3CommentClose" type="button" class="text-sm font-bold text-[#1b3b4e]/70 hover:text-[#1b3b4e]">✕</button>
      </div>
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-2.5 text-xs">
        <label class="space-y-1">
          <span class="font-semibold text-[#1b3b4e]">Your Stance</span>
          <select id="v3CommentStance" class="w-full rounded-xl border border-[#1b3b4e]/25 bg-white px-3 py-1.5 text-xs">
            <option value="Support">Support with comments</option>
            <option value="Oppose / Concerns">Share concerns / Oppose</option>
            <option value="Question / Request Info">Ask a neutral question</option>
          </select>
        </label>
        <label class="space-y-1">
          <span class="font-semibold text-[#1b3b4e]">Your Neighborhood / Role (optional)</span>
          <input id="v3CommentRole" type="text" placeholder="e.g., Resident in District 2" class="w-full rounded-xl border border-[#1b3b4e]/25 bg-white px-3 py-1.5 text-xs" />
        </label>
      </div>
      <div class="text-xs space-y-1">
        <span class="font-semibold text-[#1b3b4e]">Recipient Email</span>
        <input id="v3CommentTo" type="email" placeholder="council@city.gov" class="w-full rounded-xl border border-[#1b3b4e]/25 bg-white px-3 py-1.5 text-xs" />
      </div>
      <div class="text-xs space-y-1">
        <span class="font-semibold text-[#1b3b4e]">Draft Message (editable)</span>
        <textarea id="v3CommentBody" rows="7" class="w-full rounded-xl border border-[#1b3b4e]/25 bg-white p-3 text-xs leading-relaxed"></textarea>
      </div>
      <div class="flex flex-wrap items-center justify-between gap-2 pt-1">
        <span id="v3CommentToast" class="text-xs font-semibold text-emerald-800"></span>
        <div class="flex items-center gap-2">
          <button id="v3CommentCopy" type="button" class="px-3.5 py-1.5 rounded-xl border border-[#1b3b4e]/25 bg-white text-xs font-semibold text-[#1b3b4e] hover:bg-[#ebe0ca]">
            Copy Text
          </button>
          <a id="v3CommentMailto" href="#" class="px-4 py-1.5 rounded-xl bg-[#1b3b4e] text-[#faf5eb] text-xs font-semibold hover:bg-[#366a8a]">
            Open in Email App ↗
          </a>
        </div>
      </div>
    </div>
  `;
  document.body.appendChild(modal);

  modal.querySelector("#v3CommentClose").addEventListener("click", () => modal.classList.add("hidden"));
  modal.addEventListener("click", (e) => {
    if (e.target === modal) modal.classList.add("hidden");
  });
  return modal;
}

function openCommentComposer(ctx = {}) {
  const modal = ensureCommentModal();
  const jur = ctx.jurisdiction_name || "Local Council / Board";
  const dt = ctx.meeting_date || "upcoming meeting";
  const title = ctx.title || "Agenda Item";
  const contact = findContactForJurisdiction(ctx.jurisdiction_id || jur);

  const metaEl = modal.querySelector("#v3CommentMeta");
  const stanceEl = modal.querySelector("#v3CommentStance");
  const roleEl = modal.querySelector("#v3CommentRole");
  const toEl = modal.querySelector("#v3CommentTo");
  const bodyEl = modal.querySelector("#v3CommentBody");
  const mailtoEl = modal.querySelector("#v3CommentMailto");
  const copyBtn = modal.querySelector("#v3CommentCopy");
  const toastEl = modal.querySelector("#v3CommentToast");

  metaEl.textContent = `${jur} • ${dt} • ${title}`;
  toEl.value = contact?.council_comment_email || "";
  toastEl.textContent = "";

  function rebuildDraft() {
    const stance = stanceEl.value;
    const roleLine = roleEl.value.trim() ? `As a ${roleEl.value.trim()}, ` : "";
    const subject = `Public Comment (${dt}): ${title.slice(0, 90)}`;
    const body = [
      `Dear Members of the ${jur},`,
      "",
      `${roleLine}I am writing regarding "${title}" scheduled for ${dt} (${stance}).`,
      "",
      "[Add 2–3 concise sentences explaining how this item affects your household, neighborhood, or local business.]",
      "",
      "Thank you for your time and public service.",
      "",
      "Sincerely,",
      "[Your Name]",
    ].join("\n");
    bodyEl.value = body;
    const to = encodeURIComponent(toEl.value.trim());
    mailtoEl.href = `mailto:${to}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  }

  stanceEl.onchange = rebuildDraft;
  roleEl.oninput = rebuildDraft;
  toEl.oninput = () => {
    const subject = `Public Comment (${dt}): ${title.slice(0, 90)}`;
    mailtoEl.href = `mailto:${encodeURIComponent(toEl.value.trim())}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(bodyEl.value)}`;
  };
  bodyEl.oninput = () => {
    const subject = `Public Comment (${dt}): ${title.slice(0, 90)}`;
    mailtoEl.href = `mailto:${encodeURIComponent(toEl.value.trim())}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(bodyEl.value)}`;
  };
  copyBtn.onclick = async () => {
    try {
      await navigator.clipboard.writeText(bodyEl.value);
      toastEl.textContent = "Copied draft to clipboard.";
    } catch (_) {
      toastEl.textContent = "Select the text box to copy.";
    }
  };

  rebuildDraft();
  modal.classList.remove("hidden");
}

window.CivicPulseV3 = { openCommentComposer };

function injectPrintStyles() {
  if (document.getElementById("v3PrintStyles")) return;
  const st = document.createElement("style");
  st.id = "v3PrintStyles";
  st.textContent = `
    @media print {
      header, nav, footer, #mapSection, #unclaimedSection, button { display: none !important; }
      body { background: #ffffff !important; color: #111827 !important; }
      #v3SuiteRoot { border: none !important; box-shadow: none !important; }
    }
  `;
  document.head.appendChild(st);
}

async function mountV3CustomerSuite() {
  if (document.getElementById("v3SuiteRoot")) return;
  const anchor = document.getElementById("unclaimedSection") || document.querySelector("main");
  if (!anchor) return;

  let digest = null;
  let alignment = null;
  try {
    const [dRes, aRes, cRes] = await Promise.all([
      fetch("data/executive_digest.json"),
      fetch("data/alignment_explorer.json"),
      fetch("data/official_contacts.json"),
    ]);
    if (dRes.ok) digest = await dRes.json();
    if (aRes.ok) alignment = await aRes.json();
    if (cRes.ok) {
      const cJson = await cRes.json();
      cachedContacts = cJson.by_jurisdiction || {};
    }
  } catch (_) {
    return;
  }
  if (!digest && !alignment) return;

  injectPrintStyles();

  const root = document.createElement("section");
  root.id = "v3SuiteRoot";
  root.className = "space-y-6 my-6";

  // 1. Executive Digest + Watchlist + Printable Briefing + Embed Generator
  const stats = digest?.stats || {};
  const topDecisions = digest?.top_impact_decisions || [];
  const allTopics = (digest?.top_topics || []).map((t) => t.topic);
  const wl = loadWatchlist();

  const digestSec = document.createElement("div");
  digestSec.className = "bg-[#faf5eb] rounded-2xl border border-[#1b3b4e]/20 p-5 sm:p-6 space-y-4 shadow-sm";
  digestSec.innerHTML = `
    <div class="flex flex-col md:flex-row md:items-center justify-between gap-3">
      <div>
        <span class="text-[11px] font-bold uppercase tracking-wider text-[#c67749]">CivicPulse v3 Intelligence</span>
        <h2 class="text-lg font-bold text-[#1b3b4e]">📰 Executive Digest &amp; My Civic Watchlist</h2>
        <p class="text-xs text-[#142834]/75 mt-0.5">
          ${stats.total_events || 0} tracked decisions • ${stats.total_split_votes || 0} split votes (${stats.split_vote_pct || 0}%) • ${stats.business_relevant_events || 0} regulatory/business items
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <button id="v3PrintBriefingBtn" type="button" class="px-3 py-1.5 rounded-xl border border-[#1b3b4e]/25 bg-white text-xs font-semibold text-[#1b3b4e] hover:bg-[#ebe0ca]">
          🖨️ Print / Save PDF Briefing
        </button>
        <button id="v3OpenEmbedBtn" type="button" class="px-3 py-1.5 rounded-xl bg-[#1b3b4e] text-[#faf5eb] text-xs font-semibold hover:bg-[#366a8a]">
          &lt;/&gt; Embed Widget
        </button>
      </div>
    </div>

    <div class="rounded-xl bg-white/80 border border-[#1b3b4e]/15 p-3.5 space-y-2">
      <div class="flex items-center justify-between gap-2">
        <span class="text-xs font-bold text-[#1b3b4e]">⭐ My Watchlist Topics (saved in this browser)</span>
        <span id="v3WatchCount" class="text-[11px] font-semibold text-[#366a8a]"></span>
      </div>
      <div id="v3WatchPills" class="flex flex-wrap gap-1.5"></div>
    </div>

    <div id="v3DigestList" class="grid grid-cols-1 md:grid-cols-2 gap-3"></div>

    <div id="v3EmbedPanel" class="hidden rounded-xl bg-[#ebe0ca]/70 border border-[#1b3b4e]/20 p-4 space-y-2 text-xs">
      <div class="font-bold text-[#1b3b4e]">Embed Live Local Votes on Your Newsletter or Site (Free)</div>
      <div class="flex flex-col sm:flex-row gap-2">
        <select id="v3EmbedJurSelect" class="rounded-lg border border-[#1b3b4e]/25 bg-white px-2.5 py-1.5 text-xs"></select>
        <input id="v3EmbedCode" type="text" readonly class="flex-1 rounded-lg border border-[#1b3b4e]/25 bg-white px-2.5 py-1.5 font-mono text-[11px]" />
        <button id="v3EmbedCopyBtn" type="button" class="px-3 py-1.5 rounded-lg bg-[#1b3b4e] text-[#faf5eb] font-semibold">Copy</button>
      </div>
    </div>
  `;
  root.appendChild(digestSec);

  // 2. Council Alignment & Dissent Explorer
  const alignJurs = Object.values(alignment?.by_jurisdiction || {});
  if (alignJurs.length) {
    const alignSec = document.createElement("div");
    alignSec.className = "bg-[#faf5eb] rounded-2xl border border-[#1b3b4e]/20 p-5 sm:p-6 space-y-4 shadow-sm";
    alignSec.innerHTML = `
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <span class="text-[11px] font-bold uppercase tracking-wider text-[#366a8a]">Roll-Call Analytics</span>
          <h2 class="text-lg font-bold text-[#1b3b4e]">⚖️ Council Alignment &amp; Dissent Explorer</h2>
          <p class="text-xs text-[#142834]/75">Compare split-vote rates, frequent dissenters, and voting blocs from verified roll calls.</p>
        </div>
        <select id="v3AlignSelect" class="rounded-xl border border-[#1b3b4e]/25 bg-white px-3 py-1.5 text-xs font-semibold text-[#1b3b4e]"></select>
      </div>
      <div id="v3AlignBody" class="space-y-4"></div>
    `;
    root.appendChild(alignSec);

    const sel = alignSec.querySelector("#v3AlignSelect");
    alignJurs.forEach((aj) => {
      const opt = document.createElement("option");
      opt.value = aj.jurisdiction_id;
      opt.textContent = `${aj.jurisdiction_name} (${aj.split_events} split / ${aj.total_events} total)`;
      sel.appendChild(opt);
    });

    function renderAlign(jid) {
      const aj = alignment.by_jurisdiction[jid];
      const body = alignSec.querySelector("#v3AlignBody");
      if (!aj || !body) return;

      const dissentRows = (aj.dissent_leaderboard || []).slice(0, 6);
      const splitList = (aj.recent_split_votes || []).slice(0, 4);

      body.innerHTML = `
        <div class="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
          <div class="rounded-xl bg-white border border-[#1b3b4e]/15 p-3">
            <div class="text-[#142834]/70">Split-Vote Rate</div>
            <div class="text-xl font-bold text-[#1b3b4e]">${aj.split_rate_pct}%</div>
            <div class="text-[11px] text-[#142834]/70">${aj.split_events} split vs. ${aj.unanimous_events} unanimous</div>
          </div>
          <div class="rounded-xl bg-white border border-[#1b3b4e]/15 p-3">
            <div class="font-bold text-[#1b3b4e] mb-1">Most Frequent Dissenters</div>
            ${
              dissentRows.length
                ? dissentRows
                    .map(
                      (d) =>
                        `<div class="flex justify-between py-0.5"><span>${escHtml(d.name)}</span><span class="font-semibold text-[#c67749]">${d.dissent_rate_pct}% (${d.minority_votes}/${d.total_votes})</span></div>`
                    )
                    .join("")
                : `<div class="text-[#142834]/65">No named roll-call dissent yet.</div>`
            }
          </div>
          <div class="rounded-xl bg-white border border-[#1b3b4e]/15 p-3">
            <div class="font-bold text-[#1b3b4e] mb-1">Most Divergent Pairs</div>
            ${
              (aj.most_divergent_pairs || []).length
                ? aj.most_divergent_pairs
                    .slice(0, 4)
                    .map(
                      (p) =>
                        `<div class="flex justify-between py-0.5"><span>${escHtml(p.rep_a)} / ${escHtml(p.rep_b)}</span><span class="font-semibold">${p.agreement_pct}%</span></div>`
                    )
                    .join("")
                : `<div class="text-[#142834]/65">Needs ≥2 shared named votes.</div>`
            }
          </div>
        </div>
        ${
          splitList.length
            ? `<div class="space-y-2">
                <div class="text-xs font-bold text-[#1b3b4e]">Recent Contested / Split Votes</div>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                  ${splitList
                    .map(
                      (sv) => `
                    <div class="rounded-xl bg-white border border-[#1b3b4e]/15 p-3 text-xs space-y-1">
                      <div class="flex justify-between gap-2">
                        <span class="font-semibold text-[#366a8a]">${escHtml(sv.meeting_date)} • ${escHtml(sv.topic)}</span>
                        <span class="px-2 py-0.5 rounded-full bg-amber-100 text-amber-950 font-bold">${escHtml(sv.tally)}</span>
                      </div>
                      <div class="font-bold text-[#1b3b4e]">${escHtml(sv.title)}</div>
                      ${
                        sv.no_voters?.length
                          ? `<div class="text-[11px] text-[#c67749]"><strong>Voted No:</strong> ${escHtml(sv.no_voters.join(", "))}</div>`
                          : ""
                      }
                    </div>`
                    )
                    .join("")}
                </div>
              </div>`
            : ""
        }
      `;
    }

    sel.addEventListener("change", () => renderAlign(sel.value));
    renderAlign(sel.value);
  }

  // Insert cleanly right before #unclaimedSection
  if (anchor.id === "unclaimedSection") {
    anchor.parentNode.insertBefore(root, anchor);
  } else {
    anchor.appendChild(root);
  }

  // Wire Watchlist Pills & Digest Cards
  const pillsEl = digestSec.querySelector("#v3WatchPills");
  const listEl = digestSec.querySelector("#v3DigestList");
  const countEl = digestSec.querySelector("#v3WatchCount");

  function renderDigestCards() {
    const activeTopics = new Set(wl.topics);
    const pool = [...topDecisions, ...(digest?.notable_split_votes || []), ...(digest?.business_regulatory_alerts || [])];
    const dedup = [];
    const seen = new Set();
    for (const it of pool) {
      if (!seen.has(it.event_id)) {
        seen.add(it.event_id);
        dedup.push(it);
      }
    }
    const matched = activeTopics.size ? dedup.filter((it) => activeTopics.has(it.topic)) : dedup;
    const shown = (matched.length ? matched : topDecisions).slice(0, 6);
    countEl.textContent = `${matched.length} matching item(s)`;

    listEl.innerHTML = shown
      .map(
        (ev, idx) => `
      <article class="rounded-xl bg-white border border-[#1b3b4e]/15 p-3.5 text-xs space-y-1.5">
        <div class="flex items-center justify-between gap-2">
          <span class="font-semibold text-[#366a8a]">${escHtml(ev.jurisdiction_name)} • ${escHtml(ev.meeting_date)}</span>
          <span class="px-2 py-0.5 rounded-full bg-[#1b3b4e] text-[#faf5eb] text-[10px] font-bold">Impact ${ev.impact_score}/100</span>
        </div>
        <h3 class="font-bold text-[#1b3b4e] text-sm">${escHtml(ev.title)}</h3>
        ${ev.plain_summary ? `<p class="text-[#142834]/80 line-clamp-2">${escHtml(ev.plain_summary)}</p>` : ""}
        <div class="flex flex-wrap items-center justify-between gap-2 pt-1">
          <span class="px-2 py-0.5 rounded-full bg-[#ebe0ca] text-[#1b3b4e] text-[10px] font-semibold">${escHtml(ev.topic)} • ${escHtml(ev.outcome)} (${ev.yes_count}-${ev.no_count})</span>
          <button type="button" data-didx="${idx}" class="v3-digest-comment-btn text-[11px] font-semibold text-[#c67749] hover:underline">✉️ Draft Comment</button>
        </div>
      </article>`
      )
      .join("");

    listEl.querySelectorAll(".v3-digest-comment-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const ev = shown[Number(btn.dataset.didx)];
        if (ev) openCommentComposer(ev);
      });
    });
  }

  function renderPills() {
    pillsEl.innerHTML = allTopics
      .map((topic) => {
        const on = wl.topics.includes(topic);
        return `<button type="button" data-topic="${escHtml(topic)}" class="v3-wl-pill px-2.5 py-1 rounded-full text-[11px] font-semibold transition ${
          on ? "bg-[#1b3b4e] text-[#faf5eb]" : "bg-[#ebe0ca]/70 text-[#1b3b4e] hover:bg-[#ebe0ca]"
        }">${on ? "★ " : "+ "}${escHtml(topic)}</button>`;
      })
      .join("");
    pillsEl.querySelectorAll(".v3-wl-pill").forEach((btn) => {
      btn.addEventListener("click", () => {
        const t = btn.dataset.topic;
        if (wl.topics.includes(t)) {
          wl.topics = wl.topics.filter((x) => x !== t);
        } else {
          wl.topics.push(t);
        }
        saveWatchlist(wl);
        renderPills();
        renderDigestCards();
      });
    });
  }

  renderPills();
  renderDigestCards();

  // Print Briefing
  digestSec.querySelector("#v3PrintBriefingBtn").addEventListener("click", () => window.print());

  // Embed Widget Builder
  const embedPanel = digestSec.querySelector("#v3EmbedPanel");
  const embedSel = digestSec.querySelector("#v3EmbedJurSelect");
  const embedCode = digestSec.querySelector("#v3EmbedCode");
  Object.values(cachedContacts).forEach((c) => {
    const slug = c.jurisdiction_id.replace("ocd-division/", "").replace(/\//g, "__").replace(/[:\-]/g, "_");
    const opt = document.createElement("option");
    opt.value = slug;
    opt.textContent = c.jurisdiction_name;
    embedSel.appendChild(opt);
  });
  function updateEmbedSnippet() {
    const base = window.location.origin + window.location.pathname.replace(/index\.html$/, "");
    const url = `${base}widget.html?jur=${encodeURIComponent(embedSel.value)}&limit=5`;
    embedCode.value = `<iframe src="${url}" width="100%" height="420" style="border:1px solid #d6cbb5;border-radius:12px;" loading="lazy"></iframe>`;
  }
  embedSel.addEventListener("change", updateEmbedSnippet);
  updateEmbedSnippet();
  digestSec.querySelector("#v3OpenEmbedBtn").addEventListener("click", () => embedPanel.classList.toggle("hidden"));
  digestSec.querySelector("#v3EmbedCopyBtn").addEventListener("click", () => {
    navigator.clipboard?.writeText(embedCode.value);
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", mountV3CustomerSuite);
} else {
  mountV3CustomerSuite();
}
