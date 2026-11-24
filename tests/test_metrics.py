from civicpulse.pipeline.metrics import compute_impact_score, recalculate_all_metrics


def test_budget_contested_scores_higher_than_minutes():
    budget_score = compute_impact_score(
        title="Ordinance No. 12: $45M Capital Budget & Bond Appropriation",
        event_type="budget",
        yes_count=4,
        no_count=3,
    )
    minutes_score = compute_impact_score(
        title="Approval of Meeting Minutes",
        event_type="consent",
        yes_count=7,
        no_count=0,
    )
    assert budget_score > minutes_score
    assert 5.0 <= minutes_score <= 100.0
    assert 5.0 <= budget_score <= 100.0


def test_recalculate_all_metrics(sample_db):
    updated = recalculate_all_metrics(db_path=sample_db)
    assert updated == 2
