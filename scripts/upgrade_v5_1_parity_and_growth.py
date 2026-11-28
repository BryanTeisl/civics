"""Idempotently upgrades CivicPulse v5 frontend & daily pipeline for feature parity + growth."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def patch_frontend_js() -> None:
    js_path = REPO_ROOT / "public" / "js" / "civicpulse_app.js"
    assert js_path.exists(), "Missing public/js/civicpulse_app.js"
    src = js_path.read_text(encoding="utf-8")

    if "siteConfig: null," not in src:
        src = src.replace(
            "  officialContacts: {},",
            "  officialContacts: {},\n  siteConfig: null,",
            1,
        )

    if 'fetchJsonSafe("data/site_config.json"' not in src:
        src = src.replace(
            '      fetchJsonSafe("data/official_contacts.json", {}),\n    ]);',
            '      fetchJsonSafe("data/official_contacts.json", {}),\n      fetchJsonSafe("data/site_config.json", null),\n    ]);',
            1,
        )
        src = src.replace(
            "  const [dirRaw, geo, upRaw, prevRaw, warnRaw, alignRaw, lifeRaw, scoreRaw, feedRaw, contactsRaw] =",
            "  const [dirRaw, geo, upRaw, prevRaw, warnRaw, alignRaw, lifeRaw, scoreRaw, feedRaw, contactsRaw, siteCfg] =",
            1,
        )
        src = src.replace(
            "  AppState.officialContacts = contactsRaw?.jurisdictions || contactsRaw || {};",
            """  AppState.officialContacts = contactsRaw?.jurisdictions || contactsRaw || {};
  AppState.siteConfig = siteCfg || {};
  if (AppState.siteConfig?.cloudflare_analytics_token && !document.getElementById("cpCfBeacon")) {
    const s = document.createElement("script");
    s.id = "cpCfBeacon";
    s.defer = true;
    s.src = "https://static.cloudflareinsights.com/beacon.min.js";
    s.setAttribute("data-cf-beacon", JSON.stringify({ token: AppState.siteConfig.cloudflare_analytics_token }));
    document.head.appendChild(s);
  }""",
            1,
        )

    if "cpV51AtLargeReps" not in src:
        at_large_hook = """  // Highlight At-Large / countywide reps for matched active jurisdictions without sub-district polygons (cpV51AtLargeReps)
  activeMatches.forEach((j) => {
    const jid = jurIdOf(j);
    if (loc.districtHints.has(jid)) return;
    if (!j?.parity?.is_at_large && normalizeLevel(j.level) === "city") return;
    const cachedP = AppState.jurPayloads.get(jid);
    if (cachedP) {
      getEntitiesFromPayload(cachedP).slice(0, 4).forEach((rep) => {
        myRepBadges.push(
          `<button type="button" data-resolved-rep="${esc(rep.ocd_person_id || rep.id)}" data-jur-id="${esc(jid)}" class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-white border border-[#c67749]/40 hover:border-[#c67749] text-xs font-semibold text-[#142834] cursor-pointer">
            <span class="text-[#c67749]">&#9733;</span><span>${esc(rep.name)}</span><span class="text-slate-500 font-normal">(${esc(j.name.split(" ")[0])} At-Large)</span>
          </button>`
        );
      });
    } else {
      loadJurPayload(jid).then(() => renderResolvedPanel());
    }
  });
