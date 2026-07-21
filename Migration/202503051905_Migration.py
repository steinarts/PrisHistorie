import sqlite3

def expand_tables():
    # Koble til databasen
    conn = sqlite3.connect('data/PrisHistorie.db')
    c = conn.cursor()

    try:
        # Opprett DealerSegment-tabellen
        c.execute('''
            CREATE TABLE IF NOT EXISTS DealerSegment (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            );
        ''')

        # Legg inn data i DealerSegment-tabellen
        c.execute('''
            INSERT OR IGNORE INTO DealerSegment (id, name) VALUES
            (1, 'Privat'),
            (2, 'Forhandler'),
            (3, 'Merkeforhandler');
        ''')

        # Legg til nye kolonner i `cars`-tabellen
        c.execute('''
            ALTER TABLE cars
            ADD COLUMN dealerSegmentId TEXT;
        ''')
        c.execute('''
            ALTER TABLE cars
            ADD COLUMN organisationName TEXT;
        ''')
        c.execute('''
            ALTER TABLE cars
            ADD COLUMN adTimestamp INTEGER;
        ''')

        # Legg til nye kolonner i `inactivecars`-tabellen
        c.execute('''
            ALTER TABLE inactivecars
            ADD COLUMN DealerSegmentId TEXT;
        ''')
        c.execute('''
            ALTER TABLE inactivecars
            ADD COLUMN organisationName TEXT;
        ''')
        c.execute('''
            ALTER TABLE inactivecars
            ADD COLUMN adTimestamp INTEGER;
        ''')

        # Lagre endringene
        conn.commit()
        print("Tabellene ble utvidet vellykket!")

    except sqlite3.OperationalError as e:
        print(f"Problem med å utvide tabellene: {e}")

    finally:
        # Lukk tilkoblingen til databasen
        conn.close()

# Kjør funksjonen
expand_tables()