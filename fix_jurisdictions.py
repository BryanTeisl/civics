from db import DB_PATH, get_connection, init_db


def apply_pipeline_fixes(db_path: str = DB_PATH) -> None:
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        # Larimer County BOCC is hosted on larimer.gov rather than a larimerco CivicClerk OData API
        conn.execute(
            """
            UPDATE jurisdictions
            SET adapter_type = 'unclaimed',
                status = 'unclaimed',
                portal_url = 'https://www.larimer.gov/bocc/commissioners-meetings'
            WHERE ocd_division_id = 'ocd-division/country:us/state:co/county:larimer'
            """
        )

        # Keep Poudre School District unclaimed until its exact BoardDocs/portal URL returns 200
        conn.execute(
            """
            UPDATE jurisdictions
            SET status = 'unclaimed'
            WHERE ocd_division_id = 'ocd-division/country:us/state:co/school_district:poudre_r1'
            """
        )

        conn.commit()
        print("Applied pipeline fixes to", db_path)
    finally:
        conn.close()


if __name__ == "__main__":
    apply_pipeline_fixes()