"""
        anchor = "  const myRepsStrip = myRepBadges.length"
        if anchor in src:
            src = src.replace(anchor, at_large_hook + anchor, 1)

    if "cpV51ParityBanner" not in src:
        old_reps_intro = """  container.innerHTML = `
    <div class="text-xs text-[#142834]/75">
      Click any representative to open their full profile: direct email/phone, voting-record summary, floor comments, metrics, and roll-call log.
    </div>
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">${cards}</div>
  `;"""

        new_reps_intro = """  const parityNotes = [];
  Array.from(AppState.selectedJurIds).forEach((jid) => {
    const jm = getJurisdictionById(jid);
    (jm?.parity?.notes || []).forEach((n) => parityNotes.push(`<strong>${esc(jm.name)}:</strong> ${esc(n)}`));
  });
  const parityBanner = parityNotes.length
    ? `<div id="cpV51ParityBanner" class="p-3 rounded-xl bg-[#f4ecdc]/80 border border-[#1b3b4e]/15 text-xs text-[#142834]/85 space-y-1">${parityNotes.map((n) => `<div>&#8505;&#65039; ${n}</div>`).join("")}</div>`
    : "";
  const digestUrl = AppState.siteConfig?.weekly_digest_url || "";
  const digestBtn = digestUrl
    ? `<a href="${esc(digestUrl)}" target="_blank" rel="noopener noreferrer" class="shrink-0 px-3 py-1.5 rounded-lg bg-[#c67749] text-[#faf5eb] hover:bg-[#b56638] text-xs font-semibold">Get Weekly Email Alerts &#8599;</a>`
    : `<button type="button" data-open-modal="alertsModal" class="shrink-0 px-3 py-1.5 rounded-lg bg-[#1b3b4e] text-[#faf5eb] hover:bg-[#366a8a] text-xs font-semibold cursor-pointer">Subscribe to RSS Alerts</button>`;

  container.innerHTML = `
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div class="text-xs text-[#142834]/75">
        Click any representative to open their full profile: direct email/phone, voting-record summary, floor comments, metrics, and roll-call log.
      </div>
      ${digestBtn}
    </div>
    ${parityBanner}
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">${cards}</div>
  `;"""
        if old_reps_intro in src:
            src = src.replace(old_reps_intro, new_reps_intro, 1)
            src = src.replace(
                '  container.querySelectorAll("[data-open-rep]").forEach((btn) => {',
                '  container.querySelectorAll("[data-open-modal]").forEach((btn) => { btn.addEventListener("click", () => openModal(btn.dataset.openModal)); });\n  container.querySelectorAll("[data-open-rep]").forEach((btn) => {',
                1,
            )

    if "data-email-meeting-idx" not in src:
        old_ics_btn = """                  <button type="button" data-ics-idx="${idx}" class="px-2.5 py-1.5 rounded-lg border border-[#1b3b4e]/20 bg-white hover:bg-[#f4ecdc] text-xs font-semibold text-[#1b3b4e] cursor-pointer">
                    + Calendar (.ics)
                  </button>"""
        new_ics_btn = """                  <button type="button" data-email-meeting-idx="${idx}" class="px-2.5 py-1.5 rounded-lg border border-[#c67749]/40 bg-white hover:bg-[#faf5eb] text-xs font-semibold text-[#9c5128] cursor-pointer">
                    &#9993;&#65039; Email Council
                  </button>
                  <button type="button" data-ics-idx="${idx}" class="px-2.5 py-1.5 rounded-lg border border-[#1b3b4e]/20 bg-white hover:bg-[#f4ecdc] text-xs font-semibold text-[#1b3b4e] cursor-pointer">
                    + Calendar (.ics)
                  </button>"""
        if old_ics_btn in src:
            src = src.replace(old_ics_btn, new_ics_btn, 1)
            old_ics_wire = '  container.querySelectorAll("[data-ics-idx]").forEach((btn) => {'
            email_wire = """  container.querySelectorAll("[data-email-meeting-idx]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const m = allEntries[Number(btn.dataset.emailMeetingIdx)];
      const p = await loadJurPayload(m.jurId);
      const reps = getEntitiesFromPayload(p);
      const repEmails = reps.map((r) => r.email).filter(Boolean);
      const fallback = AppState.officialContacts?.[m.jurId]?.council_email || getJurisdictionById(m.jurId)?.council_email || "";
      const toEmail = repEmails.length ? repEmails.join(",") : fallback;
      openCommentComposer({
        toEmail: toEmail || "council@city.gov",
        recipientName: `${m.jurName} Members`,
        jurName: m.jurName,
        measureTitle: `${m.title} (${m.date})`,
      });
    });
  });
