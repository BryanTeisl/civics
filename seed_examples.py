"""Seeds one real example municipality for each of the 6 platform families."""
from db import get_connection, init_db, seed_fort_collins

EXAMPLES = [
    ("ocd-division/country:us/state:co/place:denver", "Denver City Council", "municipal", 39.7392, -104.9903, "legistar", "https://webapi.legistar.com/v1/denver"),
    ("ocd-division/country:us/state:co/place:loveland", "Loveland City Council", "municipal", 40.3978, -105.0750, "civicplus", "https://www.lovgov.org/AgendaCenter"),
    ("ocd-division/country:us/state:ca/place:san_jose", "San Jose City Council", "municipal", 37.3382, -121.8863, "primegov", "https://sanjose.primegov.com"),
    ("ocd-division/country:us/state:co/place:colorado_springs", "Colorado Springs City Council", "municipal", 38.8339, -104.8214, "granicus", "https://coloradosprings.granicus.com/ViewPublisher.php?view_id=4"),
    ("ocd-division/country:us/state:co/sd:poudre", "Poudre School District Board", "municipal", 40.5592, -105.0781, "boarddocs", "https://go.boarddocs.com/co/psdschools/Board.nsf"),
]

if __name__ == "__main__":
    init_db()
    seed_fort_collins()
    conn = get_connection()
    for row in EXAMPLES:
        conn.execute("""
            INSERT OR IGNORE INTO jurisdictions
            (ocd_division_id, name, level, lat, lng, adapter_type, portal_url, poll_tier)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'fast')
        """, row)
    conn.commit()
    conn.close()
    print("Seeded all 6 platform family examples.")