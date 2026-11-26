"""Regression tests for word-boundary topic classification precision."""
from __future__ import annotations

from civicpulse.pipeline.normalize import classify_topic


def test_word_boundary_topic_classification_avoids_proper_noun_false_positives():
    assert (
        classify_topic(
            "Approves Master Purchase Order with WoodRiver Energy, LLC",
            "The council approved a purchase order for natural gas supplies.",
            "Parks, Water & Environment",
        )
        == "Contracts & Procurement"
    )

    assert (
        classify_topic(
            "Polling for Closed Executive Session",
            "The City Council voted to hold a Closed Executive Session regarding the sale of Meadows Park Community Center.",
            "Parks, Water & Environment",
        )
        == "Governance & Elections"
    )

    assert (
        classify_topic(
            "Pass Councillor's Bill No. 54 concerning recycling, compost, and plastic regulations",
            "Amends municipal code related to recycling and composting.",
            "General",
        )
        == "Parks, Water & Environment"
    )