"""
            src = src.replace(old_ics_wire, email_wire + old_ics_wire, 1)

    if "Voice / Consent Vote" not in src:
        old_qa = '<span>QA: <strong class="text-emerald-700">${esc(ev.qa_status || "verified")}</strong></span>'
        new_qa = (
            '<span>QA: <strong class="text-emerald-700">${esc(ev.qa_status || "verified")}</strong></span>'
            '${ev._votes.length === 0 ? \'<span class="px-2 py-0.5 rounded bg-slate-100 text-slate-600 font-medium">Voice / Consent Vote</span>\' : ""}'
        )
        src = src.replace(old_qa, new_qa, 1)

    if "AppState.siteConfig?.support_links" not in src:
        src = src.replace(
            'mailto:bryanateisl@gmail.com?subject=CivicPulse%20Support%20(%245%20Coffee)',
            '${esc(AppState.siteConfig?.support_links?.coffee_5 || "mailto:bryanateisl@gmail.com?subject=CivicPulse%20Support%20(%245%20Coffee)")}',
            1,
        )
        src = src.replace(
            'mailto:bryanateisl@gmail.com?subject=CivicPulse%20Support%20(%2415%20Supporter)',
            '${esc(AppState.siteConfig?.support_links?.supporter_15 || "mailto:bryanateisl@gmail.com?subject=CivicPulse%20Support%20(%2415%20Supporter)")}',
            1,
        )
        src = src.replace(
            'mailto:bryanateisl@gmail.com?subject=CivicPulse%20Business%20Patron',
            '${esc(AppState.siteConfig?.support_links?.patron || "mailto:bryanateisl@gmail.com?subject=CivicPulse%20Business%20Patron")}',
            1,
        )

    assert src.count("{") == src.count("}"), "JS brace mismatch after v5.1 patch"
    assert src.count("(") == src.count(")"), "JS paren mismatch after v5.1 patch"
    js_path.write_text(src, encoding="utf-8")
    print("[PATCHED] public/js/civicpulse_app.js upgraded with v5.1 parity, voice-vote badges, 1-click agenda email & growth config.")


def patch_run_daily() -> None:
    p = REPO_ROOT / "scripts" / "run_daily.ps1"
    if not p.exists():
        print("[WARN] scripts/run_daily.ps1 not found.")
        return
    src = p.read_text(encoding="utf-8")
    changed = False

    if "civicpulse.pipeline.dedupe_procedural" not in src:
        anchor = "python -m civicpulse.pipeline.normalize"
        if anchor in src:
            hook = (
                'if (Test-Path "civicpulse\\pipeline\\dedupe_procedural.py") {\n'
                '        python -m civicpulse.pipeline.dedupe_procedural --db core_civic.db --apply 2>&1 | Tee-Object -FilePath $LogFile -Append\n'
                '    }\n'
                '    ' + anchor
            )
            src = src.replace(anchor, hook, 1)
            changed = True

    if "civicpulse.pipeline.scale_agenda_previews" not in src:
        anchor = "python -m civicpulse.pipeline.export_enhancements"
        if anchor in src:
            hook = (
                anchor + "\n"
                '    if (Test-Path "civicpulse\\pipeline\\scale_agenda_previews.py") {\n'
                '        python -m civicpulse.pipeline.scale_agenda_previews --db core_civic.db --out public\\data\\agenda_previews.json 2>&1 | Tee-Object -FilePath $LogFile -Append\n'
                '    }\n'
                '    if (Test-Path "civicpulse\\pipeline\\parity_audit.py") {\n'
                '        python -m civicpulse.pipeline.parity_audit --db core_civic.db --public-dir public 2>&1 | Tee-Object -FilePath $LogFile -Append\n'
                '    }'
            )
            src = src.replace(anchor, hook, 1)
            changed = True

    if changed:
        p.write_text(src, encoding="utf-8")
        print("[PATCHED] Wired dedupe_procedural, scale_agenda_previews & parity_audit into scripts/run_daily.ps1")
    else:
        print("[OK] scripts/run_daily.ps1 already wired.")


if __name__ == "__main__":
    patch_frontend_js()
    patch_run_daily()
