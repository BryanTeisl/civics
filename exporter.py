"""
Batched Static Exporter & Cloudflare Pages Publisher.
Exports sharded OCD JSON files, runs OneDrive-safe SQLite backups,
and executes a batched git push (staying well under Cloudflare's 500 builds/month).
"""
import json
import os
import subprocess
from datetime import datetime
from db import get_connection, backup_to_onedrive
from metrics import compute_legislator_metrics

EXPORT_DIR = "public/data"


def ocd_to_filename(ocd_id: str) -> str:
    return ocd_id.replace("/", "-").replace(":", "-") + ".json"


def export_all_jurisdictions() -> int:
    os.makedirs(EXPORT_DIR, exist_ok=True)
    conn = get_connection()
    jurisdictions = conn.execute("SELECT * FROM jurisdictions").fetchall()

    index_list = []
    for j in jurisdictions:
        j_id = j["ocd_division_id"]
        filename = ocd_to_filename(j_id)
        index_list.append({
            "id": filename.replace(".json", ""),
            "ocd_division_id": j_id,
            "name": j["name"],
            "level": j["level"],
            "lat": j["lat"],
            "lng": j["lng"],
        })

        entities = conn.execute(
            "SELECT * FROM entities WHERE jurisdiction_id = ? AND active = 1", (j_id,)
        ).fetchall()

        councilors_out = []
        for e in entities:
            actions = conn.execute(
                "SELECT * FROM entity_actions WHERE entity_id = ?", (e["ocd_person_id"],)
            ).fetchall()
            metrics = compute_legislator_metrics(actions)
            councilors_out.append({
                "id": e["ocd_person_id"],
                "name": e["name"],
                "entity_type": e["entity_type"],
                "role": e["role"],
                "district": e["district"],
                "website": e["website_url"],
                "metrics": metrics,
            })

        events = conn.execute(
            "SELECT * FROM events WHERE jurisdiction_id = ? ORDER BY meeting_date DESC", (j_id,)
        ).fetchall()

        agenda_items_out = []
        for ev in events:
            vote_rows = conn.execute(
                "SELECT * FROM entity_actions WHERE event_id = ? AND action_type = 'vote'",
                (ev["event_id"],),
            ).fetchall()
            votes_map = {
                vr["entity_id"]: {
                    "vote": vr["value"],
                    "is_pivotal": bool(vr["is_pivotal"]),
                    "summary": vr["rationale_summary"],
                    "quote": vr["verbatim_quote"],
                }
                for vr in vote_rows
            }
            agenda_items_out.append({
                "item_id": ev["event_id"],
                "date": ev["meeting_date"],
                "title": ev["title"],
                "event_type": ev["event_type"],
                "topic": ev["topic"],
                "outcome": f"{ev['outcome']} ({ev['yes_count']}-{ev['no_count']})",
                "impact_score": ev["impact_score"],
                "source_url": ev["source_url"],
                "votes": votes_map,
            })

        payload = {
            "jurisdiction_id": j_id,
            "jurisdiction_name": j["name"],
            "last_updated": datetime.utcnow().strftime("%Y-%m-%d"),
            "councilors": councilors_out,
            "agenda_items": agenda_items_out,
        }

        with open(os.path.join(EXPORT_DIR, filename), "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    with open(os.path.join(EXPORT_DIR, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"jurisdictions": index_list}, f, indent=2)

    conn.close()
    return len(index_list)


def git_publish_if_changed() -> None:
    """Commits and pushes only if public/data changed (protects Cloudflare build quota)."""
    subprocess.run(["git", "add", EXPORT_DIR], check=True)
    diff = subprocess.run(["git", "diff", "--staged", "--quiet"])
    if diff.returncode != 0:
        stamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        subprocess.run(["git", "commit", "-m", f"data: batched civic export ({stamp})"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("[PUBLISH] Pushed updated static JSON to Git -> Cloudflare Pages.")
    else:
        print("[PUBLISH] No data changes detected; skipping push to save Cloudflare builds.")


if __name__ == "__main__":
    count = export_all_jurisdictions()
    print(f"Exported {count} jurisdiction file(s) to {EXPORT_DIR}/")
    backup_path = backup_to_onedrive()
    if backup_path:
        print(f"Backed up SQLite DB safely to OneDrive: {backup_path}")
    # Uncomment once your Git remote is configured:
    # git_publish_if_changed()
