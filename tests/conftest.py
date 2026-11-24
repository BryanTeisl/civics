from __future__ import annotations

import pytest

from civicpulse.db import get_connection, init_db


@pytest.fixture
def sample_db(tmp_path):
    db_file = str(tmp_path / "test_civic.db")
    init_db(db_file)
    conn = get_connection(db_file)
    try:
        conn.execute(
            """
            INSERT INTO jurisdictions (ocd_division_id, name, level, lat, lng, adapter_type, portal_url, status)
            VALUES
              ('ocd-division/country:us/state:co/place:fort_collins', 'Fort Collins City Council', 'city', 40.5853, -105.0844, 'civicclerk', 'https://fortcollinsco.api.civicclerk.com/v1', 'active'),
              ('ocd-division/country:us/state:co/place:firestone', 'Firestone Board of Trustees', 'city', 40.1125, -104.9366, 'civicplus', 'https://www.firestoneco.gov/Agendas', 'unclaimed')
            """
        )
        conn.execute(
            """
            INSERT INTO entities (ocd_person_id, jurisdiction_id, name, role, district, email, active)
            VALUES
              ('ocd-person/fc_1', 'ocd-division/country:us/state:co/place:fort_collins', 'Emily Francis', 'Councilmember', 'At-Large', 'efrancis@fcgov.com', 1),
              ('ocd-person/fc_2', 'ocd-division/country:us/state:co/place:fort_collins', 'Chris Conway', 'Councilmember', 'District 1', 'cconway@fcgov.com', 1)
            """
        )
        conn.execute(
            """
            INSERT INTO documents (jurisdiction_id, external_id, meeting_date, doc_type, title, source_url, content_hash, status)
            VALUES
              ('ocd-division/country:us/state:co/place:fort_collins', 'cc_100', '2026-11-03', 'agenda', 'https://fortcollinsco.api.civicclerk.com/v1/Meetings/GetMeetingFileStream?id=100', 'https://fortcollinsco.api.civicclerk.com/v1/Meetings/GetMeetingFileStream?id=100', 'hash_100', 'processed')
            """
        )
        conn.execute(
            """
            INSERT INTO events (event_id, jurisdiction_id, meeting_date, title, plain_summary, event_type, topic, outcome, yes_count, no_count, impact_score, source_url)
            VALUES
              ('ev_ord_020_1', 'ocd-division/country:us/state:co/place:fort_collins', '2026-11-03', 'Ordinance No. 020: Municipal Budget Appropriation', 'Approves annual city budget.', 'budget', 'Budget', 'Passed', 6, 1, 78.0, 'https://fortcollinsco.portal.civicclerk.com/'),
              ('ev_ord_020_2', 'ocd-division/country:us/state:co/place:fort_collins', '2026-11-17', 'Second Reading of Ordinance No. 020', 'Final adoption of city budget.', 'ordinance', 'Budget', 'Adopted', 7, 0, 82.0, 'https://fortcollinsco.portal.civicclerk.com/')
            """
        )
        conn.execute(
            """
            INSERT INTO entity_actions (event_id, entity_id, action_type, value, is_pivotal)
            VALUES
              ('ev_ord_020_1', 'ocd-person/fc_1', 'vote', 'Yes', 0),
              ('ev_ord_020_1', 'ocd-person/fc_2', 'vote', 'No', 0),
              ('ev_ord_020_2', 'ocd-person/fc_1', 'vote', 'Yes', 0),
              ('ev_ord_020_2', 'ocd-person/fc_2', 'vote', 'Yes', 0)
            """
        )
        conn.commit()
    finally:
        conn.close()
    return db_file
