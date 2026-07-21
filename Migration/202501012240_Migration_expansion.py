import sqlite3

def expand_tables():
    conn = sqlite3.connect('data/PrisHistorie.db')
    c = conn.cursor()

    # Legg til kolonner i `cars`
    try:
        c.execute("ALTER TABLE cars ADD COLUMN regNo TEXT;")
        c.execute("ALTER TABLE cars ADD COLUMN location TEXT;")
        c.execute("ALTER TABLE cars ADD COLUMN url TEXT;")
        c.execute("ALTER TABLE cars ADD COLUMN latitude REAL;")
        c.execute("ALTER TABLE cars ADD COLUMN longitude REAL;")
        c.execute("ALTER TABLE cars ADD COLUMN imagelink TEXT;")
    except sqlite3.OperationalError as e:
        print(f"Kan ikke endre 'cars' tabellen: {e}")

    # Legg til kolonner i `inactivecars`
    try:
        c.execute("ALTER TABLE inactivecars ADD COLUMN regNo TEXT;")
        c.execute("ALTER TABLE inactivecars ADD COLUMN location TEXT;")
        c.execute("ALTER TABLE inactivecars ADD COLUMN url TEXT;")
        c.execute("ALTER TABLE inactivecars ADD COLUMN latitude REAL;")
        c.execute("ALTER TABLE inactivecars ADD COLUMN longitude REAL;")
        c.execute("ALTER TABLE inactivecars ADD COLUMN imagelink TEXT;")
        c.execute("ALTER TABLE inactivecars ADD COLUMN inactivated_timestamp DATETIME;")
    except sqlite3.OperationalError as e:
        print(f"Kan ikke endre 'inactivecars' tabellen: {e}")


    # Lagre endringene
    conn.commit()
    conn.close()

expand_tables()