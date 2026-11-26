/**
 * CivicPulse v3.2 "Before the Vote" 14-Day Agenda Previews
 * (public/assets/civicpulse_v3_2_agenda_preview.js)
 */

function escStr(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function mountAgendaPreviews() {
  const anchor = document.getElementById("upcomingMeetingsSection");
  if (!anchor || document.getElementById("v32AgendaPreviewsSection")) return;

  let payload = null;
  try {
    const res = await fetch("data/agenda_previews.json");
    if (!res.ok) return;
    payload = await res.json();
  } catch (_) {
    return;
  }

  const previews = payload.previews || [];
  if (!previews.length) return;

  const sec = document.createElement("section");
  sec.id = "v32AgendaPreviewsSection";
  sec.className = "bg-[#faf5eb] rounded-2xl border border-[#c67749]/35 p-5 sm:p-6 space-y-4 shadow-sm";

  sec.innerHTML = `
    <div class="flex flex-col md:flex-row md:items-center justify-between gap-2">
      <div>
        <span class="text-[11px] font-bold uppercase tracking-wider text-[#c67749]">Before the Vote • Next ${payload.horizon_days || 14} Days</span>
        <h2 class="text-lg font-bold text-[#1b3b4e]">📋 Upcoming Agenda Previews &amp; Public Comment</h2>
        <p class="text-xs text-[#142834]/75 mt-0.5">${escStr(payload.disclaimer || "")}</p>
      </div>
      <span class="text-xs font-semibold px-3 py-1 rounded-full bg-amber-100 text-amber-950 border border-amber-300/70 self-start">
        ${previews.length} Upcoming Agenda(s)
      </span>
    </div>
    <div id="v32PreviewCards" class="space-y-3"></div>
  `;

  anchor.insertAdjacentElement("afterend", sec);
  const box = sec.querySelector("#v32PreviewCards");

  box.innerHTML = previews
    .map((p, pIdx) => {
      const itemsHtml = (p.items || []).length
        ? `<ul class="space-y-2 pt-2 border-t border-[#1b3b4e]/10">
            ${p.items
              .map(
                (it, iIdx) => `
              <li class="rounded-xl bg-[#faf5eb]/80 border border-[#1b3b4e]/10 p-2.5 text-xs space-y-1">
                <div class="flex flex-wrap items-center justify-between gap-2">
                  <span class="font-bold text-[#1b3b4e]">${escStr(it.title)}</span>
                  <span class="px-2 py-0.5 rounded-full bg-[#ebe0ca] text-[#1b3b4e] text-[10px] font-semibold">${escStr(it.topic)}</span>
                </div>
                <p class="text-[#142834]/80">${escStr(it.plain_summary)}</p>
                <div class="pt-0.5">
                  <button type="button" data-pidx="${pIdx}" data-iidx="${iIdx}" class="v32-preview-comment-btn text-[11px] font-semibold text-[#c67749] hover:underline">
                    ✉️ Draft Public Comment Before Vote
                  </button>
                </div>
              </li>`
              )
              .join("")}
          </ul>`
        : `<p class="text-xs text-[#142834]/70 pt-1">Full agenda packet posted — open the official packet below to inspect scheduled items and sign up for public comment.</p>`;

      return `
        <article class="rounded-xl border border-[#1b3b4e]/15 bg-white p-4 space-y-2">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div class="text-xs font-bold text-[#366a8a]">${escStr(p.jurisdiction_name)} • ${escStr(p.meeting_date)}</div>
              <h3 class="text-sm font-bold text-[#1b3b4e]">${escStr(p.meeting_title)}</h3>
            </div>
            <div class="flex items-center gap-2">
              <span class="px-2.5 py-0.5 rounded-full bg-amber-100 text-amber-900 text-[11px] font-semibold">Draft Preview</span>
              ${
                p.agenda_url
                  ? `<a href="${escStr(p.agenda_url)}" target="_blank" rel="noopener noreferrer" class="px-3 py-1 rounded-xl bg-[#1b3b4e] text-[#faf5eb] text-xs font-semibold hover:bg-[#366a8a]">Official Agenda ↗</a>`
                  : ""
              }
            </div>
          </div>
          ${itemsHtml}
        </article>`;
    })
    .join("");

  box.querySelectorAll(".v32-preview-comment-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const p = previews[Number(btn.dataset.pidx)];
      const it = p && p.items ? p.items[Number(btn.dataset.iidx)] : null;
      if (p && it && window.CivicPulseV3 && typeof window.CivicPulseV3.openCommentComposer === "function") {
        window.CivicPulseV3.openCommentComposer({
          jurisdiction_name: p.jurisdiction_name,
          meeting_date: p.meeting_date,
          title: it.title,
        });
      }
    });
  });
}

mountAgendaPreviews();
