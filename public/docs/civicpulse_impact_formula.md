# CivicPulse Vote Impactfulness Formula

- **Current Version:** `v2.0.0`
- **Effective Date:** `2026-11-25`
- **Formula Checksum (SHA-256):** `292922f52a39`

> **Nonpartisan Guarantee:** CivicPulse's Impact Score is 100% deterministic math. It never evaluates political ideology, party affiliation, or AI sentiment. Anyone can verify a score by hand using the official vote tally.

## Plain-English Summary

Every local measure receives a 0 to 100 score by adding three objective components: (1) Legal Weight (10-40 pts) based on whether it changes permanent law or budgets, (2) Contestedness (0-40 pts) based on how close the Yes/No vote margin was, and (3) Turnout (0-20 pts, capped at 10 pts for subcommittees) based on how many members of that body participated.

## Exact Formula

```text
ImpactScore = min(100, LegalWeight + Contestedness + Turnout)

Where:
  LegalWeight   = 10 to 40 points (see table below)
  Contestedness = (1 - |Yes - No| / (Yes + No)) * 40   (0 if Yes + No == 0)
  Turnout       = (VotesCast / ExpectedBodySize) * Cap (Cap = 20 for full council, 10 for committee)
```

### Component 1: Legal Binding Weight (10 - 40 pts)

| Measure Type | Points | What It Covers |
| :--- | ---: | :--- |
| Budget / Appropriation / Charter | 40 | Annual budgets, mill levies, tax rates, charter changes |
| Zoning / Land Use | 38 | Rezonings, annexations, land-use code amendments |
| Ordinance | 35 | Binding permanent changes to municipal or county code |
| Resolution / Contract | 25 | Vendor contracts, grants, intergovernmental agreements, formal policy |
| Motion | 20 | General floor motions and formal council directives |
| Appointment | 15 | Board, commission, or officer appointments |
| Consent Item | 12 | Bundled routine items approved in one motion |
| Minutes / Proclamation | 10 | Approval of prior minutes or ceremonial proclamations |

### Component 2: Contestedness / Vote Margin (0 - 40 pts)

- **Unanimous votes** (e.g., `7-0` or `11-0`) add **0 points** because the governing body agreed without dissent.
- **Close / split votes** (e.g., `4-3` or `6-5`) score near the maximum **40 points** because councilmembers disagreed and every vote mattered.

### Component 3: Body Turnout (0 - 20 pts)

- Full-council roll calls earn up to **20 points** proportional to members voting (`VotesCast / FullBodySize`).
- **Committee votes** are measured against the **committee's own size** (not the full council roster) and capped at **10 points**, preventing misleading low-attendance penalties while distinguishing committee recommendations from full-council passage.

## Worked Examples

| Scenario | Legal | Split | Turnout | Final Score |
| :--- | ---: | ---: | ---: | ---: |
| Unanimous Routine Consent Item (Full Council 7-0) | 12 | 0 | 20 | **32 / 100** |
| Unanimous City Ordinance (Full Council 7-0) | 35 | 0 | 20 | **55 / 100** |
| Razor-Thin Zoning / Budget Vote (Full Council 4-3) | 40 | 34.3 | 20 | **94.3 / 100** |
| Unanimous 4-Member Committee Recommendation (4-0) | 35 | 0 | 10 | **45 / 100** |

## Formula Changelog (All Revisions)

| Version | Date | Summary of Change |
| :--- | :--- | :--- |
| `v2.0.0` | 2026-11-25 | Published full plain-English & machine-readable formula specification; fixed committee attendance/turnout denominator so committee votes are scored against committee size rather than full-council size; added deterministic formula hash for change detection. |
| `v1.1.0` | 2026-11-23 | Standardized 3-factor deterministic model: Legal Weight (10-40 pts) + Contestedness / Vote Margin (0-40 pts) + Body Turnout (0-20 pts). |
| `v1.0.0` | 2026-11-21 | Initial prototype heuristic combining event type and yes/no closeness. |
