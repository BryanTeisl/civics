from pathlib import Path

from civicpulse.cli import main


def test_cli_init_seed_and_export(tmp_path):
    db_file = str(tmp_path / "cli_test.db")
    out_dir = tmp_path / "out"
    config_file = Path("config/jurisdictions/colorado_front_range.json")

    assert main(["--db", db_file, "init"]) == 0
    assert main(["--db", db_file, "seed", "--file", str(config_file), "--activate-structured"]) == 0
    assert main(["--db", db_file, "export", "--out-dir", str(out_dir), "--no-backup"]) == 0
    assert (out_dir / "directory.json").exists()
    assert (out_dir / "search_index.json").exists()
    assert (out_dir / "engagement_guides.json").exists()
    assert (out_dir / "bill_lifecycles.json").exists()
