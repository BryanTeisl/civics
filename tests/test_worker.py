from unittest.mock import patch

from civicpulse.db import get_connection
from civicpulse.pipeline.worker import _extract_html_text, _is_pivotal_vote, _match_entity_id, run_worker


def test_html_text_extractor_strips_scripts_and_nav():
    html = "<html><head><style>body{}</style></head><body><nav>Menu</nav><main><h1>Ordinance 12</h1><p>Passed 6-1.</p></main><script>alert(1)</script></body></html>"
    text = _extract_html_text(html)
    assert "Ordinance 12" in text
    assert "Passed 6-1." in text
    assert "alert(1)" not in text
    assert "Menu" not in text


def test_entity_matching_and_pivotal_vote_logic():
    roster = [
        {"ocd_person_id": "ocd-person/fc_1", "name": "Emily Francis"},
        {"ocd_person_id": "ocd-person/fc_2", "name": "Chris Conway"},
    ]
    assert _match_entity_id("Emily Francis", roster) == "ocd-person/fc_1"
    assert _match_entity_id("Councilmember Conway", roster) == "ocd-person/fc_2"
    assert _match_entity_id("Unknown Person", roster) is None

    assert _is_pivotal_vote("Yes", "Passed", 4, 3) == 1
    assert _is_pivotal_vote("Yes", "Passed", 7, 0) == 0
    assert _is_pivotal_vote("No", "Failed", 3, 4) == 1


def test_worker_fetches_text_and_inserts_events_and_votes(sample_db):
    conn = get_connection(sample_db)
    conn.execute(
        """
        INSERT INTO documents (jurisdiction_id, external_id, meeting_date, doc_type, title, source_url, content_hash, status)
        VALUES ('ocd-division/country:us/state:co/place:fort_collins', 'min_200', '2026-11-20', 'minutes',
                'Regular Council Minutes', 'https://example.org/minutes.html', 'hash_200', 'pending')
        """
    )
    conn.commit()
    conn.close()

    fake_text = "Regular Meeting Minutes. Ordinance No. 055 regarding transit funding passed 4-3. Emily Francis voted Yes. Chris Conway voted No." * 3
    fake_events = [
        {
            "title": "Ordinance No. 055: Transit Funding",
            "event_type": "ordinance",
            "topic": "Transit",
            "outcome": "Passed",
            "yes_count": 4,
            "no_count": 3,
            "abstain_count": 0,
            "absent_count": 0,
            "plain_summary": "Funds expanded local bus service.",
            "diff_summary": "Adds $2M to transit operations.",
            "votes": [
                {"name": "Emily Francis", "vote": "Yes", "rationale_summary": "Supports transit", "verbatim_quote": ""},
                {"name": "Conway", "vote": "No", "rationale_summary": "Cost concerns", "verbatim_quote": ""},
            ],
        }
    ]

    with patch("civicpulse.pipeline.worker.fetch_document_text", return_value=fake_text), patch(
        "civicpulse.pipeline.worker._call_ollama_extract", return_value=fake_events
    ):
        stats = run_worker(db_path=sample_db, limit=5)

    assert stats["fetched"] == 1
    assert stats["processed"] == 1
    assert stats["events_created"] == 1
    assert stats["votes_created"] == 2

def test_primegov_compiled_document_pdf_resolver():
    from unittest.mock import MagicMock, patch
    from civicpulse.pipeline.worker import fetch_document_text

    fake_resp = MagicMock()
    fake_resp.ok = True
    fake_resp.headers = {"Content-Type": "application/pdf"}
    fake_resp.content = b"%PDF-1.4 fake pdf bytes"

    url = "https://longmont.primegov.com/Portal/Meeting?meetingTemplateId=17512"
    with patch("civicpulse.pipeline.worker.requests.get", return_value=fake_resp) as mock_get, patch(
        "civicpulse.pipeline.worker._extract_pdf_text", return_value="Longmont City Council Minutes Passed 7-0."
    ) as mock_pdf:
        text = fetch_document_text(url, doc_type="minutes")

    mock_get.assert_called_once()
    assert mock_get.call_args[0][0] == "https://longmont.primegov.com/Public/CompiledDocument/17512"
    mock_pdf.assert_called_once_with(b"%PDF-1.4 fake pdf bytes")
    assert "Longmont City Council Minutes" in text
