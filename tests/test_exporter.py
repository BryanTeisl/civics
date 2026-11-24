import json

from civicpulse.pipeline.exporter import export_all


def test_unified_export_creates_split_directory_and_search_index(sample_db, tmp_path):
    out_dir = tmp_path / "public_data"
    summary = export_all(db_path=sample_db, out_dir=out_dir, run_backup=False)
    assert summary["jurisdictions"] == 2
    assert summary["search_events"] == 2

    directory = json.loads((out_dir / "directory.json").read_text(encoding="utf-8"))
    search_idx = json.loads((out_dir / "search_index.json").read_text(encoding="utf-8"))
    guides = json.loads((out_dir / "engagement_guides.json").read_text(encoding="utf-8"))
    lifecycles = json.loads((out_dir / "bill_lifecycles.json").read_text(encoding="utf-8"))

    # Directory is lightweight (no inline search_index)
    assert "search_index" not in directory
    assert len(directory["jurisdictions"]) == 2
    assert len(search_idx["search_index"]) == 2

    # Engagement guide normalizes API URLs & raw stream titles
    fc_guide = guides["guides"]["ocd-division/country:us/state:co/place:fort_collins"]
    assert fc_guide["portal_url"] == "https://fortcollinsco.portal.civicclerk.com/"
    assert len(fc_guide["representatives"]) == 2
    for doc in fc_guide["recent_agendas_and_docs"]:
        assert "GetMeetingFileStream" not in doc["title"]
        assert ".api.civicclerk.com" not in doc["source_url"]

    # Lifecycle tracker links Ordinance No. 020 across both meetings
    fc_chains = lifecycles["by_jurisdiction"]["ocd-division/country:us/state:co/place:fort_collins"]
    assert len(fc_chains) == 1
    assert fc_chains[0]["stage_count"] == 2
